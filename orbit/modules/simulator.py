"""Mission simulator (slot ``source``, registered as ``simulator``): M2.

Generates a long mission for a crew, every daily record for every astronaut,
so the analytics can be tested on months of data instead of three weeks of
fixtures. Version 1 (B02) simulated a **healthy** crew; version 2 (B03) added
illness episodes with ground-truth labels; version 3 (B04) adds look-alikes
(things that look like illness but are not) and sensor faults.

Why: ORBIT compares each astronaut with their own normal, so the simulator
gives each astronaut a personal normal and realistic night-to-night noise,
then injects illnesses whose body changes start before the symptoms do. That
gap is the early warning ORBIT must find. Values are illustrative, not clinical.

Options (all defaulted; the defaults are small so the contract test is fast):

    days           60                       mission length in days (day 1 = mission_start)
    crew_size      4                        astronauts AST-01 ... AST-NN
    seed           1                        all randomness comes from this
    mission_start  "2027-01-04T00:00:00Z"   start of mission day 1, UTC
    scenarios      "random"                 "random", or a list of scenario tables (below);
                                            [] gives a healthy crew
    illness_rate   1.0                      for "random": episodes per astronaut per 90 days
    confounders    True                     for "random": add spacewalks, sleep shifts, solar events
    faults         True                     for "random": add sensor faults and missing nights
    labels_path    None                     if set, read() also writes the labels as JSONL here

In list mode (``scenarios`` is a list) the run contains **exactly** what is
listed: no random illnesses, look-alikes or faults are added, whatever
``illness_rate``, ``confounders`` and ``faults`` say.

Daily records per astronaut (times in UTC):

    06:00  5 vitals + 2 sleep signals, source "wearable", device "wrist-<id>"
    07:00  8 symptoms (0 when healthy), mood, stress, source "checkin"
    09:00  saliva EBV/VZV/HSV-1 DNA, weekly (mission days 1, 8, 15, ...), source "lab";
           plus extra tests during an illness (see below)
    23:59  radiation_dose_daily, workload, source "environment"

IDs are ``f"{astronaut}-{signal}-{yyyymmdd}"``; extra lab tests add the hour,
``f"{astronaut}-{signal}-{yyyymmdd}-09"``. Every record has ``simulated=True``.

Physiology: each astronaut's personal normal is drawn once from the ranges in
``NORMAL_RANGES``. Nightly signals get AR(1) noise (``PHI`` = 0.3) with the
standard deviations in ``NOISE_SD``, so nights are mildly correlated. Values are
clamped to each signal's plausible range from ``get_spec``.

Illness episodes (B03)
----------------------
"Day 0" is symptom onset. ``lead_days`` (1 to 3) is how long the body changes
before the symptoms; ``recovery_days`` (5 to 10) is how long it takes to get
back to normal after day 0.

* ``viral_reactivation`` (``virus`` = ``ebv``, ``vzv`` or ``hsv1``; ``lead_days``
  default 2): from day -lead_days, skin temp +0.2 -> +0.6 °C, resting HR +2 -> +7,
  HRV -10 -> -30 %, resp rate +0.4 -> +1.2, sleep -0.3 -> -1.0 h, peaking on
  day 0. That virus's saliva DNA rises from day -3. From day 0, fatigue 1-2 plus
  the virus's own sign (VZV rash/tingling, HSV-1 mouth sores, EBV swollen glands
  and sore throat).
* ``respiratory_infection`` (``lead_days`` default 1): skin temp +0.8 °C, resp
  rate +2, resting HR +8 at the peak (40 % of that on the first day), fever/chills
  and sore throat 1-3 from day 0, CRP rises.

Everything fades back to normal over ``recovery_days`` after day 0.

**Extra lab tests start on day 0**, never before, because nobody gets an extra
test before feeling sick: one 09:00 test per day of the episode's virus DNA (on
days without the weekly test) or of CRP, from day 0 to the end of recovery.
Before day 0 the DNA rise is only visible when a weekly test falls in those
days. Extra tests only happen during illness, so the *presence* of a test is a
give-away: a learned model must not use it (B09).

Look-alikes and faults (B04)
---------------------------
They should **not** alert. Each one is a ``LookAlike`` in ``self.lookalikes``
(also callable as an effect) and gives ``ScenarioLabel``s with
``should_alert=False`` and no ``symptom_onset``.

* ``eva_exertion`` (confounder): an ``EVA`` event on day d, 13:00-19:00, for
  that astronaut; workload +3 h that day (about 12 h); the next night HRV -15 %
  and resting HR +3; no symptoms. The event starts after the 10:00 assessment,
  so it counts from the next day.
* ``sleep_shift`` (confounder): a ``SLEEP_SHIFT`` event from 00:00 of day d;
  sleep -1.5 h for ``nights`` = 2-3 nights.
* ``solar_particle_event`` (confounder): a crew-wide event (``astronaut_id``
  None) from 03:00 of day d; radiation dose x2-5 for ``nights`` = 1-2 days; no
  body change. Severity high from x4, else moderate. One label per astronaut.
* ``sensor_fault`` (fault): ``nights`` = 1-3 nightly readings in a row of one
  wearable signal get an absurd value (``FAULT_VALUES``), stored with
  ``quality="bad"`` and a note. The rest of that night is normal.
* ``missing_data`` (fault): no wearable records for ``nights`` = 1-2 nights.

Event IDs are ``f"{astronaut or 'CREW'}-{event_type}-{yyyymmdd}"``.

``scenarios`` as a list of tables, for example in TOML::

    scenarios = [
      {type = "viral_reactivation", astronaut = "AST-02", virus = "vzv", symptom_day = 90},
      {type = "respiratory_infection", astronaut = "AST-01", symptom_day = 40, recovery_days = 6},
      {type = "eva_exertion", astronaut = "AST-01", day = 50},
      {type = "solar_particle_event", day = 60, nights = 2},
    ]

Illness keys: ``type``, ``astronaut``, ``symptom_day`` (required), ``virus``
(required for viral), ``lead_days``, ``recovery_days`` (optional).
Look-alike keys: ``type``, ``day`` (required), ``astronaut`` (required, except
for ``solar_particle_event``, which is crew-wide and must not have one),
``nights`` (optional, in the ranges above; not for ``eva_exertion``).

``"random"`` places about ``illness_rate * days / 90`` illness episodes per
astronaut (Poisson), 70 % viral (any virus) and 30 % respiratory, never
starting before day 22 (so a baseline exists), always ending inside the
mission, at least ``EPISODE_GAP_DAYS`` apart for one astronaut. With
``confounders`` and ``faults`` it adds look-alikes at the rates in
``LOOKALIKE_RATES`` (per astronaut per 90 days) and ``SOLAR_EVENTS_PER_60_DAYS``
(crew), also from day 22, inside the mission, never overlapping another
look-alike of the same astronaut. Look-alikes may overlap an illness.

Each illness gives one ``ScenarioLabel``: ``onset`` = 00:00 of the first day
the vitals change, ``symptom_onset`` = day 0 at 07:00, ``resolved`` = 00:00 of
day ``recovery_days`` (back to normal), ``should_alert=True``. A look-alike
label runs from 00:00 of day d to 00:00 of the day after its last effect.

Default 180-day, 4-person run (seed 1), labels per type, for sanity checks
(B06, B09)::

    viral_reactivation       6   should alert
    respiratory_infection    2   should alert
    eva_exertion            15
    sleep_shift             10
    solar_particle_event    12   (3 crew-wide events x 4 astronauts)
    sensor_fault            16   (31 readings stored with quality "bad")
    missing_data            10
    total                   71   28 events, 13 928 observations

Other seeds give similar numbers (Poisson draws), not the same ones.

Randomness: ``random.Random(seed)`` draws the crew's normals in ``__init__``,
then a seed for the noise, a seed for the illnesses and a seed for the
look-alikes, so ``read()`` gives byte-identical output every time it is
called. Adding episodes never changes the healthy noise: a missing night or a
faulty reading still uses up its noise draw. ``confounders=False,
faults=False`` reproduces B03's output exactly. No global random state, no clock.

Hook (effects)
--------------
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
scale. Lab offsets apply only on weekly lab days (mission days 1, 8, 15, ...).

Every illness ``Episode`` in ``self.episodes`` and every ``LookAlike`` in
``self.lookalikes`` is also in ``self.effects`` (both are callable as
effects). Extra lab tests come from ``Episode.extra_labs(mission_day, weekly)``;
missing nights and faulty readings from ``LookAlike.missing`` and
``LookAlike.fault``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from orbit.core.interfaces import SourceBatch
from orbit.core.registry import register
from orbit.schema import (
    ContextEvent,
    CrewMember,
    EventType,
    Observation,
    Quality,
    ScenarioLabel,
    ScenarioType,
    Severity,
    SignalType,
    Source,
    get_spec,
    write_labels,
)

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
    S.SALIVA_EBV_DNA: 0, S.SALIVA_VZV_DNA: 0, S.SALIVA_HSV1_DNA: 0, S.CRP: 1,
}
NIGHTLY = tuple(NORMAL_RANGES)
SYMPTOMS = (
    S.SYMPTOM_FATIGUE, S.SYMPTOM_FEVER_CHILLS, S.SYMPTOM_SORE_THROAT,
    S.SYMPTOM_SWOLLEN_GLANDS, S.SYMPTOM_MOUTH_SORES, S.SYMPTOM_RASH_TINGLING,
    S.SYMPTOM_HEADACHE, S.SYMPTOM_MUSCLE_ACHES,
)
SALIVA = (S.SALIVA_EBV_DNA, S.SALIVA_VZV_DNA, S.SALIVA_HSV1_DNA)
HEALTHY_SALIVA_MAX = 99  # copies/mL; healthy shedding stays below 100
HEALTHY_DOSE = 0.30  # mGy per day
LAB_EVERY_DAYS = 7

WAKE_UP = timedelta(hours=6)
CHECKIN = timedelta(hours=7)
LAB = timedelta(hours=9)
END_OF_DAY = timedelta(hours=23, minutes=59)

CALLSIGNS = ("Vega", "Altair", "Deneb", "Rigel", "Lyra", "Sirius", "Capella", "Antares")
ROLES = ("Commander", "Flight engineer", "Mission specialist", "Science officer")

# ---- illness episodes (B03) -------------------------------------------------

VIRUSES = ("ebv", "vzv", "hsv1")
VIRUS_DNA = {"ebv": S.SALIVA_EBV_DNA, "vzv": S.SALIVA_VZV_DNA, "hsv1": S.SALIVA_HSV1_DNA}
VIRUS_NAMES = {"ebv": "EBV", "vzv": "VZV", "hsv1": "HSV-1"}
VIRUS_SIGNS = {
    "vzv": (S.SYMPTOM_RASH_TINGLING,),
    "hsv1": (S.SYMPTOM_MOUTH_SORES,),
    "ebv": (S.SYMPTOM_SWOLLEN_GLANDS, S.SYMPTOM_SORE_THROAT),
}
# Offset on the first prodrome day -> offset on day 0 (HRV as a fraction of the normal).
VIRAL_RAMPS: dict[SignalType, tuple[float, float]] = {
    S.SKIN_TEMP: (0.2, 0.6),
    S.RESTING_HR: (2.0, 7.0),
    S.HRV_RMSSD: (-0.10, -0.30),
    S.RESP_RATE: (0.4, 1.2),
    S.SLEEP_DURATION: (-0.3, -1.0),
}
RESPIRATORY_PEAKS: dict[SignalType, float] = {S.SKIN_TEMP: 0.8, S.RESP_RATE: 2.0, S.RESTING_HR: 8.0}
RESPIRATORY_START_FRACTION = 0.4  # first prodrome day reaches 40 % of the peak
DNA_RISE_DAYS = 3  # saliva DNA rises from day -3
DNA_LOG_PEAK = (2.8, 4.0)  # log10 copies/mL at the peak (about 630 to 10 000)
DNA_FLOOR_LOG = 2.0  # log10(100): the detection limit
CRP_HEALTHY = 1.5  # mg/L
CRP_PEAK = (20.0, 80.0)  # mg/L added at the peak
LEAD_DAYS = (1, 3)
RECOVERY_DAYS = (5, 10)
VIRAL_SHARE = 0.7  # "random": share of episodes that are viral
FIRST_EPISODE_DAY = 22  # nothing changes in the first 21 days, so a baseline exists
EPISODE_GAP_DAYS = 7  # healthy days between two episodes of one astronaut
DEFAULT_LEAD = {ScenarioType.VIRAL_REACTIVATION: 2, ScenarioType.RESPIRATORY_INFECTION: 1}
ILLNESSES = tuple(DEFAULT_LEAD)
ILLNESS_KEYS = {"type", "astronaut", "symptom_day", "virus", "lead_days", "recovery_days"}

# ---- look-alikes and faults (B04) -------------------------------------------

T = ScenarioType
CONFOUNDERS = (T.EVA_EXERTION, T.SLEEP_SHIFT, T.SOLAR_PARTICLE_EVENT)
FAULTS = (T.SENSOR_FAULT, T.MISSING_DATA)
LOOKALIKE_KEYS = {"type", "astronaut", "day", "nights"}
# How many days each look-alike lasts. A spacewalk always covers its day and the next night.
NIGHTS: dict[ScenarioType, tuple[int, int]] = {
    T.EVA_EXERTION: (2, 2),
    T.SLEEP_SHIFT: (2, 3),
    T.SOLAR_PARTICLE_EVENT: (1, 2),
    T.SENSOR_FAULT: (1, 3),
    T.MISSING_DATA: (1, 2),
}
# "random": per astronaut per 90 days.
LOOKALIKE_RATES: dict[ScenarioType, float] = {
    T.EVA_EXERTION: 2.0,
    T.SLEEP_SHIFT: 1.0,
    T.SENSOR_FAULT: 2.0,
    T.MISSING_DATA: 1.0,
}
SOLAR_EVENTS_PER_60_DAYS = 1.0  # crew-wide
EVA_WORKLOAD = 3.0  # h added to a normal 8.5-10 h day
EVA_HRV = -0.15  # fraction of the normal, the next night
EVA_HR = 3.0
SLEEP_SHIFT_HOURS = -1.5
SOLAR_DOSE_FACTOR = (2.0, 5.0)
# Absurd values a broken sensor reports, outside the plausible range.
FAULT_VALUES: dict[SignalType, tuple[float, str]] = {
    S.SKIN_TEMP: (24.0, "loose strap, skin temperature reads cabin air"),
    S.RESTING_HR: (230.0, "motion artefact, heart rate spike"),
    S.SPO2: (40.0, "poor sensor contact, SpO2 dropout"),
    S.RESP_RATE: (0.0, "breathing rate dropout"),
}
LOOKALIKE_NAMES = {
    T.EVA_EXERTION: "Spacewalk",
    T.SLEEP_SHIFT: "Sleep schedule shift",
    T.SOLAR_PARTICLE_EVENT: "Solar particle event",
    T.SENSOR_FAULT: "Sensor fault",
    T.MISSING_DATA: "Missing wearable data",
}


@dataclass(frozen=True)
class Episode:
    """One illness injected into one astronaut's mission. Callable as an effect."""

    scenario: ScenarioType
    astronaut_id: str
    symptom_day: int  # mission day of symptom onset ("day 0")
    lead_days: int
    recovery_days: int
    hrv_normal: float  # the astronaut's HRV normal, for the relative HRV drop
    symptoms: tuple[tuple[SignalType, int], ...]  # (signal, level on day 0)
    lab_peak: float  # viral: log10 copies/mL; respiratory: CRP mg/L added
    virus: str | None = None

    @property
    def first_day(self) -> int:
        """First mission day the episode changes anything (vitals or saliva DNA)."""
        before = self.lead_days
        if self.scenario is ScenarioType.VIRAL_REACTIVATION:
            before = max(before, DNA_RISE_DAYS)
        return self.symptom_day - before

    @property
    def last_day(self) -> int:
        """Last mission day the episode changes anything."""
        return self.symptom_day + self.recovery_days - 1

    def __call__(self, astronaut: str, mission_day: int) -> dict[SignalType, float]:
        if astronaut != self.astronaut_id:
            return {}
        rel = mission_day - self.symptom_day
        out: dict[SignalType, float] = {}
        if self.scenario is ScenarioType.VIRAL_REACTIVATION:
            for signal, (lo, hi) in VIRAL_RAMPS.items():
                out[signal] = self._ramp(rel, lo, hi)
            out[S.HRV_RMSSD] *= self.hrv_normal
            dna = self._dna(rel)
            if dna:
                out[VIRUS_DNA[self.virus]] = dna  # shows only on weekly lab days
        else:
            for signal, peak in RESPIRATORY_PEAKS.items():
                out[signal] = self._ramp(rel, RESPIRATORY_START_FRACTION * peak, peak)
        for signal, level in self._symptoms(rel):
            out[signal] = out.get(signal, 0.0) + level
        return {s: v for s, v in out.items() if v}

    def extra_labs(self, mission_day: int, weekly: bool) -> dict[SignalType, float]:
        """Extra 09:00 tests on this day: only from day 0 to the end of recovery."""
        rel = mission_day - self.symptom_day
        if not 0 <= rel < self.recovery_days:
            return {}
        if self.scenario is ScenarioType.VIRAL_REACTIVATION:
            return {} if weekly else {VIRUS_DNA[self.virus]: self._dna(rel)}
        return {S.CRP: CRP_HEALTHY + self.lab_peak * self._lab_shape(rel)}

    def label(self, day_start: Callable[[int], datetime]) -> ScenarioLabel:
        name = (f"{VIRUS_NAMES[self.virus]} reactivation" if self.virus
                else "Respiratory infection")
        return ScenarioLabel(
            label_id=f"{self.astronaut_id}-{self.scenario.value}-d{self.symptom_day:03d}",
            astronaut_id=self.astronaut_id,
            scenario=self.scenario,
            virus=self.virus,
            onset=day_start(self.symptom_day - self.lead_days),
            symptom_onset=day_start(self.symptom_day) + CHECKIN,
            resolved=day_start(self.symptom_day + self.recovery_days),
            should_alert=True,
            notes=(f"{name}: symptoms on day {self.symptom_day}, body changes "
                   f"{self.lead_days} d before, recovery {self.recovery_days} d"),
        )

    # ---- shapes -----------------------------------------------------------

    def _ramp(self, rel: int, lo: float, hi: float) -> float:
        """lo on the first prodrome day -> hi on day 0 -> back to 0 over recovery."""
        if -self.lead_days <= rel <= 0:
            return lo + (hi - lo) * (rel + self.lead_days) / self.lead_days
        if 0 < rel < self.recovery_days:
            return hi * (1 - rel / self.recovery_days)
        return 0.0

    def _symptoms(self, rel: int) -> list[tuple[SignalType, int]]:
        """From day 0 for the first half of recovery, easing by 1 every 2 days."""
        if not 0 <= rel <= self.recovery_days // 2:
            return []
        return [(signal, max(1, level - rel // 2)) for signal, level in self.symptoms]

    def _lab_shape(self, rel: int) -> float:
        """0..1: half on day 0, peak on day 1, then down over recovery."""
        if rel == 0:
            return 0.5
        if rel == 1:
            return 1.0
        return max(0.0, 1 - (rel - 1) / self.recovery_days)

    def _dna(self, rel: int) -> float:
        """Viral DNA copies/mL: from just above 100 on day -3 up to the peak on day 1."""
        if not -DNA_RISE_DAYS <= rel < self.recovery_days:
            return 0.0
        if rel <= 1:
            shape = 0.15 + 0.85 * (rel + DNA_RISE_DAYS) / (DNA_RISE_DAYS + 1)
        else:
            shape = 1 - (rel - 1) / self.recovery_days
        return 10 ** (DNA_FLOOR_LOG + (self.lab_peak - DNA_FLOOR_LOG) * shape)


@dataclass(frozen=True)
class LookAlike:
    """Something that looks like illness but is not. Callable as an effect."""

    scenario: ScenarioType
    astronaut_id: str | None  # None: the whole crew (solar particle event)
    day: int  # mission day it starts
    nights: int  # how many days it lasts (see NIGHTS)
    hrv_normal: float = 0.0  # spacewalk: the astronaut's HRV normal
    dose_factor: float = 1.0  # solar particle event
    fault_signal: SignalType | None = None  # sensor fault

    @property
    def first_day(self) -> int:
        return self.day

    @property
    def last_day(self) -> int:
        return self.day + self.nights - 1

    def _hits(self, astronaut: str, mission_day: int) -> bool:
        return (self.astronaut_id in (None, astronaut)
                and self.first_day <= mission_day <= self.last_day)

    def __call__(self, astronaut: str, mission_day: int) -> dict[SignalType, float]:
        if not self._hits(astronaut, mission_day):
            return {}
        if self.scenario is T.EVA_EXERTION:
            if mission_day == self.day:
                return {S.WORKLOAD: EVA_WORKLOAD}
            return {S.HRV_RMSSD: EVA_HRV * self.hrv_normal, S.RESTING_HR: EVA_HR}
        if self.scenario is T.SLEEP_SHIFT:
            return {S.SLEEP_DURATION: SLEEP_SHIFT_HOURS}
        if self.scenario is T.SOLAR_PARTICLE_EVENT:
            return {S.RADIATION_DOSE_DAILY: (self.dose_factor - 1) * HEALTHY_DOSE}
        return {}

    def missing(self, astronaut: str, mission_day: int) -> bool:
        """True if this astronaut's wearable records are missing on this day."""
        return self.scenario is T.MISSING_DATA and self._hits(astronaut, mission_day)

    def fault(self, astronaut: str, mission_day: int, signal: SignalType) -> tuple[float, str] | None:
        """(absurd value, note) if this reading comes from a broken sensor."""
        if (self.scenario is T.SENSOR_FAULT and signal is self.fault_signal
                and self._hits(astronaut, mission_day)):
            value, reason = FAULT_VALUES[signal]
            return value, f"Simulated sensor fault: {reason}"
        return None

    def event(self, day_start: Callable[[int], datetime]) -> ContextEvent | None:
        kind = {T.EVA_EXERTION: EventType.EVA, T.SLEEP_SHIFT: EventType.SLEEP_SHIFT,
                T.SOLAR_PARTICLE_EVENT: EventType.SOLAR_PARTICLE_EVENT}.get(self.scenario)
        if kind is None:
            return None
        start = day_start(self.day)
        if self.scenario is T.EVA_EXERTION:
            start, end, source = start + timedelta(hours=13), start + timedelta(hours=19), Source.MANUAL
            severity, text = Severity.MODERATE, "Spacewalk (simulated)"
        elif self.scenario is T.SLEEP_SHIFT:
            end, source = day_start(self.day + self.nights), Source.MANUAL
            severity, text = Severity.MODERATE, f"Sleep schedule shift for {self.nights} nights (simulated)"
        else:
            start, end, source = start + timedelta(hours=3), day_start(self.day + self.nights), Source.GROUND
            severity = Severity.HIGH if self.dose_factor >= 4 else Severity.MODERATE
            text = f"Solar particle event, dose x{self.dose_factor:.1f} (simulated)"
        return ContextEvent(
            event_id=f"{self.astronaut_id or 'CREW'}-{kind.value}-{day_start(self.day):%Y%m%d}",
            event_type=kind, start=start, end=end, severity=severity,
            astronaut_id=self.astronaut_id, source=source, description=text, simulated=True,
        )

    def labels(self, crew_ids: list[str], day_start: Callable[[int], datetime]) -> list[ScenarioLabel]:
        name = LOOKALIKE_NAMES[self.scenario]
        detail = f" ({self.fault_signal.value})" if self.fault_signal else ""
        return [
            ScenarioLabel(
                label_id=f"{astronaut}-{self.scenario.value}-d{self.day:03d}",
                astronaut_id=astronaut, scenario=self.scenario,
                onset=day_start(self.first_day), resolved=day_start(self.last_day + 1),
                should_alert=False,
                notes=f"{name}{detail}: day {self.day}, {self.nights} d"
                      + (", crew-wide" if self.astronaut_id is None else ""),
            )
            for astronaut in ([self.astronaut_id] if self.astronaut_id else crew_ids)
        ]


def _parse_start(value: str | datetime) -> datetime:
    start = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError(f"mission_start needs a timezone, got {value!r}")
    return start.astimezone(timezone.utc)


def _clamp(signal: SignalType, value: float) -> float:
    spec = get_spec(signal)
    return min(max(value, spec.plausible_min), spec.plausible_max)


def _poisson(rng: random.Random, mean: float) -> int:
    """Number of events with this mean (Knuth's method; fine for small means)."""
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def _overlaps(episode: Episode, others: list[Episode], gap: int = 0) -> bool:
    return any(
        o.astronaut_id == episode.astronaut_id
        and episode.first_day <= o.last_day + gap
        and o.first_day <= episode.last_day + gap
        for o in others
    )


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
        if illness_rate < 0:
            raise ValueError("illness_rate must not be negative")
        self.days = days
        self.crew_size = crew_size
        self.seed = seed
        self.mission_start = _parse_start(mission_start)
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
        # Drawn after the noise seed, so healthy values do not depend on the episodes.
        episode_rng = random.Random(rng.getrandbits(64))
        lookalike_rng = random.Random(rng.getrandbits(64))

        if scenarios == "random":
            episodes = self._random_episodes(episode_rng)
            lookalikes = self._random_lookalikes(lookalike_rng)
        else:
            episodes, lookalikes = self._inline_scenarios(scenarios, episode_rng)
        self.episodes: list[Episode] = sorted(
            episodes, key=lambda e: (e.symptom_day, e.astronaut_id))
        self.lookalikes: list[LookAlike] = sorted(
            lookalikes, key=lambda x: (x.day, x.astronaut_id or "", x.scenario.value))
        self.effects: list[Effect] = [*self.episodes, *self.lookalikes]

    # ---- public ---------------------------------------------------------

    def read(self) -> SourceBatch:
        rng = random.Random(self._noise_seed)
        observations: list[Observation] = []
        for member in self.crew:
            observations.extend(self._astronaut_records(member.astronaut_id, rng))
        if self.labels_path:
            write_labels(self.labels_path, self.labels())
        return SourceBatch(
            source_name="simulator",
            crew=self.crew,
            observations=tuple(observations),
            events=tuple(self.events()),
        )

    def events(self) -> list[ContextEvent]:
        """Spacewalks, sleep shifts and solar particle events, by start time."""
        found = [x.event(self.day_start) for x in self.lookalikes]
        return sorted((e for e in found if e is not None), key=lambda e: (e.start, e.event_id))

    def labels(self) -> list[ScenarioLabel]:
        """Ground truth for M9: illnesses (should alert) and look-alikes (should not).

        Sorted by mission day (symptom day for an illness, start day for a
        look-alike), then astronaut; illnesses keep B03's order.
        """
        crew_ids = [m.astronaut_id for m in self.crew]
        keyed = [((e.symptom_day, e.astronaut_id, 0), e.label(self.day_start))
                 for e in self.episodes]
        for x in self.lookalikes:
            keyed += [((x.day, label.astronaut_id, 1), label)
                      for label in x.labels(crew_ids, self.day_start)]
        return [label for _, label in sorted(keyed, key=lambda pair: pair[0])]

    def day_start(self, mission_day: int) -> datetime:
        return self.mission_start + timedelta(days=mission_day - 1)

    # ---- episodes -------------------------------------------------------

    def _draw_episode(
        self,
        rng: random.Random,
        scenario: ScenarioType,
        astronaut: str,
        symptom_day: int,
        virus: str | None = None,
        lead_days: int | None = None,
        recovery_days: int | None = None,
    ) -> Episode:
        """Fill in the random details of one episode (always in the same draw order)."""
        viral = scenario is ScenarioType.VIRAL_REACTIVATION
        if viral and virus is None:
            virus = rng.choice(VIRUSES)
        if recovery_days is None:
            recovery_days = rng.randint(*RECOVERY_DAYS)
        if viral:
            symptoms = [(S.SYMPTOM_FATIGUE, rng.choice((1, 2)))]
            symptoms += [(sign, rng.choice((1, 2))) for sign in VIRUS_SIGNS[virus]]
            lab_peak = rng.uniform(*DNA_LOG_PEAK)
        else:
            symptoms = [(S.SYMPTOM_FEVER_CHILLS, rng.randint(1, 3)),
                        (S.SYMPTOM_SORE_THROAT, rng.randint(1, 3))]
            lab_peak = rng.uniform(*CRP_PEAK)
        return Episode(
            scenario=scenario, astronaut_id=astronaut, symptom_day=symptom_day,
            lead_days=DEFAULT_LEAD[scenario] if lead_days is None else lead_days,
            recovery_days=recovery_days,
            hrv_normal=self.normals[astronaut][S.HRV_RMSSD],
            symptoms=tuple(symptoms), lab_peak=lab_peak, virus=virus,
        )

    def _random_episodes(self, rng: random.Random) -> list[Episode]:
        episodes: list[Episode] = []
        expected = self.illness_rate * self.days / 90
        for member in self.crew:
            for _ in range(_poisson(rng, expected)):
                viral = rng.random() < VIRAL_SHARE
                scenario = ScenarioType.VIRAL_REACTIVATION if viral \
                    else ScenarioType.RESPIRATORY_INFECTION
                lead = rng.choice((1, 2, 2, 3)) if viral else None
                draft = self._draw_episode(rng, scenario, member.astronaut_id, 0, lead_days=lead)
                earliest = FIRST_EPISODE_DAY - draft.first_day  # first_day is relative here
                latest = self.days - draft.recovery_days + 1  # last_day inside the mission
                for _attempt in range(50):
                    if earliest > latest:
                        break
                    episode = replace(draft, symptom_day=rng.randint(earliest, latest))
                    if not _overlaps(episode, episodes, EPISODE_GAP_DAYS):
                        episodes.append(episode)
                        break
        return episodes

    def _random_lookalikes(self, rng: random.Random) -> list[LookAlike]:
        kinds = [k for k in LOOKALIKE_RATES
                 if (k in CONFOUNDERS and self.confounders) or (k in FAULTS and self.faults)]
        placed: list[LookAlike] = []
        for member in self.crew:
            for kind in kinds:
                for _ in range(_poisson(rng, LOOKALIKE_RATES[kind] * self.days / 90)):
                    self._place_lookalike(rng, kind, member.astronaut_id, placed)
        if self.confounders:
            for _ in range(_poisson(rng, SOLAR_EVENTS_PER_60_DAYS * self.days / 60)):
                self._place_lookalike(rng, T.SOLAR_PARTICLE_EVENT, None, placed)
        return placed

    def _place_lookalike(self, rng: random.Random, kind: ScenarioType,
                         astronaut: str | None, placed: list[LookAlike]) -> None:
        draft = self._draw_lookalike(rng, kind, astronaut, FIRST_EPISODE_DAY)
        latest = self.days - draft.nights + 1
        for _attempt in range(50):
            if latest < FIRST_EPISODE_DAY:
                return
            candidate = replace(draft, day=rng.randint(FIRST_EPISODE_DAY, latest))
            if not _overlaps(candidate, placed):
                placed.append(candidate)
                return

    def _draw_lookalike(self, rng: random.Random, kind: ScenarioType, astronaut: str | None,
                        day: int, nights: int | None = None) -> LookAlike:
        """Fill in the random details of one look-alike (always in the same draw order)."""
        if nights is None:
            nights = rng.randint(*NIGHTS[kind])
        extra: dict = {}
        if kind is T.EVA_EXERTION:
            extra["hrv_normal"] = self.normals[astronaut][S.HRV_RMSSD]
        elif kind is T.SOLAR_PARTICLE_EVENT:
            extra["dose_factor"] = rng.uniform(*SOLAR_DOSE_FACTOR)
        elif kind is T.SENSOR_FAULT:
            extra["fault_signal"] = rng.choice(tuple(FAULT_VALUES))
        return LookAlike(scenario=kind, astronaut_id=astronaut, day=day, nights=nights, **extra)

    def _inline_scenarios(self, tables, rng: random.Random) -> tuple[list[Episode], list[LookAlike]]:
        if isinstance(tables, str) or not isinstance(tables, (list, tuple)):
            raise ValueError(f'scenarios must be "random" or a list of tables, got {tables!r}')
        crew = {m.astronaut_id for m in self.crew}
        episodes: list[Episode] = []
        lookalikes: list[LookAlike] = []
        for n, table in enumerate(tables, start=1):
            where = f"scenario {n}"
            if not isinstance(table, Mapping):
                raise ValueError(f"{where}: expected a table, got {table!r}")
            try:
                scenario = ScenarioType(table.get("type"))
            except ValueError:
                raise ValueError(
                    f"{where}: type must be one of {[s.value for s in ScenarioType]}") from None
            if scenario in ILLNESSES:
                episodes.append(self._inline_episode(where, table, scenario, crew, episodes, rng))
            else:
                lookalikes.append(self._inline_lookalike(where, table, scenario, crew,
                                                         lookalikes, rng))
        return episodes, lookalikes

    def _inline_lookalike(self, where, table, scenario, crew, others, rng) -> LookAlike:
        unknown = set(table) - LOOKALIKE_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        if "day" not in table:
            raise ValueError(f"{where}: missing key 'day'")
        astronaut = table.get("astronaut")
        if scenario is T.SOLAR_PARTICLE_EVENT:
            if astronaut is not None:
                raise ValueError(f"{where}: solar_particle_event is crew-wide; leave out 'astronaut'")
        elif astronaut not in crew:
            raise ValueError(f"{where}: unknown or missing astronaut {astronaut!r}")
        nights = table.get("nights")
        if nights is not None:
            lo, hi = NIGHTS[scenario]
            if scenario is T.EVA_EXERTION or not lo <= nights <= hi:
                raise ValueError(f"{where}: nights for {scenario.value} must be {lo} to {hi}"
                                 if scenario is not T.EVA_EXERTION
                                 else f"{where}: eva_exertion has no 'nights'")
        lookalike = self._draw_lookalike(rng, scenario, astronaut, int(table["day"]), nights)
        if lookalike.first_day < 1 or lookalike.last_day > self.days:
            raise ValueError(f"{where}: day {lookalike.day} does not fit "
                             f"in a {self.days}-day mission")
        if _overlaps(lookalike, others):
            raise ValueError(f"{where}: overlaps another look-alike of {astronaut or 'the crew'}")
        return lookalike

    def _inline_episode(self, where, table, scenario, crew, episodes, rng) -> Episode:
        unknown = set(table) - ILLNESS_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        missing = {"type", "astronaut", "symptom_day"} - set(table)
        if missing:
            raise ValueError(f"{where}: missing keys {sorted(missing)}")
        astronaut = table["astronaut"]
        if astronaut not in crew:
            raise ValueError(f"{where}: unknown astronaut {astronaut!r}")
        virus = table.get("virus")
        if scenario is ScenarioType.VIRAL_REACTIVATION:
            if virus not in VIRUSES:
                raise ValueError(f"{where}: virus must be one of {list(VIRUSES)}")
        elif virus is not None:
            raise ValueError(f"{where}: virus is only for viral_reactivation")
        lead = table.get("lead_days")
        if lead is not None and not LEAD_DAYS[0] <= lead <= LEAD_DAYS[1]:
            raise ValueError(f"{where}: lead_days must be {LEAD_DAYS[0]} to {LEAD_DAYS[1]}")
        recovery = table.get("recovery_days")
        if recovery is not None and not RECOVERY_DAYS[0] <= recovery <= RECOVERY_DAYS[1]:
            raise ValueError(
                f"{where}: recovery_days must be {RECOVERY_DAYS[0]} to {RECOVERY_DAYS[1]}")
        episode = self._draw_episode(rng, scenario, astronaut, int(table["symptom_day"]),
                                     virus, lead, recovery)
        if episode.first_day < 1 or episode.symptom_day > self.days:
            raise ValueError(f"{where}: symptom_day {episode.symptom_day} does not fit "
                             f"in a {self.days}-day mission")
        if _overlaps(episode, episodes):
            raise ValueError(f"{where}: overlaps another episode of {astronaut}")
        return episode

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
        episodes = [e for e in self.episodes if e.astronaut_id == astronaut]
        faults = [x for x in self.lookalikes if x.scenario in FAULTS
                  and x.astronaut_id == astronaut]
        records: list[Observation] = []

        for mission_day in range(1, self.days + 1):
            date = self.day_start(mission_day)
            stamp = date.strftime("%Y%m%d")
            offsets = self._offsets(astronaut, mission_day)

            def add(signal: SignalType, value: float, source: str, when: datetime,
                    suffix: str = "", **extra):
                records.append(Observation(
                    observation_id=f"{astronaut}-{signal.value}-{stamp}{suffix}",
                    astronaut_id=astronaut, timestamp=when, signal=signal,
                    value=value, source=source, simulated=True, **extra,
                ))

            def continuous(signal: SignalType, healthy: float) -> float:
                value = _clamp(signal, healthy + offsets.get(signal, 0.0))
                return round(value, DIGITS[signal])

            def ordinal(signal: SignalType, healthy: float) -> int:
                return int(_clamp(signal, round(healthy + offsets.get(signal, 0.0))))

            # 06:00 nightly vitals and sleep. A missing night or a broken sensor
            # still uses up its noise draw, so no other value changes.
            missing = any(x.missing(astronaut, mission_day) for x in faults)
            for signal in NIGHTLY:
                noise[signal] = PHI * noise[signal] + innovation * rng.gauss(0, sd[signal])
                if missing:
                    continue
                broken = next((f for x in faults
                               if (f := x.fault(astronaut, mission_day, signal))), None)
                if broken:
                    value, note = broken
                    add(signal, value, "wearable", date + WAKE_UP, device_id=device,
                        quality=Quality.BAD, note=note)
                    continue
                add(signal, continuous(signal, normals[signal] + noise[signal]),
                    "wearable", date + WAKE_UP, device_id=device)

            # 07:00 check-in
            for signal in SYMPTOMS:
                add(signal, ordinal(signal, 0), "checkin", date + CHECKIN)
            add(S.MOOD, ordinal(S.MOOD, rng.choice((3, 4, 4, 4, 5))), "checkin", date + CHECKIN)
            add(S.STRESS, ordinal(S.STRESS, rng.choice((1, 2, 2, 3))), "checkin", date + CHECKIN)

            # 09:00 weekly saliva test
            weekly = (mission_day - 1) % LAB_EVERY_DAYS == 0
            if weekly:
                for signal in SALIVA:
                    healthy = 0 if rng.random() < 0.4 else rng.uniform(5, HEALTHY_SALIVA_MAX)
                    add(signal, continuous(signal, healthy), "lab", date + LAB,
                        device_id="qpcr-01")

            # 09:00 extra tests during an illness, from symptom day on (no random draws)
            for episode in episodes:
                for signal, value in episode.extra_labs(mission_day, weekly).items():
                    add(signal, round(_clamp(signal, value), DIGITS[signal]), "lab",
                        date + LAB, suffix=f"-{LAB.seconds // 3600:02d}", device_id="qpcr-01")

            # 23:59 environment
            add(S.RADIATION_DOSE_DAILY,
                continuous(S.RADIATION_DOSE_DAILY, HEALTHY_DOSE + rng.gauss(0, 0.02)),
                "environment", date + END_OF_DAY)
            add(S.WORKLOAD, continuous(S.WORKLOAD, rng.choice((8.5, 9.0, 9.5, 10.0))),
                "environment", date + END_OF_DAY)

        return records
