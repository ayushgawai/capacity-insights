"""Per-resource/metric linear + weekly-seasonal trend forecasting (STL-lite).

Method (deliberately simple and explainable):
1. Estimate a weekly seasonal index per weekday from detrended residuals.
2. Deseasonalise, fit a straight line with ``numpy.polyfit`` (degree 1).
3. Forecast = trend + seasonal index for that weekday.
4. Flag the series if the forecast crosses ``threshold`` within ``horizon``
   days (or is already at/above it). Report the first projected crossing date.

This is not STL/ARIMA/Prophet: no changepoints, no holidays, no confidence
calibration beyond a residual standard deviation. See README limitations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class ForecastResult:
    resource: str
    host: str
    app_team: str
    metric: str
    n_points: int
    last_date: str
    last_value: float
    slope_per_day: float
    r2: float
    residual_std: float
    projected_value_at_horizon: float
    threshold: float
    flagged: bool
    projected_crossing_date: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _weekly_seasonal(t: np.ndarray, y: np.ndarray, dow: np.ndarray) -> np.ndarray:
    """Seasonal index per weekday (0..6), centred to mean ~0."""
    if len(y) < 14:
        return np.zeros(7)
    slope, intercept = np.polyfit(t, y, 1)
    resid = y - (slope * t + intercept)
    seasonal = np.zeros(7)
    for d in range(7):
        mask = dow == d
        seasonal[d] = float(resid[mask].mean()) if mask.any() else 0.0
    return seasonal - seasonal.mean()


def forecast_series(
    timestamps: pd.Series,
    values: pd.Series,
    horizon: int = 90,
    threshold: float = 80.0,
) -> tuple[ForecastResult, pd.DataFrame]:
    """Forecast one series. Returns (result-without-identity, forecast frame)."""
    df = pd.DataFrame({"timestamp": pd.to_datetime(timestamps), "value": pd.to_numeric(values)})
    df = df.dropna().sort_values("timestamp")
    if len(df) < 2:
        raise ValueError("need at least 2 points to forecast")
    t0 = df["timestamp"].iloc[0]
    t = (df["timestamp"] - t0).dt.days.to_numpy(dtype=float)
    y = df["value"].to_numpy(dtype=float)
    dow = df["timestamp"].dt.dayofweek.to_numpy()

    seasonal = _weekly_seasonal(t, y, dow)
    y_des = y - seasonal[dow]
    slope, intercept = np.polyfit(t, y_des, 1)
    fitted = slope * t + intercept + seasonal[dow]
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    r2 = 1.0 - ss_res / ss_tot

    last_t = float(t[-1])
    future_days = np.arange(1, horizon + 1, dtype=float)
    future_dates = df["timestamp"].iloc[-1] + pd.to_timedelta(future_days, unit="D")
    future_dow = future_dates.dayofweek.to_numpy()
    yhat = slope * (last_t + future_days) + intercept + seasonal[future_dow]
    fc = pd.DataFrame({"timestamp": future_dates, "forecast": yhat})

    already = bool(y[-1] >= threshold)
    crossing = None
    if already:
        crossing = df["timestamp"].iloc[-1]
    else:
        hit = fc.loc[fc["forecast"] >= threshold, "timestamp"]
        if not hit.empty:
            crossing = hit.iloc[0]
    result = ForecastResult(
        resource="", host="", app_team="", metric="",
        n_points=int(len(df)),
        last_date=str(df["timestamp"].iloc[-1].date()),
        last_value=round(float(y[-1]), 2),
        slope_per_day=round(float(slope), 4),
        r2=round(float(r2), 3),
        residual_std=round(float(np.sqrt(ss_res / max(len(y) - 2, 1))), 2),
        projected_value_at_horizon=round(float(yhat[-1]), 2) if len(yhat) else round(float(y[-1]), 2),
        threshold=float(threshold),
        flagged=bool(already or crossing is not None),
        projected_crossing_date=str(pd.to_datetime(crossing).date()) if crossing is not None else None,
    )
    return result, fc


def forecast_all(
    df: pd.DataFrame, horizon: int = 90, threshold: float = 80.0
) -> tuple[list[ForecastResult], dict[tuple[str, str], pd.DataFrame]]:
    results: list[ForecastResult] = []
    forecasts: dict[tuple[str, str], pd.DataFrame] = {}
    clean = df.dropna(subset=["timestamp", "value"])
    # Out-of-range rows would poison a fit; forecast on the valid 0..100 range.
    clean = clean[(clean["value"] >= 0) & (clean["value"] <= 100)]
    for (resource, metric), g in clean.groupby(["resource", "metric"]):
        if len(g) < 7:
            continue
        result, fc = forecast_series(g["timestamp"], g["value"], horizon, threshold)
        result.resource, result.metric = str(resource), str(metric)
        result.host = str(g["host"].iloc[-1])
        result.app_team = str(g["app_team"].iloc[-1])
        results.append(result)
        forecasts[(str(resource), str(metric))] = fc
    results.sort(key=lambda r: (not r.flagged, r.projected_crossing_date or "9999", r.resource))
    return results, forecasts
