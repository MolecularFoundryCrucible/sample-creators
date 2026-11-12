"""B30 SEM data entry: images (FEI TIFF) and EDX (Bruker .spx/.rtx), one sample per dataset.

Sample, upload and logbook routes come from routes/instrument_page.py; the FEI SEM and
Bruker EDX ingestors extract the file metadata after the browser uploads the files.
"""
from flask import Blueprint, render_template

from config import B30_SEM_CONFIG
from routes.deposition_common import LA_TZ, clean, parse_ts, pick
from routes.instrument_page import register_instrument_routes
from routes.shared import format_user

b30_sem_bp = Blueprint("b30_sem", __name__)

LOGBOOK_COLS = ["Date", "User", "Vacuum", "Spot", "HV (V)", "Current (A)",
                "Pressure (Torr)", "EDX", "Energy (keV)", "Comment"]


def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = parse_ts(details.get("timestamp"))
    return {
        "Date": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
        "User": format_user(details.get("owner"), pick(details, "owner_orcid", default="")),
        "Vacuum": clean(sci.get("vacuum_level")),
        "Spot": clean(sci.get("spot_size")),
        "HV (V)": clean(sci.get("high_voltage_V")),
        "Current (A)": clean(sci.get("emission_current_A")),
        "Pressure (Torr)": clean(sci.get("chamber_pressure_Torr")),
        "EDX": "Yes" if sci.get("edx_used") in (True, "true", "True", 1) else "",
        "Energy (keV)": clean(sci.get("primary_energy_keV")),
        "Comment": clean(sci.get("comment")),
        "_dataset_id": details.get("unique_id") or details.get("dsid") or "",
        "_timestamp": details.get("timestamp") or "",
    }


@b30_sem_bp.route("/")
def page():
    return render_template("b30_sem.html", config=B30_SEM_CONFIG)


register_instrument_routes(
    b30_sem_bp,
    config=B30_SEM_CONFIG,
    session_key="b30_sem",
    dataset_to_row=_dataset_to_row,
    logbook_cols=LOGBOOK_COLS,
    csv_filename="b30_sem_recent_datasets.csv",
    log_prefix="b30_sem",
)
