"""Symptom triage (M15): a short conversation in front of the daily check-in.

    library.py    patterns, triage cards and how procedures are merged
    red_flags.py  fixed rules that escalate before any model runs
    service.py    TriageService: the only place triage modules meet (owns all I/O)
    config.py     the [triage] section of orbit.toml

The two pluggable parts are slots like the analytics: the extractor
(``orbit/modules/extractor.py``) and the reasoner (``orbit/modules/reasoner.py``).
See SPEC.md, M15, and ARCHITECTURE.md, decision 8.

This file imports nothing on purpose: ``orbit.modules`` loads every module,
and importing it from a package ``__init__`` invites import cycles (NOTES B08).
Import the submodules directly, e.g. ``from orbit.triage.service import TriageService``.
"""
