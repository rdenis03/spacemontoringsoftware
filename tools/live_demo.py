"""Live body demo (task B20): ORBIT reacting to a real person's numbers, on stage.

A teammate wears a watch (or just reads out their heart rate). Two problems:

1. ORBIT needs a personal "normal" before it can spot a change. ``seed``
   builds the wearer as a crew member with 14 nights of readings around their
   real resting values (small seeded noise, ``source="manual"``), ending with
   last night, and saves them in the database from ``orbit.toml``.
2. A new reading must be assessed right away, not at tomorrow's 10:00 UTC run.
   ``push`` posts the readings stamped *now* to ``POST /api/observations``, then
   a check-in stamped now to ``POST /api/crew/{id}/checkin``, which makes the API
   assess at that moment. It prints the new level and the top 3 reasons.

Stage script (values are illustrative, not medical thresholds)::

    # 0. Before the pitch, in one terminal: start the API (and the dashboard).
    python -m orbit serve

    # 1. Before the pitch, in a second terminal: the wearer's real resting values.
    python tools/live_demo.py seed --id AST-03 --callsign Live --resting-hr 62 \\
        --skin-temp 34.1 --hrv 55 --resp-rate 14 --spo2 97 --sleep 7
    #    -> AST-03 "Live" appears on the dashboard, GREEN.

    # 2. On stage, after some jumping jacks (or a hot drink): the watch's numbers,
    #    plus how the wearer feels. Heart rate and temperature alone add only 15
    #    points with the starter scorer (yellow needs 25), so report a symptom too.
    python tools/live_demo.py push --id AST-03 --resting-hr 95 --skin-temp 34.8 --fever 2
    #    -> YELLOW, reasons: fever or chills, skin temperature, resting heart rate.

    # 3. Back to normal (optional): push the resting values again. Every push sends
    #    all five symptoms (0 unless given), so this also clears the fever.
    python tools/live_demo.py push --id AST-03 --resting-hr 63 --skin-temp 34.1
    #    -> GREEN.

With a real watch export instead of typed values (needs B11's ``wearable_csv``
source): ``python tools/live_demo.py seed --id AST-03 --callsign Live --from-csv export.csv``.

Options:

    seed  --id, --callsign, --resting-hr, --skin-temp, --hrv, --resp-rate, --spo2,
          --sleep (hours), --nights (14), --seed (1), --from-csv PATH, --config (orbit.toml)
    push  --id, any of --resting-hr --skin-temp --hrv --resp-rate --spo2 --sleep,
          --mood (3), --stress (3), symptoms 0-3: --fever --fatigue --sore-throat
          --headache --aches, --api (http://localhost:8000)

Seeding again the same day replaces the readings (IDs are
``f"{id}-{signal}-{yyyymmdd}"``); seeding re-saves the crew member, which also
resets their consent to the defaults. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from orbit.core import Pipeline, SourceBatch, available, create, load_settings
from orbit.modules.simulator import DIGITS, HRV_NOISE_FRACTION, NOISE_SD
from orbit.schema import CrewMember, Observation, SignalType, get_spec

S = SignalType
NIGHT_HOUR = 6  # nightly summaries are stamped 06:00 UTC, as in the fixtures
HRV_NOISE = sum(HRV_NOISE_FRACTION) / 2  # fraction of the normal

# Command-line flag -> signal, for the values a watch (or a person) can give.
VITAL_FLAGS: dict[str, SignalType] = {
    "resting_hr": S.RESTING_HR,
    "skin_temp": S.SKIN_TEMP,
    "hrv": S.HRV_RMSSD,
    "resp_rate": S.RESP_RATE,
    "spo2": S.SPO2,
    "sleep": S.SLEEP_DURATION,
}
SYMPTOM_FLAGS: dict[str, SignalType] = {
    "fever": S.SYMPTOM_FEVER_CHILLS,
    "fatigue": S.SYMPTOM_FATIGUE,
    "sore_throat": S.SYMPTOM_SORE_THROAT,
    "headache": S.SYMPTOM_HEADACHE,
    "aches": S.SYMPTOM_MUSCLE_ACHES,
}
DEFAULT_NORMALS: dict[SignalType, float] = {
    S.RESTING_HR: 62, S.SKIN_TEMP: 34.1, S.HRV_RMSSD: 55, S.RESP_RATE: 14,
    S.SPO2: 97, S.SLEEP_DURATION: 7.0,
}


def _noise_sd(signal: SignalType, normal: float) -> float:
    return HRV_NOISE * normal if signal is S.HRV_RMSSD else NOISE_SD[signal]


def _round(signal: SignalType, value: float) -> float:
    spec = get_spec(signal)
    return round(min(max(value, spec.plausible_min), spec.plausible_max), DIGITS[signal])


def night_stamps(now: datetime, nights: int) -> list[datetime]:
    """The ``nights`` most recent 06:00 UTC stamps not after ``now``, oldest first."""
    now = now.astimezone(timezone.utc)
    last = now.replace(hour=NIGHT_HOUR, minute=0, second=0, microsecond=0)
    if last > now:
        last -= timedelta(days=1)
    return [last - timedelta(days=n) for n in range(nights - 1, -1, -1)]


def build_seed(
    astronaut_id: str,
    callsign: str,
    normals: Mapping[SignalType, float],
    now: datetime,
    nights: int = 14,
    seed: int = 1,
) -> SourceBatch:
    """A crew member plus ``nights`` nights of normal readings, ending last night."""
    stamps = night_stamps(now, nights)
    member = CrewMember(astronaut_id=astronaut_id, callsign=callsign, role="Live demo",
                        mission_start=stamps[0].replace(hour=0))
    rng = random.Random(f"{astronaut_id}-{seed}")
    observations = []
    for stamp in stamps:
        for signal, normal in normals.items():
            observations.append(Observation(
                observation_id=f"{astronaut_id}-{signal.value}-{stamp:%Y%m%d}",
                astronaut_id=astronaut_id, timestamp=stamp, signal=signal,
                value=_round(signal, normal + rng.gauss(0, _noise_sd(signal, normal))),
                source="manual", note="live demo seed",
            ))
    return SourceBatch("live_demo", crew=(member,), observations=tuple(observations))


def build_push(astronaut_id: str, readings: Mapping[SignalType, float],
               now: datetime) -> list[dict]:
    """Records for ``POST /api/observations``: the readings, stamped ``now``."""
    stamp = now.astimezone(timezone.utc)
    return [
        {"observation_id": f"{astronaut_id}-{signal.value}-live-{stamp:%Y%m%dT%H%M%S}",
         "astronaut_id": astronaut_id, "timestamp": stamp.isoformat(),
         "signal": signal.value, "value": value, "source": "manual", "note": "live demo"}
        for signal, value in readings.items()
    ]


def build_checkin(now: datetime, mood: int = 3, stress: int = 3,
                  symptoms: Mapping[SignalType, int] | None = None) -> dict:
    """Body for ``POST /api/crew/{id}/checkin``, stamped ``now``: the API assesses then."""
    return {"timestamp": now.astimezone(timezone.utc).isoformat(), "mood": mood,
            "stress": stress, "symptoms": {s.value: v for s, v in (symptoms or {}).items()}}


def describe(result: Mapping) -> str:
    """'YELLOW (27/100)' and the top 3 reasons, from a DayResult as JSON."""
    assessment = result.get("assessment") or {}
    lines = [f"{result.get('astronaut_id')}: {str(assessment.get('level', '?')).upper()} "
             f"({assessment.get('score', '?')}/100)"]
    for reason in assessment.get("contributors", [])[:3]:
        lines.append(f"  +{reason['points']:<5} {reason['label']}")
    return "\n".join(lines)


# ---- command line ------------------------------------------------------------


def _post(url: str, body) -> dict | list:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{url}: HTTP {exc.code}: {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"{url}: cannot connect ({exc.reason}). Is `python -m orbit serve` running?")


def cmd_seed(args) -> None:
    now = datetime.now(timezone.utc)
    if args.from_csv and "wearable_csv" not in available("source"):
        raise SystemExit("--from-csv needs the wearable_csv source (task B11), "
                         "which is not built yet. Type the values instead.")
    pipeline = Pipeline.from_settings(load_settings(args.config))
    if args.from_csv:
        member = CrewMember(astronaut_id=args.id, callsign=args.callsign, role="Live demo",
                            mission_start=now - timedelta(days=args.nights))
        pipeline.ingest(SourceBatch("live_demo", crew=(member,)))
        report = pipeline.ingest(create("source", "wearable_csv", path=args.from_csv,
                                        astronaut_id=args.id))
    else:
        normals = {signal: getattr(args, flag) for flag, signal in VITAL_FLAGS.items()}
        report = pipeline.ingest(build_seed(args.id, args.callsign, normals, now,
                                            args.nights, args.seed))
    print(report.summary() if hasattr(report, "summary") else report)
    print(describe(json.loads(pipeline.assess(args.id, now).model_dump_json())))


def cmd_push(args) -> None:
    now = datetime.now(timezone.utc)
    readings = {signal: getattr(args, flag) for flag, signal in VITAL_FLAGS.items()
                if getattr(args, flag) is not None}
    # Always send all five (0 = not now), so a later push clears an earlier fever.
    symptoms = {signal: getattr(args, flag) for flag, signal in SYMPTOM_FLAGS.items()}
    api = args.api.rstrip("/")
    if readings:
        sent = _post(f"{api}/api/observations", build_push(args.id, readings, now))
        if sent.get("rejected"):
            raise SystemExit(f"readings rejected: {sent['errors']}")
    result = _post(f"{api}/api/crew/{args.id}/checkin",
                   build_checkin(now, args.mood, args.stress, symptoms))
    print(describe(result))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ORBIT live body demo")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="create the wearer and their normal nights")
    seed.add_argument("--id", required=True)
    seed.add_argument("--callsign", default="Live")
    for flag, signal in VITAL_FLAGS.items():
        seed.add_argument(f"--{flag.replace('_', '-')}", dest=flag, type=float,
                          default=DEFAULT_NORMALS[signal])
    seed.add_argument("--nights", type=int, default=14)
    seed.add_argument("--seed", type=int, default=1)
    seed.add_argument("--from-csv", default=None)
    seed.add_argument("--config", default=None, help="default: orbit.toml")
    seed.set_defaults(run=cmd_seed)

    push = commands.add_parser("push", help="send readings now and print the new status")
    push.add_argument("--id", required=True)
    for flag in VITAL_FLAGS:
        push.add_argument(f"--{flag.replace('_', '-')}", dest=flag, type=float, default=None)
    push.add_argument("--mood", type=int, default=3)
    push.add_argument("--stress", type=int, default=3)
    for flag in SYMPTOM_FLAGS:
        push.add_argument(f"--{flag.replace('_', '-')}", dest=flag, type=int, default=0,
                          choices=range(4))
    push.add_argument("--api", default="http://localhost:8000")
    push.set_defaults(run=cmd_push)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    sys.exit(main())
