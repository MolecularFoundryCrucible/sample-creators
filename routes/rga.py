"""Backward-compatible module alias; implementation lives in tools.rga."""
import sys
import tools.rga as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "rga", _mod)
