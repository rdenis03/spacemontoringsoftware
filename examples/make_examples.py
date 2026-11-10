"""Build the example data files in this folder.

Three weeks (mission days 70-90) for two astronauts, with realistic
night-to-night variation. AST-01 starts showing early signs of shingles (VZV)
reactivation on days 89-90, matching the demo scenario; AST-02 stays well.
Frontend teammates can build against these files before the simulator (M2)
exists. The data is deterministic: re-running gives identical files.

Run from the project root:  python examples/make_examples.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orbit.schema import (
    ActionCard,
    ContextEvent,
    Contributor,
    CrewMember,
    Observation,
    RiskAssessment,
    write_csv,
    write_jsonl,
)

HERE = Path(__file__).parent
MISSION_START = datetime(2027, 1, 4, tzinfo=timezone.utc)
FIRST_DAY, LAST_DAY = 70, 90
WAKE_UP = timedelta(hours=6)  # nightly summaries are stamped at wake-up time

CREW = [
    CrewMember(astronaut_id="AST-01", callsign="Vega", role="Commander", mission_start=MISSION_START),
    CrewMember(astronaut_id="AST-02", callsign="Altair", role="Flight engineer",
               mission_start=MISSION_START),
]

# Personal normal and night-to-night noise (standard deviation) per astronaut.
NIGHTLY = {
    "AST-01": {"skin_temp": (34.4, 0.08, 2), "resting_hr": (52, 1.0, 0), "hrv_rmssd": (68, 3.5, 0),
               "resp_rate": (14.2, 0.2, 1), "spo2": (96.5, 0.3, 1),
               "sleep_duration": (6.9, 0.3, 1), "sleep_efficiency": (88, 1.8, 0)},
    "AST-02": {"skin_temp": (33.9, 0.09, 2), "resting_hr": (58, 1.2, 0), "hrv_rmssd": (46, 3.0, 0),
               "resp_rate": (15.1, 0.2, 1), "spo2": (97.0, 0.3, 1),
               "sleep_duration": (7.1, 0.3, 1), "sleep_efficiency": (90, 1.5, 0)},
}
# AST-01's illness: shift from normal on the last two nights.
ILLNESS = {
    89: {"skin_temp": 0.25, "resting_hr": 3.5, "hrv_rmssd": -12, "resp_rate": 0.5,
         "sleep_duration": -0.4, "sleep_efficiency": -3},
    90: {"skin_temp": 0.5, "resting_hr": 6, "hrv_rmssd": -17, "resp_rate": 1.1,
         "spo2": -0.5, "sleep_duration": -1.1, "sleep_efficiency": -7},
}
SYMPTOMS = ("symptom_fatigue", "symptom_fever_chills", "symptom_sore_throat",
            "symptom_swollen_glands", "symptom_mouth_sores", "symptom_rash_tingling",
            "symptom_headache", "symptom_muscle_aches")
ILL_SYMPTOMS = {89: {"symptom_fatigue": 1}, 90: {"symptom_fatigue": 2, "symptom_rash_tingling": 1}}


def _day(mission_day: int) -> datetime:
    return MISSION_START + timedelta(days=mission_day - 1)


def build_observations() -> list[Observation]:
    rng = random.Random(90)
    observations = []
    for astronaut in ("AST-01", "AST-02"):
        ill = astronaut == "AST-01"
        for mission_day in range(FIRST_DAY, LAST_DAY + 1):
            date = _day(mission_day)
            stamp = date.strftime("%Y%m%d")

            def add(signal, value, source, when, **extra):
                observations.append(Observation(
                    observation_id=f"{astronaut}-{signal}-{stamp}",
                    astronaut_id=astronaut, timestamp=when, signal=signal,
                    value=value, source=source, simulated=True, **extra,
                ))

            shift = ILLNESS.get(mission_day, {}) if ill else {}
            for signal, (normal, noise, digits) in NIGHTLY[astronaut].items():
                value = normal + shift.get(signal, 0) + rng.gauss(0, noise)
                if signal in ("spo2", "sleep_efficiency"):
                    value = min(value, 100)
                add(signal, round(value, digits), "wearable", date + WAKE_UP,
                    device_id=f"wrist-{astronaut.lower()}")

            symptoms = ILL_SYMPTOMS.get(mission_day, {}) if ill else {}
            for signal in SYMPTOMS:
                add(signal, symptoms.get(signal, 0), "checkin", date + timedelta(hours=7))
            mood = 3 if (ill and mission_day == 90) else rng.choice((3, 4, 4, 4, 5))
            add("mood", mood, "checkin", date + timedelta(hours=7))
            add("stress", 3 if (ill and mission_day >= 89) else rng.choice((1, 2, 2, 3)),
                "checkin", date + timedelta(hours=7))

            dose = 0.30 + rng.gauss(0, 0.02) + (0.55 if mission_day == 89 else 0) \
                + (0.12 if mission_day == 90 else 0)
            add("radiation_dose_daily", round(dose, 3), "environment",
                date + timedelta(hours=23, minutes=59))
            workload = 12.0 if (mission_day == 88 and ill) else rng.choice((8.5, 9.0, 9.5, 10.0))
            add("workload", workload, "environment", date + timedelta(hours=23, minutes=59))

    # One faulty night reading kept for audit: the sensor lost skin contact.
    observations.append(Observation(
        observation_id="AST-02-skin_temp-faulty", astronaut_id="AST-02",
        timestamp=_day(89) + timedelta(hours=3), signal="skin_temp", value=24.1,
        source="wearable", quality="bad", simulated=True, device_id="wrist-ast-02",
        note="Strap loose: sensor read cabin air temperature.",
    ))
    # Day 90: AST-01 reports a rash, so an onboard saliva test is run.
    observations.append(Observation(
        observation_id="AST-01-saliva_vzv_dna-20270403", astronaut_id="AST-01",
        timestamp=_day(90) + timedelta(hours=9), signal="saliva_vzv_dna", value=850,
        source="lab", simulated=True, device_id="qpcr-01",
    ))
    return observations


def build_events() -> list[ContextEvent]:
    return [
        ContextEvent(
            event_id="sep-20270402", event_type="solar_particle_event",
            start=_day(89) + timedelta(hours=14), end=_day(90) + timedelta(hours=2),
            severity="moderate", external_id="2027-04-02T14:00:00-SEP-001",
            description="Solar particle event; crew sheltered for 3 hours.", simulated=True,
        ),
        ContextEvent(
            event_id="eva-20270401", event_type="eva", astronaut_id="AST-01",
            start=_day(88) + timedelta(hours=8), end=_day(88) + timedelta(hours=15),
            severity="moderate", source="manual",
            description="7-hour spacewalk.", simulated=True,
        ),
    ]


def build_assessments() -> list[RiskAssessment]:
    """Hand-written examples of scorer output, for building the UI."""
    return [
        RiskAssessment(
            assessment_id="AST-01-20270403", astronaut_id="AST-01",
            assessed_at=_day(90) + timedelta(hours=10), score=72,
            model_version="example",
            contributors=[
                Contributor(label="Rash or tingling: mild in your check-in",
                            points=24, signal="symptom_rash_tingling"),
                Contributor(label="Skin temperature 0.4 °C above your normal for 2 days",
                            points=14, signal="skin_temp"),
                Contributor(label="Heart rate variability 22% below your normal for 2 days",
                            points=13, signal="hrv_rmssd"),
                Contributor(label="Resting heart rate 6 bpm above your normal for 2 days",
                            points=9, signal="resting_hr"),
                Contributor(label="VZV in saliva: 850 copies/mL", points=8, signal="saliva_vzv_dna"),
                Contributor(label="Solar particle event 1 day ago", points=4,
                            event_id="sep-20270402"),
            ],
        ),
        RiskAssessment(
            assessment_id="AST-02-20270403", astronaut_id="AST-02",
            assessed_at=_day(90) + timedelta(hours=10), score=9, model_version="example",
            contributors=[Contributor(label="Solar particle event 1 day ago", points=4,
                                      event_id="sep-20270402")],
        ),
    ]


# Illustrative cards for building the UI. Real protocols come from the
# mission's medical team, not from this file.
ACTION_CARDS = [
    ActionCard(
        card_id="keep-routine", level="green", title="Keep your routine",
        steps=("Keep your normal sleep window", "Complete tomorrow's check-in"),
        rationale="All signals are within your personal normal range.",
    ),
    ActionCard(
        card_id="saliva-test", level="yellow", title="Take a saliva sample",
        steps=("Collect a saliva sample before breakfast",
               "Run the viral DNA test on the onboard analyser",
               "Prioritise 8 hours of sleep tonight"),
        rationale="Early changes in your signals can come from viral reactivation; "
                  "a saliva test shows whether a virus is active.",
        triggers=("skin_temp", "hrv_rmssd", "resting_hr", "symptom_fatigue"),
    ),
    ActionCard(
        card_id="rest-watch", level="yellow", title="Rest and watch",
        steps=("Prioritise sleep tonight", "Repeat the check-in this evening"),
        rationale="Some signals moved away from your normal.",
    ),
    ActionCard(
        card_id="reduce-load", level="orange", title="Reduce workload and rest",
        steps=("Ask the commander to move non-critical tasks",
               "Check skin for a rash and photograph it",
               "Tell the crew medical officer today"),
        rationale="Several signals point the same way; rest helps your immune "
                  "system and medical review catches problems early.",
        escalate_to="crew_medical_officer",
        triggers=("symptom_rash_tingling", "saliva_vzv_dna", "skin_temp"),
    ),
    ActionCard(
        card_id="tell-cmo", level="orange", title="Tell the crew medical officer",
        steps=("Share today's status with the crew medical officer",),
        rationale="Several signals point the same way.",
        escalate_to="crew_medical_officer",
    ),
    ActionCard(
        card_id="isolate-consult", level="red", title="Isolate and get medical help",
        steps=("Move to your crew quarters and wear a mask",
               "Contact the crew medical officer now",
               "Send today's data to the flight surgeon"),
        rationale="High risk of an active infection that could spread to the crew.",
        escalate_to="flight_surgeon",
    ),
]


def main() -> None:
    observations = build_observations()
    write_jsonl(observations, HERE / "observations.jsonl")
    write_csv(observations, HERE / "observations.csv")
    write_jsonl(CREW, HERE / "crew.jsonl")
    write_jsonl(build_events(), HERE / "context_events.jsonl")
    write_jsonl(build_assessments(), HERE / "risk_assessments.jsonl")
    write_jsonl(ACTION_CARDS, HERE / "action_cards.jsonl")
    print(f"wrote {len(observations)} observations and 5 other example files to {HERE}")


if __name__ == "__main__":
    main()
