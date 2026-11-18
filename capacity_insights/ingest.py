"""Ingest utilization samples from CSV/TSV/JSON and generate synthetic samples.

Canonical long-form schema (one row per sample):

    timestamp, resource, host, app_team, metric, value

- ``timestamp``: ISO-8601 date/datetime, e.g. ``2026-01-01`` or ``2026-01-01T00:00:00``
- ``resource``:  logical resource id, e.g. ``res-001``
- ``host``:      host the sample came from, e.g. ``host-01``
- ``app_team``:  owning application team, e.g. ``team-payments`` (generic labels only)
- ``metric``:    one of ``cpu_pct``, ``disk_pct``, ``memory_pct``
- ``value``:     utilization percent (valid range is checked by ``quality``, not here,
                 so out-of-range rows are visible to the quality report instead of
                 being silently dropped)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

METRICS = ("cpu_pct", "disk_pct", "memory_pct")
REQUIRED_COLUMNS = ["timestamp", "resource", "host", "app_team", "metric", "value"]


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}; got {list(df.columns)}")
    df = df[REQUIRED_COLUMNS].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for col in ("resource", "host", "app_team", "metric"):
        df[col] = df[col].astype(str).str.strip()
    bad_metric = sorted(set(df["metric"]) - set(METRICS))
    if bad_metric:
        raise ValueError(f"unknown metric(s) {bad_metric}; expected one of {METRICS}")
    df = df.sort_values(["resource", "metric", "timestamp"]).reset_index(drop=True)
    return df


def load_samples(path: str | Path) -> pd.DataFrame:
    """Load samples from a .csv, .tsv/.txt or .json file (records or list of objects)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        raw = pd.read_csv(path)
    elif suffix in (".tsv", ".txt"):
        raw = pd.read_csv(path, sep="\t")
    elif suffix == ".json":
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        records = payload["samples"] if isinstance(payload, dict) else payload
        raw = pd.DataFrame.from_records(records)
    else:
        raise ValueError(f"unsupported file type {suffix!r}; use .csv, .tsv or .json")
    return _normalise(raw)


def save_samples(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".json":
        out = df.copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%d")
        path.write_text(json.dumps(out.to_dict("records"), indent=1), encoding="utf-8")
    elif suffix in (".tsv", ".txt"):
        df.to_csv(path, sep="\t", index=False, date_format="%Y-%m-%d")
    else:
        df.to_csv(path, index=False, date_format="%Y-%m-%d")
    return path


def generate_sample_data(
    n_resources: int = 40,
    days: int = 182,
    seed: int = 42,
    start: str = "2026-01-01",
) -> pd.DataFrame:
    """Plausible daily samples for ~40 resources over ~2 quarters.

    Model per resource/metric: a base level + weekly seasonality (weekdays
    busier) + a small monthly wave + Gaussian noise, clipped to 2..97 %.
    ``res-001`` (disk_pct) is the deliberately growing resource: it starts
    near 45 % and trends upward so it is projected to cross 80 % after the
    observed window. A couple of resources get an injected 5-day gap and a
    few out-of-range values so the quality checks have something real to find.
    """
    if n_resources < 1 or days < 14:
        raise ValueError("n_resources >= 1 and days >= 14 required")
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=days, freq="D")
    dow = dates.dayofweek.to_numpy()  # Mon=0
    weekly = np.where(dow < 5, 3.0, -4.0) + np.sin(dow / 7.0 * 2 * np.pi) * 1.5
    monthly = np.sin(np.arange(days) / 30.0 * 2 * np.pi) * 2.0

    teams = ["team-alpha", "team-bravo", "team-charlie", "team-delta", "team-echo"]
    rows: list[pd.DataFrame] = []
    for i in range(1, n_resources + 1):
        resource = f"res-{i:03d}"
        host = f"host-{(i - 1) % 12 + 1:02d}"
        team = teams[(i - 1) % len(teams)]
        for metric in METRICS:
            base = {"cpu_pct": 38.0, "disk_pct": 46.0, "memory_pct": 55.0}[metric]
            base += rng.uniform(-12, 12)
            slope = rng.uniform(-0.01, 0.03)  # gentle drift, %/day
            if resource == "res-001" and metric == "disk_pct":
                base, slope = 45.0, 0.16  # the growing resource
            values = base + slope * np.arange(days) + weekly + monthly
            values = values + rng.normal(0, 2.0, size=days)
            values = np.clip(values, 2, 97)
            rows.append(
                pd.DataFrame(
                    {
                        "timestamp": dates,
                        "resource": resource,
                        "host": host,
                        "app_team": team,
                        "metric": metric,
                        "value": np.round(values, 2),
                    }
                )
            )
    df = pd.concat(rows, ignore_index=True)

    # Inject defects (deterministic): a gap, stale tail and out-of-range values.
    if n_resources >= 3 and days > 30:
        gap_mask = (
            (df["resource"] == "res-002") & (df["metric"] == "cpu_pct")
            & (df["timestamp"] >= dates[20]) & (df["timestamp"] <= dates[24])
        )
        df = df[~gap_mask]
        stale_cut = dates[-10]
        df = df[~((df["resource"] == "res-003") & (df["timestamp"] > stale_cut))]
        idx = df[(df["resource"] == "res-004") & (df["metric"] == "memory_pct")].head(2).index
        df.loc[idx, "value"] = [104.0, -3.0][: len(idx)]
    return _normalise(df.reset_index(drop=True))
