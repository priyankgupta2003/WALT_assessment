import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from query_compiler import compile_sql
from query_compiler.examples import load_contract


@pytest.mark.parametrize("name", ["a", "b", "c"])
def test_sql_snapshots(model, name):
    expected = (Path(__file__).parent / "snapshots" / f"contract_{name}.sql").read_text()
    assert compile_sql(model, load_contract(name), "duckdb") + "\n" == expected


def test_no_input_mutation_and_repeatability(model, contract_b):
    original = deepcopy((model, contract_b))
    expected = compile_sql(model, contract_b, "duckdb")
    for _ in range(20):
        assert compile_sql(model, contract_b, "duckdb") == expected
    assert (model, contract_b) == original


def test_catalog_order_does_not_affect_sql(model, contract_b):
    expected = compile_sql(model, contract_b, "duckdb")
    for collection in model.values():
        collection.reverse()
    assert compile_sql(model, contract_b, "duckdb") == expected


def test_json_object_key_order_does_not_affect_sql(model, contract_a):
    expected = compile_sql(model, contract_a, "duckdb")
    assert (
        compile_sql(
            json.loads(json.dumps(model, sort_keys=True)),
            json.loads(json.dumps(contract_a, sort_keys=True)),
            "duckdb",
        )
        == expected
    )


def test_fresh_process_hash_seeds_and_no_database_import():
    script = """
import sys
from query_compiler import compile_sql
from query_compiler.examples import load_contract, load_model
for dialect in ('duckdb', 'postgres'):
    for name in ('a', 'b', 'c'):
        print(compile_sql(load_model(), load_contract(name), dialect))
assert 'duckdb' not in sys.modules
assert 'psycopg' not in sys.modules
assert 'pglast' not in sys.modules
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            text=True,
        )
        for seed in ("1", "17", "923")
    ]
    assert outputs[0] == outputs[1] == outputs[2]
