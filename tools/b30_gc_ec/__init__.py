"""B30 GC-EC tool plugin: Bio-Logic EC-Lab (.mpt) and GC (.log) files with preview review.

Supports interactive metadata preview, material sample MFID resolution
(anode, cathode, electrolyte), and direct Crucible file upload.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from routes.shared import cruc_client
from routes.uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    existing_user_project_dsids,
    hub_dataset_url,
    lookup_sample_in_project,
    register_common_uploader_routes,
    require_logged_in_user,
    resolve_dsid_for_sha256,
    verify_sample_in_project,
)

NAME = "b30_gc_ec"
KEY = "b30_gc_ec"
DIVISION = "b30"
ORDER = 135
URL_PREFIX = "/b30-gc-ec"
ENDPOINT = "b30_gc_ec.page"
NAV_LABEL = "B30 GC-EC"
CARD_TITLE = "B30 GC / Electrochemistry Upload"
CARD_DESCRIPTION = "Upload Bio-Logic EC-Lab (.mpt) and GC (.log) files with interactive metadata preview and electrode/electrolyte sample linking."
INSTRUMENT_ID = "gc-b30-001"
INSTRUMENT_MFID = "0tmfg17radzgf000w544pxmwer"
INGESTOR = ""
UI_MODE = "preview"
POST_PROCESSING = []
SAMPLE_METADATA_FIELDS = {
    "anode_material": "anode_sample_mfid",
    "cathode_material": "cathode_sample_mfid",
    "electrolyte": "electrolyte_sample_mfid",
}

TOOL_CONFIG = {
    "name": NAME,
    "key": KEY,
    "division": DIVISION,
    "order": ORDER,
    "url_prefix": URL_PREFIX,
    "endpoint": ENDPOINT,
    "nav_label": NAV_LABEL,
    "card_title": CARD_TITLE,
    "card_description": CARD_DESCRIPTION,
    "instrument_id": INSTRUMENT_ID,
    "instrument_mfid": INSTRUMENT_MFID,
    "ingestor": INGESTOR,
    "ui_mode": UI_MODE,
    "post_processing": POST_PROCESSING,
    "sample_metadata_fields": SAMPLE_METADATA_FIELDS,
    "default_printer": "b30-113",
}

b30_gc_ec_bp = Blueprint("b30_gc_ec", __name__)
BLUEPRINT = b30_gc_ec_bp


@b30_gc_ec_bp.route("/")
def page():
    return render_template("b30_gc_ec.html", tool_config=TOOL_CONFIG)


register_common_uploader_routes(b30_gc_ec_bp, tool_config=TOOL_CONFIG)


@b30_gc_ec_bp.route("/api/prepare-preview", methods=["POST"])
def prepare_preview():
    """Validate material samples and check SHA-256 reuse. Strictly read-only in Crucible."""
    user, err = require_logged_in_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    first_file_sha256 = (data.get("first_file_sha256") or "").strip()
    anode_mfid = (data.get("anode_sample_mfid") or "").strip()
    cathode_mfid = (data.get("cathode_sample_mfid") or "").strip()
    electrolyte_mfid = (data.get("electrolyte_sample_mfid") or "").strip()

    if not anode_mfid or not cathode_mfid or not electrolyte_mfid:
        return jsonify({"error": "anode_sample_mfid, cathode_sample_mfid, and electrolyte_sample_mfid are required"}), 400

    resolved_materials = {}
    material_specs = [
        ("anode_material", "Anode Material", anode_mfid),
        ("cathode_material", "Cathode Material", cathode_mfid),
        ("electrolyte", "Electrolyte", electrolyte_mfid),
    ]

    for key, label, mfid in material_specs:
        sample, s_err = lookup_sample_in_project(
            project_id=user["selected_project"],
            sample_unique_id=mfid,
        )
        if s_err or not sample:
            return jsonify({
                "error": f"No {label} sample found for MFID '{mfid}' in project '{user['selected_project']}'"
            }), 400
        resolved_materials[key] = {
            "sample_name": sample.get("sample_name", ""),
            "sample_mfid": sample["unique_id"],
        }

    valid_dsids = existing_user_project_dsids(user["orcid"], user["selected_project"])
    reused_dsid, is_reused = resolve_dsid_for_sha256(first_file_sha256, valid_dsids)

    return jsonify({
        "dsid": reused_dsid,
        "reused_dataset": is_reused,
        "resolved_materials": resolved_materials,
    }), 200


@b30_gc_ec_bp.route("/api/confirm-upload", methods=["POST"])
def confirm_upload():
    """Create or update dataset and link material + primary samples."""
    user, err = require_logged_in_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    dsid = (data.get("dsid") or "").strip() or None
    dataset_fields = data.get("dataset_fields") or {}
    scientific_metadata = data.get("scientific_metadata") or {}
    keywords = data.get("keywords") or []
    sample_unique_id = (data.get("sample_unique_id") or "").strip()
    anode_mfid = (data.get("anode_sample_mfid") or "").strip()
    cathode_mfid = (data.get("cathode_sample_mfid") or "").strip()
    electrolyte_mfid = (data.get("electrolyte_sample_mfid") or "").strip()

    try:
        for mfid in (anode_mfid, cathode_mfid, electrolyte_mfid):
            if mfid:
                verify_sample_in_project(mfid, user["selected_project"])
        if sample_unique_id:
            verify_sample_in_project(sample_unique_id, user["selected_project"])
    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404

    try:
        final_dsid, reused = create_or_update_dataset(
            orcid=user["orcid"],
            project_id=user["selected_project"],
            prod_instrument_mfid=INSTRUMENT_MFID,
            dsid=dsid,
            dataset_name=dataset_fields.get("dataset_name"),
            measurement=dataset_fields.get("measurement"),
            data_type=dataset_fields.get("data_type"),
            session_name=dataset_fields.get("session_name"),
            scientific_metadata=scientific_metadata,
            keywords=keywords,
        )
    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Link material samples
    for mfid in (anode_mfid, cathode_mfid, electrolyte_mfid):
        if mfid:
            try:
                cruc_client.datasets.link_sample(dataset_mfid=final_dsid, sample_mfid=mfid)
            except Exception as e:
                return jsonify({"error": f"Failed linking material sample {mfid}: {e}"}), 500

    # Link primary sample if provided
    if sample_unique_id:
        try:
            cruc_client.datasets.link_sample(dataset_mfid=final_dsid, sample_mfid=sample_unique_id)
        except Exception as e:
            return jsonify({"error": f"Failed linking primary sample {sample_unique_id}: {e}"}), 500

    return jsonify({
        "ok": True,
        "dataset_mfid": final_dsid,
        "reused": reused,
        "hub_url": hub_dataset_url(final_dsid),
    }), 200
