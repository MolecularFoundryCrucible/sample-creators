"""B30 XPS data entry: Kratos Axis Ultra / Vision spectra (.kal), one sample per dataset.

Sample, upload and logbook routes come from routes/instrument_page.py; KratosXpsIngestor
extracts the spectrum metadata after the browser uploads the files.
"""
from flask import Blueprint, render_template

from config import B30_XPS_CONFIG
from routes.deposition_common import LA_TZ, clean, fmt_num, parse_ts, pick
from routes.instrument_page import register_instrument_routes
from routes.shared import format_user

b30_xps_bp = Blueprint("b30_xps", __name__)

LOGBOOK_COLS = [
    "Date", "User", "Anode", "Photon (eV)", "Voltage (V)",
    "Current (A)", "Position", "Spectra", "Regions", "Comment"
]


def _dataset_to_row(details):
    sci = details.get("scientific_metadata") or {}
    dt = parse_ts(details.get("timestamp"))
    spectra_list = sci.get("spectra") if isinstance(sci.get("spectra"), list) else []
    total_spectra = sci.get("total_spectra")
    spectra_count = str(total_spectra) if total_spectra is not None else (str(len(spectra_list)) if spectra_list else "")
    regions = ", ".join(dict.fromkeys(
        str(s.get("region")).strip()
        for s in spectra_list
        if isinstance(s, dict) and str(s.get("region") or "").strip()
    ))
    return {
        "Date": dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M") if dt else "",
        "User": format_user(details.get("owner"), pick(details, "owner_orcid", default="")),
        "Anode": clean(sci.get("anode_material")),
        "Photon (eV)": fmt_num(sci.get("photon_energy_eV")),
        "Voltage (V)": fmt_num(sci.get("anode_voltage_V")),
        "Current (A)": fmt_num(sci.get("emission_current_A")),
        "Position": clean(sci.get("stage_position_name")),
        "Spectra": spectra_count,
        "Regions": regions,
        "Comment": clean(sci.get("comment") or sci.get("dataset_comment")),
        "_dataset_id": details.get("unique_id") or "",
        "_timestamp": details.get("timestamp") or "",
    }


@b30_xps_bp.route("/")
def page():
    return render_template("b30_xps.html", config=B30_XPS_CONFIG)


register_instrument_routes(
    b30_xps_bp,
    config=B30_XPS_CONFIG,
    session_key="b30_xps",
    dataset_to_row=_dataset_to_row,
    logbook_cols=LOGBOOK_COLS,
    csv_filename="b30_xps_recent_datasets.csv",
    log_prefix="b30_xps",
)


NAME = "b30_xps"
KEY = "b30_xps"
DIVISION = "b30"
ORDER = 132
BLUEPRINT = b30_xps_bp
URL_PREFIX = "/b30-xps"
ENDPOINT = "b30_xps.page"
NAV_LABEL = "B30 XPS"
CARD_TITLE = "B30 XPS Data Entry"
CARD_DESCRIPTION = "Look up or create samples by barcode and upload Kratos XPS spectra (.kal) to Crucible."
INSTRUMENT_ID = "b30_xps"
INSTRUMENT_MFID = B30_XPS_CONFIG["instrument_mfid"]
INGESTOR = B30_XPS_CONFIG["ingestion_class"]
UI_MODE = "form"
POST_PROCESSING = []
