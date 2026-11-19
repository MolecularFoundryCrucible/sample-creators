"""Multi-tool plugin for the 7 TEM session uploaders (B67 m3-Microscope + 6 NCEM TEMs)."""
from __future__ import annotations

from flask import Blueprint, render_template

from config import TEM_SESSION_TOOLS
from routes.session_uploader import register_session_uploader_routes
from routes.uploader_common import register_common_uploader_routes

NAME = "tem_sessions"
DIVISION = "ncem"
ORDER = 290
UI_MODE = "session"


def _build_tool_config(key: str, raw_cfg: dict) -> dict:
    """Build a JSON-serializable tool_config dict for one TEM session uploader."""
    return {
        "name": key,
        "key": key,
        "division": raw_cfg["division"],
        "order": raw_cfg["order"],
        "url_prefix": raw_cfg["url_prefix"],
        "endpoint": f"{key}.page",
        "nav_label": raw_cfg["nav_label"],
        "card_title": raw_cfg["card_title"],
        "card_description": raw_cfg["card_description"],
        "instrument_id": raw_cfg["instrument_id"],
        "instrument_mfid": raw_cfg["instrument_mfid"],
        "ingestor": raw_cfg.get("ingestor", ""),
        "ui_mode": UI_MODE,
        "post_processing": list(raw_cfg.get("post_processing") or []),
        "default_printer": raw_cfg.get("default_printer", ""),
        "acceptable_file_types": list(raw_cfg.get("acceptable_file_types") or []),
    }


def _sorted_instruments() -> list[tuple[str, dict]]:
    return sorted(INSTRUMENTS.items(), key=lambda item: (item[1]["order"], item[0]))


INSTRUMENTS: dict[str, dict] = {
    key: _build_tool_config(key, raw_cfg)
    for key, raw_cfg in TEM_SESSION_TOOLS.items()
}


def register(app) -> None:
    """Create and register one Flask Blueprint per TEM session uploader."""
    for key, tool_cfg in _sorted_instruments():
        bp = Blueprint(key, __name__)

        def _make_page(cfg: dict):
            def page():
                return render_template("session_uploader.html", tool_config=cfg)
            return page

        bp.add_url_rule("/", endpoint="page", view_func=_make_page(tool_cfg))
        register_common_uploader_routes(bp, tool_config=tool_cfg)
        register_session_uploader_routes(bp, tool_config=tool_cfg)
        app.register_blueprint(bp, url_prefix=tool_cfg["url_prefix"])


def get_tool_entries() -> list[dict]:
    """Return navigation and division card descriptors sorted by (order, key)."""
    return [
        {
            "key": cfg["key"],
            "division": cfg["division"],
            "endpoint": cfg["endpoint"],
            "nav_label": cfg["nav_label"],
            "card_title": cfg["card_title"],
            "card_description": cfg["card_description"],
        }
        for _, cfg in _sorted_instruments()
    ]
