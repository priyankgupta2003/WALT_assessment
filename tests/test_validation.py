from copy import deepcopy

import pytest

from query_compiler import compile_sql
from query_compiler.errors import (
    AmbiguousJoinPathError,
    InvalidContractError,
    InvalidFilterError,
    InvalidSemanticModelError,
    NoJoinPathError,
    QueryCompilerError,
    UnknownDimensionError,
    UnknownMetricError,
    UnsupportedDialectError,
    UnsupportedFeatureError,
    UnsupportedRelationshipError,
)


@pytest.mark.parametrize("value", [None, [], "revenue", 7, {}, {"metrics": []}])
def test_invalid_contract_shape(model, value):
    with pytest.raises(InvalidContractError):
        compile_sql(model, value, "duckdb")


@pytest.mark.parametrize(
    ("contract", "error", "message"),
    [
        ({"metrics": [{"name": "profit"}]}, UnknownMetricError, "metrics\\[0\\].name"),
        (
            {"metrics": [{"name": "total_revenue"}], "group_by": ["city"]},
            UnknownDimensionError,
            "group_by\\[0\\]",
        ),
        ({"metrics": [{"name": "total_revenue"}], "having": []}, UnsupportedFeatureError, "having"),
        ({"metrics": [{"name": "total_revenue", "filter": []}]}, UnsupportedFeatureError, "filter"),
        (
            {"metrics": [{"name": "total_revenue"}], "totals": "subtotal"},
            UnsupportedFeatureError,
            "totals",
        ),
        (
            {"metrics": [{"name": "total_revenue"}], "group_by": ["region", "region"]},
            InvalidContractError,
            "duplicate",
        ),
        (
            {"metrics": [{"name": "total_revenue", "as": "region"}], "group_by": ["region"]},
            InvalidContractError,
            "output",
        ),
        (
            {"metrics": [{"name": "total_revenue"}, {"name": "total_revenue"}]},
            InvalidContractError,
            "duplicate",
        ),
        (
            {
                "metrics": [
                    {"name": "total_revenue", "as": "REV"},
                    {"name": "order_count", "as": "rev"},
                ]
            },
            InvalidContractError,
            "duplicate",
        ),
    ],
)
def test_invalid_contract_requests(model, contract, error, message):
    with pytest.raises(error, match=message):
        compile_sql(model, contract, "duckdb")


@pytest.mark.parametrize("value", [None, [], {}, float("nan"), float("inf"), 2**63, "bad\x00value"])
def test_invalid_filter_literals(model, contract_a, value):
    contract_a["filters"][0]["value"] = value
    with pytest.raises(InvalidFilterError, match="filters\\[0\\].value"):
        compile_sql(model, contract_a, "duckdb")


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("field", "ship_date", UnknownDimensionError),
        ("model", "fact_sales", InvalidFilterError),
        ("op", "OR 1=1", InvalidFilterError),
        ("op", "!=", InvalidFilterError),
    ],
)
def test_invalid_filter_references(model, contract_a, key, value, error):
    contract_a["filters"][0][key] = value
    with pytest.raises(error):
        compile_sql(model, contract_a, "duckdb")


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("dimension", "month", UnknownDimensionError),
        ("dimension", "region", UnsupportedFeatureError),
        ("periods", ["2025"], UnsupportedFeatureError),
        ("periods", ["2025", "2026", "2027"], UnsupportedFeatureError),
        ("periods", [2025, 2026], InvalidContractError),
        ("periods", ["2025", "2025"], InvalidContractError),
        ("primary", "2027", InvalidContractError),
        ("outputs", [], InvalidContractError),
        ("outputs", ["values", "values"], InvalidContractError),
        ("outputs", ["cumulative"], UnsupportedFeatureError),
    ],
)
def test_invalid_comparison(model, contract_b, key, value, error):
    contract_b["compare"][key] = value
    with pytest.raises(error):
        compile_sql(model, contract_b, "duckdb")


def test_generated_alias_collisions(model, contract_b):
    contract_b["compare"]["periods"] = ["delta", "2026"]
    with pytest.raises(InvalidContractError, match="output"):
        compile_sql(model, contract_b, "duckdb")


@pytest.mark.parametrize("dialect", ["mysql", "snowflake", "DuckDB", "", None, []])
def test_unsupported_dialect(model, contract_a, dialect):
    with pytest.raises(UnsupportedDialectError):
        compile_sql(model, contract_a, dialect)


@pytest.mark.parametrize("value", [None, [], {}, "model", {"datasets": []}])
def test_invalid_model_shape(contract_a, value):
    with pytest.raises(InvalidSemanticModelError):
        compile_sql(value, contract_a, "duckdb")


@pytest.mark.parametrize("collection", ["datasets", "metrics", "dimensions", "relationships"])
def test_duplicate_model_definitions(model, contract_a, collection):
    model[collection].append(deepcopy(model[collection][0]))
    with pytest.raises(InvalidSemanticModelError, match="duplicate"):
        compile_sql(model, contract_a, "duckdb")


def test_case_insensitive_dataset_duplicates(model, contract_a):
    model["datasets"].append({"name": "FACT_SALES", "grain": "one line"})
    with pytest.raises(InvalidSemanticModelError, match="duplicate"):
        compile_sql(model, contract_a, "duckdb")


def test_undeclared_model_reference(model, contract_a):
    model["metrics"][0]["model"] = "missing"
    with pytest.raises(InvalidSemanticModelError, match="undeclared dataset"):
        compile_sql(model, contract_a, "duckdb")


def test_arbitrary_metric_sql_is_rejected(model, contract_a):
    model["metrics"][0]["expression"] = "revenue); DROP TABLE fact_sales; --"
    with pytest.raises(InvalidSemanticModelError, match="simple identifiers"):
        compile_sql(model, contract_a, "duckdb")


def test_unsupported_aggregation(model, contract_a):
    model["metrics"][0]["agg"] = "avg"
    with pytest.raises(UnsupportedFeatureError, match="aggregate"):
        compile_sql(model, contract_a, "duckdb")


def test_measure_class_must_match_aggregate(model, contract_a):
    model["metrics"][0]["measure_class"] = "distinct_count"
    with pytest.raises(InvalidSemanticModelError, match="measure_class"):
        compile_sql(model, contract_a, "duckdb")


def test_missing_join_path(model, contract_a):
    model["relationships"] = model["relationships"][:1]
    with pytest.raises(NoJoinPathError, match="dim_calendar"):
        compile_sql(model, contract_a, "duckdb")


def test_second_date_role_is_ambiguous_only_when_required(model, contract_a, contract_c):
    edge = deepcopy(model["relationships"][1])
    edge["from_column"] = "ship_date"
    model["relationships"].append(edge)
    with pytest.raises(AmbiguousJoinPathError, match="dim_calendar"):
        compile_sql(model, contract_a, "duckdb")
    assert compile_sql(model, contract_c, "duckdb")


def test_ambiguous_multihop_path(model, contract_a):
    model["relationships"].append(
        {
            "from": "dim_store",
            "from_column": "opening_date",
            "to": "dim_calendar",
            "to_column": "date",
            "cardinality": "many_to_one",
        }
    )
    with pytest.raises(AmbiguousJoinPathError, match="dim_calendar"):
        compile_sql(model, contract_a, "duckdb")


@pytest.mark.parametrize("cardinality", ["one_to_many", "many_to_many", "one_to_one", None])
def test_unsupported_cardinality(model, contract_a, cardinality):
    model["relationships"][0]["cardinality"] = cardinality
    with pytest.raises(UnsupportedRelationshipError):
        compile_sql(model, contract_a, "duckdb")


def test_reverse_join_is_not_assumed_safe(model, contract_c):
    edge = model["relationships"][0]
    edge["from"], edge["to"] = edge["to"], edge["from"]
    with pytest.raises(NoJoinPathError):
        compile_sql(model, contract_c, "duckdb")


def test_cycles_rejected(model, contract_a):
    model["relationships"].append(
        {
            "from": "dim_store",
            "from_column": "store_id",
            "to": "fact_sales",
            "to_column": "store_id",
            "cardinality": "many_to_one",
        }
    )
    with pytest.raises(UnsupportedRelationshipError, match="cycles"):
        compile_sql(model, contract_a, "duckdb")


def test_multiple_fact_datasets_rejected(model):
    model["datasets"].append({"name": "returns", "grain": "one return"})
    model["metrics"].append(
        {
            "name": "refunds",
            "agg": "sum",
            "expression": "amount",
            "model": "returns",
            "measure_class": "additive",
        }
    )
    with pytest.raises(UnsupportedFeatureError, match="multiple fact"):
        compile_sql(model, {"metrics": [{"name": "total_revenue"}, {"name": "refunds"}]}, "duckdb")


@pytest.mark.parametrize("bad_value", [None, [], {}, 7, True, ""])
@pytest.mark.parametrize("field", ["metrics", "group_by", "filters", "compare"])
def test_malformed_fields_always_raise_a_named_error(model, contract_a, field, bad_value):
    contract_a[field] = bad_value
    # Empty grouping/filter lists are valid; all other combinations here are malformed.
    if bad_value == [] and field in {"group_by", "filters"}:
        compile_sql(model, contract_a, "duckdb")
    else:
        with pytest.raises(QueryCompilerError):
            compile_sql(model, contract_a, "duckdb")
