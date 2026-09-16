"""Resolve contract intent, discover safe joins, and lower metrics to aggregate outputs."""

from typing import Any

from .errors import (
    AmbiguousJoinPathError,
    InvalidContractError,
    InvalidFilterError,
    NoJoinPathError,
    UnknownDimensionError,
    UnknownMetricError,
    UnsupportedFeatureError,
)
from .model import Catalog, Column, Relationship
from .plan import Aggregate, Comparison, MetricRequest, Output, Predicate, QueryPlan
from .validation import array, object_fields, scalar, string, unique_names


def _dimension(catalog: Catalog, value: Any, path: str) -> Column:
    name = string(value, path, InvalidContractError)
    if name not in catalog.dimensions:
        raise UnknownDimensionError(f"{path}: unknown dimension {name!r}")
    return catalog.dimensions[name]


def _filters(catalog: Catalog, value: Any, path: str) -> tuple[Predicate, ...]:
    result = []
    for i, item in enumerate(array(value, path, InvalidFilterError)):
        loc = f"{path}[{i}]"
        item = object_fields(
            item, {"field", "op", "value", "model"}, set(), loc, InvalidFilterError
        )
        field = string(item["field"], f"{loc}.field", InvalidFilterError)
        if field not in catalog.dimensions:
            raise UnknownDimensionError(f"{loc}.field: unknown dimension {field!r}")
        column = catalog.dimensions[field]
        model = string(item["model"], f"{loc}.model", InvalidFilterError)
        if model != column.dataset:
            raise InvalidFilterError(
                f"{loc}: field {field!r} belongs to {column.dataset}, not {model}"
            )
        if item["op"] != "=":
            raise InvalidFilterError(f"{loc}.op: only '=' is supported")
        result.append(Predicate(column, scalar(item["value"], f"{loc}.value", InvalidFilterError)))
    return tuple(result)


def _joins(catalog: Catalog, source: str, required: set[str]) -> tuple[Relationship, ...]:
    # Counts saturate at two: we only need to distinguish absent, unique, and ambiguous paths.
    counts = dict.fromkeys(catalog.datasets, 0)
    counts[source] = 1
    parents: dict[str, Relationship] = {}
    for name in catalog.topological_order:
        if counts[name] == 0:
            continue
        for edge in catalog.outgoing[name]:
            parents.setdefault(edge.target, edge)
            counts[edge.target] = min(2, counts[edge.target] + counts[name])

    selected = set()
    for target in sorted(required - {source}):
        if counts[target] == 0:
            raise NoJoinPathError(f"no declared many-to-one path from {source!r} to {target!r}")
        if counts[target] > 1:
            raise AmbiguousJoinPathError(f"multiple join paths from {source!r} to {target!r}")
        current = target
        while current != source:
            edge = parents[current]
            selected.add(edge)
            current = edge.source
    return tuple(
        edge
        for name in catalog.topological_order
        for edge in catalog.outgoing[name]
        if edge in selected
    )


def build_plan(catalog: Catalog, value: Any) -> QueryPlan:
    err = InvalidContractError
    contract = object_fields(
        value, {"metrics"}, {"group_by", "filters", "compare", "totals"}, "contract", err
    )
    requests = []
    for i, item in enumerate(array(contract["metrics"], "metrics", err, nonempty=True)):
        path = f"metrics[{i}]"
        item = object_fields(item, {"name"}, {"as", "filters"}, path, err)
        name = string(item["name"], f"{path}.name", err)
        if name not in catalog.metrics:
            raise UnknownMetricError(f"{path}.name: unknown metric {name!r}")
        alias = string(item.get("as", name), f"{path}.as", err)
        requests.append(
            MetricRequest(
                catalog.metrics[name],
                alias,
                _filters(catalog, item.get("filters", []), f"{path}.filters"),
            )
        )
    unique_names([request.alias for request in requests], "metrics aliases", err)
    sources = {request.metric.column.dataset for request in requests}
    if len(sources) != 1:
        raise UnsupportedFeatureError("metrics: combining multiple fact datasets is unsupported")
    source = next(iter(sources))
    groups = tuple(
        _dimension(catalog, name, f"group_by[{i}]")
        for i, name in enumerate(array(contract.get("group_by", []), "group_by", err))
    )
    unique_names([group.name for group in groups], "group_by", err)
    filters = _filters(catalog, contract.get("filters", []), "filters")
    if "totals" in contract and contract["totals"] != "grand":
        raise UnsupportedFeatureError("totals: only 'grand' is supported; omit for no totals")
    grand_total = contract.get("totals") == "grand"

    comparison = None
    if "compare" in contract:
        item = object_fields(
            contract["compare"],
            {"dimension", "periods", "primary", "outputs"},
            set(),
            "compare",
            err,
        )
        column = _dimension(catalog, item["dimension"], "compare.dimension")
        if column in groups:
            raise UnsupportedFeatureError("compare.dimension cannot also appear in group_by")
        periods = array(item["periods"], "compare.periods", err)
        if len(periods) != 2:
            raise UnsupportedFeatureError("compare.periods: exactly two periods are supported")
        periods = tuple(
            string(period, f"compare.periods[{i}]", err) for i, period in enumerate(periods)
        )
        if periods[0] == periods[1]:
            raise err("compare.periods: periods must be distinct")
        primary = string(item["primary"], "compare.primary", err)
        if primary not in periods:
            raise err("compare.primary: must be one of compare.periods")
        outputs = tuple(
            string(output, f"compare.outputs[{i}]", err)
            for i, output in enumerate(
                array(item["outputs"], "compare.outputs", err, nonempty=True)
            )
        )
        unique_names(list(outputs), "compare.outputs", err)
        if set(outputs) - {"values", "delta", "pct_change"}:
            raise UnsupportedFeatureError("compare.outputs: supported: values, delta, pct_change")
        comparison = Comparison(column, periods, primary, outputs)

    required = {source} | {column.dataset for column in groups}
    required.update(predicate.column.dataset for predicate in filters)
    for request in requests:
        required.update(predicate.column.dataset for predicate in request.filters)
    if comparison:
        required.add(comparison.column.dataset)
    joins = _joins(catalog, source, required)

    aggregates = []
    outputs = []
    for request in requests:
        if comparison is None:
            outputs.append(Output(request.alias, "value", len(aggregates)))
            aggregates.append(Aggregate(request.metric, request.filters))
            continue
        indices = {}
        for period in comparison.periods:
            indices[period] = len(aggregates)
            predicate = Predicate(comparison.column, period, as_text=True)
            aggregates.append(Aggregate(request.metric, (*request.filters, predicate)))
        for kind in comparison.outputs:
            if kind == "values":
                outputs.extend(
                    Output(f"{request.alias}_{period}", "value", indices[period])
                    for period in comparison.periods
                )
            else:
                outputs.append(
                    Output(
                        f"{request.alias}_{kind}",
                        kind,
                        indices[comparison.primary],
                        indices[comparison.baseline],
                    )
                )
    unique_names(
        [group.name for group in groups] + [output.alias for output in outputs], "output", err
    )
    return QueryPlan(
        source, joins, groups, filters, comparison, tuple(aggregates), tuple(outputs), grand_total
    )
