"""Machinery shared by the B30 deposition data-entry apps (sputter, e-beam).

Every deposition page does the same thing with samples: scan a barcode, look the sample up,
create it if it does not exist, collect several into a "run", and print labels. Only the
session key and the label printer differ, so those routes are registered from here rather
than copied per tool.

The logbook halves of the apps differ (different columns, different filters), but they share
the row cache and the small formatting helpers below.
"""

import csv
import io
from datetime import datetime, timezone
from threading import Lock
from zoneinfo import ZoneInfo

import requests
from flask import current_app, jsonify, request, send_file, session

from crucible.utils import get_tz_isoformat
from routes.shared import cruc_client, publish_barcode

LA_TZ = ZoneInfo("America/Los_Angeles")


# ---------- Session state ----------

def make_state_getter(session_key, extra_defaults=None):
    """Build the per-app `_get_state()` used by the sample routes.

    `session_key` may be a callable, resolved per request — the sputter blueprint is
    registered once per tool, so each of its pages needs its own key.
    `extra_defaults` seeds keys the app adds on top of the sample fields.
    """
    def get_state():
        key = session_key() if callable(session_key) else session_key
        state = session.setdefault(key, {})
        state.setdefault("sample_unique_id", "")
        state.setdefault("sample_name", "")
        state.setdefault("sample_type", "")
        state.setdefault("sample_description", "")
        # Samples that the next uploaded dataset will be linked to.
        state.setdefault("run_samples", [])
        for key, value in (extra_defaults or {}).items():
            state.setdefault(key, value)
        return state

    return get_state


def _add_run_sample(state, sample):
    """Put a looked-up or newly created sample into the run, ignoring repeats."""
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


# ---------- Sample routes ----------

def register_sample_routes(bp, get_state, printer_name, log_prefix):
    """Register the sample lookup/creation/run/print routes onto a blueprint.

    `printer_name` may be a callable, resolved per request, for blueprints registered
    once per instrument.
    """

    @bp.route("/api/state", methods=["GET"])
    def get_state_route():
        return jsonify(get_state())

    @bp.route("/api/lookup-sample", methods=["POST"])
    def lookup_sample():
        """Look up a sample by its Crucible unique_id (scanned barcode) and add it to the run."""
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

        state = get_state()
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

    @bp.route("/api/create-sample", methods=["POST"])
    def create_sample():
        """Create a new sample in Crucible, store it in session and add it to the run."""
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

        state = get_state()
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

    @bp.route("/api/run-samples", methods=["GET"])
    def list_run_samples():
        return jsonify({"run_samples": get_state()["run_samples"]})

    @bp.route("/api/run-samples/remove", methods=["POST"])
    def remove_run_sample():
        data = request.get_json(silent=True) or {}
        unique_id = str(data.get("unique_id") or "").strip()

        state = get_state()
        state["run_samples"] = [s for s in state["run_samples"] if s["unique_id"] != unique_id]
        session.modified = True

        return jsonify({"run_samples": state["run_samples"]})

    @bp.route("/api/run-samples/clear", methods=["POST"])
    def clear_run_samples():
        state = get_state()
        state["run_samples"] = []
        session.modified = True
        return jsonify({"run_samples": []})

    @bp.route("/api/print-barcode", methods=["POST"])
    def print_barcode():
        data = request.get_json() or {}
        sample_name = data.get("sample_name", "").strip()
        sample_mfid = data.get("sample_id", "").strip()

        if not sample_mfid:
            return jsonify({"error": "sample_id is required"}), 400

        try:
            printer = printer_name() if callable(printer_name) else printer_name
            publish_barcode(printer, sample_mfid, sample_name)
        except Exception as e:
            current_app.logger.error(f"[{log_prefix}] Barcode print failed: {e}")
            return jsonify({"error": str(e)}), 500

        return jsonify({"ok": True, "sample_id": sample_mfid, "sample_name": sample_name}), 200


# ---------- Dataset upload ----------

def build_scientific_metadata(dataset_fields, data):
    """Collect the configured form fields out of the request body, dropping blanks."""
    metadata = {}
    for field in dataset_fields:
        key = field["key"]
        value = data.get(key, "")
        if isinstance(value, str):
            value = value.strip()
        if value != "" and value is not None:
            metadata[key] = value
    return metadata


def link_samples_to_dataset(dataset_id, run_samples, log_prefix):
    """Link a freshly created dataset to every sample in the run.

    The dataset already exists by this point, so a failed link is reported per sample
    rather than failing the whole upload.
    """
    linked, failed = [], []
    for s in run_samples:
        try:
            cruc_client.datasets.add_sample(dataset_id=dataset_id, sample_id=s["unique_id"])
            linked.append(s["sample_name"] or s["unique_id"])
        except Exception as e:
            current_app.logger.error(
                f"[{log_prefix}] Failed to link sample {s['unique_id']}: {e}"
            )
            failed.append({
                "unique_id": s["unique_id"],
                "sample_name": s["sample_name"],
                "error": str(e),
            })
    return linked, failed


def link_new_samples_to_dataset(dataset_id, run_samples, log_prefix):
    """Link the run samples that are not on the dataset already.

    Used when re-saving an existing dataset: the run may have grown since it was created,
    and re-linking a sample that is already there would be an error rather than a no-op.
    """
    already_linked = {
        s["unique_id"] for s in cruc_client.samples.list(dataset_id=dataset_id)
    }
    new_samples = [s for s in run_samples if s["unique_id"] not in already_linked]
    return link_samples_to_dataset(dataset_id, new_samples, log_prefix)


# ---------- Formatting helpers ----------

def parse_ts(ts):
    """Parse a Crucible timestamp into an aware datetime; unparseable values sort oldest."""
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def pick(d, *keys, default=""):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v is not None and str(v).strip() != "":
            return v
    return default


def clean(x):
    return "" if x is None else str(x).strip()


def fmt_num(x, ndigits=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return f"{v:.{ndigits}f}" if ndigits is not None else f"{v:g}"


# ---------- ORCID name lookup ----------

_ORCID_NAME_CACHE = {}
_ORCID_NAME_CACHE_LOCK = Lock()


def get_name_from_orcid(orcid_id):
    url = f"https://orcid.org/{orcid_id}"
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        name_data = response.json().get("person", {}).get("name", {}) or {}

        credit_name = (name_data.get("credit-name") or {}).get("value", "")
        given_names = (name_data.get("given-names") or {}).get("value", "")
        family_name = (name_data.get("family-name") or {}).get("value", "")

        if credit_name:
            return credit_name
        if given_names or family_name:
            return f"{given_names} {family_name}".strip()
        return "Name is private or not set."

    except requests.exceptions.RequestException as e:
        return f"Error fetching data: {e}"


def get_name_from_orcid_cached(orcid_id):
    oid = (orcid_id or "").strip()
    if not oid:
        return ""

    with _ORCID_NAME_CACHE_LOCK:
        if oid in _ORCID_NAME_CACHE:
            return _ORCID_NAME_CACHE[oid]

    name = get_name_from_orcid(oid) or oid

    with _ORCID_NAME_CACHE_LOCK:
        _ORCID_NAME_CACHE[oid] = name

    return name


# ---------- Target filtering ----------

def norm_target(s):
    return " ".join(str(s or "").strip().lower().split())


def row_matches_target(row, target):
    if not target or str(target).strip().lower() == "all":
        return True

    tsel = norm_target(target)

    # Prefer hidden structured fields if present
    t1 = norm_target(row.get("_target_1"))
    t2 = norm_target(row.get("_target_2"))
    if t1 or t2:
        return tsel in {t1, t2}

    # Fallback: parse display field "Target" like "Au + Cu"
    parts = [norm_target(p) for p in str(row.get("Target") or "").split("+") if norm_target(p)]
    return tsel in set(parts)


# ---------- Logbook row cache ----------

# cache_key -> {"row_by_id": {...}, "ts_by_id": {...}, "ordered_ids": [...], "last_scan_at": dt}
_INCREMENTAL_CACHE = {}
_INCREMENTAL_CACHE_LOCK = Lock()


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


def incremental_refresh_rows(cache_key, fetch_summaries, build_row):
    """Return logbook rows newest first, only re-fetching datasets that changed.

    `fetch_summaries()` returns the dataset summaries in scope; `build_row(details)` turns a
    full dataset (with metadata) into a display row. Full metadata is fetched only for
    datasets that are new or whose timestamp moved, because that call is the expensive one.
    """
    bucket = _get_cache_bucket(cache_key)

    summaries = fetch_summaries()
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
        s_ts = parse_ts(s.get("timestamp"))
        cached_ts = ts_by_id.get(dsid)

        if (dsid not in row_by_id) or (cached_ts is None) or (s_ts > cached_ts):
            details = cruc_client.datasets.get(dsid=dsid, include_metadata=True)
            row_by_id[dsid] = build_row(details)
            ts_by_id[dsid] = parse_ts(details.get("timestamp"))

    ordered_ids = sorted(ts_by_id.keys(), key=lambda i: ts_by_id[i], reverse=True)
    bucket["ordered_ids"] = ordered_ids
    bucket["last_scan_at"] = datetime.now(timezone.utc)

    return [row_by_id[i] for i in ordered_ids]


# ---------- CSV export ----------

def csv_response(cols, rows, filename_suffix):
    sio = io.StringIO()
    writer = csv.DictWriter(sio, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))  # utf-8 BOM for Excel compatibility
    bio.seek(0)

    ts = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
    return send_file(
        bio,
        as_attachment=True,
        download_name=f"{ts}_{filename_suffix}.csv",
        mimetype="text/csv",
    )
