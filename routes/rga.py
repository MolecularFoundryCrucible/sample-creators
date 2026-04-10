import csv
import io
import os
from flask import Blueprint, request, jsonify, session, render_template, Response
import pandas as pd
from backend import cruc_client, als_sc_client
from config import RGA_CONFIG, RGA_POSITIONS, COORDS_FILE
from routes.shared import get_next_serial_sample
from pycrucible.utils import get_tz_isoformat

rga_bp = Blueprint("rga", __name__)

_pending_uploads: dict[str, list] = {}


def _get_rga_state():
    """Get or initialize RGA state in session."""
    if "rga" not in session:
        session["rga"] = {
            "rga_name": "",
            "rga_mf_uuid": "",
            "rga_als_uuid": "",
            "carrier_name": "",
            "carrier_uuid": "",
            "thin_films": [],
            "shutter_open_s": RGA_CONFIG["default_shutter_open_s"],
            "mass_range_amu": RGA_CONFIG["default_mass_range_amu"],
            "positions": {pos: "" for pos in RGA_POSITIONS},
        }
    return session["rga"]


@rga_bp.route("/")
def page():
    return render_template("rga.html", rga_positions=RGA_POSITIONS)


@rga_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_rga_state())


@rga_bp.route("/api/next-carrier-name", methods=["POST"])
def next_carrier_name():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project = user["selected_project"]
    num = get_next_serial_sample("RGA", project)
    rga_name = f"RGA{num:06d}"

    state = _get_rga_state()
    state["rga_name"] = rga_name
    session.modified = True

    return jsonify({"rga_name": rga_name})


@rga_bp.route("/api/lookup-carrier", methods=["POST"])
def lookup_carrier():
    data = request.get_json()
    rga_name = data.get("rga_name", "").strip()
    if not rga_name:
        return jsonify({"error": "RGA name required"}), 400

    mf_rgas = cruc_client.list_samples(sample_name=rga_name)
    mfid = ""
    alsid = ""
    if len(mf_rgas) == 1:
        mfid = mf_rgas[0]["unique_id"]
        descrip = mf_rgas[0]["description"]
        if descrip is not None:
            alsid = descrip.split("|| Set ID:")[-1].strip()

    state = _get_rga_state()
    state["rga_name"] = rga_name
    state["rga_mf_uuid"] = mfid
    state["rga_als_uuid"] = alsid
    session.modified = True

    return jsonify({"rga_name": rga_name, "mf_uuid": mfid, "als_uuid": alsid})


@rga_bp.route("/api/register-crucible", methods=["POST"])
def register_crucible():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_rga_state()
    rga_name = state["rga_name"]
    if not rga_name:
        return jsonify({"error": "No RGA name set"}), 400

    try:
        new_rga = cruc_client.add_sample(
            sample_name=rga_name,
            creation_date=get_tz_isoformat(),
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


@rga_bp.route("/api/register-als", methods=["POST"])
def register_als():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_rga_state()
    if not state["rga_mf_uuid"]:
        return jsonify({"error": "Please register in Crucible first"}), 400

    try:
        new_set = als_sc_client.create_set(
            name=state["rga_name"],
            groupId=RGA_CONFIG["group_id"],
            proposalId=RGA_CONFIG["proposal_id"],
            description=f"MF RGA Carrier (mfid: {state['rga_mf_uuid']})",
        )
        cruc_client.update_sample(
            unique_id=state["rga_mf_uuid"],
            description=f"ALS RGA Carrier || Set ID: {new_set.id}",
        )
        state["rga_als_uuid"] = new_set.id
        session.modified = True
        return jsonify({"als_uuid": new_set.id, "rga_name": state["rga_name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rga_bp.route("/api/scan-carrier", methods=["POST"])
def scan_carrier():
    data = request.get_json()
    carrier_uuid = data.get("carrier_uuid", "").strip()

    if len(carrier_uuid) != 26:
        return jsonify({"error": "Invalid carrier UUID (must be 26 characters)"}), 400

    try:
        carrier_info = cruc_client.get_sample(sample_id=carrier_uuid)
        carrier_name = carrier_info["sample_name"]

        samples = cruc_client.list_samples(parent_id=carrier_uuid)
        sorted_names = sorted(s["sample_name"] for s in samples)

        state = _get_rga_state()
        state["carrier_name"] = carrier_name
        state["carrier_uuid"] = carrier_uuid
        state["thin_films"] = sorted_names
        session.modified = True

        return jsonify({"carrier_name": carrier_name, "thin_films": sorted_names})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rga_bp.route("/api/layout", methods=["POST"])
def update_layout():
    data = request.get_json()
    state = _get_rga_state()

    if "positions" in data:
        state["positions"] = data["positions"]
    if "shutter_open_s" in data:
        state["shutter_open_s"] = int(data["shutter_open_s"])
    if "mass_range_amu" in data:
        state["mass_range_amu"] = int(data["mass_range_amu"])

    session.modified = True
    return jsonify(state)


@rga_bp.route("/api/clear-layout", methods=["POST"])
def clear_layout():
    state = _get_rga_state()
    state["positions"] = {pos: "" for pos in RGA_POSITIONS}
    session.modified = True
    return jsonify({"ok": True})


@rga_bp.route("/api/collect-preview", methods=["POST"])
def collect_preview():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_rga_state()
    project = user["selected_project"]
    samples = []

    for pos in RGA_POSITIONS:
        tf_name = state["positions"].get(pos, "")
        if not tf_name:
            continue

        tf_found = cruc_client.list_samples(sample_name=tf_name, project_id=project)
        if len(tf_found) != 1:
            continue

        tf = tf_found[0]
        tf_mfid = tf["unique_id"]
        tf_descrip = tf.get("description", "")

        # Get spin_run metadata if available
        sample_syn_md = {}
        if tf_name != "TF000000":
            sample_ds = cruc_client.list_datasets(
                sample_id=tf_mfid, measurement="spin_run", include_metadata=True
            )
            sample_synds = [ds for ds in sample_ds if ds["measurement"] == "spin_run"]
            if sample_synds:
                sample_syn_md = sample_synds[0]["scientific_metadata"]["scientific_metadata"]
                sample_syn_md["mfid"] = tf_mfid
            elif tf_name != "TF000000":
                continue

        samples.append({
            "rga_position": pos,
            "tf_name": tf_name,
            "tf_mfid": tf_mfid,
            "tf_descrip": tf_descrip,
            "sample_parameters": sample_syn_md,
        })

    samples.sort(key=lambda x: RGA_POSITIONS.index(x["rga_position"]))

    sid = session.get("_id", "")
    if not sid:
        import secrets
        sid = secrets.token_hex(8)
        session["_id"] = sid
        session.modified = True
    _pending_uploads[sid] = samples

    return jsonify({
        "rga_name": state["rga_name"],
        "rga_mf_uuid": state["rga_mf_uuid"],
        "rga_als_uuid": state["rga_als_uuid"],
        "samples": samples,
    })


@rga_bp.route("/api/upload", methods=["POST"])
def upload():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_rga_state()
    sid = session.get("_id", "")
    samples = _pending_uploads.get(sid, [])

    if not samples:
        return jsonify({"error": "No samples to upload. Run preview first."}), 400

    try:
        for tf in samples:
            tf_name = tf["tf_name"]
            tf_mfid = tf["tf_mfid"]

            cruc_client.link_samples(
                parent_id=state["rga_mf_uuid"],
                child_id=tf_mfid,
            )

            new_als_samp = als_sc_client.create_sample(
                name=tf_name,
                group_id=RGA_CONFIG["group_id"],
                proposal_id=RGA_CONFIG["proposal_id"],
                scan_type=RGA_CONFIG["scan_type"],
                set_id=state["rga_als_uuid"],
                description=f"TMF Perovskite Thin Film (mfid: {tf_mfid})",
                parameters=tf["sample_parameters"],
            )

            updated_desc = f"{tf.get('tf_descrip', '')} || rga_als_id: {new_als_samp.id}".strip()
            cruc_client.update_sample(tf_mfid, description=updated_desc)

        count = len(samples)
        _pending_uploads.pop(sid, None)
        return jsonify({"uploaded_count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rga_bp.route("/api/generate-csv", methods=["POST"])
def generate_csv():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_rga_state()

    # Collect sample info
    project = user["selected_project"]
    sample_info = []
    for pos in RGA_POSITIONS:
        tf_name = state["positions"].get(pos, "")
        if tf_name:
            sample_info.append({"rga_position": pos, "tf_name": tf_name})

    if not sample_info:
        return jsonify({"error": "No samples in layout"}), 400

    # Read coords file
    coords_path = os.path.join(os.path.dirname(__file__), "..", COORDS_FILE)
    if not os.path.exists(coords_path):
        # Try the original location
        coords_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "als-data-entry-apps",
            "ScopeFoundryHW", "giwaxs_bar_creator", COORDS_FILE,
        )

    df = pd.read_csv(coords_path, sep="\t")
    df = df.set_index("name")

    for sample in sample_info:
        df.loc[sample["rga_position"], "sample_name"] = sample["tf_name"]

    # Fill empty sample_name with empty string
    df["sample_name"] = df["sample_name"].fillna("")

    output_df = df.copy()
    output_df['"mass range, amu"'] = state["mass_range_amu"]
    output_df['"shutter open,s"'] = state["shutter_open_s"]
    output_df["sample spot"] = output_df.index
    output_df["sample x"] = output_df["x"]
    output_df["sample y"] = output_df["y"]
    output_df["group_name"] = output_df["sample_name"]

    df_serp = output_df.set_index(output_df["serp_order"]).sort_index()

    col_names = [
        "sample spot", "sample x", "sample y", "sample_name",
        '"shutter open,s"', '"mass range, amu"', "group_name",
    ]

    buf = io.StringIO()
    df_serp[col_names].to_csv(buf, sep="\t", index=False, header=True, quoting=csv.QUOTE_NONE)

    filename = f"sample_holder_position_readout_{state['rga_name']}.txt"
    return Response(
        buf.getvalue(),
        mimetype="text/tab-separated-values",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
