# Power BI model (DAX + Power Query)

This folder contains the Power BI side of capacity-insights: source files
you load into Power BI Desktop. **There is no binary `.pbix` in this repo** —
a `.pbix` is a binary artefact best created and versioned in Desktop itself.
These `.dax` / `.m` files are the pbix-compatible source: the exact query
and measures that go into such a file, kept in git where they can be diffed.

## Files

| File | What it is |
|---|---|
| `power_query.m` | Power Query (M) loader: CSV → typed `Utilization` table |
| `capacity_measures.dax` | DAX measures: trend, forecast-to-threshold, data quality |
| `README.md` | This file |

## Load it into Power BI Desktop

1. **Get data.** Produce a CSV first, e.g.
   `python -m capacity_insights generate --output sample.csv`
   (or export your own samples with columns
   `timestamp, resource, host, app_team, metric, value`).
2. **Power Query.** *Home → Get Data → Blank Query → Advanced Editor*,
   paste `power_query.m`, fix the `File.Contents("...")` path, name the
   query **`Utilization`**, then *Close & Apply*.
   For a `.tsv`/`.json` export, change `Csv.Document` delimiter or use the
   JSON connector — the column names/types after that step stay the same.
3. **(Optional) parameters.** *Home → Enter Data*: a one-row table named
   **`Params`** with numeric columns `Threshold` (80) and
   `HorizonDays` (90). Measures fall back to 80 / 90 without it.
4. **Measures.** For each measure in `capacity_measures.dax`:
   *Modeling → New measure*, paste the `Name = <expression>` text.
   Create them in file order — later measures (`Days to Threshold`,
   `Projected Crossing Date`, …) reference earlier ones.
5. **Save as** `capacity-insights.pbix`. Build visuals, for example:
   - Card: `Flagged Series Count`, `Stale Series Count`, `Data Quality % (in range)`
   - Line chart: `Utilization[value]` average + `Utilization 7d Moving Avg %`
     by `timestamp`, legend on `metric`, small multiples / filter on `resource`
   - Table: `resource, metric, Latest Utilization %, Trend Slope % per Day,
     Projected Crossing Date` with conditional formatting on the date.

## How it maps to the Python pipeline

| Python (`capacity_insights/`) | Power BI |
|---|---|
| `ingest.load_samples` | `power_query.m` (`Utilization` table) |
| `quality.run_quality_checks` | `Out-of-Range Sample Count`, `Data Quality % (in range)`, `Is Stale Series (7d)`, `Stale Series Count` |
| `forecast.forecast_all` (polyfit slope) | `Trend Slope % per Day`, `Trend Intercept %` |
| threshold crossing (80%, 90 d) | `Days to Threshold`, `Projected Crossing Date`, `Crosses Threshold Within Horizon`, `Flagged Series Count` |

**Parity caveat (honest):** the Python forecaster removes weekly seasonal
indices before fitting (STL-lite); the DAX trend is a plain least-squares
line on the filtered samples plus a 7-day moving-average measure for visual
comparison. Slopes should be close on daily data, not bit-identical. If the
two disagree, trust neither blindly — check `forecasts.json` / the DAX
values against the raw series.
