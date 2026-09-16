"""Packaged assessment fixtures, used only by the demo, tests, and benchmark."""

import json
from importlib.resources import files


def fixture_text(name: str) -> str:
    return files("query_compiler").joinpath("fixtures", name).read_text(encoding="utf-8")


def load_model() -> dict:
    return json.loads(fixture_text("semantic_model.json"))


def load_contract(name: str) -> dict:
    return json.loads(fixture_text(f"contract_{name.lower()}.json"))


def postgres_fixture_sql() -> str:
    """Use session-local tables so a PostgreSQL demo cannot overwrite existing datasets."""
    return fixture_text("schema.sql").replace("CREATE TABLE ", "CREATE TEMP TABLE ")
