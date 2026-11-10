"""Command line for the evaluation (M9)::

    python -m orbit.evaluation --config orbit.toml --config experiments/<other>.toml \\
        --days 180 --crew 4 --seeds 1 2 3 4 5 --out data/reports/evaluation.json

Options: ``--config`` (repeatable; default orbit.toml), ``--days`` (180),
``--crew`` (4), ``--seeds`` (1 2 3 4 5), ``--min-level`` (yellow), ``--out``
(JSON report; folders are created). See ``orbit/evaluation/runner.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbit.evaluation.runner import run_all, table
from orbit.schema import AlertLevel


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(prog="python -m orbit.evaluation",
                                     description="Evaluate ORBIT on simulated missions.")
    parser.add_argument("--config", action="append", default=None,
                        help="config file to evaluate; repeat to compare (default: orbit.toml)")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--crew", type=int, default=4)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--min-level", default="yellow", choices=[lvl.value for lvl in AlertLevel])
    parser.add_argument("--out", default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    report = run_all(args.config or ["orbit.toml"], args.seeds, args.days, args.crew,
                     args.min_level)
    print()
    print(table(report))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport written to {out}")
    return report


if __name__ == "__main__":
    main()
