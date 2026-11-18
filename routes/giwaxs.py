"""Backward-compatible module alias; implementation lives in tools.giwaxs."""
import sys
import tools.giwaxs as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "giwaxs", _mod)
