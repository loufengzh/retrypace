"""Pure, reproducible retry-schedule analysis. No network calls or real waits."""
from .model import Config, simulate, compare, STRATEGIES

__all__ = ["Config", "simulate", "compare", "STRATEGIES"]
__version__ = "0.1.0"
