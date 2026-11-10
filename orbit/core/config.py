"""Settings, loaded from ``orbit.toml``.

The config file decides which implementation fills each slot, so the team can
swap a starter module for a real one, or compare two, by editing one line.

Lookup order: the path given on the command line, then the ``ORBIT_CONFIG``
environment variable, then ``orbit.toml`` in the current folder, then defaults.

Option keys ending in ``_path`` (and ``storage.database``) are resolved
relative to the config file, so the project works from any folder.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .interfaces import SLOTS

ANALYTICS_SLOTS = ("baseline", "detector", "scorer", "actions", "sync")

DEFAULT_MODULES: dict[str, str] = {
    "baseline": "rolling_median",
    "detector": "robust_z",
    "scorer": "rule_based",
    "actions": "card_library",
    "sync": "consent_gate",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModuleChoice:
    """Which implementation fills a slot, and the options passed to it."""

    use: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    mission_name: str = "ORBIT mission"
    assessment_hour_utc: int = 10
    database: str = ":memory:"
    baseline_window_days: int = 14
    recent_days: int = 3
    event_lookback_days: int = 7
    #: [comms] one-way delay to Earth for queued packets (M13); Mars is 3-22 min.
    one_way_delay_minutes: float = 20.0
    modules: dict[str, ModuleChoice] = field(
        default_factory=lambda: {slot: ModuleChoice(name) for slot, name in DEFAULT_MODULES.items()}
    )
    sources: tuple[ModuleChoice, ...] = ()
    config_path: Path | None = None


def _resolve_paths(options: dict[str, Any], base: Path) -> dict[str, Any]:
    resolved = {}
    for key, value in options.items():
        if key.endswith("_path") and isinstance(value, str) and value:
            path = Path(value)
            value = str(path if path.is_absolute() else (base / path).resolve())
        resolved[key] = value
    return resolved


def _choice(raw: Any, where: str, base: Path) -> ModuleChoice:
    if not isinstance(raw, dict) or not isinstance(raw.get("use"), str):
        raise ConfigError(f"{where} needs a 'use = \"<module name>\"' line")
    options = {k: v for k, v in raw.items() if k != "use"}
    return ModuleChoice(raw["use"], _resolve_paths(options, base))


def find_config(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    env = os.environ.get("ORBIT_CONFIG")
    if env:
        return find_config(env)
    local = Path("orbit.toml")
    return local if local.is_file() else None


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = find_config(path)
    if config_path is None:
        return Settings()
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: {exc}") from exc
    base = config_path.parent.resolve()

    mission = raw.get("mission", {})
    storage = raw.get("storage", {})
    pipeline = raw.get("pipeline", {})
    comms = raw.get("comms", {})

    modules = {slot: ModuleChoice(name) for slot, name in DEFAULT_MODULES.items()}
    for slot, section in raw.get("modules", {}).items():
        if slot not in ANALYTICS_SLOTS:
            raise ConfigError(
                f"[modules.{slot}] is not a slot; use one of: {', '.join(ANALYTICS_SLOTS)} "
                "(data sources go in [[sources]])"
            )
        modules[slot] = _choice(section, f"[modules.{slot}]", base)

    sources = tuple(
        _choice(section, f"[[sources]] #{i + 1}", base)
        for i, section in enumerate(raw.get("sources", []))
    )

    database = storage.get("database", ":memory:")
    if database != ":memory:" and not Path(database).is_absolute():
        database = str((base / database).resolve())

    hour = int(mission.get("assessment_hour_utc", 10))
    if not 0 <= hour <= 23:
        raise ConfigError("mission.assessment_hour_utc must be between 0 and 23")

    settings = Settings(
        mission_name=mission.get("name", "ORBIT mission"),
        assessment_hour_utc=hour,
        database=database,
        baseline_window_days=int(pipeline.get("baseline_window_days", 14)),
        recent_days=int(pipeline.get("recent_days", 3)),
        event_lookback_days=int(pipeline.get("event_lookback_days", 7)),
        one_way_delay_minutes=float(comms.get("one_way_delay_minutes", 20.0)),
        modules=modules,
        sources=sources,
        config_path=config_path.resolve(),
    )
    for name in ("baseline_window_days", "recent_days", "event_lookback_days"):
        if getattr(settings, name) < 1:
            raise ConfigError(f"pipeline.{name} must be at least 1")
    if not 0 <= settings.one_way_delay_minutes <= 24 * 60:
        raise ConfigError("comms.one_way_delay_minutes must be between 0 and 1440")
    assert set(SLOTS) >= set(settings.modules)
    return settings
