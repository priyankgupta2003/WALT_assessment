"""Measure the public API, including validation and catalog construction, with no cache."""

import math
import platform
import statistics
from time import perf_counter_ns

from .compiler import compile_sql
from .dialects import get_dialect
from .examples import load_contract, load_model


def run_benchmark(iterations: int = 2000, warmup: int = 100, dialect: str = "duckdb") -> dict:
    if iterations < 1 or warmup < 0:
        raise ValueError("iterations must be positive and warmup nonnegative")
    dialect = get_dialect(dialect).name
    # Load all JSON before any timing. No database is imported or opened here.
    model = load_model()
    contracts = {name: load_contract(name) for name in ("a", "b", "c")}
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "dialect": dialect,
        "iterations_per_contract": iterations,
        "warmup_per_contract": warmup,
        "units": "milliseconds",
        "scope": "Full compile_sql call; parsed inputs; no caching, I/O, or database execution",
        "first_call_note": "First observed per contract in this process; only A is first overall",
        "contracts": {},
    }
    for name, contract in contracts.items():
        start = perf_counter_ns()
        expected = compile_sql(model, contract, dialect)
        first = (perf_counter_ns() - start) / 1_000_000
        for _ in range(warmup):
            compile_sql(model, contract, dialect)
        samples = []
        for _ in range(iterations):
            start = perf_counter_ns()
            sql = compile_sql(model, contract, dialect)
            samples.append((perf_counter_ns() - start) / 1_000_000)
            if sql != expected:
                raise AssertionError("compiler output changed during benchmark")
        ordered = sorted(samples)
        report["contracts"][name.upper()] = {
            "first_call_ms": first,
            "median_ms": statistics.median(samples),
            "p95_ms": ordered[math.ceil(0.95 * iterations) - 1],
            "max_ms": max(samples),
            "over_10_ms": sum(sample >= 10 for sample in samples),
        }
    return report
