"""Starter action engine (slot ``actions``, team module M10).

Picks action cards from a library for the assessment's alert level. Cards
with ``triggers`` are only shown when one of their signals is among the
reasons for the score; cards without triggers always apply at their level.
If nothing matches at the exact level, it falls back to the closest lower
level, so the astronaut is never left without a next step.

The library is a JSONL file of ``ActionCard`` records (``cards_path`` in
orbit.toml). Without one, a minimal built-in set is used.

Ideas for M10: cards that depend on time of day or crew schedule, follow-up
reminders, checking the onboard pharmacy before suggesting medication.
"""

from __future__ import annotations

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import ActionCard, AlertLevel, RiskAssessment, parse_jsonl

BUILT_IN_CARDS = (
    ActionCard(card_id="keep-routine", level=AlertLevel.GREEN, title="Keep your routine",
               steps=("Complete tomorrow's check-in",),
               rationale="Your signals are within your personal normal range."),
    ActionCard(card_id="watch-closely", level=AlertLevel.YELLOW, title="Watch closely and rest",
               steps=("Prioritise sleep tonight", "Repeat the check-in this evening"),
               rationale="Some signals moved away from your normal."),
    ActionCard(card_id="tell-cmo", level=AlertLevel.ORANGE, title="Tell the crew medical officer",
               steps=("Share today's status with the crew medical officer",),
               rationale="Several signals point the same way.",
               escalate_to="crew_medical_officer"),
    ActionCard(card_id="urgent-help", level=AlertLevel.RED, title="Get medical help now",
               steps=("Contact the crew medical officer now",),
               rationale="High risk of an active illness.", escalate_to="flight_surgeon"),
)


@register("actions", "card_library")
class CardLibraryActionEngine:
    def __init__(self, cards_path: str | None = None, max_cards: int = 3):
        if cards_path:
            self.cards = tuple(parse_jsonl(cards_path, ActionCard).raise_if_errors())
        else:
            self.cards = BUILT_IN_CARDS
        if not self.cards:
            raise ValueError("the action card library is empty")
        self.max_cards = max_cards

    def recommend(self, assessment: RiskAssessment, ctx: AssessmentContext) -> list[ActionCard]:
        reasons = {c.signal for c in assessment.contributors if c.signal is not None}
        levels = [lvl for lvl in AlertLevel if lvl.rank <= assessment.level.rank]
        for level in reversed(levels):  # exact level first, then closest lower one
            matched = [
                card for card in self.cards
                if card.level is level and (not card.triggers or reasons & set(card.triggers))
            ]
            if matched:
                matched.sort(key=lambda card: not card.triggers)  # specific cards first
                return matched[: self.max_cards]
        return []
