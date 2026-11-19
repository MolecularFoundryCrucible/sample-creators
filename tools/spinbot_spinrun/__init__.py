"""SpinBot SpinRun Uploader tool plugin.

Uploads SpinBot spin_run .h5 files with optional companion deposition .yaml logs,
extracts embedded run_id / trays, and provides batch tray barcode printing.
"""
from __future__ import annotations

import logging
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, session

from routes.multi_uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    existing_user_project_dsids,
    hub_dataset_url,
    register_logbook_routes,
    require_user_and_project,
    resolve_dsid_for_sha256,
    verify_sample_in_project,
)
from routes.shared import PrinterTimeoutError, cruc_client, publish_barcode

logger = logging.getLogger(__name__)

spinbot_spinrun_bp = Blueprint("spinbot_spinrun", __name__)

NAME = "spinbot_spinrun"
KEY = "spinbot_spinrun"
DIVISION = "b67"
ORDER = 220
BLUEPRINT = spinbot_spinrun_bp
URL_PREFIX = "/spinbot-spinrun"
ENDPOINT = "spinbot_spinrun.page"
NAV_LABEL = "Inorganic - SpinBot"
CARD_TITLE = "Inorganic - SpinBot"
CARD_DESCRIPTION = "Upload SpinBot spin_run .h5 files with optional companion deposition .yaml logs and batch tray barcode printing."
INSTRUMENT_ID = "spinbot"
INSTRUMENT_MFID = "0sh6zrzxhxsa100089bznryq88"
INGESTOR = "SpinbotSpinRunIngestor"
UI_MODE = "standard"
POST_PROCESSING = []


@spinbot_spinrun_bp.route("/")
def page():
    return render_template("spinbot_spinrun.html")


@spinbot_spinrun_bp.route("/api/print-trays", methods=["POST"])
def print_trays():
    if not session.get("user"):
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    trays = data.get("trays") or []
    printer_id = (data.get("printer_id") or "b30-113").strip()

    if not trays:
        return jsonify({"error": "No trays provided to print"}), 400
    if len(trays) > 50:
        return jsonify({"error": "Too many trays in one print batch (max 50)"}), 400

    printed = 0
    errors = []
    for tray in trays:
        mfid = tray.get("mfid")
        name = tray.get("name") or ""
        if not mfid:
            continue
        try:
            publish_barcode(printer=printer_id, mfid=mfid, name=name)
            printed += 1
        except PrinterTimeoutError as e:
            logger.error(f"Printer timeout printing tray {mfid}: {e}")
            errors.append(f"{name or mfid}: printer timeout")
            break
        except Exception as e:
            logger.error(f"Failed to print tray {mfid}: {e}")
            errors.append(f"{name or mfid}: {e}")

    if errors and printed == 0:
        return jsonify({"error": "; ".join(errors)}), 500

    return jsonify({"ok": True, "count": printed, "errors": errors})


@spinbot_spinrun_bp.route("/api/create-upload", methods=["POST"])
def create_upload():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    if not filename:
        return jsonify({"error": "filename is required"}), 400

    yaml_filename = (data.get("yaml_filename") or "").strip() or None
    embedded_dsid = (data.get("embedded_dsid") or "").strip() or None
    sha256 = (data.get("sha256") or "").strip() or None
    sample_uuid = (data.get("sample_uuid") or "").strip() or None
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
    dataset_name = f"{stem} SpinRun"
    sci_meta = {"filename": filename}
    if yaml_filename:
        sci_meta["yaml_companion"] = yaml_filename
    if comments:
        sci_meta["comments"] = comments

    if sample_uuid:
        try:
            verify_sample_in_project(sample_uuid, project_id)
        except CrossProjectError as e:
            return jsonify({"error": str(e)}), 403
        except LookupError as e:
            return jsonify({"error": str(e)}), 404

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

        if sample_uuid:
            try:
                cruc_client.datasets.link_sample(dataset_mfid=dsid, sample_mfid=sample_uuid)
            except Exception as e:
                logger.warning(f"Failed to link sample {sample_uuid} to {dsid}: {e}")

        return jsonify({
            "dataset_mfid": dsid,
            "is_existing": is_existing,
            "hub_url": hub_dataset_url(dsid),
        })

    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        logger.error(f"Failed to create/update spinbot dataset: {e}")
        return jsonify({"error": str(e)}), 500


register_logbook_routes(
    spinbot_spinrun_bp,
    prod_instrument_mfid=INSTRUMENT_MFID,
    log_prefix="spinbot_spinrun",
    csv_filename="spinbot_spinrun_recent_datasets.csv",
)
