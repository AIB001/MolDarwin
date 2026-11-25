"""Compatibility import for the panel-specific execution recipe."""
import sys
from moldarwin.experiments import posebusters
sys.modules[__name__] = posebusters
