"""Backward-compatible module alias; implementation lives in tools.electrolyte."""
import sys
import tools.electrolyte as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "electrolyte", _mod)
