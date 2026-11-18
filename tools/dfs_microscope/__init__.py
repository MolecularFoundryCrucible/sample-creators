"""DFS Microscope uploader plugin: Dark-Field Scattering ScopeFoundry .h5 datasets."""
from __future__ import annotations

from flask import Blueprint, render_template

from routes.uploader_common import register_common_uploader_routes

NAME = "dfs_microscope"
KEY = "dfs_microscope"
DIVISION = "b67"
ORDER = 230
URL_PREFIX = "/dfs-microscope"
ENDPOINT = "dfs_microscope.page"
NAV_LABEL = "DFS Microscope"
CARD_TITLE = "DFS Microscope Uploader"
CARD_DESCRIPTION = "Upload Dark-Field Scattering (DFS) ScopeFoundry .h5 microscope datasets and link samples."
INSTRUMENT_ID = "dfs-microscope"
INSTRUMENT_MFID = "0tmz428dmnrf3000128mhfcmdg"
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

dfs_microscope_bp = Blueprint("dfs_microscope", __name__)
BLUEPRINT = dfs_microscope_bp


@dfs_microscope_bp.route("/")
def page():
    return render_template("standard_uploader.html", tool_config=TOOL_CONFIG)


register_common_uploader_routes(dfs_microscope_bp, tool_config=TOOL_CONFIG)
