"""Compatibility import; implementation belongs to execution, not research."""
import sys
from moldarwin.runtime import reuse as _implementation
sys.modules[__name__] = _implementation
