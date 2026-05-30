from flask import Blueprint, request, jsonify, session, render_template
from config import GIWAXS_CONFIG
from routes.shared import cruc_client, get_next_serial_sample
from routes.als_shared import als_sc_client
from crucible.utils import get_tz_isoformat
from beamline_data_toolkit.sample_tracker import SampleSetCreateDto, SampleCreateDto, SampleSetParameterValuesByNameDto

giwaxs_bp = Blueprint("giwaxs", __name__)

# Server-side storage for collected sample info (too large for cookie)
_pending_uploads: dict[str, list] = {}

# Maps crucible/internal snake_case keys to the ALS parameter display names
# as defined in the 7-3-3-giwaxs_for_10k scan type
GIWAXS_ALS_PARAM_NAME_MAP = {
    "sample_center_position": "Sample Center Position",
    "incident_angles":        "Incident Angles",
    "measurement_spots":      "Measurement Spots",
    "exposure_time":          "Exposure Time",
    "exposure_max":           "Exposure Max",
    "image_type":             "Image Type",
    # mfid is not in 7-3-3-giwaxs_for_10k, so omit it here
}


def _get_giwaxs_state():
    """Get or initialize GIWAXS state in session."""
    if "giwaxs" not in session:
        session["giwaxs"] = {
            "bar_name": "",
            "bar_mf_uuid": "",
            "bar_als_uuid": "",
            "esaf": GIWAXS_CONFIG["default_esaf"],
            "tray_name": "",
            "tray_uuid": "",
            "thin_films": [],
            "offset_mm": GIWAXS_CONFIG["default_offset_mm"],
            "wafer_width": GIWAXS_CONFIG["default_wafer_width_mm"],
            "incidence_angle": GIWAXS_CONFIG["default_incidence_angle"],
            "positions": {str(i): "" for i in range(1, 12)},
        }
    return session["giwaxs"]


@giwaxs_bp.route("/")
def page():
    return render_template("giwaxs.html", giwaxs_config=GIWAXS_CONFIG)


@giwaxs_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_giwaxs_state())


@giwaxs_bp.route("/api/next-bar-name", methods=["POST"])
def next_bar_name():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project = user["selected_project"]
    num = get_next_serial_sample("GWBAR", "giwaxs bar", project)
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

    user = session.get("user")
    project = user["selected_project"] if user else None
    mf_bars = cruc_client.samples.list(sample_name=bar_name, sample_type="giwaxs bar", project_id=project)
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

    data = request.get_json() or {}
    state = _get_giwaxs_state()

    # Allow the client to send the current bar name (editable field)
    if data.get("bar_name"):
        state["bar_name"] = data["bar_name"].strip()
        session.modified = True

    bar_name = state["bar_name"]
    if not bar_name:
        return jsonify({"error": "No bar name set"}), 400

    try:
        new_bar = cruc_client.samples.create(
            sample_name=bar_name,
            timestamp=get_tz_isoformat(),
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

    data = request.get_json() or {}
    state = _get_giwaxs_state()

    if data.get("bar_name"):
        state["bar_name"] = data["bar_name"].strip()
        session.modified = True

    if not state["bar_mf_uuid"]:
        return jsonify({"error": "Please register in Crucible first"}), 400

    try:
        esaf = als_sc_client.esaf_get_by_name(state["esaf"])[-1]
        new_set_dto = SampleSetCreateDto(
            name=state["bar_name"],
            slug_esaf=esaf.slug,
            description=f"MF Thin Film Perovskites GWBAR (mfid: {state['bar_mf_uuid']})",
        )
        new_set = als_sc_client.set_create(new_set_dto)
        cruc_client.samples.update(
            unique_id=state["bar_mf_uuid"],
            description=f"ALS GIWAXS Bar || Set ID: {new_set.slug}",
        )
        state["bar_als_uuid"] = new_set.slug
        session.modified = True
        return jsonify({"als_uuid": new_set.slug, "bar_name": state["bar_name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@giwaxs_bp.route("/api/scan-tray", methods=["POST"])
def scan_tray():
    data = request.get_json()
    tray_uuid = data.get("tray_uuid", "").strip()

    if len(tray_uuid) != 26:
        return jsonify({"error": "Invalid tray UUID (must be 26 characters)"}), 400

    try:
        tray_info = cruc_client.samples.get(tray_uuid)
        tray_name = tray_info["sample_name"]

        samples = cruc_client.samples.list_children(tray_uuid, sample_type="thin film")
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
    if "esaf" in data:
        state["esaf"] = data["esaf"]

    session.modified = True
    return jsonify(state)


@giwaxs_bp.route("/api/clear-layout", methods=["POST"])
def clear_layout():
    state = _get_giwaxs_state()
    state["positions"] = {str(i): "" for i in range(1, 12)}
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

    for i in range(1, 12):
        tf_name = state["positions"].get(str(i), "")
        if not tf_name:
            continue

        tf_found = cruc_client.samples.list(
            sample_name=tf_name, project_id=project, sample_type="thin film"
        )
        if len(tf_found) != 1:
            continue

        tf = tf_found[0]
        tf_mfid = tf["unique_id"]
        tf_descrip = tf.get("description", "")

        # Get spin_run synthesis metadata
        sample_syn_md = {}
        if tf_name != "TF000000":
            sample_ds = cruc_client.datasets.list(
                sample_id=tf_mfid, measurement="spin_run", include_metadata=True
            )
            sample_synds = [ds for ds in sample_ds if ds["measurement"] == "spin_run"]
            if sample_synds:
                sample_syn_md = sample_synds[0]["scientific_metadata"]["scientific_metadata"]

        mm = ((i - 1) * state["wafer_width"]) + state["offset_mm"]
        scan_params = dict(GIWAXS_CONFIG["default_sample_parameters"])
        scan_params["mfid"] = tf_mfid
        scan_params["sample_center_position"] = mm
        scan_params["incident_angles"] = state["incidence_angle"]

        # Merged for upload
        all_params = {**scan_params, **sample_syn_md}

        samples.append({
            "bar_position": i,
            "tf_name": tf_name,
            "tf_mfid": tf_mfid,
            "tf_descrip": tf_descrip,
            "sample_parameters": all_params,
            "scan_params": scan_params,
            "scientific_metadata": sample_syn_md,
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

            cruc_client.samples.link(
                parent_id=state["bar_mf_uuid"],
                child_id=tf_mfid,
            )

            new_sample_dto = SampleCreateDto(
                name=tf_name,
                slug_set=state["bar_als_uuid"],
                description=f"TMF Perovskite Thin Film (mfid: {tf_mfid})",
                slug_scan_type=GIWAXS_CONFIG["scan_type_slug"]
            )
            new_als_samp = als_sc_client.sample_create(new_sample_dto)
            
            # Remap snake_case keys to ALS display names before upload
            raw_params = {k: v for k, v in tf["sample_parameters"].items() if v is not None}
            renamed_params = {
                GIWAXS_ALS_PARAM_NAME_MAP.get(k, k): v
                for k, v in raw_params.items()}

            values_dto = SampleSetParameterValuesByNameDto(
                create_parameters_if_missing=False,
                allow_parameters_not_in_scan_type=True,
                add_parameters_to_scan_type_if_missing=False,
                remove_other_values=True,
                values=renamed_params,
            )
            
            als_sc_client.sample_set_parameter_values_by_name(new_als_samp.slug, values_dto)

            updated_desc = f"{tf.get('tf_descrip', '')} || als_giwaxs_id: {new_als_samp.slug}".strip()
            cruc_client.samples.update(
                tf_mfid,
                description=updated_desc,
            )

        count = len(samples)
        _pending_uploads.pop(sid, None)
        return jsonify({"uploaded_count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
