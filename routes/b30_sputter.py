from flask import Blueprint, request, jsonify, session, render_template, current_app
from routes.shared import cruc_client
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from config import B30_SPUTTER_CONFIG
from datetime import datetime, timezone

b30_sputter_bp = Blueprint("b30_sputter", __name__)

REF_SAMPLE = "0tgfny1b35rwd000x35nr7a9d8"  # sample with all the calibrated deposition rates as datasets in Crucible

def _norm_text(v):
    return str(v).strip().lower()

def _norm_num(v, ndigits=3):
    return round(float(v), ndigits)

def _norm_power_source(v):
    # Examples:
    # "RF 1-1" -> "rf"
    # "RF 2-1" -> "rf"
    # "DC 3-2" -> "dc"
    s = str(v).strip().lower()
    if not s:
        return ""
    return s.split()[0]  # keep only first token

def _build_rate_key(target_material, gas1, gas1_pc, power_w, pressure_mtorr, power_source):
    return (
        _norm_text(target_material),
        _norm_text(gas1),
        _norm_num(gas1_pc),
        _norm_num(power_w),
        _norm_num(pressure_mtorr),
        _norm_power_source(power_source),  
    )

def _get_state():
    if "b30_sputter" not in session:
        session["b30_sputter"] = {
            "sample_unique_id": "",
            "sample_name": "",
            "sample_type": "",
            "sample_description": "",
        }
    return session["b30_sputter"]

def _parse_ts(ts):
    # Always return timezone-aware datetime
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
    
def lookup_rate_from_reference_sample(ref_sample_id, query_key):
    try:
        sample = cruc_client.samples.get(ref_sample_id)
    except Exception as e:
        current_app.logger.error(f"Failed to load reference sample {ref_sample_id}: {e}")
        return {"found": False, "error": "Reference sample not found"}

    datasets = sample.get("datasets", []) or []
    newest = None  # (timestamp_dt, response_payload)

    for link in datasets:
        ds_id = link.get("unique_id") or link.get("id")
        if not ds_id:
            continue

        try:
            md = cruc_client.datasets.get_scientific_metadata(ds_id) or {}
            sci = md.get("scientific_metadata", {})

            key = _build_rate_key(
                sci.get("target_material", ""),
                sci.get("gas1", ""),
                sci.get("gas1_pc", ""),
                sci.get("power_w", ""),
                sci.get("pressure_mtorr", ""),
                sci.get("power_source", ""),
            )
            if key != query_key:
                continue

            ds = cruc_client.datasets.get(ds_id) or {}
            ts = ds.get("timestamp", "")
            ts_dt = _parse_ts(ts)

            rate = sci.get("rate_A_s")
            if rate in ("", None):
                continue

            payload = {
                "found": True,
                "rate_A_s": float(rate),
                "timestamp": ts,
                "dataset_id": ds_id,
            }

            if newest is None or ts_dt > newest[0]:
                newest = (ts_dt, payload)

        except Exception as e:
            current_app.logger.warning(f"Skipping dataset {ds_id}: {e}")

    return newest[1] if newest else {"found": False}

# ---------- Routes ----------

@b30_sputter_bp.route("/")
def page():
    return render_template("b30_sputter.html", config=B30_SPUTTER_CONFIG)

@b30_sputter_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_state())

@b30_sputter_bp.route("/api/lookup-rate", methods=["POST"])
def lookup_rate():
    data = request.get_json(silent=True) or {}

    required = ["target_material", "gas1", "gas1_pc", "power_w", "pressure_mtorr", "power_source"]
    missing = [k for k in required if data.get(k) in (None, "")]
    if missing:
        return jsonify({"found": False, "error": f"Missing required fields: {', '.join(missing)}"}), 400

    try:
        query_key = _build_rate_key(
            data["target_material"],
            data["gas1"],
            data["gas1_pc"],
            data["power_w"],
            data["pressure_mtorr"],
            data["power_source"],
        )
    except Exception:
        return jsonify({"found": False, "error": "Invalid lookup values"}), 400

    result = lookup_rate_from_reference_sample(REF_SAMPLE, query_key)
    return jsonify(result), 200


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
            dataset_id=new_dataset["dsid"],
            sample_id=state["sample_unique_id"],
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": new_dataset["dsid"],
        "sample_name": state["sample_name"],
    })
