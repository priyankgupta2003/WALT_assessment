"""Validate the declared catalog and its directed, grain-preserving join graph."""

import heapq
from dataclasses import dataclass
from typing import Any

from .errors import InvalidSemanticModelError, UnsupportedFeatureError, UnsupportedRelationshipError
from .validation import array, identifier, object_fields, string, unique_names


@dataclass(frozen=True)
class Column:
    dataset: str
    name: str


@dataclass(frozen=True)
class Metric:
    name: str
    column: Column
    agg: str
    measure_class: str


@dataclass(frozen=True, order=True)
class Relationship:
    source: str
    source_column: str
    target: str
    target_column: str


@dataclass(frozen=True)
class Catalog:
    datasets: tuple[str, ...]
    metrics: dict[str, Metric]
    dimensions: dict[str, Column]
    outgoing: dict[str, tuple[Relationship, ...]]
    topological_order: tuple[str, ...]


def parse_model(value: Any) -> Catalog:
    err = InvalidSemanticModelError
    model = object_fields(
        value, {"datasets", "relationships", "metrics", "dimensions"}, set(), "model", err
    )
    datasets = []
    for i, item in enumerate(array(model["datasets"], "model.datasets", err, nonempty=True)):
        path = f"model.datasets[{i}]"
        item = object_fields(item, {"name", "grain"}, set(), path, err)
        datasets.append(identifier(item["name"], f"{path}.name", err))
        string(item["grain"], f"{path}.grain", err)
    unique_names(datasets, "model.datasets", err)
    dataset_set = set(datasets)

    def dataset(value: Any, path: str) -> str:
        name = identifier(value, path, err)
        if name not in dataset_set:
            raise err(f"{path}: undeclared dataset {name!r}")
        return name

    metrics = {}
    metric_names = []
    for i, item in enumerate(array(model["metrics"], "model.metrics", err, nonempty=True)):
        path = f"model.metrics[{i}]"
        item = object_fields(
            item, {"name", "agg", "expression", "model", "measure_class"}, set(), path, err
        )
        name = identifier(item["name"], f"{path}.name", err)
        agg = string(item["agg"], f"{path}.agg", err)
        measure_class = string(item["measure_class"], f"{path}.measure_class", err)
        supported = {"sum": "additive", "count_distinct": "distinct_count"}
        if agg not in supported:
            raise UnsupportedFeatureError(f"{path}.agg: unsupported aggregate {agg!r}")
        if measure_class != supported[agg]:
            raise err(f"{path}.measure_class: {agg!r} requires {supported[agg]!r}")
        column = Column(
            dataset(item["model"], f"{path}.model"),
            identifier(item["expression"], f"{path}.expression", err),
        )
        metrics[name] = Metric(name, column, agg, measure_class)
        metric_names.append(name)
    unique_names(metric_names, "model.metrics", err)

    dimensions = {}
    dimension_names = []
    for i, item in enumerate(array(model["dimensions"], "model.dimensions", err)):
        path = f"model.dimensions[{i}]"
        item = object_fields(item, {"name", "model"}, set(), path, err)
        name = identifier(item["name"], f"{path}.name", err)
        dimensions[name] = Column(dataset(item["model"], f"{path}.model"), name)
        dimension_names.append(name)
    unique_names(dimension_names, "model.dimensions", err)

    outgoing: dict[str, list[Relationship]] = {name: [] for name in sorted(datasets)}
    indegree = dict.fromkeys(datasets, 0)
    seen = set()
    for i, item in enumerate(array(model["relationships"], "model.relationships", err)):
        path = f"model.relationships[{i}]"
        item = object_fields(
            item, {"from", "from_column", "to", "to_column", "cardinality"}, set(), path, err
        )
        if item["cardinality"] != "many_to_one":
            raise UnsupportedRelationshipError(f"{path}: only many_to_one is supported")
        edge = Relationship(
            dataset(item["from"], f"{path}.from"),
            identifier(item["from_column"], f"{path}.from_column", err),
            dataset(item["to"], f"{path}.to"),
            identifier(item["to_column"], f"{path}.to_column", err),
        )
        if edge in seen:
            raise err(f"{path}: duplicate relationship")
        seen.add(edge)
        outgoing[edge.source].append(edge)
        indegree[edge.target] += 1

    # A topological traversal supports bounded path counting without enumerating paths.
    ready = [name for name, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for edge in sorted(outgoing[name]):
            indegree[edge.target] -= 1
            if indegree[edge.target] == 0:
                heapq.heappush(ready, edge.target)
    if len(order) != len(datasets):
        raise UnsupportedRelationshipError("model.relationships: cycles/self-joins are unsupported")
    return Catalog(
        tuple(sorted(datasets)),
        metrics,
        dimensions,
        {name: tuple(sorted(edges)) for name, edges in outgoing.items()},
        tuple(order),
    )
