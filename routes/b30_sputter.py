from flask import Blueprint, request, jsonify, session, render_template, current_app
from routes.shared import cruc_client
from routes.deposition_common import (
    LA_TZ,
    build_scientific_metadata,
    clean,
    csv_response,
    fmt_num,
    get_name_from_orcid_cached,
    incremental_refresh_rows,
    link_new_samples_to_dataset,
    link_samples_to_dataset,
    make_state_getter,
    parse_ts,
    pick,
    register_sample_routes,
    row_matches_target,
)
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from config import SPUTTER_TOOLS
from datetime import datetime, timezone
from threading import Lock

# This blueprint is registered once per sputter tool (see app.py), so every tool gets its
# own page and URL prefix while sharing this code. Views call _tool() to find out which
# tool they are serving; nothing here is hardcoded to a single instrument.
b30_sputter_bp = Blueprint("b30_sputter", __name__)

BLUEPRINT_NAME_PREFIX = "b30_sputter_"

LOGBOOK_COLS = [
    "Date", "User", "Gas", "Press. (mTorr)", "Temp. (°C)", "Target", "Source",
    "Power (W)", "DCV (V)", "Indiv. rates (Å/s)", "Tot. rate (Å/s)",
    "Time (s)", "Thickness (nm)", "Comment",
]

# Cache settings
RATE_INDEX_TTL_SECONDS = 300  # 5 minutes

# In-memory cache: tool key -> {"index": {...}, "built_at": datetime}
_RATE_INDEXES = {}
_RATE_INDEX_LOCK = Lock()


def blueprint_name(tool_key):
    """Registered blueprint name for a tool, e.g. "aja" -> "b30_sputter_aja"."""
    return f"{BLUEPRINT_NAME_PREFIX}{tool_key}"


def build_dataset_name(run_samples, data, date_str):
    """Compose a dataset name from the deposition targets and the samples in the run."""
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


def _tool_key():
    """The tool this request belongs to, read back from the registered blueprint name."""
    return (request.blueprint or "").removeprefix(BLUEPRINT_NAME_PREFIX)


def _tool():
    return SPUTTER_TOOLS[_tool_key()]


def _calibration_sample():
    return _tool().get("calibration_sample_id", "")


# Per-tool session state, so the tools never share a sample list.
_get_state = make_state_getter(lambda: f"b30_sputter_{_tool_key()}")


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
            ts_dt = parse_ts(ts)

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
    ref_sample = _calibration_sample()
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

def _canonical_reactive_gas(sci: dict) -> str:
    gas1 = clean(sci.get("03_gas1") or sci.get("gas1"))
    gas2 = clean(sci.get("05_gas2") or sci.get("gas2"))
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
    dt = parse_ts(details.get("timestamp"))
    date_str = dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else ""

    t1 = clean(sci.get("09_target_material") or sci.get("target_material"))
    t2 = clean(sci.get("13_target_material_2") or sci.get("target_material_2"))
    targets = " + ".join([x for x in [t1, t2] if x])

    s1 = clean(sci.get("10_power_source") or sci.get("power_source"))
    s2 = clean(sci.get("14_power_source_2") or sci.get("power_source_2"))
    sources = " + ".join([x for x in [s1, s2] if x])

    p1 = clean(sci.get("11_power_W") or sci.get("power_w"))
    p2 = clean(sci.get("15_power_W_2") or sci.get("power_w_2"))
    powers = " + ".join([x for x in [p1, p2] if x])

    d1 = clean(sci.get("12_DC_voltage_V") or sci.get("DC_voltage_V"))
    d2 = clean(sci.get("16_DC_voltage_V_2") or sci.get("DC_voltage_V_2"))
    dcvs = " + ".join([x for x in [d1, d2] if x])

    r1 = fmt_num(sci.get("17_rate_A_s_1") or sci.get("rate_A_s_1"), 2)
    r2 = fmt_num(sci.get("18_rate_A_s_2") or sci.get("rate_A_s_2"), 2)
    indiv_rates = " + ".join([x for x in [r1, r2] if x])

    owner_orcid = pick(details, "owner_orcid", default="")
    user_name = get_name_from_orcid_cached(owner_orcid) if owner_orcid else ""

    return {
        "Date": date_str,
        "User": user_name or owner_orcid,
        "Gas": _canonical_reactive_gas(sci),
        "Press. (mTorr)": pick(sci, "07_pressure_mTorr", "pressure_mTorr", default=""),
        "Temp. (°C)": pick(sci, "08_substrates_temperature_C", default=""),
        "Target": targets,
        "Source": sources,
        "Power (W)": powers,
        "DCV (V)": dcvs,
        "Indiv. rates (Å/s)": indiv_rates,
        "Tot. rate (Å/s)": fmt_num(pick(sci, "19_rate_A_s", "rate_A_s", default=""), 2),
        "Time (s)": pick(sci, "21_deposition_time_s", "deposition_time_s", default=""),
        "Thickness (nm)": pick(sci, "20_layer_thickness_nm", "layer_thickness_nm", default=""),
        "Comment": pick(sci, "22_comment", "comment", default=""),
        "_dataset_id": details.get("unique_id") or details.get("dsid") or "",
        "_timestamp": details.get("timestamp") or "",
    }

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
            sample_mfid=calibration_sample
        )
        calib_ids = {d.get("unique_id") for d in calib_ds if d.get("unique_id")}

    if view == "Calibration only":
        filtered = [d for d in all_ds if d.get("unique_id") in calib_ids]
    elif view == "Deposition only":
        filtered = [d for d in all_ds if d.get("unique_id") not in calib_ids]
    else:
        filtered = all_ds

    return sorted(filtered, key=lambda d: parse_ts(d.get("timestamp")), reverse=True)

def _rows_for_view(project_id, view):
    """Logbook rows for this page's tool only."""
    instrument_name = _tool()["instrument_name"]
    calibration_sample = _calibration_sample()
    return incremental_refresh_rows(
        cache_key=(project_id, instrument_name, calibration_sample, view),
        fetch_summaries=lambda: _get_filtered_dataset_summaries(
            project_id, instrument_name, calibration_sample, view
        ),
        build_row=_dataset_to_row,
    )

# ---------- Routes ----------

register_sample_routes(b30_sputter_bp, _get_state, lambda: _tool()["printer_name"], "b30")

@b30_sputter_bp.route("/")
def page():
    return render_template("b30_sputter.html", config=_tool())

@b30_sputter_bp.route("/api/lookup-rate", methods=["POST"])
def lookup_rate():
    data = request.get_json(silent=True) or {}

    if not _calibration_sample():
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
        "ref_sample": _calibration_sample(),
        "ttl_seconds": RATE_INDEX_TTL_SECONDS,
        "rebuilt_at": built_at.isoformat() if built_at else None,
    }), 200


# ---------- Dataset create / update ----------

@b30_sputter_bp.route("/api/create-dataset", methods=["POST"])
def create_dataset():
    """Create a sputtering dataset in Crucible and link it to every sample in the run."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    tool = _tool()
    state = _get_state()
    run_samples = state["run_samples"]
    if not run_samples:
        return jsonify({"error": "No samples in this run. Look up or create a sample first."}), 400

    data = request.get_json()

    # To add or rename fields, update this tool's "dataset_fields" list in config.py.
    scientific_metadata = build_scientific_metadata(tool["dataset_fields"], data)

    date_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")  # Timezone-aware date
    dataset_name = build_dataset_name(run_samples, data or {}, date_str)

    try:
        ds = Dataset(
            dataset_name=dataset_name,
            data_type=tool["dataset_type"],
            owner=user["orcid"],
            project_id=user["selected_project"],
            instrument_name=tool["instrument_name"],
            measurement=tool["measurement"],
            timestamp=get_tz_isoformat(),
        )
        new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    dataset_mfid = new_dataset["dataset_mfid"]
    linked, failed = link_samples_to_dataset(dataset_mfid, run_samples, "b30")

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": dataset_mfid,
        "tool": _tool_key(),
        "linked_samples": linked,
        "failed_samples": failed,
    })


@b30_sputter_bp.route("/api/update-dataset", methods=["POST"])
def update_dataset():
    """Re-save the form onto a dataset already created from it.

    The name is rebuilt so it keeps matching the targets it describes, reusing the timestamp
    it was first stamped with rather than taking a new one.
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json() or {}
    dataset_id = (data.get("dataset_id") or "").strip()
    if not dataset_id:
        return jsonify({"error": "No dataset to update. Create one first."}), 400

    run_samples = _get_state()["run_samples"]
    scientific_metadata = build_scientific_metadata(_tool()["dataset_fields"], data)

    # Keep the "YYYYMMDD_HHMMSS" the name was created with; only what follows is rebuilt.
    date_str = "_".join((data.get("dataset_name") or "").split("_")[:2])
    dataset_name = build_dataset_name(run_samples, data, date_str)

    try:
        cruc_client.datasets.update_scientific_metadata(dataset_id, scientific_metadata)
        cruc_client.datasets.update(dataset_id, dataset_name=dataset_name)
        linked, failed = link_new_samples_to_dataset(dataset_id, run_samples, "b30")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
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

    view = (request.args.get("view") or "Deposition only").strip()
    target = (request.args.get("target") or "All").strip()
    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    try:
        rows_all = _rows_for_view(project_id, view)

        rows = []
        for row in rows_all:
            if not row_matches_target(row, target):
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

    view = (request.args.get("view") or "Deposition only").strip()

    try:
        rows_all = _rows_for_view(project_id, view)
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


@b30_sputter_bp.route("/api/recent-datasets/b30_sputter_recent_datasets.csv", methods=["GET"])
def export_recent_datasets_csv():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    view = (request.args.get("view") or "Deposition only").strip()
    target = (request.args.get("target") or "All").strip()
    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    try:
        rows_all = _rows_for_view(project_id, view)

        selected = []
        for row in rows_all:
            if not row_matches_target(row, target):
                continue
            selected.append(row)
            if len(selected) >= limit:
                break

        return csv_response(LOGBOOK_COLS, selected, f"{_tool_key()}_recent_datasets")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
