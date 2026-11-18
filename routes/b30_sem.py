"""Backward-compatible module alias; implementation lives in tools.b30_sem."""
import sys
import tools.b30_sem as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "b30_sem", _mod)
