"""SQL syntax choices live here; dialects receive only resolved expressions."""

from dataclasses import dataclass

from .errors import UnsupportedDialectError, UnsupportedFeatureError


@dataclass(frozen=True)
class SQLDialect:
    """Common SQL constructs used by both supported database engines."""

    name: str

    def identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def literal(self, value: str | int | float | bool) -> str:
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        return repr(value)

    def text(self, expression: str) -> str:
        return f"CAST({expression} AS VARCHAR)"

    def aggregate(self, agg: str, expression: str, predicates: tuple[str, ...]) -> str:
        if agg == "sum":
            sql = f"SUM({expression})"
        elif agg == "count_distinct":
            sql = f"COUNT(DISTINCT {expression})"
        else:
            raise AssertionError(f"unplanned aggregate: {agg}")
        if predicates:
            sql += " FILTER (WHERE " + " AND ".join(predicates) + ")"
        return sql


@dataclass(frozen=True)
class DuckDBDialect(SQLDialect):
    name: str = "duckdb"


@dataclass(frozen=True)
class PostgresDialect(SQLDialect):
    name: str = "postgres"

    def identifier(self, value: str) -> str:
        # PostgreSQL otherwise silently truncates identifiers, potentially causing collisions.
        if len(value.encode("utf-8")) > 63:
            raise UnsupportedFeatureError(
                f"postgres identifier exceeds the supported 63-byte limit: {value!r}"
            )
        return super().identifier(value)

    def literal(self, value: str | int | float | bool) -> str:
        if isinstance(value, str):
            # Explicit escape strings behave consistently with standard_conforming_strings on/off.
            escaped = value.replace("\\", "\\\\").replace("'", "''")
            return "E'" + escaped + "'"
        return super().literal(value)

    def text(self, expression: str) -> str:
        return f"CAST({expression} AS TEXT)"


def get_dialect(name: str) -> SQLDialect:
    if name == "duckdb":
        return DuckDBDialect()
    if name in ("postgres", "postgresql"):
        return PostgresDialect()
    raise UnsupportedDialectError(f"unsupported dialect {name!r}; supported: duckdb, postgres")
