"""Action engines (slot ``actions``, team module M10).

Two engines live here: the starter ``card_library`` and the M10 engine
``protocol`` (further down), which ranks cards by how much of the score
their triggers explain and checks the library when it loads.

Starter (``card_library``):

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

from collections import defaultdict

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import ActionCard, AlertLevel, EscalationTarget, RiskAssessment, get_spec, parse_jsonl

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


# ---- M10: protocol engine -------------------------------------------------------


class CardLibraryError(ValueError):
    """The action card library breaks a rule every astronaut relies on."""


def check_library(cards: tuple[ActionCard, ...]) -> None:
    """Rules a library must meet, checked once when the engine starts.

    * Every level has at least one card without triggers, so there is always
      a next step whatever the reasons are.
    * Orange and red cards name who else must know (``escalate_to`` is not
      ``self``).
    * Card ids are unique.
    * Each card's triggers stay within one signal category (task B19). The
      shared crew view (B15) hides a card whose triggers touch a private
      category, so a card mixing a lab result with a symptom would vanish
      whenever symptoms are private, which is the default.
    """
    problems: list[str] = []
    ids = [card.card_id for card in cards]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"duplicate card ids: {', '.join(duplicates)}")
    for level in AlertLevel:
        if not any(card.level is level and not card.triggers for card in cards):
            problems.append(f"no general card (without triggers) for level {level.value}")
    for card in cards:
        if card.level.rank >= AlertLevel.ORANGE.rank and card.escalate_to is EscalationTarget.SELF:
            problems.append(f"{card.card_id}: {card.level.value} cards must set escalate_to")
        categories = sorted({get_spec(signal).category.value for signal in card.triggers})
        if len(categories) > 1:
            problems.append(f"{card.card_id}: triggers mix categories ({', '.join(categories)})")
    if problems:
        raise CardLibraryError("action card library: " + "; ".join(problems))


@register("actions", "protocol")
class ProtocolActionEngine:
    """M10 action engine: the most relevant vetted cards for today's reasons.

    How it chooses, for an assessment at level L:

    1. Look at the cards for level L. A card with ``triggers`` is relevant
       when one of its signals is a reason for the score; its relevance is
       the sum of the points of those reasons, so the card that explains most
       of the score comes first. Ties keep library order.
    2. Cards without triggers (general cards for that level) follow.
    3. If no card at level L speaks to today's reasons, the most relevant
       specific cards from the level just below are added after the general
       card, so a red day still gets the virus-specific steps.
    4. If level L has no card at all, use the closest lower level. Never a
       card above L.
    5. Return at most ``max_cards``.

    Cards are written by people and checked on load (``check_library``):
    the engine decides which cards fit, never what they say. Wording,
    thresholds and steps are illustrative for the demo, not medical advice.

    Options:
        cards_path: JSONL file of ``ActionCard`` records. Default: the small
            built-in set shared with ``card_library``.
        max_cards: most cards to show at once (default 3).

    Pure: no clock, no I/O after loading, same input gives the same output.
    Escalation after several orange days would need past assessments in the
    context, which is a core change still to be agreed.
    """

    def __init__(self, cards_path: str | None = None, max_cards: int = 3):
        if max_cards < 1:
            raise ValueError("max_cards must be at least 1")
        cards = (
            tuple(parse_jsonl(cards_path, ActionCard).raise_if_errors()) if cards_path else BUILT_IN_CARDS
        )
        check_library(cards)
        self.cards = cards
        self.max_cards = max_cards

    def recommend(self, assessment: RiskAssessment, ctx: AssessmentContext) -> list[ActionCard]:
        weight: dict[str, float] = defaultdict(float)
        for reason in assessment.contributors:
            if reason.signal is not None:
                weight[reason.signal] += reason.points

        def relevance(card: ActionCard) -> float:
            return sum(weight.get(signal, 0.0) for signal in card.triggers)

        def specific_at(level: AlertLevel) -> list[ActionCard]:
            cards = [c for c in self.cards if c.level is level and c.triggers and relevance(c) > 0]
            return sorted(cards, key=relevance, reverse=True)  # stable: ties keep library order

        levels = [lvl for lvl in AlertLevel if lvl.rank <= assessment.level.rank]
        for index in range(len(levels) - 1, -1, -1):  # exact level first, then the closest lower one
            level = levels[index]
            specific = specific_at(level)
            general = [card for card in self.cards if card.level is level and not card.triggers]
            chosen = specific + general
            if not chosen:
                continue
            if not specific and index > 0:
                chosen += specific_at(levels[index - 1])
            return chosen[: self.max_cards]
        return []
