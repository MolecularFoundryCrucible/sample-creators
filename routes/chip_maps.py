"""Backward-compatible module alias; implementation lives in tools.fabrication.chip_maps."""
import sys
import tools.fabrication.chip_maps as _mod

sys.modules[__name__] = _mod
if "routes" in sys.modules:
    setattr(sys.modules["routes"], "chip_maps", _mod)
