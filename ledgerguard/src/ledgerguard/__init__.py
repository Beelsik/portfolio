"""LedgerGuard: deterministic B2B procurement & invoice reconciliation before ERP/1C posting."""

from .benchmark import run_benchmark
from .engine import LedgerGuardEngine
from .models import ReconciliationReport

__version__ = "1.0.0"
__all__ = ["LedgerGuardEngine", "ReconciliationReport", "run_benchmark", "__version__"]
