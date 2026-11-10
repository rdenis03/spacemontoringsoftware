"""ORBIT command line.

    python -m orbit demo                  load example data, run, show results
    python -m orbit serve                 start the API for the dashboard
    python -m orbit ingest                read the data sources in orbit.toml
    python -m orbit run [--start D] [--end D] [--astronaut ID]
    python -m orbit status AST-01         latest status for one astronaut
    python -m orbit modules               list module slots and implementations
    python -m orbit reset                 delete the database

All commands accept --config path/to/orbit.toml.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from orbit.core import Pipeline, Settings, Store, available, create, load_settings
from orbit.core.interfaces import SLOTS, DayResult

LEVEL_MARK = {"green": "G", "yellow": "Y", "orange": "O", "red": "R"}


def _ingest_sources(pipeline: Pipeline, settings: Settings) -> None:
    if not settings.sources:
        print("no [[sources]] in the config; nothing to ingest")
    for choice in settings.sources:
        report = pipeline.ingest(create("source", choice.use, **choice.options))
        print(report.summary())
        for error in report.errors[:5]:
            print(f"  {error}")


def _print_status(pipeline: Pipeline, result: DayResult) -> None:
    member = pipeline.store.member(result.astronaut_id)
    a = result.assessment
    print(f"\n{member.astronaut_id} {member.callsign} · mission day {result.mission_day} · "
          f"{result.as_of:%Y-%m-%d %H:%M} UTC")
    if a is None:
        print("  no score: " + "; ".join(result.errors))
        return
    print(f"  Status: {a.level.value.upper()} ({a.score:g}/100)")
    if a.contributors:
        print("  Why:")
        for reason in a.contributors:
            print(f"    +{reason.points:<5g} {reason.label}")
    if result.actions:
        print("  What to do:")
        for card in result.actions:
            who = "" if card.escalate_to.value == "self" else \
                f"  -> {card.escalate_to.value.replace('_', ' ')}"
            print(f"    [{card.title}]{who}")
            for step in card.steps:
                print(f"      - {step}")
    if result.errors:
        print("  Module errors: " + "; ".join(result.errors))


def cmd_modules(settings: Settings, args: argparse.Namespace) -> int:
    for slot in SLOTS:
        active = settings.modules[slot].use if slot in settings.modules else None
        names = [f"{n} (active)" if n == active else n for n in available(slot)]
        if slot == "source":
            used = {c.use for c in settings.sources}
            names = [f"{n} (used)" if n in used else n for n in available(slot)]
        print(f"{slot:<9} {', '.join(names)}")
    return 0


def cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    _ingest_sources(Pipeline.from_settings(settings), settings)
    return 0


EMPTY_HINT = ("the database is empty: run `python -m orbit ingest` first "
              "(or `python -m orbit demo` to try everything in memory)")


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    pipeline = Pipeline.from_settings(settings)
    if not pipeline.store.crew():
        print(EMPTY_HINT)
        return 1
    report = pipeline.run(args.start, args.end, args.astronaut)
    print(report.summary())
    return 0


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    pipeline = Pipeline.from_settings(settings)
    if not pipeline.store.crew():
        print(EMPTY_HINT)
        return 1
    try:
        result = pipeline.status(args.astronaut_id)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 2
    if result is None:
        print("no assessment yet; run `python -m orbit run` first")
        return 1
    _print_status(pipeline, result)
    return 0


def cmd_demo(settings: Settings, args: argparse.Namespace) -> int:
    """Everything in one go, in memory, so it never touches the real database."""
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    print(f"{settings.mission_name}: modules "
          + ", ".join(f"{slot}={name}" for slot, name in pipeline.module_names.items()))
    _ingest_sources(pipeline, settings)
    report = pipeline.run()
    print(report.summary())

    print("\nDaily status, last 10 days (G green, Y yellow, O orange, R red):")
    for member in pipeline.store.crew():
        days = [r for r in report.results if r.astronaut_id == member.astronaut_id][-10:]
        marks = " ".join(LEVEL_MARK.get(r.assessment.level.value, "?") if r.assessment else "-"
                         for r in days)
        if days:
            print(f"  {member.astronaut_id} days {days[0].mission_day}-{days[-1].mission_day}: {marks}")
    for member in pipeline.store.crew():
        result = pipeline.status(member.astronaut_id)
        if result is not None:
            _print_status(pipeline, result)
    print("\nNext: `python -m orbit serve` and open http://localhost:8000/docs")
    return 0


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    import uvicorn

    from orbit.api import create_app

    pipeline = Pipeline.from_settings(settings)
    if pipeline.store.counts()["observations"] == 0 and settings.sources:
        print("empty database: loading the configured sources and assessing them first")
        _ingest_sources(pipeline, settings)
        print(pipeline.run().summary())
    app = create_app(pipeline, mission_name=settings.mission_name,
                     comms_delay_minutes=settings.comms_delay_minutes,
                     auto_send_level=settings.comms_auto_send_level)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_reset(settings: Settings, args: argparse.Namespace) -> int:
    if settings.database == ":memory:":
        print("database is in memory; nothing to delete")
        return 0
    path = Path(settings.database)
    if path.exists():
        path.unlink()
        print(f"deleted {path}")
    else:
        print(f"{path} does not exist")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orbit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="path to orbit.toml")
    parser.add_argument("--database", help="override storage.database from the config")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("demo", help="load example data, run, show results").set_defaults(func=cmd_demo)

    serve = commands.add_parser("serve", help="start the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    commands.add_parser("ingest", help="read the configured data sources").set_defaults(func=cmd_ingest)

    run = commands.add_parser("run", help="run daily assessments")
    run.add_argument("--start", type=date.fromisoformat, help="first day, YYYY-MM-DD")
    run.add_argument("--end", type=date.fromisoformat, help="last day, YYYY-MM-DD")
    run.add_argument("--astronaut", action="append", help="limit to this astronaut (repeatable)")
    run.set_defaults(func=cmd_run)

    status = commands.add_parser("status", help="latest status for one astronaut")
    status.add_argument("astronaut_id")
    status.set_defaults(func=cmd_status)

    commands.add_parser("modules", help="list module slots").set_defaults(func=cmd_modules)
    commands.add_parser("reset", help="delete the database").set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    if args.database:
        settings = replace(settings, database=args.database)
    return args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())
