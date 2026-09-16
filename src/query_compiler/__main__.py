"""Compile and execute query contracts in DuckDB or PostgreSQL, or benchmark generation."""

import argparse
import json
from pathlib import Path

from .compiler import compile_sql
from .dialects import get_dialect
from .errors import QueryCompilerError
from .examples import fixture_text, load_contract, load_model, postgres_fixture_sql
from .execution import DatabaseExecutionError, postgres_connection


def _print_result(result) -> None:
    columns = [item[0] for item in result.description]
    print(" | ".join(columns))
    for row in result.fetchall():
        print(" | ".join(_display(value, col) for value, col in zip(row, columns, strict=True)))


def _demo_queries(connection, dialect: str, show_sql: bool, contract: str | None) -> None:
    model = load_model()
    for name in (contract,) if contract else ("a", "b", "c"):
        sql = compile_sql(model, load_contract(name), dialect)
        print(f"\nContract {name.upper()}")
        if show_sql:
            print(sql)
        _print_result(connection.execute(sql))


def demo(
    show_sql: bool,
    database: Path | None = None,
    contract: str | None = None,
    dialect: str = "duckdb",
    dsn: str | None = None,
) -> None:
    dialect = get_dialect(dialect).name
    if dialect == "postgres":
        if database is not None:
            raise ValueError("--database is a DuckDB file option; PostgreSQL uses --dsn")
        with postgres_connection(dsn, read_only=False) as connection:
            # All fixture writes target session-local tables, even if public tables already exist.
            connection.execute("SET LOCAL search_path = pg_temp")
            connection.execute(postgres_fixture_sql())
            _demo_queries(connection, dialect, show_sql, contract)
        return
    if dsn is not None:
        raise ValueError("--dsn requires --dialect postgres")
    import duckdb

    initialize = database is None or not database.exists()
    if database is not None:
        database.parent.mkdir(parents=True, exist_ok=True)
    target = str(database) if database is not None else ":memory:"
    # Existing databases are queried read-only: rerunning the demo never reseeds them.
    with duckdb.connect(target, read_only=not initialize) as connection:
        if initialize:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(fixture_text("schema.sql"))
            connection.execute("COMMIT")
        _demo_queries(connection, dialect, show_sql, contract)


def run_contract(
    model: dict,
    contract: dict,
    database: Path | None,
    show_sql: bool,
    dialect: str = "duckdb",
    dsn: str | None = None,
) -> None:
    dialect = get_dialect(dialect).name
    sql = compile_sql(model, contract, dialect)
    if dialect == "postgres" and database is not None:
        raise ValueError("--database is a DuckDB file option; PostgreSQL uses --dsn")
    if dialect == "duckdb":
        if dsn is not None:
            raise ValueError("--dsn requires --dialect postgres")
        if database is None:
            raise ValueError("--database is required for DuckDB execution")
        if not database.is_file():
            raise FileNotFoundError(f"database file does not exist: {database}")
    if show_sql:
        print(sql)
    if dialect == "postgres":
        with postgres_connection(dsn) as connection:
            _print_result(connection.execute(sql))
        return

    import duckdb

    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            _print_result(connection.execute(sql))
    except duckdb.Error as exc:
        raise DatabaseExecutionError(str(exc)) from exc


def _display(value: object, column: str) -> str:
    if value is None:
        return "NULL"
    if column.endswith("_pct_change"):
        return f"{value:.1f}%"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo_parser = subparsers.add_parser("demo", help="execute assessment contracts")
    demo_parser.add_argument("--show-sql", action="store_true")
    demo_parser.add_argument("--dialect", default="duckdb")
    demo_parser.add_argument(
        "--dsn", help="PostgreSQL connection string (or set QUERY_COMPILER_POSTGRES_DSN)"
    )
    demo_parser.add_argument(
        "--contract",
        type=str.lower,
        choices=("a", "b", "c"),
        help="run only this contract (default: run all three)",
    )
    demo_parser.add_argument(
        "--database",
        type=Path,
        help="persistent DuckDB file; seed the assessment data only if the file is new",
    )
    run_parser = subparsers.add_parser("run", help="execute a custom contract JSON file")
    run_parser.add_argument("--contract", type=Path, required=True)
    run_parser.add_argument("--database", type=Path, help="existing DuckDB file")
    run_parser.add_argument("--dialect", default="duckdb")
    run_parser.add_argument(
        "--dsn", help="PostgreSQL connection string (or set QUERY_COMPILER_POSTGRES_DSN)"
    )
    run_parser.add_argument(
        "--model", type=Path, help="semantic model JSON (default: assessment model)"
    )
    run_parser.add_argument("--show-sql", action="store_true")
    compile_parser = subparsers.add_parser(
        "compile", help="compile JSON files without database I/O"
    )
    compile_parser.add_argument("--model", type=Path, required=True)
    compile_parser.add_argument("--contract", type=Path, required=True)
    compile_parser.add_argument("--dialect", default="duckdb")
    benchmark_parser = subparsers.add_parser("benchmark", help="measure full compilation latency")
    benchmark_parser.add_argument("--iterations", type=int, default=2000)
    benchmark_parser.add_argument("--warmup", type=int, default=100)
    benchmark_parser.add_argument("--output", type=Path)
    benchmark_parser.add_argument("--dialect", default="duckdb")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            demo(args.show_sql, args.database, args.contract, args.dialect, args.dsn)
        elif args.command == "run":
            model = (
                json.loads(args.model.read_text(encoding="utf-8")) if args.model else load_model()
            )
            contract = json.loads(args.contract.read_text(encoding="utf-8"))
            run_contract(model, contract, args.database, args.show_sql, args.dialect, args.dsn)
        elif args.command == "compile":
            model = json.loads(args.model.read_text(encoding="utf-8"))
            contract = json.loads(args.contract.read_text(encoding="utf-8"))
            print(compile_sql(model, contract, args.dialect))
        else:
            from .benchmark import run_benchmark

            report = run_benchmark(args.iterations, args.warmup, args.dialect)
            text = json.dumps(report, indent=2) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
            print(text, end="")
    except (QueryCompilerError, DatabaseExecutionError, OSError, ValueError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
