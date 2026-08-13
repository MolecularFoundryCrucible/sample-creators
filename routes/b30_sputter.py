from flask import Blueprint, request, jsonify, session, render_template, current_app, send_file
from routes.shared import cruc_client, publish_barcode
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from config import SPUTTER_TOOLS
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from threading import Lock
import requests
import io
import csv

# This blueprint is registered once per sputter tool (see app.py), so every tool gets its
# own page and URL prefix while sharing this code. Views call _tool() to find out which
# tool they are serving; nothing here is hardcoded to a single instrument.
b30_sputter_bp = Blueprint("b30_sputter", __name__)

LA_TZ = ZoneInfo("America/Los_Angeles")

# Cache settings
RATE_INDEX_TTL_SECONDS = 300  # 5 minutes
_ORCID_NAME_CACHE = {}
_ORCID_NAME_CACHE_LOCK = Lock()

_INCREMENTAL_CACHE = {}
_INCREMENTAL_CACHE_LOCK = Lock()

# In-memory cache: tool key -> {"index": {...}, "built_at": datetime}
_RATE_INDEXES = {}
_RATE_INDEX_LOCK = Lock()


BLUEPRINT_NAME_PREFIX = "b30_sputter_"


def blueprint_name(tool_key):
    """Registered blueprint name for a tool, e.g. "aja" -> "b30_sputter_aja"."""
    return f"{BLUEPRINT_NAME_PREFIX}{tool_key}"


def _tool_key():
    """The tool this request belongs to, read back from the registered blueprint name."""
    return (request.blueprint or "").removeprefix(BLUEPRINT_NAME_PREFIX)


def _tool():
    return SPUTTER_TOOLS[_tool_key()]

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
    """Per-tool session state, so the two tools never share a sample list."""
    state = session.setdefault(f"b30_sputter_{_tool_key()}", {})
    state.setdefault("sample_unique_id", "")
    state.setdefault("sample_name", "")
    state.setdefault("sample_type", "")
    state.setdefault("sample_description", "")
    # Samples the next uploaded dataset will be linked to.
    state.setdefault("run_samples", [])
    return state


def _add_run_sample(state, sample):
    """Add a looked-up or newly created sample to the run, ignoring repeats."""
    unique_id = sample["unique_id"]
    if any(s["unique_id"] == unique_id for s in state["run_samples"]):
        return False

    state["run_samples"].append({
        "unique_id": unique_id,
        "sample_name": sample.get("sample_name", ""),
        "sample_type": sample.get("sample_type", ""),
        "description": sample.get("description", ""),
    })
    session.modified = True
    return True

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
    
def _index_is_stale(tool_key):
    entry = _RATE_INDEXES.get(tool_key)
    if not entry:
        return True
    age = (datetime.now(timezone.utc) - entry["built_at"]).total_seconds()
    return age > RATE_INDEX_TTL_SECONDS

def _build_rate_index_from_reference_sample(ref_sample):
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

    sample = cruc_client.samples.get(ref_sample)
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
    TTL-cached index getter, one index per tool.
    Rebuilds at most once per TTL window unless force=True.
    """
    tool_key = _tool_key()
    ref_sample = _tool().get("calibration_sample_id", "")
    if not ref_sample:
        return {}

    if not force and not _index_is_stale(tool_key):
        return _RATE_INDEXES[tool_key]["index"]

    with _RATE_INDEX_LOCK:
        # Re-check after acquiring lock (avoid duplicate rebuilds)
        if not force and not _index_is_stale(tool_key):
            return _RATE_INDEXES[tool_key]["index"]

        try:
            new_index = _build_rate_index_from_reference_sample(ref_sample)
            _RATE_INDEXES[tool_key] = {"index": new_index, "built_at": datetime.now(timezone.utc)}
            current_app.logger.info(
                f"[b30] Rate index rebuilt for {tool_key}: {len(new_index)} keys "
                f"(ttl={RATE_INDEX_TTL_SECONDS}s, ref_sample={ref_sample})"
            )
        except Exception as e:
            current_app.logger.error(f"[b30] Failed to rebuild rate index for {tool_key}: {e}")
            # Keep old cache if present
            if tool_key not in _RATE_INDEXES:
                _RATE_INDEXES[tool_key] = {"index": {}, "built_at": datetime.now(timezone.utc)}

    return _RATE_INDEXES[tool_key]["index"]

def _pick(d, *keys, default=""):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v is not None and str(v).strip() != "":
            return v
    return default

def _clean(x):
    return "" if x is None else str(x).strip()

def _fmt_num(x, ndigits=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return f"{v:.{ndigits}f}" if ndigits is not None else f"{v:g}"

def _canonical_reactive_gas(sci: dict) -> str:
    gas1 = _clean(sci.get("03_gas1") or sci.get("gas1"))
    gas2 = _clean(sci.get("05_gas2") or sci.get("gas2"))
    pc1 = sci.get("04_gas1_pc", sci.get("gas1_pc"))
    pc2 = sci.get("06_gas2_pc", sci.get("gas2_pc"))

    def to_num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    pc1 = to_num(pc1)
    pc2 = to_num(pc2)

    if gas1 and not gas2 and pc1 is None:
        pc1 = 100.0

    parts = []
    if gas1:
        p1 = f"{int(pc1)}%" if pc1 is not None and pc1.is_integer() else (f"{pc1:g}%" if pc1 is not None else "")
        parts.append(f"{p1} {gas1}".strip())
    if gas2:
        p2 = f"{int(pc2)}%" if pc2 is not None and pc2.is_integer() else (f"{pc2:g}%" if pc2 is not None else "")
        parts.append(f"{p2} {gas2}".strip())

    return " + ".join(parts)

def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = _parse_ts(details.get("timestamp"))
    date_str = dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else ""

    t1 = _clean(sci.get("09_target_material") or sci.get("target_material"))
    t2 = _clean(sci.get("13_target_material_2") or sci.get("target_material_2"))
    targets = " + ".join([x for x in [t1, t2] if x])

    s1 = _clean(sci.get("10_power_source") or sci.get("power_source"))
    s2 = _clean(sci.get("14_power_source_2") or sci.get("power_source_2"))
    sources = " + ".join([x for x in [s1, s2] if x])

    p1 = _clean(sci.get("11_power_W") or sci.get("power_w"))
    p2 = _clean(sci.get("15_power_W_2") or sci.get("power_w_2"))
    powers = " + ".join([x for x in [p1, p2] if x])

    d1 = _clean(sci.get("12_DC_voltage_V") or sci.get("DC_voltage_V"))
    d2 = _clean(sci.get("16_DC_voltage_V_2") or sci.get("DC_voltage_V_2"))
    dcvs = " + ".join([x for x in [d1, d2] if x])

    r1 = _fmt_num(sci.get("17_rate_A_s_1") or sci.get("rate_A_s_1"), 2)
    r2 = _fmt_num(sci.get("18_rate_A_s_2") or sci.get("rate_A_s_2"), 2)
    indiv_rates = " + ".join([x for x in [r1, r2] if x])

    owner_orcid = _pick(details, "owner_orcid", default="")
    user_name = get_name_from_orcid_cached(owner_orcid) if owner_orcid else ""

    return {
        "Date": date_str,
        "User": user_name or owner_orcid,
        "Gas": _canonical_reactive_gas(sci),
        "Press. (mTorr)": _pick(sci, "07_pressure_mTorr", "pressure_mTorr", default=""),
        "Temp. (°C)": _pick(sci, "08_substrates_temperature_C", default=""),
        "Target": targets,
        "Source": sources,
        "Power (W)": powers,
        "DCV (V)": dcvs,
        "Indiv. rates (Å/s)": indiv_rates,
        "Tot. rate (Å/s)": _fmt_num(_pick(sci, "19_rate_A_s", "rate_A_s", default=""), 2),
        "Time (s)": _pick(sci, "21_deposition_time_s", "deposition_time_s", default=""),
        "Thickness (nm)": _pick(sci, "20_layer_thickness_nm", "layer_thickness_nm", default=""),
        "Comment": _pick(sci, "22_comment", "comment", default=""),
        "_dataset_id": details.get("unique_id") or details.get("dsid") or "",
        "_timestamp": details.get("timestamp") or "",
    }

def get_name_from_orcid(orcid_id):
    # Format the API endpoint URL
    url = f"https://orcid.org/{orcid_id}"
    
    # ORCID requires specific headers to return JSON
    headers = {
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad status codes
        
        data = response.json()
        
        # Navigate the deep nested structure of the ORCID JSON response
        name_data = data.get("person", {}).get("name", {})
        
        if "given-names" in name_data:
            given_names = name_data.get("given-names", {}).get("value", "")
        if "family-name" in name_data:
            family_name = name_data.get("family-name", {}).get("value", "")
        if "credit-name" in name_data:
            credit_name = ((name_data or {}).get("credit-name") or {}).get("value", "")
        
        # Prefer a credit name if it exists, otherwise combine given and family names
        if credit_name:
            return credit_name
        elif given_names or family_name:
            return f"{given_names} {family_name}".strip()
        else:
            return "Name is private or not set."
            
    except requests.exceptions.RequestException as e:
        return f"Error fetching data: {e}"
    
def get_name_from_orcid_cached(orcid_id: str) -> str:
    oid = (orcid_id or "").strip()
    if not oid:
        return ""

    with _ORCID_NAME_CACHE_LOCK:
        if oid in _ORCID_NAME_CACHE:
            return _ORCID_NAME_CACHE[oid]

    name = get_name_from_orcid(oid)
    if not name:
        name = oid  # fallback

    with _ORCID_NAME_CACHE_LOCK:
        _ORCID_NAME_CACHE[oid] = name

    return name

def _get_filtered_dataset_summaries(project_id, instrument_name, calibration_sample, view):
    all_ds = cruc_client.datasets.list(
        project_id=project_id,
        instrument_name=instrument_name,
        limit=2000
    )

    calib_ids = set()
    if calibration_sample:
        calib_ds = cruc_client.datasets.list(
            project_id=project_id,
            instrument_name=instrument_name,
            limit=2000,
            sample_id=calibration_sample
        )
        calib_ids = {d.get("unique_id") for d in calib_ds if d.get("unique_id")}

    if view == "Calibration only":
        filtered = [d for d in all_ds if d.get("unique_id") in calib_ids]
    elif view == "Deposition only":
        filtered = [d for d in all_ds if d.get("unique_id") not in calib_ids]
    else:
        filtered = all_ds

    return sorted(filtered, key=lambda d: _parse_ts(d.get("timestamp")), reverse=True)

def _norm_target(s):
    return " ".join(str(s or "").strip().lower().split())

def _row_matches_target(row, target):
    if not target or str(target).strip().lower() == "all":
        return True

    tsel = _norm_target(target)

    # Prefer hidden structured fields if present
    t1 = _norm_target(row.get("_target_1"))
    t2 = _norm_target(row.get("_target_2"))
    if t1 or t2:
        return tsel in {t1, t2}

    # Fallback: parse display field "Target" like "Au + Cu"
    disp = str(row.get("Target") or "")
    parts = [_norm_target(p) for p in disp.split("+") if _norm_target(p)]
    return tsel in set(parts)

def _get_cache_bucket(key):
    with _INCREMENTAL_CACHE_LOCK:
        if key not in _INCREMENTAL_CACHE:
            _INCREMENTAL_CACHE[key] = {
                "row_by_id": {},
                "ts_by_id": {},
                "ordered_ids": [],
                "last_scan_at": None,
            }
        return _INCREMENTAL_CACHE[key]

def _incremental_refresh_rows(project_id, instrument_name, calibration_sample, view):
    key = (project_id, instrument_name, calibration_sample, view)
    bucket = _get_cache_bucket(key)

    summaries = _get_filtered_dataset_summaries(project_id, instrument_name, calibration_sample, view)
    summary_by_id = {d["unique_id"]: d for d in summaries if d.get("unique_id")}
    current_ids = set(summary_by_id.keys())

    row_by_id = bucket["row_by_id"]
    ts_by_id = bucket["ts_by_id"]

    # remove deleted/out-of-scope
    for dsid in list(row_by_id.keys()):
        if dsid not in current_ids:
            row_by_id.pop(dsid, None)
            ts_by_id.pop(dsid, None)

    # add/update changed
    for dsid, s in summary_by_id.items():
        s_ts = _parse_ts(s.get("timestamp"))
        cached_ts = ts_by_id.get(dsid)

        need_fetch = (dsid not in row_by_id) or (cached_ts is None) or (s_ts > cached_ts)
        if need_fetch:
            details = cruc_client.datasets.get(dsid=dsid, include_metadata=True)
            row_by_id[dsid] = _dataset_to_row(details)
            ts_by_id[dsid] = _parse_ts(details.get("timestamp"))

    # rebuild order newest first
    ordered_ids = sorted(ts_by_id.keys(), key=lambda i: ts_by_id[i], reverse=True)
    bucket["ordered_ids"] = ordered_ids
    bucket["last_scan_at"] = datetime.now(timezone.utc)

    return [row_by_id[i] for i in ordered_ids]

# ---------- Routes ----------

@b30_sputter_bp.route("/")
def page():
    return render_template("b30_sputter.html", config=_tool())

@b30_sputter_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_state())

@b30_sputter_bp.route("/api/lookup-rate", methods=["POST"])
def lookup_rate():
    data = request.get_json(silent=True) or {}

    if not _tool().get("calibration_sample_id"):
        return jsonify({"found": False, "reason": "no_calibration_sample"}), 200

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
    built_at = (_RATE_INDEXES.get(_tool_key()) or {}).get("built_at")
    return jsonify({
        "ok": True,
        "count": len(idx or {}),
        "ref_sample": _tool().get("calibration_sample_id", ""),
        "ttl_seconds": RATE_INDEX_TTL_SECONDS,
        "rebuilt_at": built_at.isoformat() if built_at else None,
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
    added = _add_run_sample(state, sample)
    session.modified = True

    return jsonify({
        "found": True,
        "unique_id": sample["unique_id"],
        "sample_name": sample["sample_name"],
        "sample_type": sample.get("sample_type", ""),
        "description": sample.get("description", ""),
        "already_in_run": not added,
        "run_samples": state["run_samples"],
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

    project = user["selected_project"]

    # A duplicate name is allowed here, but never silently — the user has to confirm.
    if not data.get("allow_duplicate"):
        existing = cruc_client.samples.list(
            sample_name=sample_name, sample_type=sample_type, project_id=project
        )
        if existing:
            return jsonify({
                "exists": True,
                "error": f"{len(existing)} sample(s) named {sample_name} "
                         f"of type {sample_type} already exist in {project}.",
                "sample_name": sample_name,
                "existing_ids": [s["unique_id"] for s in existing],
            }), 409

    try:
        returned_sample = cruc_client.samples.create(
            sample_name=sample_name,
            timestamp=get_tz_isoformat(),
            owner_orcid=user["orcid"],
            project_id=project,
            sample_type=sample_type,
            description=description or None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    state = _get_state()
    state["sample_unique_id"] = returned_sample["unique_id"]
    state["sample_name"] = returned_sample["sample_name"]
    state["sample_type"] = sample_type
    state["sample_description"] = description
    _add_run_sample(state, {
        "unique_id": returned_sample["unique_id"],
        "sample_name": returned_sample["sample_name"],
        "sample_type": sample_type,
        "description": description,
    })
    session.modified = True

    return jsonify({
        "unique_id": returned_sample["unique_id"],
        "sample_name": returned_sample["sample_name"],
        "sample_type": sample_type,
        "description": description,
        "run_samples": state["run_samples"],
    })


# ---------- Samples linked to the next run ----------

@b30_sputter_bp.route("/api/run-samples/remove", methods=["POST"])
def remove_run_sample():
    data = request.get_json(silent=True) or {}
    unique_id = str(data.get("unique_id") or "").strip()

    state = _get_state()
    state["run_samples"] = [s for s in state["run_samples"] if s["unique_id"] != unique_id]
    session.modified = True

    return jsonify({"run_samples": state["run_samples"]})


@b30_sputter_bp.route("/api/run-samples/clear", methods=["POST"])
def clear_run_samples():
    state = _get_state()
    state["run_samples"] = []
    session.modified = True
    return jsonify({"run_samples": []})


# --- Sample Barcode printing -----

@b30_sputter_bp.route("/api/print-barcode", methods=["POST"])
def print_barcode():
    data = request.get_json() or {}
    sample_name = data.get("sample_name", "").strip()
    sample_mfid = data.get("sample_id", "").strip()

    if not sample_mfid:
        return jsonify({"error": "sample_id is required"}), 400

    try:
        publish_barcode(_tool()["printer_name"], sample_mfid, sample_name)
    except Exception as e:
        current_app.logger.error(f"[b30] Barcode print failed: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "sample_id": sample_mfid, "sample_name": sample_name}), 200


# ---------- Dataset upload ----------

@b30_sputter_bp.route("/api/upload-dataset", methods=["POST"])
def upload_dataset():
    """Create a sputtering dataset in Crucible and link it to every sample in the run."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    tool = _tool()
    state = _get_state()
    run_samples = state["run_samples"]
    if not run_samples:
        return jsonify({"error": "No samples in this run. Look up or create a sample first."}), 400

    def build_dataset_name(run_samples, data):
        date_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S") #Timezone-aware date
        co_dep = bool(data.get("01_co_deposition_enabled"))

        t1 = (data.get("09_target_material") or "").strip()
        t2 = (data.get("13_target_material_2") or "").strip()

        if co_dep and t1 and t2:
            target_part = f"{t1}+{t2}"
        else:
            target_part = t1 or "unknown-target"

        if len(run_samples) == 1:
            sample_part = (run_samples[0].get("sample_name") or "").strip() or "unknown-sample"
        else:
            sample_part = f"{len(run_samples)}_samples"

        return f"{date_str}_{target_part}_Sputtering_on_{sample_part}"

    data = request.get_json()

    # Build scientific_metadata from the fields defined for this tool in config.py.
    # To add or rename fields, update its "dataset_fields" list there.
    scientific_metadata = {}
    for field in tool["dataset_fields"]:
        key = field["key"]
        value = data.get(key, "").strip() if isinstance(data.get(key), str) else data.get(key, "")
        if value != "" and value is not None:
            scientific_metadata[key] = value

    dataset_name = build_dataset_name(run_samples, data or {})

    try:
        ds = Dataset(
            dataset_name=dataset_name,
            dataset_type=tool["dataset_type"],
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            instrument_name=tool["instrument_name"],
            measurement=tool["measurement"],
            timestamp=get_tz_isoformat(),
        )
        new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # The dataset exists by this point, so a failed link is reported per sample
    # instead of failing the whole upload.
    linked, failed = [], []
    for s in run_samples:
        try:
            cruc_client.datasets.add_sample(
                dataset_id=new_dataset["dsid"],
                sample_id=s["unique_id"],
            )
            linked.append(s["sample_name"] or s["unique_id"])
        except Exception as e:
            current_app.logger.error(f"[b30] Failed to link sample {s['unique_id']}: {e}")
            failed.append({"unique_id": s["unique_id"], "sample_name": s["sample_name"], "error": str(e)})

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": new_dataset["dsid"],
        "linked_samples": linked,
        "failed_samples": failed,
    })

# ---------- Dataset lookup ----------

@b30_sputter_bp.route("/api/recent-datasets", methods=["GET"])
def recent_datasets():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    instrument_name = _tool()["instrument_name"]
    calibration_sample = _tool().get("calibration_sample_id", "")
    view = (request.args.get("view") or "Deposition only").strip()
    target = (request.args.get("target") or "All").strip()
    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    try:
        rows_all = _incremental_refresh_rows(
            project_id, instrument_name, calibration_sample, view
        )

        rows = []
        for row in rows_all:
            if not _row_matches_target(row, target):
                continue
            out = dict(row)
            out.pop("_target_1", None)
            out.pop("_target_2", None)
            rows.append(out)
            if len(rows) >= limit:
                break

        return jsonify({"rows": rows, "count": len(rows)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_sputter_bp.route("/api/recent-target-options", methods=["GET"])
def recent_target_options():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    instrument_name = _tool()["instrument_name"]
    calibration_sample = _tool().get("calibration_sample_id", "")
    view = (request.args.get("view") or "Deposition only").strip()

    try:
        rows_all = _incremental_refresh_rows(project_id, instrument_name, calibration_sample, view)
        mats = set()
        for row in rows_all:
            t1 = (row.get("_target_1") or "").strip()
            t2 = (row.get("_target_2") or "").strip()
            if t1:
                mats.add(t1)
            if t2:
                mats.add(t2)

        return jsonify({"options": ["All"] + sorted(mats, key=str.lower)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_sputter_bp.route("/api/recent-datasets.csv", methods=["GET"])
def export_recent_datasets_csv():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    instrument_name = _tool()["instrument_name"]
    calibration_sample = _tool().get("calibration_sample_id", "")
    view = (request.args.get("view") or "Deposition only").strip()
    target = (request.args.get("target") or "All").strip()
    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    cols = [
        "Date", "User", "Gas", "Press. (mTorr)", "Temp. (°C)", "Target", "Source",
        "Power (W)", "DCV (V)", "Indiv. rates (Å/s)", "Tot. rate (Å/s)",
        "Time (s)", "Thickness (nm)", "Comment"
    ]

    try:
        rows_all = _incremental_refresh_rows(project_id, instrument_name, calibration_sample, view)

        selected = []
        for row in rows_all:
            if not _row_matches_target(row, target):
                continue
            selected.append(row)
            if len(selected) >= limit:
                break

        sio = io.StringIO()
        writer = csv.DictWriter(sio, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in selected:
            writer.writerow(row)

        bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))  # utf-8 BOM for Excel compatibility
        bio.seek(0)

        ts = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
        return send_file(
            bio,
            as_attachment=True,
            download_name=f"{ts}_{_tool_key()}_recent_datasets.csv",
            mimetype="text/csv",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
