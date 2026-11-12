"""B30 Raman data entry: Horiba LabRAM spectra (LabSpec 6 .ngs), one sample per dataset.

Sample, upload and logbook routes come from routes/instrument_page.py; HoribaNgsIngestor
extracts the spectrum metadata after the browser uploads the files.
"""
from flask import Blueprint, render_template

from config import B30_RAMAN_CONFIG
from routes.deposition_common import LA_TZ, clean, fmt_num, parse_ts, pick
from routes.instrument_page import register_instrument_routes
from routes.shared import format_user

b30_raman_bp = Blueprint("b30_raman", __name__)

LOGBOOK_COLS = ["Date", "User", "Laser (nm)", "Exposure (s)", "Accumulation", "Grating",
                "Objective", "Range (1/cm)", "Spectra", "Comment"]


def _shift_range(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{fmt_num(value[0])}–{fmt_num(value[1])}"
    return clean(value)


def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = parse_ts(details.get("timestamp"))
    return {
        "Date": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
        "User": format_user(details.get("owner"), pick(details, "owner_orcid", default="")),
        "Laser (nm)": fmt_num(sci.get("laser_wavelength_nm")),
        "Exposure (s)": fmt_num(sci.get("exposure_time_s")),
        "Accumulation": clean(sci.get("accumulation")),
        "Grating": clean(sci.get("grating")),
        "Objective": clean(sci.get("objective")),
        "Range (1/cm)": _shift_range(sci.get("raman_shift_range_cm-1")),
        "Spectra": str(len(sci.get("raman_spectra") or {})) if sci.get("raman_spectra") else "",
        "Comment": clean(sci.get("comment")),
        "_dataset_id": details.get("unique_id") or "",
        "_timestamp": details.get("timestamp") or "",
    }


@b30_raman_bp.route("/")
def page():
    return render_template("b30_raman.html", config=B30_RAMAN_CONFIG)


register_instrument_routes(
    b30_raman_bp,
    config=B30_RAMAN_CONFIG,
    session_key="b30_raman",
    dataset_to_row=_dataset_to_row,
    logbook_cols=LOGBOOK_COLS,
    csv_filename="b30_raman_recent_datasets.csv",
    log_prefix="b30_raman",
)
