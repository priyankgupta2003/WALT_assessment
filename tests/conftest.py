import os

import duckdb
import pytest

from query_compiler import compile_sql
from query_compiler.examples import fixture_text, load_contract, load_model, postgres_fixture_sql
from query_compiler.execution import postgres_connection


@pytest.fixture
def model():
    return load_model()


@pytest.fixture
def contract_a():
    return load_contract("a")


@pytest.fixture
def contract_b():
    return load_contract("b")


@pytest.fixture
def contract_c():
    return load_contract("c")


@pytest.fixture
def postgres_dsn():
    dsn = os.environ.get("QUERY_COMPILER_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set QUERY_COMPILER_TEST_POSTGRES_DSN to run PostgreSQL integration tests")
    pytest.importorskip(
        "psycopg", reason="install PostgreSQL execution support with uv sync --extra postgres"
    )
    return dsn


@pytest.fixture(params=["duckdb", pytest.param("postgres", marks=pytest.mark.postgres)])
def dialect(request):
    return request.param


@pytest.fixture
def db(dialect, request):
    if dialect == "postgres":
        dsn = request.getfixturevalue("postgres_dsn")
        with postgres_connection(dsn, read_only=False) as connection:
            connection.execute("SET LOCAL search_path = pg_temp")
            connection.execute(postgres_fixture_sql())
            yield connection
        return
    with duckdb.connect(":memory:") as connection:
        connection.execute(fixture_text("schema.sql"))
        yield connection


@pytest.fixture
def execute(db, model, dialect):
    def run(contract):
        result = db.execute(compile_sql(model, contract, dialect))
        columns = [col[0] for col in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]

    return run
