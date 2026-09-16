"""Render a resolved aggregate plan; contract interpretation belongs in the planner."""

from .dialects import SQLDialect
from .model import Column
from .plan import Predicate, QueryPlan


def render(plan: QueryPlan, dialect: SQLDialect) -> str:
    quote = dialect.identifier
    aliases = {plan.source: "t0"}
    for join in plan.joins:
        aliases.setdefault(join.target, f"t{len(aliases)}")

    def column(col: Column) -> str:
        return f"{quote(aliases[col.dataset])}.{quote(col.name)}"

    def predicate(pred: Predicate) -> str:
        expression = column(pred.column)
        if pred.as_text:
            expression = dialect.text(expression)
        return f"{expression} = {dialect.literal(pred.value)}"

    def cell(name: str) -> str:
        return f"{quote('q')}.{quote(name)}"

    grouped_total = plan.grand_total and bool(plan.groups)
    inner_columns = [f"{column(group)} AS {quote(f'g{i}')}" for i, group in enumerate(plan.groups)]
    if grouped_total:
        inner_columns.append(f"GROUPING({column(plan.groups[0])}) AS {quote('is_total')}")
    for i, aggregate in enumerate(plan.aggregates):
        expression = dialect.aggregate(
            aggregate.metric.agg,
            column(aggregate.metric.column),
            tuple(predicate(pred) for pred in aggregate.filters),
        )
        inner_columns.append(f"{expression} AS {quote(f'm{i}')}")

    inner = ["SELECT\n  " + ",\n  ".join(inner_columns)]
    inner.append(f"FROM {quote(plan.source)} AS {quote(aliases[plan.source])}")
    for edge in plan.joins:
        inner.append(
            f"LEFT JOIN {quote(edge.target)} AS {quote(aliases[edge.target])}"
            f" ON {column(Column(edge.source, edge.source_column))}"
            f" = {column(Column(edge.target, edge.target_column))}"
        )
    predicates = [predicate(pred) for pred in plan.filters]
    if plan.comparison:
        comparison = plan.comparison
        periods = ", ".join(dialect.literal(period) for period in comparison.periods)
        predicates.append(f"{dialect.text(column(comparison.column))} IN ({periods})")
    if predicates:
        inner.append("WHERE " + " AND ".join(predicates))
    if plan.groups:
        groups = ", ".join(column(group) for group in plan.groups)
        inner.append(
            f"GROUP BY GROUPING SETS (({groups}), ())" if grouped_total else f"GROUP BY {groups}"
        )

    outer_columns = []
    for i, group in enumerate(plan.groups):
        expression = cell(f"g{i}")
        if grouped_total:
            # Types aren't in the model. A total label has an explicit text output contract.
            label = dialect.literal("Total") if i == 0 else "NULL"
            expression = (
                f"CASE WHEN {cell('is_total')} = 1 THEN {label} ELSE {dialect.text(expression)} END"
            )
        outer_columns.append(f"{expression} AS {quote(group.name)}")
    for output in plan.outputs:
        expression = cell(f"m{output.primary}")
        if output.kind != "value":
            baseline = cell(f"m{output.baseline}")
            expression = f"({expression} - {baseline})"
            if output.kind == "pct_change":
                expression = f"100.0 * {expression} / NULLIF({baseline}, 0)"
        outer_columns.append(f"{expression} AS {quote(output.alias)}")

    sql = (
        "WITH "
        + quote("aggregated")
        + " AS (\n"
        + "\n".join("  " + line for line in "\n".join(inner).splitlines())
        + "\n)\nSELECT\n  "
        + ",\n  ".join(outer_columns)
        + f"\nFROM {quote('aggregated')} AS {quote('q')}"
    )
    ordering = [f"{cell('is_total')} ASC"] if grouped_total else []
    ordering.extend(f"{cell(f'g{i}')} ASC NULLS LAST" for i in range(len(plan.groups)))
    if ordering:
        sql += "\nORDER BY " + ", ".join(ordering)
    return sql + ";"
