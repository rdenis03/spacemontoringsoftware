"""The backbone: module slots, shared store, plug-in registry, config and pipeline."""

from .config import ConfigError, ModuleChoice, Settings, load_settings
from .interfaces import (
    SLOTS,
    ActionEngine,
    AnomalyDetector,
    AssessmentContext,
    BaselineEngine,
    DataSource,
    DayResult,
    EarthPacket,
    RiskScorer,
    SourceBatch,
    SymptomExtractor,
    SyncGate,
    TriageEvidence,
    TriageReasoner,
)
from .pipeline import IngestReport, Pipeline, RunReport
from .registry import RegistryError, available, create, register
from .store import Store, StoreError

__all__ = [
    "SLOTS", "ActionEngine", "AnomalyDetector", "AssessmentContext", "BaselineEngine",
    "DataSource", "DayResult", "EarthPacket", "RiskScorer", "SourceBatch", "SyncGate",
    "TriageEvidence", "SymptomExtractor", "TriageReasoner",
    "ConfigError", "ModuleChoice", "Settings", "load_settings",
    "IngestReport", "Pipeline", "RunReport",
    "RegistryError", "available", "create", "register",
    "Store", "StoreError",
]
