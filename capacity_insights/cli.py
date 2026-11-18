"""CLI: python -m capacity_insights <report|generate|bench>

Examples
--------
Generate sample data, then run the full pipeline on it::

    python -m capacity_insights generate --output sample.csv
    python -m capacity_insights report --sample-data sample.csv --horizon 90

``report --sample-data PATH`` loads PATH if it exists, otherwise generates
the built-in sample data to PATH first — so the one-liner above works on a
fresh checkout. Use ``--input`` for your own CSV/TSV/JSON instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bench import format_bench, run_bench
from .forecast import forecast_all
from .ingest import generate_sample_data, load_samples, save_samples
from .quality import run_quality_checks
from .report import build_report


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--horizon", type=int, default=90, help="forecast horizon in days (default 90)")
    p.add_argument("--threshold", type=float, default=80.0, help="utilization threshold %% (default 80)")
    p.add_argument("--stale-days", type=int, default=7, help="stale if no sample for N days (default 7)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capacity_insights")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="generate synthetic sample data")
    p_gen.add_argument("--output", default="sample.csv")
    p_gen.add_argument("--resources", type=int, default=40)
    p_gen.add_argument("--days", type=int, default=182)
    p_gen.add_argument("--seed", type=int, default=42)

    p_rep = sub.add_parser("report", help="run ingest -> quality -> forecast -> report")
    src = p_rep.add_mutually_exclusive_group()
    src.add_argument("--input", help="input .csv/.tsv/.json with real samples")
    src.add_argument("--sample-data", help="sample CSV path; generated there first if missing")
    p_rep.add_argument("--output-dir", default="out")
    _add_common(p_rep)

    p_bench = sub.add_parser("bench", help="scaled-down synthetic benchmark")
    p_bench.add_argument("--quick", action="store_true", help="only the two smallest sizes")

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        df = generate_sample_data(n_resources=args.resources, days=args.days, seed=args.seed)
        path = save_samples(df, args.output)
        print(f"wrote {len(df)} rows for {df['resource'].nunique()} resources to {path}")
        return 0

    if args.cmd == "bench":
        sizes = [(10, 90), (40, 182)] if args.quick else None
        print(format_bench(run_bench(sizes)))
        return 0

    # report
    if args.input:
        df = load_samples(args.input)
    elif args.sample_data:
        path = Path(args.sample_data)
        if path.exists():
            df = load_samples(path)
        else:
            df = generate_sample_data()
            save_samples(df, path)
            print(f"generated sample data -> {path}")
    else:
        df = generate_sample_data()
        print("no --input/--sample-data: using generated sample data")

    quality = run_quality_checks(df, stale_days=args.stale_days)
    results, forecasts = forecast_all(df, horizon=args.horizon, threshold=args.threshold)
    report_path = build_report(df, quality, results, forecasts, args.output_dir,
                               horizon=args.horizon, threshold=args.threshold)
    flagged = [r for r in results if r.flagged]
    print(f"rows={len(df)} resources={quality.n_resources} series={len(results)} "
          f"flagged={len(flagged)} quality_issues={len(quality.issues)}")
    for r in flagged:
        print(f"  FLAG {r.resource} {r.metric} last={r.last_value:.1f}% "
              f"slope={r.slope_per_day:+.3f}%/day crossing={r.projected_crossing_date}")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
