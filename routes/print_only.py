"""Backward-compatible module alias; implementation lives in tools.print_only."""
import sys
import tools.print_only as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "print_only", _mod)
