from flask import Blueprint, request, jsonify, session, render_template
from backend import cruc_client, als_sc_client
from config import GIWAXS_CONFIG
from routes.shared import get_next_serial_sample
from pycrucible.utils import get_tz_isoformat

giwaxs_bp = Blueprint("giwaxs", __name__)

# Server-side storage for collected sample info (too large for cookie)
_pending_uploads: dict[str, list] = {}


def _get_giwaxs_state():
    """Get or initialize GIWAXS state in session."""
    if "giwaxs" not in session:
        session["giwaxs"] = {
            "bar_name": "",
            "bar_mf_uuid": "",
            "bar_als_uuid": "",
            "tray_name": "",
            "tray_uuid": "",
            "thin_films": [],
            "offset_mm": GIWAXS_CONFIG["default_offset_mm"],
            "wafer_width": GIWAXS_CONFIG["default_wafer_width_mm"],
            "incidence_angle": GIWAXS_CONFIG["default_incidence_angle"],
            "positions": {str(i): "" for i in range(1, 15)},
        }
    return session["giwaxs"]


@giwaxs_bp.route("/")
def page():
    return render_template("giwaxs.html")


@giwaxs_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_giwaxs_state())


@giwaxs_bp.route("/api/next-bar-name", methods=["POST"])
def next_bar_name():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project = user["selected_project"]
    num = get_next_serial_sample("GWBAR", project)
    bar_name = f"GWBAR{num:06d}"

    state = _get_giwaxs_state()
    state["bar_name"] = bar_name
    session.modified = True

    return jsonify({"bar_name": bar_name})


@giwaxs_bp.route("/api/lookup-bar", methods=["POST"])
def lookup_bar():
    data = request.get_json()
    bar_name = data.get("bar_name", "").strip()
    if not bar_name:
        return jsonify({"error": "Bar name required"}), 400

    mf_bars = cruc_client.list_samples(sample_name=bar_name)
    mfid = ""
    alsid = ""
    if len(mf_bars) == 1:
        mfid = mf_bars[0]["unique_id"]
        descrip = mf_bars[0]["description"]
        if descrip is not None:
            alsid = descrip.split("|| Set ID:")[-1].strip()

    state = _get_giwaxs_state()
    state["bar_name"] = bar_name
    state["bar_mf_uuid"] = mfid
    state["bar_als_uuid"] = alsid
    session.modified = True

    return jsonify({"bar_name": bar_name, "mf_uuid": mfid, "als_uuid": alsid})


@giwaxs_bp.route("/api/register-crucible", methods=["POST"])
def register_crucible():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_giwaxs_state()
    bar_name = state["bar_name"]
    if not bar_name:
        return jsonify({"error": "No bar name set"}), 400

    try:
        new_bar = cruc_client.add_sample(
            sample_name=bar_name,
            creation_date=get_tz_isoformat(),
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            sample_type="giwaxs bar",
        )
        mfid = new_bar["unique_id"]
        state["bar_mf_uuid"] = mfid
        session.modified = True
        return jsonify({"mf_uuid": mfid, "bar_name": bar_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@giwaxs_bp.route("/api/register-als", methods=["POST"])
def register_als():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_giwaxs_state()
    if not state["bar_mf_uuid"]:
        return jsonify({"error": "Please register in Crucible first"}), 400

    try:
        new_set = als_sc_client.create_set(
            name=state["bar_name"],
            groupId=GIWAXS_CONFIG["group_id"],
            proposalId=GIWAXS_CONFIG["proposal_id"],
            description=f"MF Thin Film Perovskites GWBAR (mfid: {state['bar_mf_uuid']})",
        )
        cruc_client.update_sample(
            unique_id=state["bar_mf_uuid"],
            description=f"ALS GIWAXS Bar || Set ID: {new_set.id}",
        )
        state["bar_als_uuid"] = new_set.id
        session.modified = True
        return jsonify({"als_uuid": new_set.id, "bar_name": state["bar_name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@giwaxs_bp.route("/api/scan-tray", methods=["POST"])
def scan_tray():
    data = request.get_json()
    tray_uuid = data.get("tray_uuid", "").strip()

    if len(tray_uuid) != 26:
        return jsonify({"error": "Invalid tray UUID (must be 26 characters)"}), 400

    try:
        tray_info = cruc_client.get_sample(sample_id=tray_uuid)
        tray_name = tray_info["sample_name"]

        samples = cruc_client.list_samples(parent_id=tray_uuid)
        sorted_names = sorted(s["sample_name"] for s in samples)

        state = _get_giwaxs_state()
        state["tray_name"] = tray_name
        state["tray_uuid"] = tray_uuid
        state["thin_films"] = sorted_names
        session.modified = True

        return jsonify({"tray_name": tray_name, "thin_films": sorted_names})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@giwaxs_bp.route("/api/layout", methods=["POST"])
def update_layout():
    data = request.get_json()
    state = _get_giwaxs_state()

    if "positions" in data:
        state["positions"] = data["positions"]
    if "offset_mm" in data:
        state["offset_mm"] = float(data["offset_mm"])
    if "wafer_width" in data:
        state["wafer_width"] = float(data["wafer_width"])
    if "incidence_angle" in data:
        state["incidence_angle"] = data["incidence_angle"]

    session.modified = True
    return jsonify(state)


@giwaxs_bp.route("/api/clear-layout", methods=["POST"])
def clear_layout():
    state = _get_giwaxs_state()
    state["positions"] = {str(i): "" for i in range(1, 15)}
    session.modified = True
    return jsonify({"ok": True})


@giwaxs_bp.route("/api/collect-preview", methods=["POST"])
def collect_preview():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_giwaxs_state()
    project = user["selected_project"]
    samples = []

    for i in range(1, 15):
        tf_name = state["positions"].get(str(i), "")
        if not tf_name:
            continue

        tf_found = cruc_client.list_samples(sample_name=tf_name, project_id=project)
        if len(tf_found) != 1:
            continue

        tf = tf_found[0]
        tf_mfid = tf["unique_id"]

        mm = ((i - 1) * state["wafer_width"]) + state["offset_mm"]
        params = dict(GIWAXS_CONFIG["default_sample_parameters"])
        params["mfid"] = tf_mfid
        params["sample_center_position"] = mm
        params["incident_angles"] = state["incidence_angle"]

        samples.append({
            "bar_position": i,
            "tf_name": tf_name,
            "tf_mfid": tf_mfid,
            "sample_parameters": params,
        })

    samples.sort(key=lambda x: x["bar_position"])

    # Store for upload confirmation
    sid = session.get("_id", "")
    if not sid:
        import secrets
        sid = secrets.token_hex(8)
        session["_id"] = sid
        session.modified = True
    _pending_uploads[sid] = samples

    return jsonify({
        "bar_name": state["bar_name"],
        "bar_mf_uuid": state["bar_mf_uuid"],
        "bar_als_uuid": state["bar_als_uuid"],
        "samples": samples,
    })


@giwaxs_bp.route("/api/upload", methods=["POST"])
def upload():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_giwaxs_state()
    sid = session.get("_id", "")
    samples = _pending_uploads.get(sid, [])

    if not samples:
        return jsonify({"error": "No samples to upload. Run preview first."}), 400

    try:
        for tf in samples:
            tf_name = tf["tf_name"]
            tf_mfid = tf["tf_mfid"]

            cruc_client.link_samples(
                parent_id=state["bar_mf_uuid"],
                child_id=tf_mfid,
            )

            new_als_samp = als_sc_client.create_sample(
                name=tf_name,
                group_id=GIWAXS_CONFIG["group_id"],
                proposal_id=GIWAXS_CONFIG["proposal_id"],
                scan_type=GIWAXS_CONFIG["scan_type"],
                set_id=state["bar_als_uuid"],
                description=f"TMF Perovskite Thin Film (mfid: {tf_mfid})",
                parameters=tf["sample_parameters"],
            )

            cruc_client.update_sample(
                tf_mfid,
                description=f"als_giwaxs_id: {new_als_samp.id}",
            )

        count = len(samples)
        _pending_uploads.pop(sid, None)
        return jsonify({"uploaded_count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
