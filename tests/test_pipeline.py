import json

import pandas as pd
import pytest

from capacity_insights.forecast import forecast_all, forecast_series
from capacity_insights.ingest import generate_sample_data, load_samples, save_samples
from capacity_insights.quality import run_quality_checks


def test_generator_shape_and_growing_resource():
    df = generate_sample_data(n_resources=40, days=182, seed=42)
    assert df["resource"].nunique() == 40
    assert set(df["metric"]) == {"cpu_pct", "disk_pct", "memory_pct"}
    growing = df[(df.resource == "res-001") & (df.metric == "disk_pct")]
    first = growing.head(14)["value"].mean()
    last = growing.tail(14)["value"].mean()
    assert last - first > 20  # deliberate growth


def test_ingest_roundtrip_formats(tmp_path):
    df = generate_sample_data(n_resources=3, days=20, seed=1)
    for name in ("s.csv", "s.tsv", "s.json"):
        path = save_samples(df, tmp_path / name)
        loaded = load_samples(path)
        assert len(loaded) == len(df)
        assert list(loaded.columns) == list(df.columns)


def test_ingest_rejects_bad_metric(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,resource,host,app_team,metric,value\n2026-01-01,r,h,t,net_pct,1\n")
    with pytest.raises(ValueError, match="unknown metric"):
        load_samples(p)


def test_quality_detects_injected_defects():
    df = generate_sample_data(n_resources=5, days=60, seed=42)
    q = run_quality_checks(df, stale_days=7)
    kinds = {i.kind for i in q.issues}
    assert "gap" in kinds and "out_of_range" in kinds and "stale" in kinds
    assert any(i.resource == "res-002" for i in q.issues if i.kind == "gap")
    assert any(i.resource == "res-003" for i in q.issues if i.kind == "stale")


def test_quality_clean_frame_has_no_issues():
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    df = pd.DataFrame({"timestamp": dates, "resource": "r1", "host": "h1",
                       "app_team": "t1", "metric": "cpu_pct", "value": 50.0})
    assert run_quality_checks(df).ok


def test_forecast_flags_growing_not_flat():
    dates = pd.date_range("2026-01-01", periods=90, freq="D")
    base = {"timestamp": dates, "host": "h1", "app_team": "t1"}
    growing = pd.DataFrame({**base, "resource": "grow", "metric": "disk_pct",
                            "value": 50 + 0.3 * pd.RangeIndex(90)})
    flat = pd.DataFrame({**base, "resource": "flat", "metric": "cpu_pct", "value": 40.0})
    results, _ = forecast_all(pd.concat([growing, flat]), horizon=90, threshold=80)
    by = {(r.resource, r.metric): r for r in results}
    assert by[("grow", "disk_pct")].flagged
    assert by[("grow", "disk_pct")].projected_crossing_date is not None
    assert not by[("flat", "cpu_pct")].flagged


def test_forecast_series_small_input_raises():
    with pytest.raises(ValueError):
        forecast_series(pd.Series(["2026-01-01"]), pd.Series([50.0]))


def test_sample_data_forecast_flags_res001_disk():
    df = generate_sample_data()
    results, _ = forecast_all(df, horizon=90)
    flagged = {(r.resource, r.metric) for r in results if r.flagged}
    assert ("res-001", "disk_pct") in flagged
