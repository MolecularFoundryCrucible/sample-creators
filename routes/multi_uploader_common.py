"""Shared backend helpers for Group 2 multi-uploaders (inorganic_xrd, spinbot_spinrun,
spinbot_photobox, nirvana).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import jsonify, request, session

from crucible import Dataset, Sample
from crucible.utils import get_tz_isoformat
from crucible.utils.identifiers import is_mfid
from routes.deposition_common import LA_TZ, clean, csv_response, incremental_refresh_rows, parse_ts, pick
from routes.shared import cruc_client, format_user, instrument_mfid, publish_barcode
from routes.uploader_common import CrossProjectError, verify_sample_in_project

logger = logging.getLogger(__name__)

HUB_BASE_URL = os.environ.get("CRUCIBLE_HUB_URL", "https://crucible.lbl.gov/hub").rstrip("/")


def hub_dataset_url(dsid: str) -> str:
    """Generate link to view dataset in Crucible Web Hub."""
    return f"{HUB_BASE_URL}/datasets/{dsid}"


def require_user_and_project() -> tuple[dict | None, tuple[Any, int] | None]:
    """Retrieve logged-in user and validated selected project from Flask session."""
    user = session.get("user")
    if not user:
        return None, (jsonify({"error": "Not logged in"}), 401)
    project_id = user.get("selected_project")
    if not project_id:
        return None, (jsonify({"error": "No selected project"}), 400)
    return user, None


def existing_user_project_dsids(orcid: str, project_id: str) -> set[str]:
    """Return set of all dataset unique_ids owned by user in project."""
    try:
        ds_list = cruc_client.datasets.list(owner_ref=orcid, project_id=project_id, limit=None)
    except TypeError:
        ds_list = cruc_client.datasets.list(project_id=project_id, limit=None)

    valid_ids = set()
    for ds in ds_list:
        uid = ds.get("unique_id")
        if not uid:
            continue
        owner = ds.get("owner")
        owner_id = ds.get("owner_orcid") or (owner.get("unique_id") if isinstance(owner, dict) else owner)
        if orcid and owner_id and owner_id != orcid:
            continue
        valid_ids.add(uid)
    return valid_ids


def resolve_dsid_for_sha256(sha256_hash: str, valid_dsids: set[str]) -> tuple[str | None, bool]:
    """Check if file with sha256_hash has already been uploaded to one of valid_dsids."""
    if not sha256_hash:
        return None, False
    try:
        file_records = cruc_client.files.list(sha256_hash=sha256_hash, limit=100)
    except Exception as e:
        logger.warning(f"Error querying files by sha256: {e}")
        return None, False

    for f in file_records:
        ds_mfid = f.get("dataset_mfid")
        if ds_mfid and ds_mfid in valid_dsids:
            return ds_mfid, True
    return None, False


def dataset_exists(dsid: str) -> bool:
    """Check if a dataset record already exists in Crucible."""
    if not dsid or not isinstance(dsid, str) or not is_mfid(dsid):
        return False
    try:
        rec = cruc_client.datasets.get(dsid)
        return bool(rec and rec.get("unique_id"))
    except Exception:
        return False


def create_or_update_dataset(
    *,
    orcid: str,
    project_id: str,
    prod_instrument_mfid: str,
    dsid: str | None = None,
    dataset_name: str | None = None,
    measurement: str | None = None,
    data_type: str | None = None,
    session_name: str | None = None,
    scientific_metadata: dict | None = None,
    keywords: list[str] | None = None,
) -> tuple[str, bool]:
    """Create a new dataset or update existing dataset fields, metadata and keywords."""
    inst_mfid = instrument_mfid(prod_instrument_mfid)
    reused = False
    if dsid and is_mfid(dsid):
        try:
            existing = cruc_client.datasets.get(dsid)
        except Exception:
            existing = None
        if existing and existing.get("unique_id"):
            existing_proj = existing.get("project_id") or (existing.get("project") or {}).get("project_id")
            if existing_proj != project_id:
                raise CrossProjectError(f"Dataset '{dsid}' belongs to project '{existing_proj}', not '{project_id}'")
            reused = True

    if reused:
        updates: dict[str, Any] = {}
        if dataset_name is not None:
            updates["dataset_name"] = dataset_name
        if measurement is not None:
            updates["measurement"] = measurement
        if data_type is not None:
            updates["data_type"] = data_type
        if session_name is not None:
            updates["session_name"] = session_name
        if updates:
            cruc_client.datasets.update(dsid, **updates)
        if scientific_metadata:
            cruc_client.datasets.update_scientific_metadata(dsid, scientific_metadata)
        for kw in (keywords or []):
            if kw:
                cruc_client.datasets.add_keyword(dsid, kw)
        return dsid, True
    else:
        name = dataset_name or f"{datetime.now(LA_TZ).strftime('%Y%m%d_%H%M%S')}_upload"
        valid_uid = dsid if (dsid and is_mfid(dsid)) else None
        ds = Dataset(
            unique_id=valid_uid,
            dataset_name=name,
            owner=orcid,
            project_id=project_id,
            instrument_mfid=inst_mfid,
            measurement=measurement,
            data_type=data_type,
            session_name=session_name,
            timestamp=get_tz_isoformat(),
        )
        resp = cruc_client.datasets.create(
            ds,
            scientific_metadata=scientific_metadata or {},
            keywords=[k for k in (keywords or []) if k],
        )
        new_dsid = resp.get("dataset_mfid") or (resp.get("created_record") or {}).get("unique_id")
        return new_dsid, False


def resolve_children_sorted(parent_sample_mfid: str) -> list[dict]:
    """Return sorted child samples of a parent sample."""
    children = cruc_client.samples.list_children(parent_sample_mfid)
    return sorted(
        [
            {
                "unique_id": c.get("unique_id", ""),
                "sample_name": str(c.get("sample_name") or ""),
            }
            for c in children
            if c.get("unique_id")
        ],
        key=lambda x: x["sample_name"],
    )


def resolve_holder_slots(holder_uuids: list[str], layout_slots: list[dict], project_id: str | None = None) -> dict:
    """Map holder sample slots sequentially into S01..Snn slots."""
    all_samples = []
    labels = []
    trays_info = []
    pos = 1

    for i, uuid in enumerate(holder_uuids):
        uuid = (uuid or "").strip()
        if not uuid:
            continue
        if project_id:
            verify_sample_in_project(uuid, project_id)
        holder_cfg = layout_slots[i] if i < len(layout_slots) else {}
        label = holder_cfg.get("label", f"Holder {i + 1}")
        labels.append(label)
        slots = holder_cfg.get("slots", 8)
        try:
            tray_rec = cruc_client.samples.get(uuid)
            tray_name = tray_rec.get("sample_name") or uuid
        except Exception:
            tray_name = uuid
        trays_info.append({"unique_id": uuid, "sample_name": tray_name})

        children = resolve_children_sorted(uuid)
        for j in range(slots):
            if j < len(children):
                c = children[j]
                all_samples.append({
                    "position": f"S{pos:02d}",
                    "name": c.get("sample_name") or "",
                    "uuid": c.get("unique_id") or "",
                    "tray_uuid": uuid,
                    "tray_name": tray_name,
                    "excluded": False,
                })
            else:
                all_samples.append({
                    "position": f"S{pos:02d}",
                    "name": "",
                    "uuid": "",
                    "tray_uuid": uuid,
                    "tray_name": tray_name,
                    "excluded": False,
                })
            pos += 1

    basename = " + ".join(labels) if labels else "Holders"
    return {"basename": basename, "trays": trays_info, "samples": all_samples}


_CAR_RE = re.compile(r"^CAR(\d+)$")


def next_carrier_name(project_id: str) -> str:
    """Find highest existing CARnnnnnn in project and return next in sequence."""
    existing = cruc_client.samples.list(project_id=project_id, sample_type="thin film carrier", limit=None)
    nums = []
    for s in existing:
        name = s.get("sample_name") or ""
        m = _CAR_RE.match(name)
        if m:
            try:
                nums.append(int(m.group(1)))
            except ValueError:
                pass
    if not nums:
        return "CAR000001"
    return f"CAR{max(nums) + 1:06d}"


DEFAULT_LOGBOOK_COLS = ["Date", "User", "Dataset Name", "Measurement", "Comment"]


def default_dataset_to_row(details: dict) -> dict:
    sci = details.get("scientific_metadata") or {}
    dt = parse_ts(details.get("timestamp"))
    return {
        "Date": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
        "User": format_user(details.get("owner"), details.get("owner_orcid") or ""),
        "Dataset Name": details.get("dataset_name") or "",
        "Measurement": details.get("measurement") or "",
        "Comment": sci.get("comment") or sci.get("comments") or "",
        "_dataset_id": details.get("unique_id") or "",
        "_timestamp": details.get("timestamp") or "",
    }


def register_logbook_routes(
    bp,
    *,
    prod_instrument_mfid: str,
    log_prefix: str,
    csv_filename: str,
    dataset_to_row=None,
    logbook_cols=None,
):
    """Register GET /api/recent-datasets and GET /api/recent-datasets/<csv_filename> on bp."""
    instrument = instrument_mfid(prod_instrument_mfid)
    cols = logbook_cols or DEFAULT_LOGBOOK_COLS
    to_row = dataset_to_row or default_dataset_to_row

    def logbook_rows(project_id: str):
        return incremental_refresh_rows(
            cache_key=(log_prefix, project_id, instrument),
            fetch_summaries=lambda: cruc_client.datasets.list(
                project_id=project_id, instrument_mfid=instrument, limit=2000
            ),
            build_row=to_row,
        )

    @bp.route("/api/recent-datasets", methods=["GET"])
    def recent_datasets():
        user, err = require_user_and_project()
        if err:
            return err
        project_id = user["selected_project"]
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 5000))
        except (TypeError, ValueError):
            limit = 100
        try:
            rows = [
                {k: v for k, v in row.items() if not k.startswith("_")}
                for row in logbook_rows(project_id)[:limit]
            ]
            return jsonify({"rows": rows, "count": len(rows)}), 200
        except Exception as e:
            logger.error(f"Failed to fetch recent datasets: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route(f"/api/recent-datasets/{csv_filename}", methods=["GET"])
    def export_recent_datasets_csv():
        user, err = require_user_and_project()
        if err:
            return err
        project_id = user["selected_project"]
        try:
            return csv_response(
                cols,
                logbook_rows(project_id)[:500],
                csv_filename.rsplit(".", 1)[0],
            )
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            return jsonify({"error": str(e)}), 500
