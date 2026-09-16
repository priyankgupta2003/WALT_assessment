"""Strict validation helpers shared by the model and contract parsers."""

import math
import re
from typing import Any

from .errors import QueryCompilerError, UnsupportedFeatureError

ErrorType = type[QueryCompilerError]
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def object_fields(
    value: Any, required: set[str], optional: set[str], path: str, error: ErrorType
) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise error(f"{path}: expected an object with string keys")
    missing = required - value.keys()
    if missing:
        raise error(f"{path}: missing fields {', '.join(sorted(missing))}")
    extra = value.keys() - required - optional
    if extra:
        raise UnsupportedFeatureError(f"{path}: unsupported fields {', '.join(sorted(extra))}")
    return value


def array(value: Any, path: str, error: ErrorType, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        raise error(f"{path}: expected {'a nonempty' if nonempty else 'an'} array")
    return value


def string(value: Any, path: str, error: ErrorType) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise error(f"{path}: expected a nonempty string without NUL characters")
    return value


def identifier(value: Any, path: str, error: ErrorType) -> str:
    value = string(value, path, error)
    if not _IDENTIFIER.fullmatch(value):
        raise error(f"{path}: only simple identifiers are supported, got {value!r}")
    return value


def scalar(value: Any, path: str, error: ErrorType) -> str | int | float | bool:
    if type(value) not in (str, int, float, bool):
        raise error(f"{path}: expected a non-null string, number, or boolean")
    if isinstance(value, str) and "\x00" in value:
        raise error(f"{path}: NUL characters are not supported")
    if isinstance(value, float) and not math.isfinite(value):
        raise error(f"{path}: non-finite numbers are not supported")
    if type(value) is int and not -(2**63) <= value < 2**63:
        raise error(f"{path}: integers must fit in a signed 64-bit value")
    return value


def unique_names(values: list[str], path: str, error: ErrorType) -> None:
    # DuckDB identifiers are case insensitive, including quoted identifiers.
    folded = [value.casefold() for value in values]
    if len(set(folded)) != len(folded):
        raise error(f"{path}: duplicate names (case insensitive)")
