"""Backward-compatible module alias; implementation lives in tools.b30_xps."""
import sys
import tools.b30_xps as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "b30_xps", _mod)
