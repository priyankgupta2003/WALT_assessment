"""Optional database execution helpers. These are never imported by the compiler."""

import os
from contextlib import contextmanager


class DatabaseExecutionError(RuntimeError):
    """The generated query could not run against the supplied database."""


@contextmanager
def postgres_connection(dsn: str | None, *, read_only: bool = True):
    connection_string = dsn or os.environ.get("QUERY_COMPILER_POSTGRES_DSN")
    if not connection_string:
        raise ValueError("PostgreSQL requires --dsn or the QUERY_COMPILER_POSTGRES_DSN variable")
    try:
        import psycopg
    except ImportError as exc:
        raise DatabaseExecutionError(
            "PostgreSQL execution requires the driver: uv sync --extra postgres"
        ) from exc
    try:
        with psycopg.connect(connection_string, connect_timeout=10) as connection:
            connection.read_only = read_only
            yield connection
    except psycopg.Error as exc:
        raise DatabaseExecutionError(str(exc)) from exc
