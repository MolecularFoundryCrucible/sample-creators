"""Backward-compatible module alias; implementation lives in tools.b30_raman."""
import sys
import tools.b30_raman as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "b30_raman", _mod)
