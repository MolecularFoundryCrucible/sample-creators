"""Backward-compatible module alias; implementation lives in tools.b30_sputter."""
import sys
import tools.b30_sputter as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "b30_sputter", _mod)
