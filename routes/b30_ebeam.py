"""B30 e-beam evaporator data entry and logbook.

Same workflow as the sputter app — scan samples into a run, record the deposition
parameters, upload one dataset linked to every sample — with a much smaller parameter set.
The sample handling itself lives in deposition_common.
"""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session

from config import B30_EBEAM_CONFIG
from crucible import Dataset
from crucible.utils import get_tz_isoformat
from routes.deposition_common import (
    LA_TZ,
    build_scientific_metadata,
    clean,
    csv_response,
    fmt_num,
    get_name_from_orcid_cached,
    incremental_refresh_rows,
    link_samples_to_dataset,
    make_state_getter,
    parse_ts,
    pick,
    register_sample_routes,
    row_matches_target,
)
from routes.shared import cruc_client

b30_ebeam_bp = Blueprint("b30_ebeam", __name__)

INSTRUMENT_NAME = B30_EBEAM_CONFIG["instrument_name"]
PRINTER_NAME = B30_EBEAM_CONFIG.get("printer_name", "crucible-printer/b30-113")

LOGBOOK_COLS = [
    "Date", "User", "Target", "Power (W)", "Rate (Å/s)",
    "Base press. (mTorr)", "Dep. press. (mTorr)", "Comment",
]

_get_state = make_state_getter("b30_ebeam")

register_sample_routes(b30_ebeam_bp, _get_state, PRINTER_NAME, "b30-ebeam")


def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = parse_ts(details.get("timestamp"))

    owner_orcid = pick(details, "owner_orcid", default="")

    return {
        "Date": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
        "User": get_name_from_orcid_cached(owner_orcid) if owner_orcid else "",
        "Target": clean(sci.get("01_target_material")),
        "Power (W)": clean(sci.get("02_power_W")),
        "Rate (Å/s)": fmt_num(sci.get("03_rate_A_s"), 2),
        "Base press. (mTorr)": clean(sci.get("04_base_pressure_mTorr")),
        "Dep. press. (mTorr)": clean(sci.get("05_deposition_pressure_mTorr")),
        "Comment": clean(sci.get("06_comment")),
        "_target_1": clean(sci.get("01_target_material")),
        "_dataset_id": details.get("unique_id") or details.get("dsid") or "",
        "_timestamp": details.get("timestamp") or "",
    }


def _fetch_summaries(project_id):
    datasets = cruc_client.datasets.list(
        project_id=project_id,
        instrument_name=INSTRUMENT_NAME,
        limit=2000,
    )
    return sorted(datasets, key=lambda d: parse_ts(d.get("timestamp")), reverse=True)


def _all_rows(project_id):
    return incremental_refresh_rows(
        cache_key=(project_id, INSTRUMENT_NAME),
        fetch_summaries=lambda: _fetch_summaries(project_id),
        build_row=_dataset_to_row,
    )


def _require_project():
    """Return (project_id, error_response). Exactly one of the two is set."""
    user = session.get("user")
    if not user:
        return None, (jsonify({"error": "Not logged in"}), 401)

    project_id = user.get("selected_project")
    if not project_id:
        return None, (jsonify({"error": "No selected project"}), 400)

    return project_id, None


def _selected_rows(project_id, target, limit):
    rows = []
    for row in _all_rows(project_id):
        if not row_matches_target(row, target):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _limit_arg():
    return max(1, min(int(request.args.get("limit", 100)), 5000))


# ---------- Routes ----------

@b30_ebeam_bp.route("/")
def page():
    return render_template("b30_ebeam.html", config=B30_EBEAM_CONFIG)


@b30_ebeam_bp.route("/api/upload-dataset", methods=["POST"])
def upload_dataset():
    """Create an e-beam dataset in Crucible and link it to every sample in the run."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    run_samples = _get_state()["run_samples"]
    if not run_samples:
        return jsonify({
            "error": "No samples in this run. Look up or create a sample first."
        }), 400

    data = request.get_json() or {}

    # To add or rename fields, update the "dataset_fields" list in config.py.
    scientific_metadata = build_scientific_metadata(B30_EBEAM_CONFIG["dataset_fields"], data)

    date_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
    target = (data.get("01_target_material") or "").strip() or "unknown-target"
    if len(run_samples) == 1:
        sample_part = (run_samples[0].get("sample_name") or "").strip() or "unknown-sample"
    else:
        sample_part = f"{len(run_samples)}_samples"
    dataset_name = f"{date_str}_{target}_Ebeam_on_{sample_part}"

    try:
        ds = Dataset(
            dataset_name=dataset_name,
            dataset_type=B30_EBEAM_CONFIG["dataset_type"],
            owner_orcid=user["orcid"],
            project_id=user["selected_project"],
            instrument_name=INSTRUMENT_NAME,
            measurement=B30_EBEAM_CONFIG["measurement"],
            timestamp=get_tz_isoformat(),
        )
        new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    linked, failed = link_samples_to_dataset(new_dataset["dsid"], run_samples, "b30-ebeam")

    return jsonify({
        "dataset_name": dataset_name,
        "dataset_id": new_dataset["dsid"],
        "linked_samples": linked,
        "failed_samples": failed,
    })


@b30_ebeam_bp.route("/api/recent-datasets", methods=["GET"])
def recent_datasets():
    project_id, err = _require_project()
    if err:
        return err

    target = (request.args.get("target") or "All").strip()

    try:
        rows = []
        for row in _selected_rows(project_id, target, _limit_arg()):
            out = dict(row)
            out.pop("_target_1", None)
            rows.append(out)

        return jsonify({"rows": rows, "count": len(rows)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_ebeam_bp.route("/api/recent-target-options", methods=["GET"])
def recent_target_options():
    project_id, err = _require_project()
    if err:
        return err

    try:
        mats = {t for row in _all_rows(project_id) if (t := (row.get("_target_1") or "").strip())}
        return jsonify({"options": ["All"] + sorted(mats, key=str.lower)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@b30_ebeam_bp.route("/api/recent-datasets/b30_ebeam_recent_datasets.csv", methods=["GET"])
def export_recent_datasets_csv():
    project_id, err = _require_project()
    if err:
        return err

    target = (request.args.get("target") or "All").strip()

    try:
        rows = _selected_rows(project_id, target, _limit_arg())
        return csv_response(LOGBOOK_COLS, rows, "ebeam_recent_datasets")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
