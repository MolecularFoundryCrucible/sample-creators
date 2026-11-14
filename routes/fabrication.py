"""Per-wafer fabrication traveler (QCMF): wafer -> chiplet -> chip, one dataset per process step.

Ported from manual-synthesis-ui backend/routes/fabrication.py (c25ae5c). Step file attachments
are uploaded by the browser straight to storage through /api/uploads (with ingestion recorded
as not requested), so there is no file upload route here.
"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, render_template, request

from crucible import Dataset
from crucible.utils import get_tz_isoformat
from routes import crucible_api
from routes.chip_maps import clean_chiplet_plan, load_chip_map, lock_chip_map
from routes.fab_templates import DEFAULT_TEMPLATE_DEFAULT, FAB_TEMPLATES, get_step, step_applies
from routes.shared import PrinterTimeoutError, cruc_client, publish_barcode
from routes.synthesis_common import (ApiError, add_sample, current_user, explorer_url, parse_body,
                                     register_error_handlers)
from routes.synthesis_models import PrintLabelRequest, StepEditRequest, StepRecordRequest, WaferCreateRequest

logger = logging.getLogger(__name__)
fabrication_bp = Blueprint("fabrication", __name__)
register_error_handlers(fabrication_bp)

CHILD_TYPE = {"create_chiplets": "chiplet", "create_chips": "chip"}
ALLOWED_PARENT_TYPES = {"create_chiplets": {"wafer"}, "create_chips": {"wafer", "chiplet"}}


def get_template(template_id):
    template = FAB_TEMPLATES.get(template_id)
    if not template:
        raise ApiError(400, f"Unknown template: {template_id}")
    return template


def check_template_default(template, default_id):
    if default_id not in template["template_defaults"]:
        raise ApiError(400, f"Unknown template default: {default_id}")
    return default_id


def clean_value(field, value, where):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field["type"] == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ApiError(400, f"{where} '{field['label']}' must be a number, got '{value}'")
        return int(number) if number.is_integer() else number
    return str(value).strip()


def clean_parameters(step, values):
    """Wafer specification fields; keep only declared keys."""
    declared = {p["key"]: p for p in step["parameters"]}
    unknown = set(values) - set(declared)
    if unknown:
        raise ApiError(400, f"Unknown fields for {step['label']}: {sorted(unknown)}")
    return {key: clean_value(field, values.get(key), step["label"]) for key, field in declared.items()}


def clean_rows(step, values):
    """Validate {row_key: {field_key: value}} against the step's rows.

    Returns the rows as stored (template order, every field) and a flat {row_field: value}
    map of the filled-in values for searching.
    """
    template_rows = {r["key"]: r for r in step["rows"]}
    unknown_rows = set(values) - set(template_rows)
    if unknown_rows:
        raise ApiError(400, f"Unknown rows for {step['label']}: {sorted(unknown_rows)}")
    rows, flat = [], {}
    for row in step["rows"]:
        given = values.get(row["key"]) or {}
        fields = {f["key"]: f for f in row["fields"]}
        unknown = set(given) - set(fields)
        if unknown:
            raise ApiError(400, f"Unknown fields for {step['label']} {row['process']}: {sorted(unknown)}")
        cleaned = {key: clean_value(field, given.get(key), f"{step['label']} {row['process']}")
                   for key, field in fields.items()}
        rows.append({"key": row["key"], "process": row["process"], "values": cleaned})
        flat.update({f"{row['key']}_{key}": v for key, v in cleaned.items() if v is not None})
    return rows, flat


def unit_summary(sample, parent_id, project):
    # Map-derived fields let Step 19 put each chip under the chiplet cut from its block.
    meta = sample.get("scientific_metadata") or {}
    chip_details = {k: meta[k] for k in ("chip_id", "block", "label", "outline_mm", "mask_design") if k in meta}
    return {
        "unique_id": sample["unique_id"],
        "sample_name": sample.get("sample_name"),
        "sample_type": sample.get("sample_type"),
        "parent_id": parent_id,
        "explorer_url": explorer_url(project, sample["unique_id"]),
        "chip_details": chip_details or None,
    }


def get_tree(wafer):
    """Wafer plus its chiplets and chips, as a flat list with parent ids."""
    project = wafer.get("project_id")
    units = [unit_summary(wafer, None, project)]
    frontier = [wafer["unique_id"]]
    while frontier:
        next_frontier = []
        for parent_id in frontier:
            # The nested child listing has no metadata option; fetching it separately
            # preserves map provenance for chiplets and chips in the traveler.
            for child in cruc_client.samples.list(parent_mfid=parent_id, limit=None):
                if child.get("sample_type") in ("chiplet", "chip"):
                    child = cruc_client.samples.get(child["unique_id"], include_metadata=True)
                    units.append(unit_summary(child, parent_id, project))
                    next_frontier.append(child["unique_id"])
        frontier = next_frontier
    parent_ids = {u["parent_id"] for u in units}
    for u in units:
        u["is_leaf"] = u["unique_id"] not in parent_ids
    return units


def collect_records(units, template_id):
    """Step datasets linked to any unit in the tree, keyed by dataset id."""
    def fetch(unit_id):
        return unit_id, cruc_client.datasets.list(sample_mfid=unit_id, include_metadata=True, limit=None)

    records = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for unit_id, datasets in pool.map(fetch, [u["unique_id"] for u in units]):
            for ds in datasets:
                meta = ds.get("scientific_metadata") or {}
                if meta.get("fab_template") != template_id:
                    continue
                rec = records.setdefault(ds["unique_id"], {
                    "dataset_id": ds["unique_id"],
                    "step_id": meta.get("fab_step_id"),
                    "status": meta.get("status"),
                    "step_date": meta.get("step_date"),
                    "operator": meta.get("operator"),
                    "parameters": meta.get("parameters") or {},
                    "rows": meta.get("rows") or [],
                    "values": meta.get("values") or {},
                    "comments": meta.get("comments"),
                    "created_children": meta.get("created_children"),
                    "edited_by": meta.get("edited_by"),
                    "edited_at": meta.get("edited_at"),
                    "wafer_options": meta.get("wafer_options"),
                    "planned_chiplets": meta.get("planned_chiplets"),
                    "template_default": meta.get("template_default"),
                    "unit_ids": [],
                })
                rec["unit_ids"].append(unit_id)
    return list(records.values())


def load_wafer(wafer_id):
    try:
        wafer = cruc_client.samples.get(wafer_id, include_datasets=False)
    except Exception:
        wafer = None
    if not wafer or wafer.get("sample_type") != "wafer":
        raise ApiError(404, f"Wafer {wafer_id} not found")
    # Wafers are only visible to users of the wafer's project.
    current_user(wafer.get("project_id"))
    return wafer


def find_template_id(wafer_id):
    """A traveler wafer carries its template id on its Step 0 dataset."""
    for ds in cruc_client.datasets.list(sample_mfid=wafer_id, include_metadata=True, limit=None):
        meta = ds.get("scientific_metadata") or {}
        if meta.get("fab_step_id") == "wafer_spec" and meta.get("fab_template") in FAB_TEMPLATES:
            return meta["fab_template"]
    raise ApiError(404, "This wafer has no traveler (no wafer specification record)")


def create_step_dataset(project, orcid, template_id, step, wafer, metadata, target_ids):
    ds_obj = Dataset(dataset_name=f"{step['label']} {step['name']} - {wafer['sample_name']}",
                     public=False,
                     owner=orcid,
                     project_id=project,
                     measurement=step["name"],
                     timestamp=get_tz_isoformat())
    keywords = [k for k in [template_id, step["id"], step.get("tool"), wafer["sample_name"]] if k]
    new_ds = cruc_client.datasets.create(ds_obj, keywords=keywords)
    dataset_id = new_ds["created_record"]["unique_id"]
    crucible_api.add_scientific_metadata(dataset_id, metadata)

    link_errors = []
    for target_id in target_ids:
        try:
            cruc_client.samples.link_dataset(target_id, dataset_id)
        except Exception as err:
            logger.error(f"Linking dataset {dataset_id} to {target_id} failed: {err}")
            link_errors.append(f"{target_id}: {err}")
    return dataset_id, link_errors


def step_metadata(template_id, step, wafer, req_status, step_date, operator, comments, **fields):
    return {
        "fab_template": template_id,
        "fab_step_id": step["id"],
        "step_label": step["label"],
        "step_name": step["name"],
        "status": req_status,
        "step_date": step_date,
        "operator": operator,
        "wafer_id": wafer["unique_id"],
        "wafer_name": wafer["sample_name"],
        "comments": comments,
        **fields,
    }


def name_taken(name, project):
    return bool(cruc_client.samples.list(sample_name=name, project_id=project))


@fabrication_bp.route("/")
@fabrication_bp.route("/wafer/<wafer_id>")
def page(wafer_id=None):
    return render_template("fabrication.html", wafer_id=wafer_id)


@fabrication_bp.route("/masks/")
@fabrication_bp.route("/masks/<mask_id>")
def masks_page(mask_id=None):
    return render_template("fabrication.html", mask_id=mask_id)


@fabrication_bp.route("/api/templates", methods=["GET"])
def list_templates():
    return jsonify({"templates": FAB_TEMPLATES})


@fabrication_bp.route("/api/wafers", methods=["GET"])
def list_wafers():
    project = request.args.get("project", "")
    current_user(project)
    wafers = cruc_client.samples.list(project_id=project, sample_type="wafer", limit=None)
    return jsonify({"wafers": [{
        "unique_id": w["unique_id"],
        "sample_name": w.get("sample_name"),
        "description": w.get("description"),
        "timestamp": w.get("timestamp"),
    } for w in wafers]})


@fabrication_bp.route("/api/wafers", methods=["POST"])
def create_wafer():
    req = parse_body(WaferCreateRequest)
    user = current_user(req.project)
    template = get_template(req.template_id)
    name = req.wafer_name.strip()
    if not name:
        raise ApiError(400, "Wafer name is required")
    for option, allowed in template["wafer_options"].items():
        if req.wafer_options.get(option) not in allowed:
            raise ApiError(400, f"'{option}' must be one of {allowed}")
    if name_taken(name, req.project):
        raise ApiError(409, f"A sample named '{name}' already exists in {req.project}")

    template_default = check_template_default(template, req.template_default)
    spec_step = template["wafer_spec"]
    spec = clean_parameters(spec_step, req.spec)
    if spec.get("mask_design"):
        load_chip_map(spec["mask_design"], project=req.project)
    planned_chiplets = clean_chiplet_plan(req.planned_chiplets, spec.get("mask_design"), req.project)
    wafer_options = {k: req.wafer_options[k] for k in template["wafer_options"]}

    new_wafer = add_sample(orcid=user["orcid"], project=req.project, sample_name=name,
                           description=req.description, sample_type="wafer")
    wafer = {"unique_id": new_wafer["unique_id"], "sample_name": name}
    step_date = req.step_date or get_tz_isoformat()[:10]
    metadata = step_metadata(req.template_id, spec_step, wafer, "done", step_date, user["user_name"], None,
                             parameters=spec, wafer_options=wafer_options, template_default=template_default,
                             planned_chiplets=planned_chiplets)
    dataset_id, link_errors = create_step_dataset(req.project, user["orcid"], req.template_id, spec_step,
                                                  wafer, metadata, [wafer["unique_id"]])
    if spec.get("mask_design"):
        try:
            lock_chip_map(spec["mask_design"], wafer["unique_id"], name)
        except Exception as err:
            logger.error("Locking chip map %s failed: %s", spec["mask_design"], err)
            link_errors.append(f"Chip map could not be marked as used: {err}")
    return jsonify({"wafer": {**wafer, "explorer_url": explorer_url(req.project, wafer["unique_id"])},
                    "dataset_id": dataset_id, "errors": link_errors})


@fabrication_bp.route("/api/wafers/<wafer_id>/traveler", methods=["GET"])
def get_traveler(wafer_id):
    wafer = load_wafer(wafer_id)
    template_id = find_template_id(wafer_id)
    template = FAB_TEMPLATES[template_id]
    units = get_tree(wafer)
    records = collect_records(units, template_id)

    spec_record = next((r for r in records if r["step_id"] == "wafer_spec"), None)
    wafer_options = (spec_record or {}).get("wafer_options") or {}
    spec = (spec_record or {}).get("parameters") or {}
    chip_map = load_chip_map(spec["mask_design"]) if spec.get("mask_design") else None

    steps = []
    for step in template["steps"]:
        if not step_applies(step, wafer_options):
            continue
        step_records = sorted((r for r in records if r["step_id"] == step["id"]),
                              key=lambda r: r["step_date"] or "")
        statuses = {r["status"] for r in step_records}
        status = "done" if "done" in statuses else "skipped" if statuses else "pending"
        steps.append({**step, "status": status, "records": step_records})

    return jsonify({
        "template_id": template_id,
        "template_name": template["name"],
        "project": wafer.get("project_id"),
        "label_after_step": template.get("label_after_step"),
        "template_defaults": template["template_defaults"],
        "template_default": (spec_record or {}).get("template_default") or DEFAULT_TEMPLATE_DEFAULT,
        "wafer": units[0],
        "wafer_options": wafer_options,
        "spec": spec,
        "planned_chiplets": (spec_record or {}).get("planned_chiplets"),
        "chip_map": chip_map,
        "spec_record": spec_record,
        "units": units,
        "steps": steps,
    })


def clean_child_details(planned, details, wafer_map_id, project, unit_by_id, action, units):
    """Bind every map-derived child to the wafer's exact map and physical parent block."""
    if not wafer_map_id:
        if details:
            raise ApiError(400, "This wafer has no reviewed chip map")
        return {}
    chip_map = load_chip_map(wafer_map_id, project=project)["chip_map"]
    blocks = {b["id"]: b for b in chip_map["blocks"]}
    blocks.update({b["name"]: b for b in blocks.values()})
    chips = {c["id"]: c for c in chip_map["chips"]}
    missing = set(details) ^ {name for _, name in planned}
    if missing:
        raise ApiError(400, f"Map-derived children need exactly one metadata entry: {sorted(missing)}")

    cleaned = {}
    for parent_id, name in planned:
        fields = details[name]
        if not isinstance(fields, dict):
            raise ApiError(400, f"Chip details for {name} must be an object")
        required = ({"chip_id", "block", "label", "outline_mm", "mask_design"}
                    if action == "create_chips" else {"block", "outline_mm", "mask_design"})
        unknown = set(fields) - required
        missing_fields = required - set(fields)
        if unknown:
            raise ApiError(400, f"Unknown chip detail fields for {name}: {sorted(unknown)}")
        if missing_fields:
            raise ApiError(400, f"Missing chip detail fields for {name}: {sorted(missing_fields)}")
        if fields.get("mask_design") != wafer_map_id:
            raise ApiError(400, f"{name}: child details must use the wafer's reviewed chip map")
        supplied_block = fields.get("block")
        block = blocks.get(supplied_block) if isinstance(supplied_block, str) else None
        if block is None:
            raise ApiError(400, f"Unknown block for {name}")
        outline = fields.get("outline_mm")
        if (not isinstance(outline, list) or len(outline) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in outline)
                or outline[2] <= outline[0] or outline[3] <= outline[1]):
            raise ApiError(400, f"Invalid outline_mm for {name}")

        parent = unit_by_id[parent_id]
        parent_details = parent.get("chip_details")
        if parent["sample_type"] == "chiplet" and parent_details:
            parent_block = blocks.get(parent_details.get("block"))
            if parent_details.get("mask_design") != wafer_map_id or not parent_block:
                raise ApiError(400, f"{parent['sample_name']} uses a different or invalid chip map")
            if parent_block["id"] != block["id"]:
                raise ApiError(400, f"{name}: chip block does not match parent {parent['sample_name']}")

        if action == "create_chiplets":
            members = [c["outline"] for c in chip_map["chips"] if c["block"] == block["id"]]
            if not members:
                raise ApiError(400, f"{name}: the chiplet's block has no chips")
            expected_outline = [min(o[0] for o in members), min(o[1] for o in members),
                                max(o[2] for o in members), max(o[3] for o in members)]
            if outline != expected_outline:
                raise ApiError(400, f"{name}: chiplet outline must cover all chips in {block['id']}")
            cleaned[name] = {"block": block["id"], "outline_mm": expected_outline,
                             "mask_design": wafer_map_id}
        else:
            chip_id = fields.get("chip_id")
            chip = chips.get(chip_id) if isinstance(chip_id, str) else None
            if chip is None:
                raise ApiError(400, f"Unknown chip_id '{chip_id}' for {name}")
            if chip["block"] != block["id"]:
                raise ApiError(400, f"Chip {chip_id} does not belong to block {block['id']}")
            if outline != chip["outline"] or fields.get("label") != chip["label"]:
                raise ApiError(400, f"{name}: chip metadata must match the reviewed map")
            cleaned[name] = {"chip_id": chip_id, "block": block["id"], "label": chip["label"],
                             "outline_mm": list(chip["outline"]), "mask_design": wafer_map_id}

    # Prevent duplicate blocks beneath one wafer or re-cutting an existing chip through a raw request.
    seen = set()
    existing_chips = {u["chip_details"].get("chip_id") for u in units
                      if u["sample_type"] == "chip" and u.get("chip_details")
                      and u["chip_details"].get("mask_design") == wafer_map_id}
    for parent_id, name in planned:
        detail = cleaned[name]
        if action == "create_chips" and detail["chip_id"] in existing_chips:
            raise ApiError(409, f"Chip {detail['chip_id']} has already been cut")
        identity = ((parent_id, detail["block"]) if action == "create_chiplets"
                    else detail["chip_id"])
        if identity in seen:
            raise ApiError(400, f"Duplicate map selection for {name}")
        seen.add(identity)
    return cleaned


@fabrication_bp.route("/api/steps", methods=["POST"])
def record_step():
    req = parse_body(StepRecordRequest)
    user = current_user(req.project)
    template = get_template(req.template_id)
    if req.template_default is not None:
        check_template_default(template, req.template_default)
    step = get_step(req.template_id, req.step_id)
    if not step or step["id"] == "wafer_spec":
        raise ApiError(400, f"Unknown step: {req.step_id}")
    if req.status == "skipped" and not step["optional"]:
        raise ApiError(400, f"{step['label']} is required and can't be skipped")

    wafer = load_wafer(req.wafer_id)
    if wafer.get("project_id") != req.project:
        raise ApiError(400, "This wafer belongs to a different project")
    if find_template_id(req.wafer_id) != req.template_id:
        raise ApiError(400, "Template does not match this wafer's traveler")
    units = get_tree(wafer)
    unit_by_id = {u["unique_id"]: u for u in units}

    spec_record = next((r for r in collect_records(units[:1], req.template_id)
                        if r["step_id"] == "wafer_spec"), None)
    if not step_applies(step, (spec_record or {}).get("wafer_options") or {}):
        raise ApiError(400, f"{step['label']} does not apply to this wafer")

    target_ids = list(dict.fromkeys(req.target_ids))
    if not target_ids:
        raise ApiError(400, "Select at least one wafer/chiplet/chip")
    outside = [t for t in target_ids if t not in unit_by_id]
    if outside:
        raise ApiError(400, f"Not part of this wafer: {outside}")

    rows, values = clean_rows(step, req.rows) if req.status == "done" else ([], {})

    created, errors = [], []
    action = step.get("action")
    if action and req.status == "done":
        child_type = CHILD_TYPE[action]
        planned = []
        for parent_id, names in req.new_children.items():
            parent = unit_by_id.get(parent_id)
            if not parent or parent["sample_type"] not in ALLOWED_PARENT_TYPES[action]:
                raise ApiError(400, f"Can't create {child_type}s under {parent_id}")
            if not parent["is_leaf"]:
                raise ApiError(400, f"{parent['sample_name']} has already been cut")
            for name in names:
                if name.strip():
                    planned.append((parent_id, name.strip()))
        if not planned:
            raise ApiError(400, f"Enter at least one {child_type} name")
        planned_names = {n for _, n in planned}
        unknown_details = set(req.child_details) - planned_names
        if unknown_details:
            raise ApiError(400, f"Chip details supplied for unknown children: {sorted(unknown_details)}")
        child_details = clean_child_details(
            planned, req.child_details, ((spec_record or {}).get("parameters") or {}).get("mask_design"),
            req.project, unit_by_id, action, units,
        )
        all_names = [n for _, n in planned]
        dupes = sorted({n for n in all_names if all_names.count(n) > 1})
        if dupes:
            raise ApiError(400, f"Duplicate names: {dupes}")
        taken = [n for n in all_names if name_taken(n, req.project)]
        if taken:
            raise ApiError(409, f"Names already used in {req.project}: {taken}")

        for parent_id, name in planned:
            try:
                child = add_sample(orcid=user["orcid"], project=req.project, sample_name=name,
                                   description=f"{child_type} of {unit_by_id[parent_id]['sample_name']}",
                                   sample_type=child_type)
                if name in child_details:
                    crucible_api.add_scientific_metadata(child["unique_id"], child_details[name])
                cruc_client.samples.link(parent_id, child["unique_id"])
                created.append({"unique_id": child["unique_id"], "sample_name": name,
                                "sample_type": child_type, "parent_id": parent_id,
                                "explorer_url": explorer_url(req.project, child["unique_id"])})
            except Exception as err:
                logger.error(f"Creating {child_type} {name} failed: {err}")
                errors.append(f"{name}: {err}")
        # The cut is recorded on the units that were cut.
        target_ids = list(dict.fromkeys(p for p, _ in planned))

    metadata = step_metadata(req.template_id, step, wafer, req.status, req.step_date, user["user_name"],
                             req.comments, rows=rows, values=values, created_children=created or None,
                             template_default=req.template_default)
    dataset_id, link_errors = create_step_dataset(req.project, user["orcid"], req.template_id, step,
                                                  wafer, metadata, target_ids)
    errors.extend(link_errors)
    return jsonify({"success": not errors, "dataset_id": dataset_id, "created": created, "errors": errors})


@fabrication_bp.route("/api/printers", methods=["GET"])
def list_printers():
    return jsonify({"printers": crucible_api.list_printers()})


@fabrication_bp.route("/api/print", methods=["POST"])
def print_label():
    req = parse_body(PrintLabelRequest)
    current_user()
    try:
        sample = cruc_client.samples.get(req.sample_id, include_datasets=False)
    except Exception:
        sample = None
    if not sample:
        raise ApiError(404, f"Sample {req.sample_id} not found")
    current_user(sample.get("project_id"))
    try:
        publish_barcode(req.printer_id, sample["unique_id"], sample.get("sample_name") or "")
    except ValueError as err:
        raise ApiError(400, str(err))
    except PrinterTimeoutError as err:
        return jsonify({"success": False, "status": "timeout", "detail": str(err)})
    except RuntimeError as err:
        return jsonify({"success": False, "status": "error", "detail": str(err)})
    return jsonify({"success": True, "status": "ok", "detail": None})


def http_status(err):
    return getattr(getattr(err, "response", None), "status_code", None)


def load_step_record(dataset_id):
    try:
        ds = cruc_client.datasets.get(dataset_id, include_metadata=True)
    except Exception:
        ds = None
    meta = (ds or {}).get("scientific_metadata") or {}
    template_id = meta.get("fab_template")
    step = get_step(template_id, meta.get("fab_step_id")) if template_id in FAB_TEMPLATES else None
    if not step:
        raise ApiError(404, f"No traveler step record {dataset_id}")
    current_user(ds.get("project_id"))
    return meta, step


@fabrication_bp.route("/api/steps/<dataset_id>", methods=["GET"])
def get_step_record(dataset_id):
    meta, step = load_step_record(dataset_id)
    files = cruc_client.datasets.list_files(dataset_id)
    try:
        links = cruc_client.datasets.get_download_links(dataset_id) if files else {}
    except Exception as err:
        logger.warning(f"Download links for {dataset_id} unavailable: {err}")
        links = {}
    return jsonify({
        "dataset_id": dataset_id,
        "step": step,
        "record": meta,
        "files": [{"mfid": f.get("mfid"), "filename": f.get("filename"), "size": f.get("size"),
                   "url": links.get(f.get("mfid"))} for f in files],
    })


@fabrication_bp.route("/api/steps/<dataset_id>", methods=["PUT"])
def edit_step_record(dataset_id):
    req = parse_body(StepEditRequest)
    user = current_user()
    meta, step = load_step_record(dataset_id)
    updated = {
        **meta,
        "step_date": req.step_date,
        "comments": req.comments,
        "edited_by": user["user_name"],
        "edited_at": get_tz_isoformat(),
    }
    if step["id"] == "wafer_spec":
        updated["parameters"] = clean_parameters(step, req.parameters)
        old_map = (meta.get("parameters") or {}).get("mask_design")
        new_map = updated["parameters"].get("mask_design")
        existing_plan = meta.get("planned_chiplets")
        if new_map != old_map and existing_plan and req.planned_chiplets is None:
            raise ApiError(400, "Changing the chip map requires reviewing or clearing the planned chiplets")
        supplied_plan = req.planned_chiplets if req.planned_chiplets is not None else (
            (existing_plan or {}).get("chiplets") or [])
        updated["planned_chiplets"] = clean_chiplet_plan(
            supplied_plan, new_map, load_wafer(meta["wafer_id"]).get("project_id"))
    elif meta.get("status") == "done":
        updated["rows"], updated["values"] = clean_rows(step, req.rows)
    if step["id"] == "wafer_spec" and updated["parameters"].get("mask_design"):
        load_chip_map(updated["parameters"]["mask_design"], project=load_wafer(meta["wafer_id"]).get("project_id"))
    try:
        cruc_client.datasets.update_scientific_metadata(dataset_id, updated, overwrite=True)
        if step["id"] == "wafer_spec" and updated["parameters"].get("mask_design"):
            lock_chip_map(updated["parameters"]["mask_design"], meta["wafer_id"], meta["wafer_name"])
    except Exception as err:
        if http_status(err) == 403:
            raise ApiError(403, "Editing needs edit permission for the app's service account "
                                "on this Crucible project. Ask a Crucible admin to grant it.")
        raise
    return jsonify({"success": True, "record": updated})
