"""GDS mask designs and reviewed, versioned chip maps for the fabrication traveler.

The GDS is uploaded from the browser and GdsChipMapIngestor adds generic ``gds_geometry``.
Reviewing a map creates a new child "Chip map" dataset instead of changing an older version.
"""
import logging
import math

from flask import Blueprint, jsonify

from crucible import Dataset
from crucible.utils import get_tz_isoformat
from routes import crucible_api
from routes.shared import cruc_client
from routes.synthesis_common import (ApiError, current_user, parse_body,
                                     register_error_handlers)
from routes.synthesis_models import (ChipMapCreateRequest, MaskCreateRequest,
                                     PlannedChiplet)

logger = logging.getLogger(__name__)
chip_maps_bp = Blueprint("chip_maps", __name__)
register_error_handlers(chip_maps_bp)

MASK_MEASUREMENT = "Mask design"
CHIP_MAP_MEASUREMENT = "Chip map"


def dataset_summary(ds):
    return {
        "dataset_id": ds.get("unique_id") or ds["dataset_id"],
        "dataset_name": ds.get("dataset_name"),
        "measurement": ds.get("measurement"),
        "timestamp": ds.get("timestamp"),
    }


def load_mask(mask_id):
    try:
        mask = cruc_client.datasets.get(mask_id, include_metadata=True)
    except Exception:
        mask = None
    if not mask or mask.get("measurement") != MASK_MEASUREMENT:
        raise ApiError(404, f"Mask design {mask_id} not found")
    current_user(mask.get("project_id"))
    return mask


def map_versions(mask_id):
    versions = []
    # The API's nested child listing has no metadata option despite the client accepting
    # one: its DatasetRead response omits scientific_metadata. Fetch matching children
    # individually so reviewed maps are not discarded just because the listing omitted it.
    for child in cruc_client.datasets.list_children(mask_id, limit=None):
        if child.get("measurement") != CHIP_MAP_MEASUREMENT:
            continue
        ds = cruc_client.datasets.get(child["unique_id"], include_metadata=True)
        meta = ds.get("scientific_metadata") or {}
        if not isinstance(meta.get("version"), int) or not meta.get("chips"):
            continue
        versions.append({**dataset_summary(ds), "chip_map": meta})
    return sorted(versions, key=lambda v: v["chip_map"]["version"], reverse=True)


def latest_map(mask_id):
    versions = map_versions(mask_id)
    return versions[0] if versions else None


def load_chip_map(map_id, project=None):
    try:
        ds = cruc_client.datasets.get(map_id, include_metadata=True)
    except Exception:
        ds = None
    meta = (ds or {}).get("scientific_metadata") or {}
    if not ds or ds.get("measurement") != CHIP_MAP_MEASUREMENT or not meta.get("chips"):
        raise ApiError(404, f"Reviewed chip map {map_id} not found")
    if project is not None and ds.get("project_id") != project:
        raise ApiError(400, "This chip map belongs to a different project")
    current_user(ds.get("project_id"))
    used_by = list(meta.get("used_by") or [])
    used_by.extend(s["unique_id"] for s in cruc_client.samples.list(dataset_mfid=map_id, limit=None))
    meta = {**meta, "used_by": sorted(set(used_by)), "locked": bool(meta.get("locked") or used_by)}
    return {**dataset_summary(ds), "chip_map": meta}


def lock_chip_map(map_id, wafer_id, wafer_name):
    """One-way lock: future reviews make another child dataset, never edit this map."""
    current = load_chip_map(map_id)
    # A separate link per wafer cannot lose a concurrent wafer's usage. The old shared
    # used_by list required an atomic append, which metadata PATCH does not provide.
    cruc_client.datasets.link_sample(map_id, wafer_id)
    if not current["chip_map"].get("locked"):
        cruc_client.datasets.update_scientific_metadata(map_id, {"locked": True}, overwrite=False)
    logger.info("Chip map %s locked by wafer %s (%s)", map_id, wafer_id, wafer_name)


def ingestion_status(mask_id):
    response = crucible_api.list_ingestion_requests(mask_id)
    requests = response.get("items") or []
    return [{
        "request_id": r.get("id"),
        "status": r.get("status"),
        "ingestion_class": r.get("ingestion_class"),
        "time_created": r.get("time_created"),
        "time_completed": r.get("time_completed"),
    } for r in requests]


def clean_outline(values, where):
    if len(values) != 4 or any(isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ApiError(400, f"{where}: outline must be four finite numbers [x0, y0, x1, y1]")
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        raise ApiError(400, f"{where}: outline must have positive width and height")
    return [float(v) for v in values]


def validate_review(req):
    if not req.blocks or not req.chips:
        raise ApiError(400, "A reviewed map needs at least one block and one chip")
    block_ids = [b.id.strip() for b in req.blocks]
    if any(not b for b in block_ids) or len(set(block_ids)) != len(block_ids):
        raise ApiError(400, "Block ids must be non-empty and unique")
    names = [b.name.strip() for b in req.blocks]
    if any(not n for n in names) or len(set(names)) != len(names):
        raise ApiError(400, "Block names must be non-empty and unique")
    chip_ids = [c.id.strip() for c in req.chips]
    if any(not c for c in chip_ids) or len(set(chip_ids)) != len(chip_ids):
        raise ApiError(400, "Chip ids must be non-empty and unique")
    known_blocks = set(block_ids)
    chips = []
    for chip in req.chips:
        where = f"Chip {chip.id}"
        if chip.block not in known_blocks:
            raise ApiError(400, f"{where}: unknown block '{chip.block}'")
        label = chip.label.strip()
        if label == "?":
            raise ApiError(400, f"{where}: resolve its unreadable printed label before saving")
        chips.append({"id": chip.id.strip(), "block": chip.block, "label": label,
                      "outline": clean_outline(chip.outline, where),
                      **({"layer": chip.layer.strip()} if chip.layer and chip.layer.strip() else {})})
    nonempty_blocks = {c.block for c in req.chips}
    empty_blocks = [b.id for b in req.blocks if b.id not in nonempty_blocks]
    if empty_blocks:
        raise ApiError(400, f"These blocks have no chips; move a chip into them or remove them: {empty_blocks}")
    return {
        "units": "mm",
        "blocks": [{"id": b.id.strip(), "name": b.name.strip()} for b in req.blocks],
        "chips": chips,
    }


def clean_chiplet_plan(plan, map_id, project):
    """Validate future chiplet names against one reviewed map, without creating samples."""
    if not plan:
        return None
    if not map_id:
        raise ApiError(400, "Planning chiplets requires a reviewed chip map")
    chip_map = load_chip_map(map_id, project=project)["chip_map"]
    blocks = {b["id"] for b in chip_map["blocks"]}
    entries = [p.model_dump() if isinstance(p, PlannedChiplet) else p for p in plan]
    cleaned = []
    for entry in entries:
        block = entry["block"]
        name = entry["name"].strip()
        if block not in blocks:
            raise ApiError(400, f"Planned chiplet uses unknown block '{block}'")
        if not name:
            raise ApiError(400, "Every planned chiplet needs a name")
        cleaned.append({"block": block, "name": name})
    block_ids = [p["block"] for p in cleaned]
    names = [p["name"] for p in cleaned]
    if len(set(block_ids)) != len(block_ids) or len(set(names)) != len(names):
        raise ApiError(400, "Planned chiplet blocks and names must be unique")
    return {"mask_design": map_id, "chiplets": cleaned}


@chip_maps_bp.route("/api/masks", methods=["GET"])
def list_masks():
    from flask import request
    project = request.args.get("project", "")
    current_user(project)
    masks = cruc_client.datasets.list(project_id=project, measurement=MASK_MEASUREMENT,
                                      include_metadata=True, limit=None)
    out = []
    for mask in masks:
        latest = latest_map(mask["unique_id"])
        latest_summary = None
        if latest:
            meta = latest["chip_map"]
            latest_summary = {**dataset_summary(latest), "version": meta["version"],
                              "chip_count": len(meta["chips"]), "block_count": len(meta["blocks"]),
                              "locked": bool(meta.get("locked"))}
        out.append({**dataset_summary(mask),
                    "geometry_ready": bool((mask.get("scientific_metadata") or {}).get("gds_geometry")),
                    "reviewed_map": latest_summary})
    return jsonify({"masks": sorted(out, key=lambda m: m["dataset_name"] or "")})


@chip_maps_bp.route("/api/masks", methods=["POST"])
def create_mask():
    req = parse_body(MaskCreateRequest)
    user = current_user(req.project)
    name = req.dataset_name.strip()
    if not name:
        raise ApiError(400, "Mask design name is required")
    ds = Dataset(dataset_name=name, public=False, owner=user["orcid"], project_id=req.project,
                 measurement=MASK_MEASUREMENT, data_type="GDS layout", data_format="GDSII",
                 timestamp=get_tz_isoformat())
    created = cruc_client.datasets.create(ds, keywords=["fabrication", "mask-design"])
    mask_id = created["created_record"]["unique_id"]
    return jsonify({"mask": {"dataset_id": mask_id, "dataset_name": name}})


@chip_maps_bp.route("/api/masks/<mask_id>", methods=["GET"])
def get_mask(mask_id):
    mask = load_mask(mask_id)
    versions = map_versions(mask_id)
    return jsonify({
        "project": mask.get("project_id"),
        "mask": dataset_summary(mask),
        "geometry": (mask.get("scientific_metadata") or {}).get("gds_geometry"),
        "ingestion": ingestion_status(mask_id),
        "versions": [{**dataset_summary(v), "chip_map": v["chip_map"]} for v in versions],
        "chip_map": versions[0] if versions else None,
    })


@chip_maps_bp.route("/api/masks/<mask_id>/chip-maps", methods=["POST"])
def save_chip_map(mask_id):
    req = parse_body(ChipMapCreateRequest)
    mask = load_mask(mask_id)
    user = current_user(mask.get("project_id"))
    cleaned = validate_review(req)
    latest = latest_map(mask_id)
    current_version = latest["chip_map"]["version"] if latest else 0
    if req.expected_version != current_version:
        raise ApiError(409, f"This mask now has chip-map version {current_version}; reload before saving")
    version = current_version + 1
    metadata = {**cleaned, "version": version, "source_mask_design": mask_id,
                "reviewed_by": user.get("user_name"), "reviewed_at": get_tz_isoformat(),
                "locked": False, "used_by": []}
    ds = Dataset(dataset_name=f"{mask['dataset_name']} chip map v{version}", public=False,
                 owner=user["orcid"], project_id=mask["project_id"], measurement=CHIP_MAP_MEASUREMENT,
                 data_type="Chip map", data_format="JSON", timestamp=get_tz_isoformat())
    created = cruc_client.datasets.create(ds, keywords=["fabrication", "chip-map"])
    map_id = created["created_record"]["unique_id"]
    crucible_api.add_scientific_metadata(map_id, metadata)
    cruc_client.datasets.link(mask_id, map_id)
    return jsonify({"map": {"dataset_id": map_id, "chip_map": metadata}})


@chip_maps_bp.route("/api/chip-maps/<map_id>", methods=["GET"])
def get_chip_map(map_id):
    """Read one exact reviewed map for wafer creation and its chiplet planner."""
    return jsonify({"map": load_chip_map(map_id)})
