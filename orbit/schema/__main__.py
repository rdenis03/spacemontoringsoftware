"""Command line tools for the ORBIT schema.

    python -m orbit.schema validate data.jsonl            check a file
    python -m orbit.schema validate events.jsonl --model context_event
    python -m orbit.schema signals                        list every signal
    python -m orbit.schema export schemas/                write JSON Schemas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export import EXPORTED_MODELS, export_all
from .io import parse_csv, parse_jsonl
from .signals import SIGNALS


def _validate(args: argparse.Namespace) -> int:
    model = EXPORTED_MODELS[args.model]
    path = Path(args.file)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 2
    reader = parse_csv if path.suffix.lower() == ".csv" else parse_jsonl
    result = reader(path, model)
    print(f"{path}: {result.summary()}")
    for error in result.errors[: args.max_errors]:
        print(f"  {error}")
    hidden = len(result.errors) - args.max_errors
    if hidden > 0:
        print(f"  ... and {hidden} more (use --max-errors to show them)")
    return 0 if result.ok else 1


def _signals(_: argparse.Namespace) -> int:
    print(f"{'signal':<24} {'category':<10} {'unit':<13} {'range':<14} concern")
    for spec in SIGNALS.values():
        span = f"{spec.plausible_min:g}–{spec.plausible_max:g}"
        print(
            f"{spec.signal.value:<24} {spec.category.value:<10} "
            f"{spec.unit:<13} {span:<14} {spec.concern.value}"
        )
    return 0


def _export(args: argparse.Namespace) -> int:
    for path in export_all(args.out_dir):
        print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orbit.schema", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="check a .jsonl or .csv file")
    validate.add_argument("file")
    validate.add_argument("--model", choices=sorted(EXPORTED_MODELS), default="observation")
    validate.add_argument("--max-errors", type=int, default=20)
    validate.set_defaults(func=_validate)

    signals = commands.add_parser("signals", help="list every signal in the registry")
    signals.set_defaults(func=_signals)

    export = commands.add_parser("export", help="write JSON Schemas and signals.json")
    export.add_argument("out_dir", nargs="?", default="schemas")
    export.set_defaults(func=_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
