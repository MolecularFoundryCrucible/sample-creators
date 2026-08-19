import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, session, render_template, current_app

from config import PRINT_CONFIG
from routes.shared import cruc_client, publish_barcode, resolve_printer

print_bp = Blueprint("print", __name__)

LA_TZ = ZoneInfo("America/Los_Angeles")
FUZZY_SEARCH_MAX = 50  # server-side cap on /samples/search


def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sample_ts(sample):
    return _parse_ts(sample.get("timestamp")) or _parse_ts(sample.get("creation_time"))


def _parse_date_filter(value, end_of_day=False):
    """Parse a "YYYY-MM-DD" from the date picker as a local-time boundary."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=LA_TZ) if dt.tzinfo is None else dt


def _require_project():
    """Return (project_id, error_response). Exactly one is None."""
    user = session.get("user")
    if not user:
        return None, (jsonify({"error": "Not logged in"}), 401)
    project_id = user.get("selected_project")
    if not project_id:
        return None, (jsonify({"error": "No project selected"}), 400)
    return project_id, None


def _to_row(sample):
    dt = _sample_ts(sample)
    return {
        "unique_id": sample.get("unique_id", ""),
        "sample_name": sample.get("sample_name", ""),
        "sample_type": sample.get("sample_type", ""),
        "description": sample.get("description", "") or "",
        "timestamp": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
    }


@print_bp.route("/")
def page():
    return render_template("print.html", print_config=PRINT_CONFIG)


@print_bp.route("/api/search", methods=["POST"])
def search():
    project_id, err = _require_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = (data.get("sample_name") or "").strip()
    sample_type = (data.get("sample_type") or "").strip()
    exact = bool(data.get("exact"))
    date_from = _parse_date_filter(data.get("date_from"))
    date_to = _parse_date_filter(data.get("date_to"), end_of_day=True)

    fuzzy = not exact and len(name) >= 3
    if name and not exact and not fuzzy:
        return jsonify({
            "error": "Fuzzy search needs at least 3 characters. "
                     "Tick 'Exact match' to look up a shorter name."
        }), 400

    try:
        if fuzzy:
            samples = cruc_client.samples.search(
                q=name, project_id=project_id, limit=FUZZY_SEARCH_MAX
            )
        else:
            # limit=None follows the keyset cursor to the end, so an exact search is
            # not capped by page size the way the fuzzy endpoint is.
            samples = cruc_client.samples.list(
                project_id=project_id,
                sample_name=name or None,
                sample_type=sample_type or None,
                limit=None,
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    rows = []
    for s in samples:
        # /samples/search matches on name only, so type has to be applied here.
        if fuzzy and sample_type and (s.get("sample_type") or "") != sample_type:
            continue
        if date_from or date_to:
            dt = _sample_ts(s)
            if dt is None:
                continue
            if date_from and dt < date_from:
                continue
            if date_to and dt > date_to:
                continue
        rows.append(_to_row(s))

    return jsonify({"rows": rows, "count": len(rows), "fuzzy": fuzzy})


@print_bp.route("/api/print-batch", methods=["POST"])
def print_batch():
    if not session.get("user"):
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    items = data.get("items") or []

    try:
        printer = resolve_printer(data.get("printer"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not items:
        return jsonify({"error": "Nothing to print"}), 400
    if len(items) > PRINT_CONFIG["max_batch"]:
        return jsonify({
            "error": f"{len(items)} labels requested, limit is {PRINT_CONFIG['max_batch']}"
        }), 400

    results = []
    for i, item in enumerate(items):
        mfid = str(item.get("mfid") or "").strip()
        name = str(item.get("name") or "").strip()

        if not mfid:
            results.append({"mfid": "", "name": name, "ok": False, "error": "Missing MFID"})
            continue

        if i:
            time.sleep(PRINT_CONFIG["print_delay_s"])

        try:
            publish_barcode(printer, mfid, name)
            results.append({"mfid": mfid, "name": name, "ok": True, "error": ""})
        except Exception as e:
            current_app.logger.error(f"[print] Failed to print {mfid} on {printer}: {e}")
            results.append({"mfid": mfid, "name": name, "ok": False, "error": str(e)})

    printed = sum(1 for r in results if r["ok"])
    return jsonify({
        "printer": printer,
        "printed": printed,
        "failed": len(results) - printed,
        "results": results,
    })
