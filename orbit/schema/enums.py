"""Enumerations shared by every ORBIT module.

All enums are string-valued so they serialise to readable JSON
("skin_temp", not 3) and can be used directly by a JavaScript frontend.
"""

from enum import StrEnum


class SignalCategory(StrEnum):
    """Broad groups of health indicators. Used for consent and dashboard grouping."""

    VITAL = "vital"  # wearable physiology, nightly summaries
    SLEEP = "sleep"  # wearable sleep metrics
    SYMPTOM = "symptom"  # daily check-in, 0-3 severity
    WELLBEING = "wellbeing"  # daily check-in, 1-5 scale
    LAB = "lab"  # onboard assays (saliva, blood)
    CONTEXT = "context"  # stressors: radiation, workload


class SignalType(StrEnum):
    """Every health indicator the system understands.

    Adding a signal: add it here AND to the registry in ``signals.py``.
    A test fails if the two ever get out of sync.
    """

    # Vitals (wearable, one nightly summary per day)
    SKIN_TEMP = "skin_temp"
    RESTING_HR = "resting_hr"
    HRV_RMSSD = "hrv_rmssd"
    RESP_RATE = "resp_rate"
    SPO2 = "spo2"

    # Sleep (wearable)
    SLEEP_DURATION = "sleep_duration"
    SLEEP_EFFICIENCY = "sleep_efficiency"

    # Symptoms (daily check-in, 0 none / 1 mild / 2 moderate / 3 severe)
    SYMPTOM_FATIGUE = "symptom_fatigue"
    SYMPTOM_FEVER_CHILLS = "symptom_fever_chills"
    SYMPTOM_SORE_THROAT = "symptom_sore_throat"
    SYMPTOM_SWOLLEN_GLANDS = "symptom_swollen_glands"
    SYMPTOM_MOUTH_SORES = "symptom_mouth_sores"
    SYMPTOM_RASH_TINGLING = "symptom_rash_tingling"
    SYMPTOM_HEADACHE = "symptom_headache"
    SYMPTOM_MUSCLE_ACHES = "symptom_muscle_aches"

    # Wellbeing (daily check-in, 1-5)
    MOOD = "mood"
    STRESS = "stress"

    # Onboard lab
    SALIVA_EBV_DNA = "saliva_ebv_dna"
    SALIVA_VZV_DNA = "saliva_vzv_dna"
    SALIVA_HSV1_DNA = "saliva_hsv1_dna"
    SALIVA_CORTISOL = "saliva_cortisol"
    WBC_COUNT = "wbc_count"
    CRP = "crp"

    # Context / stressors
    RADIATION_DOSE_DAILY = "radiation_dose_daily"
    WORKLOAD = "workload"


class SignalKind(StrEnum):
    CONTINUOUS = "continuous"  # any real number in range
    ORDINAL = "ordinal"  # whole-number scale (symptom severity, mood)


class ConcernDirection(StrEnum):
    """Which direction of change is worrying. Used by the anomaly detector (M7)."""

    UP = "up"  # e.g. skin temperature, viral DNA
    DOWN = "down"  # e.g. HRV, sleep, SpO2
    BOTH = "both"  # e.g. white blood cell count


class Source(StrEnum):
    """Where a reading came from (the channel, not whether it is simulated)."""

    WEARABLE = "wearable"
    CHECKIN = "checkin"  # astronaut's daily self-report
    LAB = "lab"  # onboard assay device
    ENVIRONMENT = "environment"  # habitat sensors, e.g. dosimeters
    GROUND = "ground"  # uplinked from Earth, e.g. NASA DONKI space weather
    MANUAL = "manual"  # typed in by a crew member, e.g. a thermometer reading


class Quality(StrEnum):
    """Data quality flag. Analytics should ignore BAD and down-weight SUSPECT."""

    GOOD = "good"
    SUSPECT = "suspect"  # plausible but questionable (motion artefact, short wear time)
    BAD = "bad"  # known faulty: kept for audit, never used for scoring


class EventType(StrEnum):
    """Things that happen to the crew and can stress the immune system."""

    SOLAR_FLARE = "solar_flare"
    SOLAR_PARTICLE_EVENT = "solar_particle_event"
    CME = "cme"
    GEOMAGNETIC_STORM = "geomagnetic_storm"
    EVA = "eva"  # spacewalk
    SLEEP_SHIFT = "sleep_shift"  # schedule change, e.g. for a docking
    CREW_ILLNESS = "crew_illness"  # another crew member is ill (exposure)
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    EXTREME = "extreme"


class AlertLevel(StrEnum):
    """Traffic-light status shown to the astronaut. Ordered from best to worst."""

    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"

    @property
    def rank(self) -> int:
        """0 for GREEN up to 3 for RED, so levels can be compared: ``a.rank > b.rank``."""
        return list(AlertLevel).index(self)


class AnomalyKind(StrEnum):
    SPIKE = "spike"  # sudden jump away from the personal baseline
    DRIFT = "drift"  # slow sustained shift over several days


class EscalationTarget(StrEnum):
    """Who should act on an action card."""

    SELF = "self"
    CREW_MEDICAL_OFFICER = "crew_medical_officer"
    FLIGHT_SURGEON = "flight_surgeon"  # on Earth, reached with communication delay
