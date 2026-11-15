"""M1: the shared data schema every ORBIT module builds on.

Typical use::

    from orbit.schema import Observation, parse_jsonl, to_dataframe

    obs = parse_jsonl("mission.jsonl").raise_if_errors()
    df = to_dataframe(obs)
"""

from .enums import (
    AlertLevel,
    AnomalyKind,
    ConcernDirection,
    EscalationTarget,
    EventType,
    Quality,
    Severity,
    SignalCategory,
    SignalKind,
    SignalType,
    Source,
)
from .io import (
    OBSERVATION_COLUMNS,
    ParseResult,
    RowError,
    SchemaError,
    from_dataframe,
    parse_csv,
    parse_jsonl,
    parse_records,
    to_dataframe,
    write_csv,
    write_jsonl,
)
from .labels import ALERTING_SCENARIOS, ScenarioLabel, ScenarioType, read_labels, write_labels
from .models import (
    DEFAULT_SHARED_CATEGORIES,
    LEVEL_THRESHOLDS,
    SCHEMA_VERSION,
    ActionCard,
    Anomaly,
    Baseline,
    Contributor,
    ContextEvent,
    CrewMember,
    Observation,
    RiskAssessment,
    level_for_score,
)
from .signals import SIGNALS, SignalSpec, get_spec, signals_in
from .triage import (
    OPEN_STATUSES,
    PatternScore,
    SymptomFinding,
    SymptomReport,
    TriageAnswer,
    TriagePattern,
    TriageQuestion,
    TriageResult,
    TriageSession,
    TriageStatus,
)

__all__ = [
    # enums
    "AlertLevel", "AnomalyKind", "ConcernDirection", "EscalationTarget", "EventType",
    "Quality", "Severity", "SignalCategory", "SignalKind", "SignalType", "Source",
    # registry
    "SIGNALS", "SignalSpec", "get_spec", "signals_in",
    # models
    "SCHEMA_VERSION", "Observation", "ContextEvent", "CrewMember",
    "DEFAULT_SHARED_CATEGORIES", "Baseline", "Anomaly", "Contributor", "RiskAssessment",
    "ActionCard", "LEVEL_THRESHOLDS", "level_for_score",
    # io
    "OBSERVATION_COLUMNS", "ParseResult", "RowError", "SchemaError",
    "parse_records", "parse_jsonl", "parse_csv", "write_jsonl", "write_csv",
    "to_dataframe", "from_dataframe",
    # scenario labels
    "ScenarioType", "ScenarioLabel", "ALERTING_SCENARIOS", "read_labels", "write_labels",
    # symptom triage (M15)
    "TriagePattern", "TriageStatus", "OPEN_STATUSES", "SymptomReport", "SymptomFinding",
    "TriageQuestion", "TriageAnswer", "PatternScore", "TriageResult", "TriageSession",
]
