import csv
import io
import os
from flask import Blueprint, request, jsonify, session, render_template, Response
import pandas as pd
from routes.shared import cruc_client, get_next_serial_sample
from crucible.utils import get_tz_isoformat

b30_sputter_bp = Blueprint("b30_sputter", __name__)

_pending_uploads: dict[str, list] = {}


def _get_b30_sputter_state():
    """Get or initialize B30 Sputter state in session."""
    if "b30_sputter" not in session:
        session["b30_sputter"] = {
            "b30_sputter_name": "",
            "rga_mf_uuid": "",
            "rga_als_uuid": "",
            "esaf": RGA_CONFIG["default_esaf"],
            "carrier_name": "",
            "carrier_uuid": "",
            "thin_films": [],
            "shutter_open_s": RGA_CONFIG["default_shutter_open_s"],
            "mass_range_amu": RGA_CONFIG["default_mass_range_amu"],
            "positions": {pos: "" for pos in RGA_POSITIONS},
        }
    return session["b30_sputter"]


@b30_sputter_bp.route("/")
def page():
    return render_template("b30_sputter.html", b30_sputter_positions=B30_SPUTTER_POSITIONS, b30_sputter_config=B30_SPUTTER_CONFIG)


@b30_sputter_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_b30_sputter_state())


@b30_sputter_bp.route("/api/next-carrier-name", methods=["POST"])
def next_carrier_name():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project = user["selected_project"]
    num = get_next_serial_sample("B30 Sputter", "b30 sputter carrier", project)
    b30_sputter_name = f"B30Sputter{num:06d}"

    state = _get_b30_sputter_state()
    state["b30_sputter_name"] = b30_sputter_name
    session.modified = True

    return jsonify({"b30_sputter_name": b30_sputter_name})


@b30_sputter_bp.route("/api/lookup-carrier", methods=["POST"])
def lookup_carrier():
    data = request.get_json()
    b30_sputter_name = data.get("b30_sputter_name", "").strip()
    if not b30_sputter_name:
        return jsonify({"error": "B30 Sputter name required"}), 400

    user = session.get("user")
    project = user["selected_project"] if user else None
    mf_b30_sputters = cruc_client.samples.list(sample_name=b30_sputter_name, sample_type="b30 sputter carrier", project_id=project)
    mfid = ""
    alsid = ""
    if len(mf_b30_sputters) == 1:
        mfid = mf_b30_sputters[0]["unique_id"]
        descrip = mf_b30_sputters[0]["description"]
        if descrip is not None:
            alsid = descrip.split("|| Set ID:")[-1].strip()

    state = _get_b30_sputter_state()
    state["b30_sputter_name"] = b30_sputter_name
    state["b30_sputter_mf_uuid"] = mfid
    state["b30_sputter_als_uuid"] = alsid
    session.modified = True

    return jsonify({"b30_sputter_name": b30_sputter_name, "mf_uuid": mfid, "als_uuid": alsid})


@b30_sputter_bp.route("/api/register-crucible", methods=["POST"])
def register_crucible():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json() or {}
    state = _get_b30_sputter_state()

    if data.get("b30_sputter_name"):
        state["b30_sputter_name"] = data["b30_sputter_name"].strip()
        session.modified = True

    b30_sputter_name = state["b30_sputter_name"]
    if not b30_sputter_name:
        return jsonify({"error": "No B30 Sputter name set"}), 400

    try:
        new_rga = cruc_client.samples.create(
            sample_name=b30_sputter_name,
            timestamp=get_tz_isoformat(),
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            sample_type="rga carrier",
        )
        mfid = new_rga["unique_id"]
        state["rga_mf_uuid"] = mfid
        session.modified = True
        return jsonify({"mf_uuid": mfid, "rga_name": rga_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_sputter_bp.route("/api/scan-carrier", methods=["POST"])
def scan_carrier():
    data = request.get_json()
    carrier_uuid = data.get("carrier_uuid", "").strip()

    if len(carrier_uuid) != 26:
        return jsonify({"error": "Invalid carrier UUID (must be 26 characters)"}), 400

    try:
        carrier_info = cruc_client.samples.get(carrier_uuid)
        carrier_name = carrier_info["sample_name"]

        samples = cruc_client.samples.list_children(carrier_uuid, sample_type="thin film")
        sorted_names = sorted(s["sample_name"] for s in samples)

        state = _get_b30_sputter_state()
        state["carrier_name"] = carrier_name
        state["carrier_uuid"] = carrier_uuid
        state["thin_films"] = sorted_names
        session.modified = True

        return jsonify({"carrier_name": carrier_name, "thin_films": sorted_names})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_sputter_bp.route("/api/upload", methods=["POST"])
def upload():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_b30_sputter_state()
    sid = session.get("_id", "")
    samples = _pending_uploads.get(sid, [])

    if not samples:
        return jsonify({"error": "No samples to upload. Run preview first."}), 400

    try:
        for tf in samples:
            tf_name = tf["tf_name"]
            tf_mfid = tf["tf_mfid"]

            cruc_client.samples.link(
                parent_id=state["rga_mf_uuid"],
                child_id=tf_mfid,
            )

        count = len(samples)
        _pending_uploads.pop(sid, None)
        return jsonify({"uploaded_count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


