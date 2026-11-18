"""Run the scaled-down benchmark: `python scripts/bench.py [--quick]`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capacity_insights.bench import format_bench, run_bench  # noqa: E402

if __name__ == "__main__":
    sizes = [(10, 90), (40, 182)] if "--quick" in sys.argv else None
    print(format_bench(run_bench(sizes)))
