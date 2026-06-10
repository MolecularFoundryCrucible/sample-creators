from flask import Blueprint, request, jsonify, session, render_template, current_app
from routes.shared import cruc_client
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from config import B30_SPUTTER_CONFIG
from datetime import datetime, timezone
from threading import Lock

b30_sputter_bp = Blueprint("b30_sputter", __name__)

REF_SAMPLE = "0tgfny1b35rwd000x35nr7a9d8"  # sample with all the calibrated deposition rates as datasets in Crucible

# Cache settings
RATE_INDEX_TTL_SECONDS = 300  # 5 minutes

# In-memory cache
_RATE_INDEX = None
_RATE_INDEX_BUILT_AT = None
_RATE_INDEX_LOCK = Lock()

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

def _build_rate_key(target_material, gas1, gas1_pc, power_W, pressure_mTorr, power_source):
    return (
        _norm_text(target_material),
        _norm_text(gas1),
        _norm_num(gas1_pc),
        _norm_num(power_W),
        _norm_num(pressure_mTorr),
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
    
def _index_is_stale():
    if _RATE_INDEX is None or _RATE_INDEX_BUILT_AT is None:
        return True
    age = (datetime.now(timezone.utc) - _RATE_INDEX_BUILT_AT).total_seconds()
    return age > RATE_INDEX_TTL_SECONDS

def _build_rate_index_from_reference_sample():
    """
    Builds:
      key -> {
        "19_rate_A_s": float,
        "timestamp": str,
        "dataset_id": str,
        "ts_dt": datetime (internal)
      }
    Keeping only the newest timestamp per key.
    """
    index = {}

    sample = cruc_client.samples.get(REF_SAMPLE)
    datasets = sample.get("datasets", []) or []

    for link in datasets:
        ds_id = link.get("unique_id") or link.get("id")
        if not ds_id:
            continue

        try:
            md = cruc_client.datasets.get_scientific_metadata(ds_id) or {}
            sci = md.get("scientific_metadata", {}) or {}

            key = _build_rate_key(
                sci.get("09_target_material", ""),
                sci.get("03_gas1", ""),
                sci.get("04_gas1_pc", ""),
                sci.get("11_power_W", ""),
                sci.get("07_pressure_mTorr", ""),
                sci.get("10_power_source", ""),
            )

            rate_val = sci.get("19_rate_A_s")
            if rate_val in ("", None):
                continue

            ds_obj = cruc_client.datasets.get(ds_id) or {}
            ts = ds_obj.get("timestamp", "")
            ts_dt = _parse_ts(ts)

            prev = index.get(key)
            if prev is None or ts_dt > prev["ts_dt"]:
                index[key] = {
                    "19_rate_A_s": float(rate_val),
                    "timestamp": ts,
                    "dataset_id": ds_id,
                    "ts_dt": ts_dt,  # internal
                }

        except Exception as e:
            current_app.logger.warning(f"[b30] Skipping dataset {ds_id}: {e}")
            continue

    return index

def get_rate_index(force=False):
    """
    TTL-cached index getter.
    Rebuilds at most once per TTL window unless force=True.
    """
    global _RATE_INDEX, _RATE_INDEX_BUILT_AT

    if not force and not _index_is_stale():
        return _RATE_INDEX

    with _RATE_INDEX_LOCK:
        # Re-check after acquiring lock (avoid duplicate rebuilds)
        if not force and not _index_is_stale():
            return _RATE_INDEX

        try:
            new_index = _build_rate_index_from_reference_sample()
            _RATE_INDEX = new_index
            _RATE_INDEX_BUILT_AT = datetime.now(timezone.utc)
            current_app.logger.info(
                f"[b30] Rate index rebuilt: {len(_RATE_INDEX)} keys "
                f"(ttl={RATE_INDEX_TTL_SECONDS}s, ref_sample={REF_SAMPLE})"
            )
        except Exception as e:
            current_app.logger.error(f"[b30] Failed to rebuild rate index: {e}")
            # Keep old cache if present
            if _RATE_INDEX is None:
                _RATE_INDEX = {}
                _RATE_INDEX_BUILT_AT = datetime.now(timezone.utc)

    return _RATE_INDEX

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

    required = ["09_target_material", "03_gas1", "04_gas1_pc", "11_power_W", "07_pressure_mTorr", "10_power_source"]
    missing = [k for k in required if data.get(k) in (None, "")]
    if missing:
        return jsonify({"found": False, "error": f"Missing required fields: {', '.join(missing)}"}), 400

    try:
        query_key = _build_rate_key(
            data["09_target_material"],
            data["03_gas1"],
            data["04_gas1_pc"],
            data["11_power_W"],
            data["07_pressure_mTorr"],
            data["10_power_source"],
        )
    except Exception:
        return jsonify({"found": False, "error": "Invalid lookup values"}), 400

    idx = get_rate_index(force=False)
    entry = idx.get(query_key)

    if not entry:
        return jsonify({"found": False}), 200

    return jsonify({
        "found": True,
        "19_rate_A_s": entry["19_rate_A_s"],
        "timestamp": entry["timestamp"],
        "dataset_id": entry["dataset_id"],
    }), 200

@b30_sputter_bp.route("/api/reload-rate-index", methods=["POST"])
def reload_rate_index():
    idx = get_rate_index(force=True)
    return jsonify({
        "ok": True,
        "count": len(idx or {}),
        "ref_sample": REF_SAMPLE,
        "ttl_seconds": RATE_INDEX_TTL_SECONDS,
        "rebuilt_at": _RATE_INDEX_BUILT_AT.isoformat() if _RATE_INDEX_BUILT_AT else None,
    }), 200


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
    
    def build_dataset_name(state, data):
        date_str = datetime.now().strftime("%Y%m%d")
        co_dep = bool(data.get("01_co_deposition_enabled"))

        t1 = (data.get("09_target_material") or "").strip()
        t2 = (data.get("13_target_material_2") or "").strip()
        sample = (state.get("sample_name") or "").strip()

        if co_dep and t1 and t2:
            target_part = f"{t1}+{t2}"
        else:
            target_part = t1 or "unknown-target"

        sample = sample or "unknown-sample"
        return f"{date_str}_{target_part}_Sputtering_on_{sample}"

    data = request.get_json()

    # Build scientific_metadata from the fields defined in B30_SPUTTER_CONFIG.
    # To add or rename fields, update the "dataset_fields" list in config.py.
    scientific_metadata = {}
    for field in B30_SPUTTER_CONFIG["dataset_fields"]:
        key = field["key"]
        value = data.get(key, "").strip() if isinstance(data.get(key), str) else data.get(key, "")
        if value != "" and value is not None:
            scientific_metadata[key] = value

    dataset_name = build_dataset_name(state, data or {})

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
