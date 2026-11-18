from pathlib import Path

from capacity_insights.cli import main


def test_cli_report_end_to_end(tmp_path, capsys):
    sample = tmp_path / "sample.csv"
    out = tmp_path / "out"
    rc = main(["report", "--sample-data", str(sample), "--horizon", "90",
               "--output-dir", str(out)])
    assert rc == 0
    assert sample.exists()
    report = out / "report.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Quarterly capacity report" in text
    assert "res-001" in text
    assert (out / "forecasts.json").exists()
    assert (out / "quality.json").exists()
    charts = list((out / "charts").glob("*.png"))
    assert charts, "expected at least one chart for a flagged resource"
    assert all(p.stat().st_size > 1000 for p in charts)
    assert "FLAG res-001 disk_pct" in capsys.readouterr().out


def test_cli_generate_and_bench(tmp_path, capsys):
    out = tmp_path / "gen.csv"
    assert main(["generate", "--output", str(out), "--resources", "5", "--days", "30"]) == 0
    assert Path(out).exists()
    assert main(["bench", "--quick"]) == 0
    assert "capacity-insights bench" in capsys.readouterr().out
