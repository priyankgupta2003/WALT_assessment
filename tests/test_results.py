import pytest


def test_contract_a(execute, contract_a):
    assert execute(contract_a) == [{"online_rev": 420, "total_revenue": 710}]


def test_contract_b(execute, contract_b):
    rows = execute(contract_b)
    expected = [
        ("North", 100, 250, 150, 150),
        ("South", 200, 370, 170, 85),
        ("West", 150, 90, -60, -40),
        ("Total", 450, 710, 260, 100 * 260 / 450),
    ]
    assert len(rows) == len(expected)
    for actual, (region, baseline, primary, delta, pct) in zip(rows, expected, strict=True):
        assert actual == {
            "region": region,
            "total_revenue_2025": baseline,
            "total_revenue_2026": primary,
            "total_revenue_delta": delta,
            "total_revenue_pct_change": pytest.approx(pct),
        }


def test_contract_c_recounts_overlapping_orders(execute, contract_c):
    assert execute(contract_c) == [
        {"region": "North", "order_count": 4},
        {"region": "South", "order_count": 3},
        {"region": "West", "order_count": 2},
        {"region": "Total", "order_count": 8},
    ]


def test_grand_without_groups_has_one_row(execute):
    assert execute({"metrics": [{"name": "order_count"}], "totals": "grand"}) == [
        {"order_count": 8}
    ]


def test_comparison_uses_primary_not_period_position(execute, contract_b):
    contract_b["compare"]["periods"] = ["2026", "2025"]
    contract_b["compare"]["primary"] = "2025"
    total = execute(contract_b)[-1]
    assert list(total) == [
        "region",
        "total_revenue_2026",
        "total_revenue_2025",
        "total_revenue_delta",
        "total_revenue_pct_change",
    ]
    assert total["total_revenue_delta"] == -260
    assert total["total_revenue_pct_change"] == pytest.approx(-100 * 260 / 710)


def test_derived_only_outputs_and_requested_order(execute, contract_b):
    contract_b["compare"]["outputs"] = ["pct_change", "delta"]
    total = execute(contract_b)[-1]
    assert list(total) == ["region", "total_revenue_pct_change", "total_revenue_delta"]
    assert total["total_revenue_delta"] == 260


def test_comparison_and_metric_filter_compose(execute, contract_b):
    contract_b["metrics"].insert(
        0,
        {
            "name": "total_revenue",
            "as": "online",
            "filters": [{"field": "channel", "model": "fact_sales", "op": "=", "value": "Online"}],
        },
    )
    total = execute(contract_b)[-1]
    assert total["online_2025"] == 250
    assert total["online_2026"] == 420
    assert total["online_delta"] == 170
    assert total["online_pct_change"] == 68
    assert total["total_revenue_2026"] == 710


def test_distinct_comparison_total_recounts(execute, contract_b):
    contract_b["metrics"] = [{"name": "order_count"}]
    total = execute(contract_b)[-1]
    assert total["order_count_2025"] == 3
    assert total["order_count_2026"] == 5
    assert total["order_count_delta"] == 2
    assert float(total["order_count_pct_change"]) == pytest.approx(100 * 2 / 3)


def test_multiple_group_dimensions(execute):
    rows = execute(
        {"metrics": [{"name": "order_count"}], "group_by": ["region", "channel"], "totals": "grand"}
    )
    assert len(rows) == 7
    assert rows[-1] == {"region": "Total", "channel": None, "order_count": 8}
    assert sum(row["order_count"] for row in rows[:-1]) == 9


def test_numeric_group_totals_have_explicit_text_labels(execute):
    rows = execute(
        {"metrics": [{"name": "order_count"}], "group_by": ["fiscal_year"], "totals": "grand"}
    )
    assert rows == [
        {"fiscal_year": "2025", "order_count": 3},
        {"fiscal_year": "2026", "order_count": 5},
        {"fiscal_year": "Total", "order_count": 8},
    ]


def test_zero_baseline_yields_null_percentage(db, execute, contract_b):
    db.execute("UPDATE fact_sales SET revenue = 0 WHERE order_date < DATE '2026-01-01'")
    total = execute(contract_b)[-1]
    assert total["total_revenue_2025"] == 0
    assert total["total_revenue_delta"] == 710
    assert total["total_revenue_pct_change"] is None


def test_missing_period_is_not_silently_zero(db, execute, contract_b):
    db.execute("DELETE FROM fact_sales WHERE order_date < DATE '2026-01-01'")
    total = execute(contract_b)[-1]
    assert total["total_revenue_2025"] is None
    assert total["total_revenue_2026"] == 710
    assert total["total_revenue_delta"] is None
    assert total["total_revenue_pct_change"] is None


def test_empty_input_aggregate_semantics(db, execute):
    db.execute("DELETE FROM fact_sales")
    assert execute({"metrics": [{"name": "total_revenue"}, {"name": "order_count"}]}) == [
        {"total_revenue": None, "order_count": 0}
    ]
    assert execute({"metrics": [{"name": "order_count"}], "group_by": ["region"]}) == []
    assert execute(
        {"metrics": [{"name": "order_count"}], "group_by": ["region"], "totals": "grand"}
    ) == [{"region": "Total", "order_count": 0}]


def test_all_null_revenue(db, execute, contract_a):
    db.execute("UPDATE fact_sales SET revenue = NULL")
    assert execute(contract_a) == [{"online_rev": None, "total_revenue": None}]


def test_global_filters_restrict_comparison(execute, contract_b):
    contract_b["filters"] = [
        {"field": "fiscal_year", "model": "dim_calendar", "op": "=", "value": 2026}
    ]
    total = execute(contract_b)[-1]
    assert total["total_revenue_2025"] is None
    assert total["total_revenue_2026"] == 710


def test_comparison_excludes_unrequested_periods(db, execute, contract_b):
    db.execute("INSERT INTO dim_calendar VALUES ('2027-01-01', 2027, 'Q1')")
    db.execute("INSERT INTO dim_store VALUES ('S5', 'Future', 'East')")
    db.execute("INSERT INTO fact_sales VALUES ('future', '2027-01-01', NULL, 'S5', 'Online', 999)")
    rows = execute(contract_b)
    assert [row["region"] for row in rows] == ["North", "South", "West", "Total"]
    assert rows[-1]["total_revenue_2026"] == 710


def test_sql_literal_and_alias_escaping(db, execute, dialect):
    value = "O'Reilly\\shop'; DROP TABLE fact_sales; --"
    alias = 'revenue "quoted"; --'
    placeholder = "%s" if dialect == "postgres" else "?"
    db.execute(f"UPDATE fact_sales SET channel = {placeholder} WHERE order_id = 'O-200'", [value])
    assert execute(
        {
            "metrics": [{"name": "total_revenue", "as": alias}],
            "filters": [{"field": "channel", "model": "fact_sales", "op": "=", "value": value}],
        }
    ) == [{alias: 120}]
    assert db.execute("SELECT COUNT(*) FROM fact_sales").fetchone() == (9,)


def test_metric_filter_distinct_count(execute):
    assert execute(
        {
            "metrics": [
                {
                    "name": "order_count",
                    "as": "online_orders",
                    "filters": [
                        {"field": "channel", "model": "fact_sales", "op": "=", "value": "Online"}
                    ],
                },
                {"name": "order_count"},
            ]
        }
    ) == [{"online_orders": 4, "order_count": 8}]
