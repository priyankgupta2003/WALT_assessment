"""Resolved, dialect-independent query structures. No SQL fragments or database handles."""

from dataclasses import dataclass

from .model import Column, Metric, Relationship


@dataclass(frozen=True)
class Predicate:
    column: Column
    value: str | int | float | bool
    as_text: bool = False


@dataclass(frozen=True)
class MetricRequest:
    metric: Metric
    alias: str
    filters: tuple[Predicate, ...]


@dataclass(frozen=True)
class Comparison:
    column: Column
    periods: tuple[str, str]
    primary: str
    outputs: tuple[str, ...]

    @property
    def baseline(self) -> str:
        return next(period for period in self.periods if period != self.primary)


@dataclass(frozen=True)
class Aggregate:
    metric: Metric
    filters: tuple[Predicate, ...]


@dataclass(frozen=True)
class Output:
    alias: str
    kind: str  # value | delta | pct_change
    primary: int  # index into QueryPlan.aggregates
    baseline: int | None = None


@dataclass(frozen=True)
class QueryPlan:
    source: str
    joins: tuple[Relationship, ...]
    groups: tuple[Column, ...]
    filters: tuple[Predicate, ...]
    comparison: Comparison | None
    aggregates: tuple[Aggregate, ...]
    outputs: tuple[Output, ...]
    grand_total: bool
