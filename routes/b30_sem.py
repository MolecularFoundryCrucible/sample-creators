from flask import Blueprint, request, jsonify, session, render_template, current_app, send_file
from routes.shared import cruc_client, format_user, instrument_mfid, publish_barcode
from crucible import Dataset, Sample
from crucible.utils import get_tz_isoformat
from config import B30_SEM_CONFIG
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from threading import Lock
import io
import csv

b30_sem_bp = Blueprint("b30_sem", __name__)

PRINTER_NAME = B30_SEM_CONFIG.get("printer_name", "crucible-printer/b30-122")
LA_TZ = ZoneInfo("America/Los_Angeles")
INSTRUMENT_MFID = instrument_mfid(B30_SEM_CONFIG["instrument_mfid"])

_INCREMENTAL_CACHE = {}
_INCREMENTAL_CACHE_LOCK = Lock()


# ---------- Helpers ----------

def _parse_ts(ts):
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        # Producers (e.g. the SEM/EDX ingestors) write instrument-local times without an offset.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LA_TZ)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _pick(d, *keys, default=""):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v is not None and str(v).strip() != "":
            return v
    return default


def _clean(x):
    return "" if x is None else str(x).strip()


def _get_state():
    if "b30_sem" not in session:
        session["b30_sem"] = {
            "sample_unique_id": "",
            "sample_name": "",
            "sample_type": "",
            "sample_description": "",
        }
    return session["b30_sem"]


def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = _parse_ts(details.get("timestamp"))
    date_str = dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else ""

    owner_orcid = _pick(details, "owner_orcid", default="")

    return {
        "Date": date_str,
        "User": format_user(details.get("owner"), owner_orcid),
        "Vacuum": _clean(sci.get("vacuum_level")),
        "Spot": _clean(sci.get("spot_size")),
        "HV (V)": _clean(sci.get("high_voltage_V")),
        "Current (A)": _clean(sci.get("emission_current_A")),
        "Pressure (Torr)": _clean(sci.get("chamber_pressure_Torr")),
        "EDX": "Yes" if sci.get("edx_used") in (True, "true", "True", 1) else "",
        "Energy (keV)": _clean(sci.get("primary_energy_keV")),
        "Comment": _clean(sci.get("comment")),
        "_dataset_id": details.get("unique_id") or details.get("dsid") or "",
        "_timestamp": details.get("timestamp") or "",
    }


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


def _incremental_refresh_rows(project_id, instrument):
    key = (project_id, instrument)
    bucket = _get_cache_bucket(key)

    all_ds = cruc_client.datasets.list(
        project_id=project_id,
        instrument_mfid=instrument,
        limit=2000
    )
    summaries = sorted(all_ds, key=lambda d: _parse_ts(d.get("timestamp")), reverse=True)
    summary_by_id = {d["unique_id"]: d for d in summaries if d.get("unique_id")}
    current_ids = set(summary_by_id.keys())

    row_by_id = bucket["row_by_id"]
    ts_by_id = bucket["ts_by_id"]

    for dsid in list(row_by_id.keys()):
        if dsid not in current_ids:
            row_by_id.pop(dsid, None)
            ts_by_id.pop(dsid, None)

    for dsid, s in summary_by_id.items():
        s_ts = _parse_ts(s.get("timestamp"))
        cached_ts = ts_by_id.get(dsid)
        need_fetch = (dsid not in row_by_id) or (cached_ts is None) or (s_ts > cached_ts)
        if need_fetch:
            details = cruc_client.datasets.get(
                dataset_mfid=dsid,
                include_metadata=True,
                include_owner=True,
            )
            row_by_id[dsid] = _dataset_to_row(details)
            ts_by_id[dsid] = _parse_ts(details.get("timestamp"))

    ordered_ids = sorted(ts_by_id.keys(), key=lambda i: ts_by_id[i], reverse=True)
    bucket["ordered_ids"] = ordered_ids
    bucket["last_scan_at"] = datetime.now(timezone.utc)

    return [row_by_id[i] for i in ordered_ids]


# ---------- Routes ----------

@b30_sem_bp.route("/")
def page():
    return render_template("b30_sem.html", config=B30_SEM_CONFIG)


@b30_sem_bp.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(_get_state())


# ---------- Sample lookup (barcode scan) ----------

@b30_sem_bp.route("/api/lookup-sample", methods=["POST"])
def lookup_sample():
    data = request.get_json()
    unique_id = data.get("unique_id", "").strip()
    if not unique_id:
        return jsonify({"error": "No barcode value provided"}), 400

    try:
        sample = cruc_client.samples.get(unique_id)
    except Exception:
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


# ---------- Sample creation ----------

@b30_sem_bp.route("/api/create-sample", methods=["POST"])
def create_sample():
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
        returned_sample = cruc_client.samples.create(Sample(
            sample_name=sample_name,
            timestamp=get_tz_isoformat(),
            owner=user["orcid"],
            project_id=user["selected_project"],
            sample_type=sample_type,
            description=description or None,
        ))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    state = _get_state()
    state["sample_unique_id"] = returned_sample["unique_id"]
    state["sample_name"] = returned_sample["sample_name"]
    state["sample_type"] = sample_type
    state["sample_description"] = description
    session.modified = True

    return jsonify({
        "unique_id": returned_sample["unique_id"],
        "sample_name": returned_sample["sample_name"],
        "sample_type": sample_type,
        "description": description,
    })


# ---------- Barcode printing ----------

@b30_sem_bp.route("/api/print-barcode", methods=["POST"])
def print_barcode():
    data = request.get_json() or {}
    sample_name = data.get("sample_name", "").strip()
    sample_mfid = data.get("sample_id", "").strip()

    if not sample_mfid:
        return jsonify({"error": "sample_id is required"}), 400

    try:
        publish_barcode(PRINTER_NAME, sample_mfid, sample_name)
    except Exception as e:
        current_app.logger.error(f"[b30_sem] Barcode print failed: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "sample_id": sample_mfid, "sample_name": sample_name}), 200


# ---------- Dataset upload ----------

@b30_sem_bp.route("/api/upload-dataset", methods=["POST"])
def upload_dataset():
    """Create the SEM dataset (form fields only) and link the sample.

    The browser then uploads the files straight to storage via /api/uploads and requests
    ingestion; the FEI SEM and Bruker EDX ingestors fill in the file metadata.
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    state = _get_state()
    if not state.get("sample_unique_id"):
        return jsonify({"error": "No sample selected. Scan a barcode first."}), 400

    data = request.get_json(silent=True) or {}

    # Build scientific metadata from config-defined fields
    scientific_metadata = {}
    for field in B30_SEM_CONFIG["dataset_fields"]:
        key = field["key"]
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if value != "" and value is not None:
            scientific_metadata[key] = value

    sample_name = (state.get("sample_name") or "").strip() or "unknown-sample"
    date_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
    dataset_name = f"{date_str}_SEM_on_{sample_name}"

    try:
        ds = Dataset(
            dataset_name=dataset_name,
            data_type=B30_SEM_CONFIG["dataset_type"],
            owner=user["orcid"],
            project_id=user["selected_project"],
            instrument_mfid=INSTRUMENT_MFID,
            measurement=B30_SEM_CONFIG["measurement"],
            timestamp=get_tz_isoformat(),
        )
        new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)
        dataset_mfid = new_dataset["dataset_mfid"]

        cruc_client.datasets.add_sample(
            dataset_mfid=dataset_mfid,
            sample_mfid=state["sample_unique_id"],
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": dataset_mfid,
        "sample_name": state["sample_name"],
    })


# ---------- Dataset logbook ----------

@b30_sem_bp.route("/api/recent-datasets", methods=["GET"])
def recent_datasets():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    try:
        rows_all = _incremental_refresh_rows(project_id, INSTRUMENT_MFID)
        rows = []
        for row in rows_all:
            out = dict(row)
            out.pop("_dataset_id", None)
            out.pop("_timestamp", None)
            rows.append(out)
            if len(rows) >= limit:
                break
        return jsonify({"rows": rows, "count": len(rows)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_sem_bp.route("/api/recent-datasets/b30_sem_recent_datasets.csv", methods=["GET"])
def export_recent_datasets_csv():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    project_id = user.get("selected_project")
    if not project_id:
        return jsonify({"error": "No selected project"}), 400

    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 5000))

    cols = ["Date", "User", "Vacuum", "Spot", "HV (V)", "Current (A)",
            "Pressure (Torr)", "EDX", "Energy (keV)", "Comment"]

    try:
        rows_all = _incremental_refresh_rows(project_id, INSTRUMENT_MFID)
        selected = rows_all[:limit]

        sio = io.StringIO()
        writer = csv.DictWriter(sio, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in selected:
            writer.writerow(row)

        bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))
        bio.seek(0)

        ts = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
        return send_file(
            bio,
            as_attachment=True,
            download_name=f"{ts}_sem_recent_datasets.csv",
            mimetype="text/csv",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
