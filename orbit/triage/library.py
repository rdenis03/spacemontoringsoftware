"""Triage library (M15, not a slot): patterns, triage cards and the procedures shown.

Two hand-written files, checked when the triage service starts:

* ``cards/patterns.jsonl``: one line per ``TriagePattern`` with its label in
  plain words ("Signs that fit shingles (VZV)", never a diagnosis) and the
  ``card_ids`` to show for it. Ids may name cards in ``triage_cards.jsonl``
  or in the action engine's library (``pipeline.actions.cards``).
* ``cards/triage_cards.jsonl``: ``ActionCard``s used only by triage: the
  pattern cards and the red-flag cards (ids start with ``rf-``). They are
  never added to ``cards/action_cards.jsonl``: the daily ``protocol`` engine
  would pick them on normal days.

``merge_procedures`` builds what the astronaut sees: red-flag cards first,
then the top pattern's cards, then the action engine's cards for the day;
duplicates dropped, at most 4, and never a card above the level except
red-flag cards. People write card text; models choose cards, never words.

Without paths, small built-in libraries are used; their patterns name only
built-in triage cards, so they always load. All wording is illustrative.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orbit.schema import (
    ActionCard,
    AlertLevel,
    EscalationTarget,
    TriagePattern,
    get_spec,
    parse_jsonl,
    parse_records,
)
from orbit.schema.models import Slug

RED_FLAG_PREFIX = "rf-"
MAX_PROCEDURES = 4
_DOSE = re.compile(r"\d\s*mg", re.IGNORECASE)


class TriageLibraryError(ValueError):
    """A triage library breaks a rule every astronaut relies on."""


class PatternInfo(BaseModel):
    """One line of ``cards/patterns.jsonl``."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    pattern: TriagePattern
    label: str = Field(min_length=1, max_length=80)
    card_ids: tuple[Slug, ...] = ()


def check_cards(cards: Sequence[ActionCard], day_cards: Sequence[ActionCard] = ()) -> None:
    """Rules for triage cards, checked on load. Raises ``TriageLibraryError``.

    Unique ids, also against the action engine's library (``day_cards``);
    orange and red cards name who else must know; triggers within one signal
    category (the shared view hides a card with any private trigger, B15);
    steps under 200 characters; no medication doses (a digit followed by "mg").
    """
    problems: list[str] = []
    ids = [card.card_id for card in cards]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"duplicate card ids: {', '.join(duplicates)}")
    clashes = sorted(set(ids) & {card.card_id for card in day_cards})
    if clashes:
        problems.append(f"ids already in the action card library: {', '.join(clashes)}")
    for card in cards:
        if card.level.rank >= AlertLevel.ORANGE.rank and card.escalate_to is EscalationTarget.SELF:
            problems.append(f"{card.card_id}: {card.level.value} cards must set escalate_to")
        categories = sorted({get_spec(signal).category.value for signal in card.triggers})
        if len(categories) > 1:
            problems.append(f"{card.card_id}: triggers mix categories ({', '.join(categories)})")
        if any(len(step) >= 200 for step in card.steps):
            problems.append(f"{card.card_id}: steps must be under 200 characters")
        if _DOSE.search(" ".join((card.title, card.rationale, *card.steps))):
            problems.append(f"{card.card_id}: no medication doses")
    if problems:
        raise TriageLibraryError("triage cards: " + "; ".join(problems))


def _card(card_id: str, level: str, title: str, steps: tuple[str, ...], rationale: str,
          triggers: tuple[str, ...] = (), escalate_to: str = "self") -> ActionCard:
    return ActionCard(card_id=card_id, level=level, title=title, steps=steps, rationale=rationale,
                      triggers=triggers, escalate_to=escalate_to)


_HELP = "What you described needs a medical check straight away, whatever your score."
BUILT_IN_TRIAGE_CARDS: tuple[ActionCard, ...] = (
    _card("watch-patch", "yellow", "Watch the patch",
          ("Photograph the patch this morning and this evening", "Keep it covered and don't share towels"),
          "A tingling patch on one side can be the first sign of shingles.", ("symptom_rash_tingling",)),
    _card("mouth-care-early", "yellow", "Look after your mouth early",
          ("Don't share cups, cutlery or towels",), "Mouth sores spread through shared items.",
          ("symptom_mouth_sores",)),
    _card("rest-fluids", "yellow", "Rest and drink fluids", ("Drink water regularly through the day",),
          "Rest and fluids help your body fight a virus.", ("symptom_sore_throat", "symptom_swollen_glands")),
    _card("keep-distance", "yellow", "Keep your distance from the crew", ("Wear a mask in shared modules",),
          "An infection can pass to your crewmates.", ("symptom_fever_chills", "symptom_sore_throat")),
    _card("recover-after-work", "green", "Recover after hard work", ("Stretch gently and drink water",),
          "Aches after hard work usually settle with rest.", ("symptom_muscle_aches", "symptom_fatigue")),
    _card("describe-to-cmo", "green", "Describe it to the medical officer",
          ("Tell the crew medical officer what you feel, in your own words",),
          "A person should look at what ORBIT cannot match.", escalate_to="crew_medical_officer"),
    *(_card(f"rf-{name}", "red", "Get medical help now",
            ("Stop what you are doing", "Call the crew medical officer now"), _HELP,
            escalate_to="crew_medical_officer")
      for name in ("breathing", "chest", "faint", "confused", "eye")),
)
"""Small fallback set. The full, hand-edited one is cards/triage_cards.jsonl."""

BUILT_IN_PATTERNS: tuple[dict[str, Any], ...] = (
    {"pattern": "vzv_like", "label": "Signs that fit shingles (VZV)", "card_ids": ["watch-patch"]},
    {"pattern": "hsv1_like", "label": "Signs that fit cold sores (HSV-1)", "card_ids": ["mouth-care-early"]},
    {"pattern": "ebv_like", "label": "Signs that fit glandular fever (EBV)", "card_ids": ["rest-fluids"]},
    {"pattern": "respiratory", "label": "Signs that fit a chest or throat infection",
     "card_ids": ["keep-distance"]},
    {"pattern": "exertion", "label": "Signs that fit hard physical work", "card_ids": ["recover-after-work"]},
    {"pattern": "sleep_loss", "label": "Signs that fit short or broken sleep"},
    {"pattern": "stress", "label": "Signs that fit stress"},
    {"pattern": "other", "label": "Something else: describe it to the medical officer",
     "card_ids": ["describe-to-cmo"]},
)


class TriageLibrary:
    """Checked patterns and triage cards, plus the action engine's cards for lookups."""

    def __init__(self, patterns: Iterable[PatternInfo], cards: Iterable[ActionCard],
                 day_cards: Iterable[ActionCard] = ()):
        cards, day_cards = tuple(cards), tuple(day_cards)
        check_cards(cards, day_cards)
        problems: list[str] = []
        by_pattern: dict[TriagePattern, PatternInfo] = {}
        for info in patterns:
            if info.pattern in by_pattern:
                problems.append(f"{info.pattern.value} is listed twice")
            by_pattern[info.pattern] = info
        missing = [p.value for p in TriagePattern if p not in by_pattern]
        if missing:
            problems.append(f"no entry for {', '.join(missing)}")
        known = {card.card_id: card for card in (*day_cards, *cards)}
        for info in by_pattern.values():
            problems += [f"{info.pattern.value}: unknown card '{card_id}'"
                         for card_id in info.card_ids if card_id not in known]
        if problems:
            raise TriageLibraryError("triage patterns: " + "; ".join(problems))
        self.patterns = by_pattern
        self.cards = cards
        self._known = known

    @classmethod
    def load(cls, patterns_path: str | None = None, triage_cards_path: str | None = None,
             day_cards: Iterable[ActionCard] = ()) -> TriageLibrary:
        patterns = (parse_jsonl(patterns_path, PatternInfo) if patterns_path
                    else parse_records(BUILT_IN_PATTERNS, PatternInfo)).raise_if_errors()
        cards = (tuple(parse_jsonl(triage_cards_path, ActionCard).raise_if_errors())
                 if triage_cards_path else BUILT_IN_TRIAGE_CARDS)
        return cls(patterns, cards, day_cards)

    def label(self, pattern: TriagePattern) -> str:
        return self.patterns[pattern].label

    def has_card(self, card_id: str) -> bool:
        return card_id in self._known

    def card(self, card_id: str) -> ActionCard:
        """A triage card or a card of the action engine's library; KeyError if unknown."""
        return self._known[card_id]

    def pattern_cards(self, pattern: TriagePattern) -> list[ActionCard]:
        return [self._known[card_id] for card_id in self.patterns[pattern].card_ids]


def merge_procedures(
    red_flag_cards: Sequence[ActionCard],
    pattern_cards: Sequence[ActionCard],
    day_cards: Sequence[ActionCard],
    level: AlertLevel | str,
    max_cards: int = MAX_PROCEDURES,
) -> list[ActionCard]:
    """What the astronaut sees, in order: red-flag cards, the top pattern's cards, the day's cards.

    Duplicate card ids are dropped (the first one stays) and at most
    ``max_cards`` are kept. No card above ``level`` is added, except red-flag
    cards, which come first whatever the score.
    """
    level = AlertLevel(level)
    chosen: list[ActionCard] = []
    seen: set[str] = set()
    for cards, exempt in ((red_flag_cards, True), (pattern_cards, False), (day_cards, False)):
        for card in cards:
            if card.card_id in seen or (not exempt and card.level.rank > level.rank):
                continue
            seen.add(card.card_id)
            chosen.append(card)
    return chosen[:max_cards]
