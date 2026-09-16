# Query contract to SQL: assessment and implementation plan

Source: [Takehome_Query_Contract_to_SQL.pdf](Takehome_Query_Contract_to_SQL.pdf), three pages.

Status: this document records the original plan. Python, uv, DuckDB, and PostgreSQL support are now implemented. See [README.md](README.md) for current behavior and validation. The approximately 8–10 hour budget below is an estimate, not a requirement from the assessment.

## 1. What the assessment is asking for

Build a small query compiler with this public interface:

```text
compile_sql(semantic_model, contract, dialect) -> sql_string
```

The contract specifies intent. The semantic model supplies the allowed metrics, dimensions, and relationships. The compiler resolves that intent and emits SQL without inspecting a database, making network requests, or calling an LLM.

Hard requirements:

- Generate identical SQL bytes for identical inputs, across runs.
- Generate SQL in approximately less than 10 ms, excluding database execution; measure and report it.
- Execute generated SQL on DuckDB and emit at least one additional dialect: PostgreSQL or Snowflake.
- Resolve joins using declared relationships, preserve facts when attaching dimensions, and apply dimension filters correctly.
- Return clear, named errors for unknown names and unsupported requests.
- Provide one command for the DuckDB demonstration and one for tests.
- Write a README explaining the architecture, extensions, scaling limits, measurements, and omissions.

Evaluation is explicitly ordered: structure, semantic correctness, written reasoning, failure handling, then performance. Reserve substantial time for explanation and tests.

## 2. The three contracts, in plain language

| Contract | Behavior | Acceptance result | Main trap |
|---|---|---|---|
| A | Online revenue beside all revenue, in fiscal 2026 | `online_rev=420`, `total_revenue=710` | A metric's filter must not restrict the other metric; the fiscal filter requires a calendar join. |
| B | Revenue by region, with 2025/2026 columns, change, percentage change, and a grand total | See table below | Compute total percentage change from total revenue values. |
| C | Distinct orders by region, with a grand total | North 4, South 3, West 2, total **8** | Adding group counts gives 9 because O-203 crosses regions. |

Contract B:

| Region | 2025 | 2026 | Delta | Percent change, displayed |
|---|---:|---:|---:|---:|
| North | 100 | 250 | 150 | 150.0% |
| South | 200 | 370 | 170 | 85.0% |
| West | 150 | 90 | -60 | -40.0% |
| Total | 450 | 710 | 260 | 57.8% |

For B, primary is 2026 and baseline is 2025. Delta is primary minus baseline. Percent change is `100.0 * delta / baseline`. Keep the SQL result numeric and unrounded; round to one decimal only in the demo display. Document this output convention because the PDF specifies display percentages, not a numeric representation.

The PDF explicitly allows explaining C concretely in the README if time is short. Implementing it is worthwhile because the proposed totals strategy naturally supports it.

## 3. Proposed architecture

```text
JSON-compatible model + contract
        |
        v
Validate and normalize
        |
        v
Resolve names and relationship paths
        |
        v
Build a typed query plan
        |
        v
Render using a dialect adapter
        |
        v
SQL string
```

Use Python with small dataclasses for internal structures. Keep DuckDB as a demo/test dependency; the compiler itself should have no database connection. Use PostgreSQL as the second dialect.

Suggested modules:

```text
src/query_compiler/
    compiler.py       # public function and orchestration
    validation.py     # input shape, supported features, normalization
    model.py          # semantic catalog and name resolution
    plan.py           # typed expressions, joins, aggregates, output columns
    planner.py        # relationship discovery and query construction
    dialects.py       # quoting, literals, casts, aggregate rendering
    renderer.py       # render the resolved plan
    errors.py         # named exceptions
examples/
    schema.sql
    semantic_model.json
    contract_a.json
    contract_b.json
    contract_c.json
tests/
    test_results.py
    test_join_semantics.py
    test_validation.py
    test_dialects.py
    test_determinism.py
README.md
```

The query plan is a small intermediate representation: resolved columns, join edges, scoped predicates, aggregate expressions, grouping sets, and derived outputs. It must not contain unresolved contract names or depend on a database connection. Keep it limited to the supported query shapes; a general SQL optimizer is unnecessary.

Choose a small custom renderer initially. The required SQL vocabulary is narrow, and explaining every generated construct is valuable in the follow-up. A SQL library is also allowed, but it does not replace the semantic planner and introduces behavior you must be able to explain.

## 4. SQL strategy and correctness rules

### Discover only the necessary joins

Collect dataset dependencies from metric expressions, grouping dimensions, global filters, metric filters, and the comparison dimension. Starting at the metric's fact dataset, find declared relationship paths to those dependencies.

- Support a single fact dataset and unambiguous paths in the declared many-to-one direction.
- Reuse each necessary join once.
- Use deterministic traversal and alias allocation.
- Reject missing paths, ambiguous paths, and unsupported cardinalities.
- Do not reverse a many-to-one edge and assume it remains safe.
- Trust the model's cardinality declarations; the compiler cannot check warehouse data. Document this boundary.

For this model, the calendar relationship uses `order_date`. Do not infer a relationship on `ship_date`.

### Preserve facts; keep filter scopes separate

Use `LEFT JOIN` for dimension attachment. A sale with an unknown store remains in the revenue total and appears in a null-region group when grouping by region.

Put global predicates in `WHERE`. Thus `WHERE store.region = 'North'` genuinely restricts the facts, including excluding unmatched stores. Moving this condition only into the join's `ON` clause would preserve unwanted facts.

Put per-metric predicates inside their corresponding aggregates. For A, the conceptual expressions are:

```sql
SUM(revenue) FILTER (WHERE channel = 'Online') AS online_rev,
SUM(revenue) AS total_revenue
```

Both see the global fiscal-year restriction, while only the first sees the channel restriction. The same rule must work for a per-metric filter on a joined dimension.

### Aggregate first; calculate changes afterward

For B, build one conditional aggregate per metric and comparison period. Then use an outer query to calculate delta and percentage change from the aggregated columns. This avoids relying on same-select alias visibility and makes the total row obey the same arithmetic as detail rows.

Combine a metric filter and a period filter with `AND`. Never put one metric's local predicate into the shared `WHERE` clause.

### Compute totals at their own grain

Use `GROUP BY GROUPING SETS ((region), ())` for grouped queries requesting a grand total. The database evaluates each aggregate at both the region grain and the total grain.

- Revenue totals aggregate the underlying revenue.
- Distinct-order totals run `COUNT(DISTINCT order_id)` at total grain, producing 8.
- Percentage changes are calculated afterward from each row's aggregate values.

Use `GROUPING(region)` to distinguish a generated total from a real null-region group. Do not label every null region as `Total`. Preserve this grouping marker internally for sorting and labeling; label the total as `Total` for the supplied region contracts. For other dimension types, define a typed output convention before supporting totals for them, or reject that combination clearly.

Both selected dialects support grouping sets, so they can share this semantic plan. SQL can legitimately be identical for their common syntax; the adapter boundary should still own dialect-sensitive operations and validate supported capabilities.

### Specify edge behavior before coding

Proposed policies to state in the README:

- Exactly two distinct comparison periods; `primary` must be one of them. The other is the baseline, regardless of list order.
- Period output columns follow the contract's period order; metric and grouping output order follow their input lists.
- The provided model has no field types, while comparison periods are strings. For this initial vocabulary, explicitly compare the resolved dimension cast to text against string period keys. This handles fiscal years without warehouse introspection or assuming numeric strings are integers. A richer typed model is a later extension.
- Preserve ordinary SQL aggregate behavior: an absent period or all-null revenue sum is `NULL`; distinct count is zero. Delta/percentage propagate missing values. Do not silently equate missing data with zero.
- A zero baseline yields `NULL` percentage change via `NULLIF(baseline, 0)`.
- Global filters and comparison period restrictions both apply. A conflicting filter can therefore produce missing values; document and test this.
- No grouping plus a grand-total request produces one aggregate row, not a duplicate total.
- Reject comparison on a dimension simultaneously listed in `group_by` in the initial version unless its semantics are explicitly implemented.
- Stable SQL generation and stable result ordering are distinct. Add explicit ordering for the demo, with the total last and explicit null ordering.

The calendar fixture lists order dates but omits shipping dates despite asking for every date. Populate the union of order and ship dates in fixture setup and document the repair. The compiler still uses only the declared order-date relationship. Fixture setup may use the provided data; the compiler may not inspect it.

## 5. Scope and named failures

Initial supported vocabulary: declared `sum` and `count_distinct` metrics with simple column expressions; aliases; declared dimensions; conjunctions of equality filters; two-period comparisons; value/delta/percent-change outputs; and grand totals for the supplied grouping shape.

Support a few additional combinations only if their semantics are explicit and tested. Reject unsupported input before rendering, including unknown JSON keys rather than silently ignoring a misspelled feature.

Useful error names:

- `InvalidContractError`: malformed shapes, duplicate output aliases, invalid comparison settings.
- `InvalidSemanticModelError`: duplicate definitions or inconsistent references.
- `UnknownMetricError` / `UnknownDimensionError`.
- `InvalidFilterError`: undeclared field, mismatched model, unsupported operator or value.
- `NoJoinPathError` / `AmbiguousJoinPathError` / `UnsupportedRelationshipError`.
- `UnsupportedFeatureError`: multiple fact datasets, arbitrary SQL expressions, unsupported combinations.
- `UnsupportedDialectError`.

Include an input location and concrete reason in each message, such as `metrics[0].filters[0]: field 'region' belongs to dim_store, not fact_sales`.

Resolve contract identifiers through the catalog. Quote identifiers and escape literal values centrally. Treat model expressions as supported column references, not arbitrary executable SQL. Reject unsupported literal types, non-finite numbers, and null equality in the initial equality-only filter vocabulary. Full schema-level type checking requires metadata the supplied model does not contain.

## 6. Implementation milestones

| Phase | Estimate | Completion check |
|---|---:|---|
| Fixtures and documented policies | 45 min | Three contracts and data transcribed; expected outputs recorded; ambiguities resolved. |
| Validation, catalog, and plan structures | 90 min | Names resolve; unsupported inputs have named errors; no database dependency. |
| Join planning and A | 75 min | DuckDB returns 420 and 710; unmatched-fact and filter-scope tests pass. |
| Comparison, totals, B and C | 120 min | B matches numeric expectations; C totals 8; null region differs from total. |
| Dialect rendering and determinism | 60 min | PostgreSQL emission is checked; output is stable across fresh processes. |
| Edge tests and benchmarking | 60 min | Failure and boundary cases pass; generation measurements recorded. |
| README and clean-run review | 60 min | Demo/test commands work; design and limitations are explainable. |

Total: approximately 8.5 hours, with contingency up to 10 hours. This is a planning estimate, not the assessment's stated time limit.

If limited to roughly four hours: prioritize A and B, both dialect emitters, meaningful correctness tests, measurements, and a clear README. C may use the PDF's explicit written-explanation allowance; no other mandatory requirement has that allowance. Avoid adding extra contract features.

## 7. Test and measurement plan

### Execute against DuckDB

1. Exact A values and output aliases.
2. B detail values and total values; approximate numeric comparison for percentages.
3. C's total is 8, even though detail counts sum to 9.
4. An orphan-store fact remains in unfiltered grouped revenue and the grand total.
5. A global region filter excludes the orphan; a local metric region filter leaves the other metric untouched.
6. A genuine null region is distinguishable from the total row.
7. Zero baseline, missing comparison period, empty filtered input, and all-null revenue.
8. Reversed comparison period list and changed primary yield the documented arithmetic.
9. Filter strings containing apostrophes render safely and evaluate correctly.

### Validate compilation itself

- Unknown names, model mismatches, alias collisions including generated comparison names, unsupported keys/operators, bad periods, missing/ambiguous/unsafe relationships, multiple facts, and unsupported dialects.
- Rename datasets and relationship columns in a model fixture to catch hardcoded joins.
- Snapshot representative SQL for each dialect; snapshots supplement execution tests.
- Compare SQL bytes across repeated calls and fresh processes using different Python hash seeds. Preserve meaningful list order; do not rely on unordered set iteration.
- For PostgreSQL, prefer executing fixtures if an instance is readily available. Otherwise use dialect-aware syntax validation or reviewed snapshots and explicitly report that PostgreSQL execution was not verified. DuckDB execution does not establish PostgreSQL compatibility by itself.

### Benchmark the required boundary

Use a monotonic high-resolution timer around the entire public function: model validation/indexing, contract validation, planning, and rendering. Preload fixture files and exclude database execution and network/file I/O. State that the API accepts parsed JSON-compatible values; report JSON decoding separately if included in a demo wrapper.

Warm up, then measure thousands of compilations of A/B/C in both dialects. Report first-call time separately, plus median, p95, maximum, iteration count, machine, and runtime version. Measure the uncached path; do not hide model preparation or report only repeated cached output retrieval. Investigate a p95 above 10 ms before adding complexity, and report any observed outliers honestly. No timings exist yet.

## 8. README and follow-up preparation

Write the README alongside implementation. It should contain:

1. Setup and single-command demo/test instructions; a benchmark command.
2. Public API and a brief architecture diagram.
3. Example SQL/results for A/B/C.
4. Why left joins, aggregate-local filters, grouping sets, and outer derived calculations are necessary.
5. Supported vocabulary, edge policies, named failures, and model-trust boundaries.
6. The dialect boundary and what was actually tested for each dialect.
7. Measured timings and methodology.
8. Cuts and next steps.

## 9. Technical references checked during planning

- [DuckDB grouping sets](https://duckdb.org/docs/stable/sql/query_syntax/grouping_sets): grouping at multiple grains and identifying generated total rows.
- [PostgreSQL table expressions](https://www.postgresql.org/docs/current/queries-table-expressions.html): outer join/filter placement and grouping sets.
- [PostgreSQL value expressions](https://www.postgresql.org/docs/current/sql-expressions.html): aggregate `FILTER` syntax.

The assessment remains the source of requirements; these references support the proposed SQL strategy.
