"""Mission simulator (slot ``source``, registered as ``simulator``): M2.

Generates a long mission for a crew, every daily record for every astronaut,
so the analytics can be tested on months of data instead of three weeks of
fixtures. Version 1 (B02) simulates a **healthy** crew only; B03 adds illness
episodes and labels, B04 adds look-alike episodes and sensor faults.

Why: ORBIT compares each astronaut with their own normal, so the simulator
gives each astronaut a personal normal and realistic night-to-night noise.
Values are illustrative, not clinical.

Options (all defaulted; the defaults are small so the contract test is fast):

    days           60                       mission length in days (day 1 = mission_start)
    crew_size      4                        astronauts AST-01 ... AST-NN
    seed           1                        all randomness comes from this
    mission_start  "2027-01-04T00:00:00Z"   start of mission day 1, UTC
    scenarios      "random"                 B03: "random" or a list of scenario tables (ignored now)
    illness_rate   1.0                      B03: episodes per astronaut per 90 days (ignored now)
    confounders    True                     B04: add look-alike episodes (ignored now)
    faults         True                     B04: add sensor faults and missing nights (ignored now)
    labels_path    None                     B03: write labels as JSONL here (ignored now)

Daily records per astronaut (times in UTC):

    06:00  5 vitals + 2 sleep signals, source "wearable", device "wrist-<id>"
    07:00  8 symptoms (0 when healthy), mood, stress, source "checkin"
    09:00  saliva EBV/VZV/HSV-1 DNA, weekly (mission days 1, 8, 15, ...), source "lab"
    23:59  radiation_dose_daily, workload, source "environment"

IDs are ``f"{astronaut}-{signal}-{yyyymmdd}"``; every record has ``simulated=True``.

Physiology: each astronaut's personal normal is drawn once from the ranges in
``NORMAL_RANGES``. Nightly signals get AR(1) noise (``PHI`` = 0.3) with the
standard deviations in ``NOISE_SD``, so nights are mildly correlated. Values are
clamped to each signal's plausible range from ``get_spec``.

Randomness: ``random.Random(seed)`` draws the crew's normals in ``__init__``
and a second seed for the noise, so ``read()`` gives byte-identical output
every time it is called. No global random state, no clock.

Hook for B03 and B04 (effects)
------------------------------
``self.normals[astronaut_id][signal]`` holds each astronaut's personal normal
(nightly signals only), available right after ``__init__``.

``self.effects`` is a list of functions with the shape::

    Effect = Callable[[str, int], Mapping[SignalType, float]]
    effect(astronaut_id, mission_day) -> {signal: offset, ...}

For every astronaut and day, ``read()`` calls every effect and adds the
offsets of each signal together, on top of the healthy value (normal + noise
for nightly signals, 0 for symptoms, the healthy draw for mood, stress, lab
and context). Then it rounds and clamps. Return ``{}`` on days without an
effect. For a relative change, use the normal, for example
``-0.2 * sim.normals["AST-01"][SignalType.HRV_RMSSD]`` for HRV 20 % down.
Symptoms and mood/stress are rounded to whole numbers and clamped to their
scale. Lab offsets apply only on lab days (mission days 1, 8, 15, ...).
Extra lab tests on other days, events, labels and faults are not hooked yet:
B03/B04 add them in ``read()``, next to the day loop in ``_astronaut_records``.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone

from orbit.core.interfaces import SourceBatch
from orbit.core.registry import register
from orbit.schema import CrewMember, Observation, ScenarioLabel, SignalType, get_spec

S = SignalType
Effect = Callable[[str, int], Mapping[SignalType, float]]

# Personal normal for each nightly signal: drawn once per astronaut, uniform.
NORMAL_RANGES: dict[SignalType, tuple[float, float]] = {
    S.SKIN_TEMP: (33.5, 35.0),
    S.RESTING_HR: (48, 65),
    S.HRV_RMSSD: (30, 90),
    S.RESP_RATE: (13, 16),
    S.SPO2: (95.5, 98),
    S.SLEEP_DURATION: (6.0, 7.5),
    S.SLEEP_EFFICIENCY: (84, 93),
}
# Night-to-night noise (standard deviation). HRV is relative: 4-5 % of the normal.
NOISE_SD: dict[SignalType, float] = {
    S.SKIN_TEMP: 0.08,
    S.RESTING_HR: 1.0,
    S.RESP_RATE: 0.2,
    S.SPO2: 0.3,
    S.SLEEP_DURATION: 0.3,
    S.SLEEP_EFFICIENCY: 1.8,
}
HRV_NOISE_FRACTION = (0.04, 0.05)
PHI = 0.3  # AR(1) coefficient: how much of last night's noise carries over

# Decimal places for each signal, as in examples/make_examples.py.
DIGITS: dict[SignalType, int] = {
    S.SKIN_TEMP: 2, S.RESTING_HR: 0, S.HRV_RMSSD: 0, S.RESP_RATE: 1, S.SPO2: 1,
    S.SLEEP_DURATION: 1, S.SLEEP_EFFICIENCY: 0,
    S.RADIATION_DOSE_DAILY: 3, S.WORKLOAD: 1,
    S.SALIVA_EBV_DNA: 0, S.SALIVA_VZV_DNA: 0, S.SALIVA_HSV1_DNA: 0,
}
NIGHTLY = tuple(NORMAL_RANGES)
SYMPTOMS = (
    S.SYMPTOM_FATIGUE, S.SYMPTOM_FEVER_CHILLS, S.SYMPTOM_SORE_THROAT,
    S.SYMPTOM_SWOLLEN_GLANDS, S.SYMPTOM_MOUTH_SORES, S.SYMPTOM_RASH_TINGLING,
    S.SYMPTOM_HEADACHE, S.SYMPTOM_MUSCLE_ACHES,
)
SALIVA = (S.SALIVA_EBV_DNA, S.SALIVA_VZV_DNA, S.SALIVA_HSV1_DNA)
HEALTHY_SALIVA_MAX = 99  # copies/mL; healthy shedding stays below 100
LAB_EVERY_DAYS = 7

WAKE_UP = timedelta(hours=6)
CHECKIN = timedelta(hours=7)
LAB = timedelta(hours=9)
END_OF_DAY = timedelta(hours=23, minutes=59)

CALLSIGNS = ("Vega", "Altair", "Deneb", "Rigel", "Lyra", "Sirius", "Capella", "Antares")
ROLES = ("Commander", "Flight engineer", "Mission specialist", "Science officer")


def _parse_start(value: str | datetime) -> datetime:
    start = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError(f"mission_start needs a timezone, got {value!r}")
    return start.astimezone(timezone.utc)


def _clamp(signal: SignalType, value: float) -> float:
    spec = get_spec(signal)
    return min(max(value, spec.plausible_min), spec.plausible_max)


@register("source", "simulator")
class MissionSimulator:
    def __init__(
        self,
        days: int = 60,
        crew_size: int = 4,
        seed: int = 1,
        mission_start: str = "2027-01-04T00:00:00Z",
        scenarios: str | list = "random",
        illness_rate: float = 1.0,
        confounders: bool = True,
        faults: bool = True,
        labels_path: str | None = None,
    ):
        if days < 1:
            raise ValueError("days must be at least 1")
        if not 1 <= crew_size <= 99:
            raise ValueError("crew_size must be between 1 and 99")
        self.days = days
        self.crew_size = crew_size
        self.seed = seed
        self.mission_start = _parse_start(mission_start)
        # Stored for B03/B04; not used yet.
        self.scenarios = scenarios
        self.illness_rate = illness_rate
        self.confounders = confounders
        self.faults = faults
        self.labels_path = labels_path

        self.crew = tuple(
            CrewMember(
                astronaut_id=f"AST-{n:02d}",
                callsign=CALLSIGNS[n - 1] if n <= len(CALLSIGNS) else f"Crew {n}",
                role=ROLES[(n - 1) % len(ROLES)],
                mission_start=self.mission_start,
            )
            for n in range(1, crew_size + 1)
        )

        rng = random.Random(seed)
        self.normals: dict[str, dict[SignalType, float]] = {}
        self.noise_sd: dict[str, dict[SignalType, float]] = {}
        for member in self.crew:
            normals = {s: rng.uniform(lo, hi) for s, (lo, hi) in NORMAL_RANGES.items()}
            sd = dict(NOISE_SD)
            sd[S.HRV_RMSSD] = rng.uniform(*HRV_NOISE_FRACTION) * normals[S.HRV_RMSSD]
            self.normals[member.astronaut_id] = normals
            self.noise_sd[member.astronaut_id] = sd
        self._noise_seed = rng.getrandbits(64)
        self.effects: list[Effect] = []

    # ---- public ---------------------------------------------------------

    def read(self) -> SourceBatch:
        rng = random.Random(self._noise_seed)
        observations: list[Observation] = []
        for member in self.crew:
            observations.extend(self._astronaut_records(member.astronaut_id, rng))
        return SourceBatch(
            source_name="simulator",
            crew=self.crew,
            observations=tuple(observations),
            events=(),
        )

    def labels(self) -> list[ScenarioLabel]:
        """Ground truth for M9. Empty for a healthy crew (B03 fills it)."""
        return []

    def day_start(self, mission_day: int) -> datetime:
        return self.mission_start + timedelta(days=mission_day - 1)

    # ---- generation -----------------------------------------------------

    def _offsets(self, astronaut: str, mission_day: int) -> dict[SignalType, float]:
        total: dict[SignalType, float] = {}
        for effect in self.effects:
            for signal, offset in effect(astronaut, mission_day).items():
                signal = SignalType(signal)
                total[signal] = total.get(signal, 0.0) + offset
        return total

    def _astronaut_records(self, astronaut: str, rng: random.Random) -> list[Observation]:
        normals = self.normals[astronaut]
        sd = self.noise_sd[astronaut]
        noise = {s: rng.gauss(0, sd[s]) for s in NIGHTLY}  # stationary start
        innovation = (1 - PHI**2) ** 0.5  # keeps the AR(1) noise at the stated SD
        device = f"wrist-{astronaut.lower()}"
        records: list[Observation] = []

        for mission_day in range(1, self.days + 1):
            date = self.day_start(mission_day)
            stamp = date.strftime("%Y%m%d")
            offsets = self._offsets(astronaut, mission_day)

            def add(signal: SignalType, value: float, source: str, when: datetime, **extra):
                records.append(Observation(
                    observation_id=f"{astronaut}-{signal.value}-{stamp}",
                    astronaut_id=astronaut, timestamp=when, signal=signal,
                    value=value, source=source, simulated=True, **extra,
                ))

            def continuous(signal: SignalType, healthy: float) -> float:
                value = _clamp(signal, healthy + offsets.get(signal, 0.0))
                return round(value, DIGITS[signal])

            def ordinal(signal: SignalType, healthy: float) -> int:
                return int(_clamp(signal, round(healthy + offsets.get(signal, 0.0))))

            # 06:00 nightly vitals and sleep
            for signal in NIGHTLY:
                noise[signal] = PHI * noise[signal] + innovation * rng.gauss(0, sd[signal])
                add(signal, continuous(signal, normals[signal] + noise[signal]),
                    "wearable", date + WAKE_UP, device_id=device)

            # 07:00 check-in
            for signal in SYMPTOMS:
                add(signal, ordinal(signal, 0), "checkin", date + CHECKIN)
            add(S.MOOD, ordinal(S.MOOD, rng.choice((3, 4, 4, 4, 5))), "checkin", date + CHECKIN)
            add(S.STRESS, ordinal(S.STRESS, rng.choice((1, 2, 2, 3))), "checkin", date + CHECKIN)

            # 09:00 weekly saliva test
            if (mission_day - 1) % LAB_EVERY_DAYS == 0:
                for signal in SALIVA:
                    healthy = 0 if rng.random() < 0.4 else rng.uniform(5, HEALTHY_SALIVA_MAX)
                    add(signal, continuous(signal, healthy), "lab", date + LAB,
                        device_id="qpcr-01")

            # 23:59 environment
            add(S.RADIATION_DOSE_DAILY,
                continuous(S.RADIATION_DOSE_DAILY, 0.30 + rng.gauss(0, 0.02)),
                "environment", date + END_OF_DAY)
            add(S.WORKLOAD, continuous(S.WORKLOAD, rng.choice((8.5, 9.0, 9.5, 10.0))),
                "environment", date + END_OF_DAY)

        return records
