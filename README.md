# capacity-insights

Turn CPU, disk and memory utilization time series from technology platforms
into three things a capacity conversation actually needs: **forecasts** of
when a resource will run out of headroom, **data-quality checks** so you know
which series to trust, and a **quarterly capacity report** (Markdown + charts)
you can hand to application owners. A Power BI model (Power Query M + DAX
source) mirrors the same measures for teams that live in Power BI Desktop.

Synthetic sample data is included via a generator — no real infrastructure
data. Plausible numbers, honest limitations (below).

## Design

```
                        ┌────────────────────┐
  samples.csv/.tsv/.json│      ingest        │  generate_sample_data()
  ─────────────────────►│  load_samples()    │◄─── ~40 resources × 3 metrics
                        │  (long-form schema)│     × ~182 daily samples
                        └─────────┬──────────┘
                                  │ normalised DataFrame
                                  │ timestamp, resource, host,
                                  │ app_team, metric, value
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
           ┌─────────────────┐         ┌──────────────────────┐
           │     quality     │         │       forecast       │
           │ gaps / range /  │         │ STL-lite weekly      │
           │ stale resources │         │ seasonal + polyfit   │
           └────────┬────────┘         │ trend → 80% crossing │
                    │ QualityReport    └──────────┬───────────┘
                    └─────────────┬───────────────┘
                                  ▼
                        ┌────────────────────┐      ┌──────────────────┐
                        │       report       │      │   dax/ (Power BI)│
                        │ report.md + charts │      │ power_query.m    │
                        │ forecasts.json     │      │ capacity_        │
                        │ quality.json       │      │   measures.dax   │
                        └────────────────────┘      └──────────────────┘
                                  ▲
                        cli.py (python -m capacity_insights …)
```

| Module | Responsibility | Key entry point |
|---|---|---|
| `capacity_insights/ingest.py` | Load CSV/TSV/JSON samples; generate plausible synthetic daily data (weekly seasonality, monthly wave, noise, one growing resource, a few injected defects) | `load_samples()`, `generate_sample_data()` |
| `capacity_insights/quality.py` | Missing-gap, out-of-range (not 0–100%), missing/bad values, and stale-series checks | `run_quality_checks()` → `QualityReport` |
| `capacity_insights/forecast.py` | Per resource×metric: weekly seasonal indices → deseasonalise → `numpy.polyfit` line → project forward, flag ≥80% crossings with date | `forecast_all()`, `forecast_series()` |
| `capacity_insights/report.py` | Quarterly Markdown report + one chart per flagged series, plus `forecasts.json` / `quality.json` | `build_report()` |
| `capacity_insights/cli.py` | End-to-end CLI (`generate` / `report` / `bench`) | `python -m capacity_insights …` |
| `capacity_insights/bench.py` | Scaled-down synthetic timing benchmark | `python -m capacity_insights bench` |
| `dax/` | Power BI Desktop source: Power Query loader + DAX trend / forecast-to-threshold / data-quality measures, with load instructions | `dax/README.md` |
| `tests/` | pytest suite (ingest formats, quality defects, forecast flags, CLI end-to-end) | `pytest -q` |

**Input schema** (long form, one row per sample):
`timestamp, resource, host, app_team, metric, value` where
`metric ∈ {cpu_pct, disk_pct, memory_pct}` and `value` is a percent number
(`62.5` means 62.5%). Out-of-range values are *kept* at ingest so the quality
report can surface them; forecasting excludes them.

## Run

```bash
pip install -e .            # or just run from the repo root (deps: numpy, pandas, matplotlib)

# Full pipeline on sample data (generates sample.csv first if it doesn't exist)
python -m capacity_insights report --sample-data sample.csv --horizon 90
# -> out/report.md, out/charts/*.png, out/forecasts.json, out/quality.json

# Your own data
python -m capacity_insights report --input my_samples.tsv --horizon 90 --threshold 80 --output-dir out

# Sample data only / benchmark
python -m capacity_insights generate --output sample.csv --resources 40 --days 182
python -m capacity_insights bench          # or: python scripts/bench.py
```

Sanity run on the generated sample data (40 resources, 182 days, 3 metrics):

```
rows=21808 resources=40 series=120 flagged=1 quality_issues=6
  FLAG res-001 disk_pct last=77.2% slope=+0.159%/day crossing=2026-07-14
report -> out/report.md
```

The generator deliberately injects defects for the quality checks to find:
a 6-day gap (`res-002` cpu), two out-of-range values (`res-004` memory:
104%, −3%), and a stale resource (`res-003`, silent for the last 9 days).
`res-001` disk is the one growing resource.

## Tests

```bash
pytest -q
# 10 passed
```

Covers: generator shape/growth, CSV/TSV/JSON round-trips, bad-metric
rejection, quality detection of the injected gap/range/stale defects,
forecast flagging a growing series but not a flat one, the sample-data
headline flag, and a full CLI report run asserting `report.md`, JSON
outputs and non-empty PNG charts.

## Benchmark (scaled down, honest)

`python -m capacity_insights bench` — synthetic data, local Windows
dev machine, Python 3.12. Timings will vary; this is a sanity check that
the pipeline is fast at plausible scale, **not** a production benchmark:

```
capacity-insights bench (synthetic, local machine, scaled down)
resources  days     rows   gen_s  qual_s  fcst_s  total_s flagged
       10    90     2668   0.094   0.023   0.050    0.167       0
       40   182    21808   0.075   0.061   0.326    0.461       1
      100   182    54568   0.302   0.364   0.888    1.553       1
      200   365   218968   0.689   0.552   2.184    3.425      10
```

## Power BI

See [`dax/README.md`](dax/README.md). Short version: load `dax/power_query.m`
as the `Utilization` query, add the measures from `dax/capacity_measures.dax`
in order, save as `.pbix`. There is intentionally **no binary `.pbix` checked
in** — the `.m`/`.dax` files are the diffable, pbix-compatible source for it.

## Limitations (read before acting on a crossing date)

- **Linear trend only.** No changepoints, step changes (new workload, disk
  cleanup, resize), holidays, or saturation effects. A crossing date means
  "at current drift, roughly then" — nothing more.
- **Weekly seasonality only**, estimated as per-weekday means of detrended
  residuals ("STL-lite"). Monthly/quarterly cycles and holiday effects are
  not modelled; <14 points of history disables the seasonal term.
- **No calibrated uncertainty.** `forecasts.json` carries R² and residual
  std, but there are no prediction intervals; noisy low-R² series will see
  their crossing dates jump around between quarters.
- **Flat 80% threshold** for every metric and team by default (`--threshold`
  changes it globally, not per metric). Real headroom needs differ — disk
  usually wants action earlier than CPU.
- **Daily data assumed.** Sub-daily or irregular sampling will confuse the
  gap check and the weekday seasonal indices.
- **Staleness is relative to the freshest series** in the file, not to
  wall-clock time, which is the right call for batch exports but will miss
  "the whole export stopped" — check the file's own freshness separately.
- **Sample data is synthetic** (seeded RNG, invented teams/hosts). The
  injected defects are labelled in the generator docstring; don't read
  anything into the specific numbers.
- **Power BI parity is approximate, and the `.pbix` was not built/tested
  here** (no Power BI Desktop in this environment): DAX uses a plain
  least-squares line + 7-day moving average rather than the Python
  deseasonalised fit. Measures were written carefully but not executed —
  verify them against `forecasts.json` after loading.
- Everything is in-memory pandas; fine to ~10⁵–10⁶ rows (see bench), not a
  streaming/large-scale monitoring system.

## Status

Working end-to-end for the sample pipeline, tests and benchmark above.
Known unfinished / future work: per-metric thresholds, prediction intervals,
a checked-in `.pbix` built in Power BI Desktop, and non-daily sampling
support. If something in that list matters to you, it's a genuine gap, not
an oversight in this README.

## License

MIT — see [LICENSE](LICENSE). © 2026 Ayush Gawai.
