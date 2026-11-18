"""Backward-compatible module alias; implementation lives in tools.schema_forms."""
import sys
import tools.schema_forms as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "schema_forms", _mod)
