"""Benchmark / simulation: time ingest + quality + forecast at synthetic scales.

Scaled-down, honest benchmark: it times the pipeline on generated data at a
few sizes on the local machine. It is not a production capacity test.
"""
from __future__ import annotations

import time

from .forecast import forecast_all
from .ingest import generate_sample_data
from .quality import run_quality_checks


def run_bench(sizes: list[tuple[int, int]] | None = None) -> list[dict]:
    sizes = sizes or [(10, 90), (40, 182), (100, 182), (200, 365)]
    rows = []
    for n_resources, days in sizes:
        t0 = time.perf_counter()
        df = generate_sample_data(n_resources=n_resources, days=days)
        t1 = time.perf_counter()
        q = run_quality_checks(df)
        t2 = time.perf_counter()
        results, _ = forecast_all(df)
        t3 = time.perf_counter()
        rows.append({
            "resources": n_resources, "days": days, "rows": len(df),
            "generate_s": t1 - t0, "quality_s": t2 - t1, "forecast_s": t3 - t2,
            "total_s": t3 - t0, "series": len(results),
            "flagged": sum(r.flagged for r in results), "issues": len(q.issues),
        })
    return rows


def format_bench(rows: list[dict]) -> str:
    lines = ["capacity-insights bench (synthetic, local machine, scaled down)",
             f"{'resources':>9} {'days':>5} {'rows':>8} {'gen_s':>7} {'qual_s':>7} {'fcst_s':>7} {'total_s':>8} {'flagged':>7}"]
    for r in rows:
        lines.append(f"{r['resources']:>9} {r['days']:>5} {r['rows']:>8} "
                     f"{r['generate_s']:>7.3f} {r['quality_s']:>7.3f} {r['forecast_s']:>7.3f} "
                     f"{r['total_s']:>8.3f} {r['flagged']:>7}")
    return "\n".join(lines)
