"""The ``[triage]`` section of orbit.toml (M15).

``orbit/core/config.py`` stays unchanged: ``load_settings`` ignores unknown
top-level sections, and this module reads ``[triage]`` from the same file
(``Settings.config_path``). Keys ending in ``_path`` are resolved relative to
that file, like ``[modules.*]`` options. Without a config file, or without a
``[triage]`` section, the starters (``lexicon``, ``rules``) and their small
built-in libraries are used::

    [triage]
    session_timeout_minutes = 120        # an open chat expires after this long without a turn
    patterns_path = "cards/patterns.jsonl"
    triage_cards_path = "cards/triage_cards.jsonl"
    red_flags_path = "cards/red_flags.jsonl"

    [triage.extractor]
    use = "lexicon"
    lexicon_path = "cards/symptom_lexicon.jsonl"

    [triage.reasoner]
    use = "rules"
    questions_path = "cards/questions.jsonl"
    max_questions = 5
    stop_probability = 0.8
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from orbit.core.config import ConfigError, ModuleChoice, Settings, _choice, _resolve_paths

DEFAULT_EXTRACTOR = "lexicon"
DEFAULT_REASONER = "rules"
_KEYS = frozenset({"session_timeout_minutes", "patterns_path", "triage_cards_path", "red_flags_path",
                   "extractor", "reasoner"})


@dataclass(frozen=True)
class TriageSettings:
    session_timeout_minutes: float = 120.0
    patterns_path: str | None = None
    triage_cards_path: str | None = None
    red_flags_path: str | None = None
    extractor: ModuleChoice = field(default_factory=lambda: ModuleChoice(DEFAULT_EXTRACTOR))
    reasoner: ModuleChoice = field(default_factory=lambda: ModuleChoice(DEFAULT_REASONER))
    config_path: Path | None = None


def load_triage_settings(settings: Settings | None = None) -> TriageSettings:
    """Read ``[triage]`` from the file ``settings`` came from; defaults if there is none."""
    path = settings.config_path if settings is not None else None
    if path is None:
        return TriageSettings()
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("triage", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("[triage] must be a table")
    unknown = sorted(set(raw) - _KEYS)
    if unknown:
        raise ConfigError(f"[triage] has unknown keys: {', '.join(unknown)}; "
                          f"allowed: {', '.join(sorted(_KEYS))}")
    base = Path(path).parent.resolve()
    paths = _resolve_paths({k: v for k, v in raw.items() if k.endswith("_path")}, base)
    timeout = raw.get("session_timeout_minutes", 120)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 24 * 60:
        raise ConfigError("triage.session_timeout_minutes must be a number between 1 and 1440")
    return TriageSettings(
        session_timeout_minutes=float(timeout),
        patterns_path=paths.get("patterns_path"),
        triage_cards_path=paths.get("triage_cards_path"),
        red_flags_path=paths.get("red_flags_path"),
        extractor=(_choice(raw["extractor"], "[triage.extractor]", base) if "extractor" in raw
                   else ModuleChoice(DEFAULT_EXTRACTOR)),
        reasoner=(_choice(raw["reasoner"], "[triage.reasoner]", base) if "reasoner" in raw
                  else ModuleChoice(DEFAULT_REASONER)),
        config_path=Path(path),
    )
