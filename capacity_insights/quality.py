"""Data-quality checks: missing gaps, out-of-range values, stale resources."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd


@dataclass
class QualityIssue:
    kind: str  # gap | out_of_range | stale | missing_value | bad_timestamp
    resource: str
    metric: str
    detail: str


@dataclass
class QualityReport:
    n_rows: int
    n_resources: int
    start: str
    end: str
    issues: list[QualityIssue] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for i in self.issues if i.kind == kind)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        d = asdict(self)
        d["counts"] = {k: self.count(k) for k in sorted({i.kind for i in self.issues})}
        d["ok"] = self.ok
        return d

    def to_markdown(self) -> str:
        lines = [
            "## Data quality",
            "",
            f"- Rows: {self.n_rows} · Resources: {self.n_resources} · "
            f"Window: {self.start} to {self.end}",
            f"- Gaps: {self.count('gap')} · Out-of-range: {self.count('out_of_range')} · "
            f"Stale series: {self.count('stale')} · Missing values: {self.count('missing_value')} · "
            f"Bad timestamps: {self.count('bad_timestamp')}",
            "",
        ]
        if not self.issues:
            lines.append("No issues found.")
        else:
            lines += ["| Kind | Resource | Metric | Detail |", "|---|---|---|---|"]
            for i in self.issues[:100]:
                lines.append(f"| {i.kind} | {i.resource} | {i.metric} | {i.detail} |")
            if len(self.issues) > 100:
                lines.append(f"\n_…and {len(self.issues) - 100} more (see quality.json)._")
        return "\n".join(lines)


def run_quality_checks(
    df: pd.DataFrame,
    stale_days: int = 7,
    max_gap_days: int = 2,
    as_of: pd.Timestamp | None = None,
) -> QualityReport:
    """Check a normalised frame (see ``ingest``).

    - gap: consecutive daily samples more than ``max_gap_days`` apart
    - out_of_range: value < 0 or > 100
    - stale: last sample older than ``stale_days`` before ``as_of``
      (defaults to the dataset's maximum timestamp, so staleness is
      relative to the freshest series, not wall-clock time)
    """
    issues: list[QualityIssue] = []
    if df.empty:
        return QualityReport(0, 0, "-", "-", [QualityIssue("gap", "-", "-", "empty input")])

    valid_ts = df["timestamp"].notna()
    for _, r in df[~valid_ts].iterrows():
        issues.append(QualityIssue("bad_timestamp", str(r["resource"]), str(r["metric"]),
                                   "unparseable timestamp"))
    for _, r in df[df["value"].isna()].iterrows():
        issues.append(QualityIssue("missing_value", str(r["resource"]), str(r["metric"]),
                                   f"missing value at {r['timestamp']}"))
    for _, r in df[(df["value"] < 0) | (df["value"] > 100)].iterrows():
        issues.append(QualityIssue("out_of_range", str(r["resource"]), str(r["metric"]),
                                   f"value {r['value']} at {pd.to_datetime(r['timestamp']).date()}"))

    clean = df[valid_ts].dropna(subset=["value"])
    end = as_of if as_of is not None else clean["timestamp"].max()
    for (resource, metric), g in clean.groupby(["resource", "metric"]):
        g = g.sort_values("timestamp")
        diffs = g["timestamp"].diff().dt.days
        for ts, d in zip(g["timestamp"][diffs > max_gap_days], diffs[diffs > max_gap_days]):
            issues.append(QualityIssue("gap", str(resource), str(metric),
                                       f"{int(d)}-day gap ending {pd.to_datetime(ts).date()}"))
        last = g["timestamp"].max()
        age = (end - last).days
        if age > stale_days:
            issues.append(QualityIssue("stale", str(resource), str(metric),
                                       f"last sample {last.date()}, {age}d before {pd.to_datetime(end).date()}"))
    return QualityReport(
        n_rows=int(len(df)),
        n_resources=int(df["resource"].nunique()),
        start=str(clean["timestamp"].min().date()) if not clean.empty else "-",
        end=str(pd.to_datetime(end).date()),
        issues=sorted(issues, key=lambda i: (i.kind, i.resource, i.metric)),
    )
