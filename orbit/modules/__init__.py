"""Starter implementations for every slot.

Each one is deliberately simple but genuinely works, so the whole system runs
end to end from day one. The owner of each team module replaces (or improves)
its starter:

    file           slot       registered as     team module
    -------------  ---------  ----------------  -----------
    sources.py     source     files, memory     M3 (M2 simulator, M5 DONKI add new ones)
    baseline.py    baseline   rolling_median    M6
    detector.py    detector   robust_z          M7
    scorer.py      scorer     rule_based        M8
    actions.py     actions    card_library      M10
    consent.py     sync       consent_gate      M13

To add a module: create a file here, decorate the class with
``@register("<slot>", "<name>")``, import it below, and select it in orbit.toml.
"""

from . import actions, baseline, consent, detector, scorer, sources  # noqa: F401
from . import simulator  # noqa: F401
from . import scorer_learned  # noqa: F401
from . import ingestion  # noqa: F401
from . import extractor  # noqa: F401
from . import reasoner  # noqa: F401
from . import extractor_learned  # noqa: F401
from . import reasoner_bayes  # noqa: F401
from . import space_weather  # noqa: F401
