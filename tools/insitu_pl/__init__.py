"""In-Situ PL uploader plugin: standard single/grouped upload with insitu_aggregation post-processing."""
from __future__ import annotations

from flask import Blueprint, render_template

from routes.uploader_common import register_common_uploader_routes

NAME = "insitu_pl"
KEY = "insitu_pl"
DIVISION = "b67"
ORDER = 220
URL_PREFIX = "/insitu-pl"
ENDPOINT = "insitu_pl.page"
NAV_LABEL = "In-Situ PL"
CARD_TITLE = "In-Situ PL Uploader"
CARD_DESCRIPTION = "Upload In-Situ Photoluminescence datasets with sample linking and automatic insitu_aggregation post-processing."
INSTRUMENT_ID = "in-situ-pl"
INSTRUMENT_MFID = "0t0nah22xxxjd000gy940mm9d8"
INGESTOR = "InSituPlIngestor"
UI_MODE = "standard"
POST_PROCESSING = ["insitu_aggregation"]

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

insitu_pl_bp = Blueprint("insitu_pl", __name__)
BLUEPRINT = insitu_pl_bp


@insitu_pl_bp.route("/")
def page():
    return render_template("standard_uploader.html", tool_config=TOOL_CONFIG)


register_common_uploader_routes(insitu_pl_bp, tool_config=TOOL_CONFIG)
