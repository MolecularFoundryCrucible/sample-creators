"""Plugin registry for sample-creators tools.

Discovers and registers tool plugins in tools/<plugin_name>/__init__.py,
mirroring crucible-upload-uis/instruments/registry.py.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import TYPE_CHECKING

import tools as _pkg

if TYPE_CHECKING:
    from flask import Flask

TOOL_MODULES: dict[str, ModuleType] = {}
INSTRUMENT_IDS: dict[str, str] = {}
INSTRUMENT_MFIDS: dict[str, str] = {}
INGESTORS: dict[str, str] = {}
UI_MODES: dict[str, str] = {}
POST_PROCESSING_STEPS: dict[str, list[str]] = {}

_CACHED_MODS: list[ModuleType] | None = None


def _populate_dicts(mods: list[ModuleType]) -> None:
    TOOL_MODULES.clear()
    INSTRUMENT_IDS.clear()
    INSTRUMENT_MFIDS.clear()
    INGESTORS.clear()
    UI_MODES.clear()
    POST_PROCESSING_STEPS.clear()

    for m in mods:
        name = getattr(m, "NAME", None)
        if not name:
            continue
        TOOL_MODULES[name] = m
        if getattr(m, "INSTRUMENT_ID", None):
            INSTRUMENT_IDS[name] = m.INSTRUMENT_ID
        if getattr(m, "INSTRUMENT_MFID", None):
            INSTRUMENT_MFIDS[name] = m.INSTRUMENT_MFID
        if getattr(m, "INGESTOR", None):
            INGESTORS[name] = m.INGESTOR
        if getattr(m, "UI_MODE", None):
            UI_MODES[name] = m.UI_MODE
        if getattr(m, "POST_PROCESSING", None):
            POST_PROCESSING_STEPS[name] = m.POST_PROCESSING

        instruments = getattr(m, "INSTRUMENTS", None)
        if isinstance(instruments, dict):
            for inst_key, inst_cfg in instruments.items():
                if not isinstance(inst_cfg, dict):
                    continue
                if inst_cfg.get("instrument_id"):
                    INSTRUMENT_IDS[inst_key] = inst_cfg["instrument_id"]
                if inst_cfg.get("instrument_mfid"):
                    INSTRUMENT_MFIDS[inst_key] = inst_cfg["instrument_mfid"]
                if inst_cfg.get("ingestor"):
                    INGESTORS[inst_key] = inst_cfg["ingestor"]
                if inst_cfg.get("ui_mode"):
                    UI_MODES[inst_key] = inst_cfg["ui_mode"]
                if inst_cfg.get("post_processing"):
                    POST_PROCESSING_STEPS[inst_key] = inst_cfg["post_processing"]


def discover_tools(force_reload: bool = False) -> list[ModuleType]:
    """Discover all tool plugins in the tools package, sorted by (ORDER, NAME)."""
    global _CACHED_MODS
    if _CACHED_MODS is not None and not force_reload:
        return _CACHED_MODS

    mods = []
    for mod_info in pkgutil.iter_modules(_pkg.__path__):
        name = mod_info.name
        if name.startswith("_") or name == "registry":
            continue
        mod_name = f"tools.{name}"
        if force_reload and mod_name in importlib.sys.modules:
            mod = importlib.reload(importlib.sys.modules[mod_name])
        else:
            mod = importlib.import_module(mod_name)
        mods.append(mod)

    mods.sort(key=lambda m: (getattr(m, "ORDER", 1000), getattr(m, "NAME", m.__name__)))
    _CACHED_MODS = mods
    _populate_dicts(mods)
    return mods


def register_all_tools(app: Flask, force_reload: bool = False) -> list[dict]:
    """Register every discovered plugin's blueprint(s) onto app and return tool descriptors."""
    mods = discover_tools(force_reload=force_reload)
    all_tool_entries = []

    for mod in mods:
        # 1. Blueprint registration
        if hasattr(mod, "register") and callable(mod.register):
            mod.register(app)
        elif hasattr(mod, "BLUEPRINT") and getattr(mod, "BLUEPRINT") is not None:
            url_prefix = getattr(mod, "URL_PREFIX", None)
            app.register_blueprint(mod.BLUEPRINT, url_prefix=url_prefix)

        # 2. Navigation / card descriptor(s)
        if hasattr(mod, "get_tool_entries") and callable(mod.get_tool_entries):
            entries = mod.get_tool_entries()
            all_tool_entries.extend(entries)
        else:
            key = getattr(mod, "KEY", getattr(mod, "NAME", None))
            division = getattr(mod, "DIVISION", None)
            endpoint = getattr(mod, "ENDPOINT", None)
            nav_label = getattr(mod, "NAV_LABEL", None)
            card_title = getattr(mod, "CARD_TITLE", None)
            card_description = getattr(mod, "CARD_DESCRIPTION", None)

            if all([key, division, endpoint, nav_label, card_title, card_description]):
                all_tool_entries.append({
                    "key": key,
                    "division": division,
                    "endpoint": endpoint,
                    "nav_label": nav_label,
                    "card_title": card_title,
                    "card_description": card_description,
                })

    return all_tool_entries


# Discover and populate lookup dicts on initial import
discover_tools()
