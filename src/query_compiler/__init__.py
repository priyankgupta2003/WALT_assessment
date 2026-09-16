"""Compile declared query intent into SQL without connecting to a warehouse."""

from .compiler import compile_sql
from .errors import QueryCompilerError

__all__ = ["QueryCompilerError", "compile_sql"]
