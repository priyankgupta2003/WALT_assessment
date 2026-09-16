"""Public compilation boundary. All validation and model preparation happen inside it."""

from typing import Any

from .dialects import get_dialect
from .model import parse_model
from .planner import build_plan
from .renderer import render


def compile_sql(semantic_model: dict[str, Any], contract: dict[str, Any], dialect: str) -> str:
    """Compile parsed JSON-compatible inputs without I/O, mutable global state, or caching.

    Raises a named QueryCompilerError subclass for invalid/unsupported inputs.
    Supported dialects are 'duckdb' and 'postgres' (also spelled 'postgresql').
    """
    backend = get_dialect(dialect)
    catalog = parse_model(semantic_model)
    plan = build_plan(catalog, contract)
    return render(plan, backend)
