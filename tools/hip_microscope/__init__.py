"""HiP Microscope uploader plugin: HiP ScopeFoundry .h5 datasets."""
from __future__ import annotations

from flask import Blueprint, render_template

from routes.uploader_common import register_common_uploader_routes

NAME = "hip_microscope"
KEY = "hip_microscope"
DIVISION = "b67"
ORDER = 240
URL_PREFIX = "/hip-microscope"
ENDPOINT = "hip_microscope.page"
NAV_LABEL = "HiP Microscope"
CARD_TITLE = "HiP Microscope Uploader"
CARD_DESCRIPTION = "Upload HiP ScopeFoundry .h5 microscope datasets and link samples."
INSTRUMENT_ID = "hip-microscope"
INSTRUMENT_MFID = "0sh6zrzxhxybd000wwyrkcn2cw"
INGESTOR = "SingleSpecScopeFoundryH5Ingestor"
UI_MODE = "standard"
POST_PROCESSING = []

TOOL_CONFIG = {
    "name": NAME,
    "key": KEY,
    "division": DIVISION,
    "order": ORDER,
    "url_prefix": URL_PREFIX,
    "endpoint": ENDPOINT,
    "nav_label": NAV_LABEL,
    "card_title": CARD_TITLE,
    "card_description": CARD_DESCRIPTION,
    "instrument_id": INSTRUMENT_ID,
    "instrument_mfid": INSTRUMENT_MFID,
    "ingestor": INGESTOR,
    "ui_mode": UI_MODE,
    "post_processing": POST_PROCESSING,
    "default_printer": "b67-123",
}

hip_microscope_bp = Blueprint("hip_microscope", __name__)
BLUEPRINT = hip_microscope_bp


@hip_microscope_bp.route("/")
def page():
    return render_template("standard_uploader.html", tool_config=TOOL_CONFIG)


register_common_uploader_routes(hip_microscope_bp, tool_config=TOOL_CONFIG)
