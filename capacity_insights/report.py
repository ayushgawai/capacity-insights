"""Quarterly capacity report (Markdown) + one chart per flagged series."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .forecast import ForecastResult  # noqa: E402
from .quality import QualityReport  # noqa: E402

OBSERVED, FORECAST_C, THRESHOLD_C = "#2563eb", "#d97706", "#dc2626"


def chart_flagged(df: pd.DataFrame, fc: pd.DataFrame, r: ForecastResult, out: Path) -> Path:
    g = df[(df["resource"] == r.resource) & (df["metric"] == r.metric)].sort_values("timestamp")
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    ax.plot(g["timestamp"], g["value"], color=OBSERVED, lw=1.8, label="Observed")
    ax.plot(fc["timestamp"], fc["forecast"], color=FORECAST_C, lw=1.8, ls="--", label="Forecast")
    ax.axhline(r.threshold, color=THRESHOLD_C, lw=1.4, ls=":", label=f"Threshold {r.threshold:.0f}%")
    if r.projected_crossing_date:
        ax.axvline(pd.to_datetime(r.projected_crossing_date), color=THRESHOLD_C, lw=1.0, alpha=0.6)
    ax.set_title(f"{r.resource} · {r.metric} ({r.host}, {r.app_team})", fontsize=10, loc="left")
    ax.set_ylabel("Utilization (%)")
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def build_report(
    df: pd.DataFrame,
    quality: QualityReport,
    results: list[ForecastResult],
    forecasts: dict,
    out_dir: str | Path,
    horizon: int = 90,
    threshold: float = 80.0,
) -> Path:
    out_dir = Path(out_dir)
    charts_dir = out_dir / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    flagged = [r for r in results if r.flagged]
    chart_files: dict[tuple[str, str], str] = {}
    for r in flagged:
        p = chart_flagged(df, forecasts[(r.resource, r.metric)], r,
                          charts_dir / f"{r.resource}_{r.metric}.png")
        chart_files[(r.resource, r.metric)] = f"charts/{p.name}"

    (out_dir / "forecasts.json").write_text(
        json.dumps([r.to_dict() for r in results], indent=1), encoding="utf-8")
    (out_dir / "quality.json").write_text(
        json.dumps(quality.to_dict(), indent=1), encoding="utf-8")

    lines = [
        "# Quarterly capacity report",
        "",
        f"Window: **{quality.start} to {quality.end}** · Resources: **{quality.n_resources}** · "
        f"Series forecast: **{len(results)}** · Horizon: **{horizon} days** · Threshold: **{threshold:.0f}%**",
        "",
        "## Executive summary",
        "",
        f"- **Flagged series: {len(flagged)}** — projected to reach {threshold:.0f}% within {horizon} days "
        f"(or are already there). Each has a chart below and an owner team to contact.",
        f"- Data quality: {quality.count('gap')} gap(s), {quality.count('out_of_range')} out-of-range "
        f"value(s), {quality.count('stale')} stale series. Details below — forecasts on "
        "flagged-but-stale series should be treated as unconfirmed.",
        "",
        "## Action list (flagged series)",
        "",
    ]
    if not flagged:
        lines.append("No series crossed the threshold in the horizon. No action required this quarter.")
    else:
        lines += ["| Resource | Metric | Host | App team | Last % | Slope %/day | Projected crossing | Chart |",
                  "|---|---|---|---|---:|---:|---|---|"]
        for r in flagged:
            lines.append(
                f"| {r.resource} | {r.metric} | {r.host} | {r.app_team} | {r.last_value:.1f} | "
                f"{r.slope_per_day:+.3f} | {r.projected_crossing_date or '-'} | "
                f"[chart]({chart_files[(r.resource, r.metric)]}) |")
        lines.append("")
        for r in flagged:
            lines += [f"### {r.resource} — {r.metric}",
                      f"![{r.resource} {r.metric}]({chart_files[(r.resource, r.metric)]})", ""]

    lines += [quality.to_markdown(), "", "## All series", "",
              "| Resource | Metric | Team | Last % | Slope %/day | R² | Forecast at horizon % | Flagged | Crossing |",
              "|---|---|---|---:|---:|---:|---:|:--:|---|"]
    for r in results:
        lines.append(
            f"| {r.resource} | {r.metric} | {r.app_team} | {r.last_value:.1f} | {r.slope_per_day:+.3f} | "
            f"{r.r2:.2f} | {r.projected_value_at_horizon:.1f} | {'YES' if r.flagged else ''} | "
            f"{r.projected_crossing_date or '-'} |")

    lines += ["", "## Method & limitations", "",
              "- Forecast: weekly seasonal indices (STL-lite) removed, then a straight-line "
              "`numpy.polyfit` trend; forecast = trend + weekday seasonal index.",
              "- A linear trend cannot represent step changes (new workload, disk cleanup, "
              "instance resize), holidays, or saturation. Treat crossing dates as "
              "'at current drift, roughly when', not commitments.",
              "- R² and residual std are in `forecasts.json`; low-R² series are noisy and "
              "their crossing dates move a lot between quarters.",
              "- Threshold is a flat 80% for every metric/team; real headroom needs differ "
              "(e.g. disk usually needs action earlier than CPU).",
              "- This report is only as good as the input: see the data-quality section. "
              "Stale or gappy series can look flat simply because nobody is reporting.", ""]
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
