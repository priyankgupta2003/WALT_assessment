from query_compiler import compile_sql


def test_orphan_fact_survives_attachment_and_null_is_not_total(db, execute):
    db.execute(
        "INSERT INTO fact_sales VALUES ('orphan', '2026-02-01', NULL, 'missing', 'Online', 40)"
    )
    rows = execute(
        {"metrics": [{"name": "total_revenue"}], "group_by": ["region"], "totals": "grand"}
    )
    assert rows[-2] == {"region": None, "total_revenue": 40}
    assert rows[-1] == {"region": "Total", "total_revenue": 1200}


def test_global_dimension_filter_restricts_facts(db, execute):
    db.execute("INSERT INTO fact_sales VALUES ('orphan', NULL, NULL, 'missing', 'Online', 40)")
    assert execute(
        {
            "metrics": [{"name": "total_revenue"}],
            "filters": [{"field": "region", "model": "dim_store", "op": "=", "value": "North"}],
        }
    ) == [{"total_revenue": 350}]


def test_metric_dimension_filter_preserves_other_metric(db, execute):
    db.execute("INSERT INTO fact_sales VALUES ('orphan', NULL, NULL, 'missing', 'Online', 40)")
    assert execute(
        {
            "metrics": [
                {
                    "name": "total_revenue",
                    "as": "north_rev",
                    "filters": [
                        {"field": "region", "model": "dim_store", "op": "=", "value": "North"}
                    ],
                },
                {"name": "total_revenue"},
            ]
        }
    ) == [{"north_rev": 350, "total_revenue": 1200}]


def test_missing_calendar_is_preserved_until_filtered(db, execute):
    db.execute("INSERT INTO fact_sales VALUES ('orphan', '2030-01-01', NULL, 'S1', 'Online', 40)")
    contract = {"metrics": [{"name": "total_revenue"}], "group_by": ["fiscal_year"]}
    assert execute(contract)[-1] == {"fiscal_year": None, "total_revenue": 40}
    contract["filters"] = [
        {"field": "fiscal_year", "model": "dim_calendar", "op": "=", "value": 2026}
    ]
    assert execute(contract) == [{"fiscal_year": 2026, "total_revenue": 710}]


def test_calendar_uses_order_date_even_when_shipping_crosses_year(db, execute, contract_a):
    db.execute("INSERT INTO dim_calendar VALUES ('2027-01-01', 2027, 'Q1')")
    db.execute("UPDATE fact_sales SET ship_date = '2027-01-01' WHERE order_id = 'O-200'")
    assert execute(contract_a) == [{"online_rev": 420, "total_revenue": 710}]


def test_only_required_joins_and_join_reuse(model, contract_a, contract_b, contract_c, dialect):
    sql = compile_sql(model, {"metrics": [{"name": "total_revenue"}]}, dialect)
    assert "JOIN" not in sql
    a = compile_sql(model, contract_a, dialect)
    assert 'LEFT JOIN "dim_calendar"' in a
    assert 'JOIN "dim_store"' not in a
    assert compile_sql(model, contract_b, dialect).count("LEFT JOIN") == 2
    assert compile_sql(model, contract_c, dialect).count("LEFT JOIN") == 1


def test_renamed_tables_and_join_columns_are_resolved(db, model, contract_a, dialect):
    replacements = {"fact_sales": "sales", "dim_calendar": "dates", "dim_store": "stores"}
    for old, new in replacements.items():
        db.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
    db.execute("ALTER TABLE sales RENAME COLUMN order_date TO purchased_on")
    db.execute("ALTER TABLE dates RENAME COLUMN date TO calendar_day")
    for item in model["datasets"]:
        item["name"] = replacements[item["name"]]
    for item in model["metrics"] + model["dimensions"]:
        item["model"] = replacements[item["model"]]
    for edge in model["relationships"]:
        edge["from"] = replacements[edge["from"]]
        edge["to"] = replacements[edge["to"]]
        if edge["to"] == "dates":
            edge["from_column"] = "purchased_on"
            edge["to_column"] = "calendar_day"
    contract_a["filters"][0]["model"] = "dates"
    contract_a["metrics"][0]["filters"][0]["model"] = "sales"
    assert db.execute(compile_sql(model, contract_a, dialect)).fetchall() == [(420, 710)]


def test_multihop_relationships(db, model, contract_c, dialect):
    db.execute("CREATE TEMP TABLE store_link AS SELECT store_id FROM dim_store")
    model["datasets"].append({"name": "store_link", "grain": "one store"})
    model["relationships"][0]["to"] = "store_link"
    model["relationships"].append(
        {
            "from": "store_link",
            "from_column": "store_id",
            "to": "dim_store",
            "to_column": "store_id",
            "cardinality": "many_to_one",
        }
    )
    sql = compile_sql(model, contract_c, dialect)
    assert sql.count("LEFT JOIN") == 2
    assert db.execute(sql).fetchall() == [("North", 4), ("South", 3), ("West", 2), ("Total", 8)]
