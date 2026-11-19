"""Inorganic Nirvana Uploader tool plugin.

Uploads multi-position Nirvana UV-Vis / PL .h5 scans from file metadata or
2x8 tray holders with automatic per-sample splitting.
"""
from __future__ import annotations

import logging
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request

from routes.multi_uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    existing_user_project_dsids,
    hub_dataset_url,
    register_logbook_routes,
    require_user_and_project,
    resolve_children_sorted,
    resolve_dsid_for_sha256,
    resolve_holder_slots,
    verify_sample_in_project,
)
from routes.shared import cruc_client

logger = logging.getLogger(__name__)

nirvana_bp = Blueprint("nirvana", __name__)

NAME = "nirvana"
KEY = "nirvana"
DIVISION = "b67"
ORDER = 210
BLUEPRINT = nirvana_bp
URL_PREFIX = "/nirvana"
ENDPOINT = "nirvana.page"
NAV_LABEL = "Inorganic - Nirvana"
CARD_TITLE = "Inorganic - Nirvana"
CARD_DESCRIPTION = "Upload multi-position Nirvana UV-Vis / PL .h5 scans from file metadata or 2x8 tray holders with automatic per-sample splitting."
INSTRUMENT_ID = "nirvana-spectrometer"
INSTRUMENT_MFID = "0t8vneqh81rbz000b41bdw6adw"
INGESTOR = "NirvanaMultiPosLineScanIngestor"
UI_MODE = "multi_assignment"
POST_PROCESSING = []
HOLDER_LAYOUTS = {
    "Tray 2×8": [
        {"label": "Tray A", "slots": 8},
        {"label": "Tray B", "slots": 8},
    ],
}
DEFAULT_HOLDER_LAYOUT = "Tray 2×8"


@nirvana_bp.route("/")
def page():
    return render_template("nirvana.html")


@nirvana_bp.route("/api/resolve-holders", methods=["POST"])
def resolve_holders():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    holder_uuids = data.get("holder_uuids") or []
    layout_name = data.get("layout_name") or DEFAULT_HOLDER_LAYOUT
    layout_slots = HOLDER_LAYOUTS.get(layout_name, HOLDER_LAYOUTS[DEFAULT_HOLDER_LAYOUT])

    if not any(holder_uuids):
        return jsonify({"error": "At least one holder UUID is required"}), 400

    try:
        result = resolve_holder_slots(holder_uuids, layout_slots, project_id=user["selected_project"])
        return jsonify(result)
    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to resolve holders: {e}")
        return jsonify({"error": str(e)}), 500


@nirvana_bp.route("/api/prepare-upload", methods=["POST"])
def prepare_upload():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    source = data.get("source") or "file"
    filename = (data.get("filename") or "nirvana_scan.h5").strip()
    embedded_dsid = (data.get("embedded_dsid") or "").strip() or None
    sha256 = (data.get("sha256") or "").strip() or None
    excluded_positions = data.get("excluded_positions") or []
    excluded_uuids = data.get("excluded_uuids") or []
    sample_positions = data.get("sample_positions") or {}
    tray_uuids = data.get("tray_uuids") or []
    trays = data.get("trays") or []
    comments = (data.get("comments") or "").strip() or None
    keywords = data.get("keywords") or []

    orcid = user["orcid"]
    project_id = user["selected_project"]

    target_dsid = None
    if embedded_dsid:
        target_dsid = embedded_dsid
    elif sha256:
        valid_dsids = existing_user_project_dsids(orcid, project_id)
        reused_dsid, _ = resolve_dsid_for_sha256(sha256, valid_dsids)
        target_dsid = reused_dsid

    stem = Path(filename).stem
    dataset_name = f"{stem} Nirvana Scan"

    sci_meta: dict = {"filename": filename}
    if source == "file":
        if excluded_uuids:
            sci_meta["skipped thin films"] = excluded_uuids
        if excluded_positions:
            sci_meta["skipped_positions"] = excluded_positions
        if comments:
            sci_meta["comments"] = comments
    elif source == "holders":
        try:
            for tray_id in tray_uuids:
                if tray_id:
                    verify_sample_in_project(tray_id, project_id)
            for pos, sinfo in sample_positions.items():
                s_uid = sinfo.get("sample_uuid") if isinstance(sinfo, dict) else sinfo
                if s_uid:
                    verify_sample_in_project(s_uid, project_id)
        except CrossProjectError as e:
            return jsonify({"error": str(e)}), 403
        except LookupError as e:
            return jsonify({"error": str(e)}), 404

        if sample_positions:
            sci_meta["sample_positions"] = sample_positions
        if tray_uuids:
            sci_meta["tray_uuids"] = tray_uuids
        if trays:
            sci_meta["trays"] = trays
        if excluded_positions:
            sci_meta["skipped_positions"] = excluded_positions
        if comments:
            sci_meta["comments"] = comments

    try:
        dsid, is_existing = create_or_update_dataset(
            orcid=orcid,
            project_id=project_id,
            prod_instrument_mfid=INSTRUMENT_MFID,
            dsid=target_dsid,
            dataset_name=dataset_name,
            measurement=None,
            data_type=None,
            scientific_metadata=sci_meta,
            keywords=keywords,
        )

        # In holders mode, link tray samples to the parent dataset if available
        if source == "holders" and tray_uuids:
            for tray_id in tray_uuids:
                if tray_id:
                    try:
                        cruc_client.datasets.link_sample(dataset_mfid=dsid, sample_mfid=tray_id)
                    except Exception as e:
                        logger.warning(f"Could not link tray {tray_id} to dataset {dsid}: {e}")

        return jsonify({
            "dataset_mfid": dsid,
            "is_existing": is_existing,
            "hub_url": hub_dataset_url(dsid),
        })

    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        logger.error(f"Failed to prepare nirvana upload: {e}")
        return jsonify({"error": str(e)}), 500

    except Exception as e:
        logger.error(f"Failed to prepare Nirvana dataset: {e}")
        return jsonify({"error": str(e)}), 500


register_logbook_routes(
    nirvana_bp,
    prod_instrument_mfid=INSTRUMENT_MFID,
    log_prefix="nirvana",
    csv_filename="nirvana_recent_datasets.csv",
)
