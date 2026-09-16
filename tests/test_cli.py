import json
import subprocess
import sys

import duckdb
import pytest

from query_compiler.examples import fixture_text


def test_demo_command():
    result = subprocess.run(
        [sys.executable, "-m", "query_compiler", "demo"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "420.0 | 710.0" in result.stdout
    assert "57.8%" in result.stdout
    assert "Total | 8" in result.stdout


def test_persistent_demo_preserves_data_across_processes(tmp_path):
    database = tmp_path / "data" / "assessment.duckdb"
    command = [sys.executable, "-m", "query_compiler", "demo", "--database", str(database)]
    subprocess.run(command, capture_output=True, text=True, check=True)
    assert database.is_file()
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fact_sales").fetchone() == (9,)
        assert connection.execute("SELECT COUNT(*) FROM dim_store").fetchone() == (4,)
        assert connection.execute("SELECT COUNT(*) FROM dim_calendar").fetchone() == (16,)
        connection.execute(
            "INSERT INTO fact_sales VALUES ('O-extra', '2026-02-01', NULL, 'S1', 'Retail', 10)"
        )
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "420.0 | 720.0" in result.stdout
    assert "Total | 9" in result.stdout
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fact_sales").fetchone() == (10,)


def test_compile_command_returns_named_error(tmp_path):
    model = tmp_path / "model.json"
    model.write_text(fixture_text("semantic_model.json"))
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"metrics": [{"name": "unknown"}]}))
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
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "UnknownMetricError" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("custom_model", [False, True])
def test_run_custom_contract_against_existing_data(tmp_path, custom_model):
    database = tmp_path / "custom.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(fixture_text("schema.sql"))
        connection.execute("UPDATE fact_sales SET revenue = 1")
    contract = tmp_path / "custom.json"
    contract.write_text(json.dumps({"metrics": [{"name": "total_revenue", "as": "custom_sum"}]}))
    command = [
        sys.executable,
        "-m",
        "query_compiler",
        "run",
        "--contract",
        str(contract),
        "--database",
        str(database),
        "--show-sql",
    ]
    if custom_model:
        model = json.loads(fixture_text("semantic_model.json"))
        model["metrics"][0]["expression"] = "amount"
        with duckdb.connect(str(database)) as connection:
            connection.execute("ALTER TABLE fact_sales RENAME COLUMN revenue TO amount")
        model_file = tmp_path / "model.json"
        model_file.write_text(json.dumps(model))
        command.extend(["--model", str(model_file)])
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    assert 'WITH "aggregated" AS' in result.stdout
    assert "custom_sum\n9.0\n" in result.stdout
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fact_sales").fetchone() == (9,)


def test_run_does_not_create_a_missing_database(tmp_path):
    contract = tmp_path / "contract.json"
    contract.write_text(fixture_text("contract_a.json"))
    database = tmp_path / "missing.duckdb"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "query_compiler",
            "run",
            "--contract",
            str(contract),
            "--database",
            str(database),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "FileNotFoundError" in result.stderr
    assert not database.exists()


def test_run_reports_database_schema_mismatch(tmp_path):
    database = tmp_path / "empty.duckdb"
    with duckdb.connect(str(database)):
        pass
    contract = tmp_path / "contract.json"
    contract.write_text(fixture_text("contract_a.json"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "query_compiler",
            "run",
            "--contract",
            str(contract),
            "--database",
            str(database),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "DatabaseExecutionError" in result.stderr
    assert "Traceback" not in result.stderr
