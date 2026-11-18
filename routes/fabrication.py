"""Backward-compatible module alias; implementation lives in tools.fabrication."""
import sys
import tools.fabrication as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "fabrication", _mod)
