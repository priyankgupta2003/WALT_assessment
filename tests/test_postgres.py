import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from pglast import parse_sql

from query_compiler import compile_sql
from query_compiler.__main__ import demo, run_contract
from query_compiler.dialects import PostgresDialect
from query_compiler.errors import UnsupportedFeatureError
from query_compiler.examples import fixture_text, load_contract
from query_compiler.execution import postgres_connection


@pytest.mark.parametrize("name", ["a", "b", "c"])
def test_postgres_syntax_and_snapshot(model, name):
    sql = compile_sql(model, load_contract(name), "postgres")
    assert len(parse_sql(sql)) == 1
    expected = (
        Path(__file__).parent / "snapshots" / "postgres" / f"contract_{name}.sql"
    ).read_text()
    assert sql + "\n" == expected


@pytest.mark.parametrize("name", ["a", "b", "c"])
def test_postgres_repeatability_and_model_order(model, name):
    contract = load_contract(name)
    original = deepcopy((model, contract))
    expected = compile_sql(model, contract, "postgres")
    for _ in range(10):
        assert compile_sql(model, contract, "postgresql") == expected
    assert (model, contract) == original
    for collection in model.values():
        collection.reverse()
    assert compile_sql(model, contract, "postgres") == expected


@pytest.mark.parametrize("alias", ["x" * 64, "é" * 32])
def test_postgres_rejects_identifier_truncation(model, alias):
    contract = {"metrics": [{"name": "total_revenue", "as": alias}]}
    with pytest.raises(UnsupportedFeatureError, match="63-byte"):
        compile_sql(model, contract, "postgres")
    assert compile_sql(model, contract, "duckdb")


def test_postgres_checks_generated_alias_length(model, contract_b):
    contract_b["metrics"][0]["as"] = "r" * 60
    with pytest.raises(UnsupportedFeatureError, match="63-byte"):
        compile_sql(model, contract_b, "postgres")


def test_postgres_identifier_at_limit(model):
    sql = compile_sql(model, {"metrics": [{"name": "total_revenue", "as": "x" * 63}]}, "postgres")
    assert parse_sql(sql)


def test_postgres_backslash_and_quote_literal(model):
    value = "O'Reilly\\shop'; SELECT 1; --"
    contract = {
        "metrics": [{"name": "total_revenue"}],
        "filters": [{"field": "channel", "model": "fact_sales", "op": "=", "value": value}],
    }
    sql = compile_sql(model, contract, "postgres")
    assert PostgresDialect().literal(value) == "E'O''Reilly\\\\shop''; SELECT 1; --'"
    assert len(parse_sql(sql)) == 1


def test_compile_cli_postgres(tmp_path):
    model = tmp_path / "model.json"
    model.write_text(fixture_text("semantic_model.json"))
    contract = tmp_path / "contract.json"
    contract.write_text(fixture_text("contract_b.json"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "query_compiler",
            "compile",
            "--model",
            str(model),
            "--contract",
            str(contract),
            "--dialect",
            "postgres",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "AS TEXT" in result.stdout
    assert parse_sql(result.stdout)


def test_postgres_requires_connection_target(monkeypatch):
    monkeypatch.delenv("QUERY_COMPILER_POSTGRES_DSN", raising=False)
    with pytest.raises(ValueError, match="--dsn"):
        with postgres_connection(None):
            pytest.fail("must not connect without an explicit target")


def test_database_option_is_not_a_postgres_connection(model, contract_a):
    with pytest.raises(ValueError, match="DuckDB file"):
        run_contract(model, contract_a, Path("data.duckdb"), False, "postgres")


@pytest.mark.postgres
def test_postgres_demo_command(postgres_dsn):
    result = subprocess.run(
        [sys.executable, "-m", "query_compiler", "demo", "--dialect", "postgres"],
        env={**os.environ, "QUERY_COMPILER_POSTGRES_DSN": postgres_dsn},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "420.0 | 710.0" in result.stdout
    assert "57.8%" in result.stdout
    assert "Total | 8" in result.stdout


@pytest.mark.postgres
def test_postgres_run_uses_read_only_transactions(postgres_dsn):
    import psycopg

    with postgres_connection(postgres_dsn) as connection:
        assert connection.execute("SHOW transaction_read_only").fetchone() == ("on",)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("CREATE TABLE must_not_be_created (id INTEGER)")


@pytest.mark.postgres
@pytest.mark.parametrize("setting", ["on", "off"])
def test_postgres_literal_round_trip(postgres_dsn, setting):
    value = "O'Reilly\\new\nline\ttab'; SELECT 1; --"
    with postgres_connection(postgres_dsn) as connection:
        connection.execute(f"SET LOCAL standard_conforming_strings = {setting}")
        assert connection.execute(f"SELECT {PostgresDialect().literal(value)}").fetchone() == (
            value,
        )


@pytest.mark.postgres
def test_postgres_demo_leaves_existing_tables_untouched(postgres_dsn, monkeypatch, capsys):
    # Reuse one session so we can observe permanent and temporary table lifetimes.
    from contextlib import contextmanager

    with postgres_connection(postgres_dsn, read_only=False) as connection:

        @contextmanager
        def same_connection(dsn, *, read_only=True):
            yield connection

        # A transaction-local schema disappears on rollback, even if the test fails.
        with connection.transaction(force_rollback=True):
            connection.execute("CREATE SCHEMA qc_demo_isolation")
            connection.execute("SET LOCAL search_path = qc_demo_isolation")
            connection.execute("CREATE TABLE fact_sales (sentinel INTEGER)")
            connection.execute("INSERT INTO fact_sales VALUES (123)")
            monkeypatch.setattr("query_compiler.__main__.postgres_connection", same_connection)
            demo(False, contract="a", dialect="postgres", dsn=postgres_dsn)
            assert "420.0 | 710.0" in capsys.readouterr().out
            assert connection.execute(
                "SELECT sentinel FROM qc_demo_isolation.fact_sales"
            ).fetchone() == (123,)


@pytest.mark.postgres
def test_postgres_run_custom_model_in_existing_schema(postgres_dsn, tmp_path):
    import psycopg
    from psycopg.conninfo import make_conninfo

    schema = "qc_custom_run"
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"metrics": [{"name": "revenue", "as": "custom_total"}]}))
    model = tmp_path / "model.json"
    model.write_text(
        json.dumps(
            {
                "datasets": [{"name": "sales", "grain": "one sale"}],
                "relationships": [],
                "dimensions": [],
                "metrics": [
                    {
                        "name": "revenue",
                        "agg": "sum",
                        "expression": "amount",
                        "model": "sales",
                        "measure_class": "additive",
                    }
                ],
            }
        )
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(f"CREATE SCHEMA {schema}")
        try:
            connection.execute(f"CREATE TABLE {schema}.sales (amount INTEGER)")
            connection.execute(f"INSERT INTO {schema}.sales VALUES (7), (11)")
            dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "query_compiler",
                    "run",
                    "--dialect",
                    "postgres",
                    "--model",
                    str(model),
                    "--contract",
                    str(contract),
                    "--show-sql",
                ],
                env={**os.environ, "QUERY_COMPILER_POSTGRES_DSN": dsn},
                capture_output=True,
                text=True,
                check=True,
            )
            assert "custom_total\n18\n" in result.stdout
            assert connection.execute(f"SELECT SUM(amount) FROM {schema}.sales").fetchone() == (18,)
        finally:
            connection.execute(f"DROP SCHEMA {schema} CASCADE")
