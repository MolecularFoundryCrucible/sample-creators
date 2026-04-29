from flask import Blueprint, request, jsonify, session, render_template
from routes.shared import cruc_client
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from config import B30_SPUTTER_CONFIG

b30_sputter_bp = Blueprint("b30_sputter", __name__)


def _get_state():
    if "b30_sputter" not in session:
        session["b30_sputter"] = {
            "sample_unique_id": "",
            "sample_name": "",
            "sample_type": "",
            "sample_description": "",
        }
    return session["b30_sputter"]


@b30_sputter_bp.route("/")
def page():
    return render_template("b30_sputter.html", config=B30_SPUTTER_CONFIG)


@b30_sputter_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_state())


# ---------- Sample lookup (barcode scan) ----------

@b30_sputter_bp.route("/api/lookup-sample", methods=["POST"])
def lookup_sample():
    """Look up a sample by its Crucible unique_id (scanned barcode)."""
    data = request.get_json()
    unique_id = data.get("unique_id", "").strip()
    if not unique_id:
        return jsonify({"error": "No barcode value provided"}), 400

    try:
        sample = cruc_client.samples.get(unique_id)
    except Exception as e:
        return jsonify({"found": False, "unique_id": unique_id})

    if sample is None:
        return jsonify({"found": False, "unique_id": unique_id})

    state = _get_state()
    state["sample_unique_id"] = sample["unique_id"]
    state["sample_name"] = sample["sample_name"]
    state["sample_type"] = sample.get("sample_type", "")
    state["sample_description"] = sample.get("description", "")
    session.modified = True

    return jsonify({
        "found": True,
        "unique_id": sample["unique_id"],
        "sample_name": sample["sample_name"],
        "sample_type": sample.get("sample_type", ""),
        "description": sample.get("description", ""),
    })


# ---------- Sample creation (if not found) ----------

@b30_sputter_bp.route("/api/create-sample", methods=["POST"])
def create_sample():
    """Create a new sample in Crucible and store it in session."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    sample_name = data.get("sample_name", "").strip()
    sample_type = data.get("sample_type", "").strip()
    description = data.get("description", "").strip()

    if not sample_name or not sample_type:
        return jsonify({"error": "sample_name and sample_type are required"}), 400

    try:
        new_sample = cruc_client.samples.create(
            sample_name=sample_name,
            timestamp=get_tz_isoformat(),
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            sample_type=sample_type,
            description=description or None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    state = _get_state()
    state["sample_unique_id"] = new_sample["unique_id"]
    state["sample_name"] = new_sample["sample_name"]
    state["sample_type"] = sample_type
    state["sample_description"] = description
    session.modified = True

    return jsonify({
        "unique_id": new_sample["unique_id"],
        "sample_name": new_sample["sample_name"],
        "sample_type": sample_type,
        "description": description,
    })


# ---------- Dataset upload ----------

@b30_sputter_bp.route("/api/upload-dataset", methods=["POST"])
def upload_dataset():
    """Create a sputtering dataset in Crucible and link it to the current sample."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_state()
    if not state.get("sample_unique_id"):
        return jsonify({"error": "No sample selected. Scan a barcode first."}), 400

    data = request.get_json()

    # Build scientific_metadata from the fields defined in B30_SPUTTER_CONFIG.
    # To add or rename fields, update the "dataset_fields" list in config.py.
    scientific_metadata = {}
    for field in B30_SPUTTER_CONFIG["dataset_fields"]:
        key = field["key"]
        value = data.get(key, "").strip() if isinstance(data.get(key), str) else data.get(key, "")
        if value != "" and value is not None:
            scientific_metadata[key] = value

    dataset_name = f"{B30_SPUTTER_CONFIG['dataset_name_prefix']} {state['sample_name']}"

    try:
        ds = Dataset(
            dataset_name=dataset_name,
            dataset_type=B30_SPUTTER_CONFIG["dataset_type"],
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            instrument_name=B30_SPUTTER_CONFIG["instrument_name"],
            measurement=B30_SPUTTER_CONFIG["measurement"],
            timestamp=get_tz_isoformat(),
        )
        new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)

        cruc_client.datasets.add_sample(
            dataset_id=new_dataset["unique_id"],
            sample_id=state["sample_unique_id"],
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": new_dataset["unique_id"],
        "sample_name": state["sample_name"],
    })
