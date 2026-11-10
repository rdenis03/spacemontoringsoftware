"""Plain-language report for Earth (M13, task B17).

Every packet queued for Earth carries one line a flight surgeon can read in
ten seconds: who, status, top reasons, the advised actions, and what the
astronaut kept private::

    AST-01 Vega · ORANGE (70) · mission day 90 · Skin temperature 0.45 °C above
    normal for 2 days; VZV in saliva: 850 copies/mL; Sleep duration 17% below
    normal in the latest reading; 2 private reasons · Actions: Reduce workload:
    VZV is active (crew medical officer); Tell the crew medical officer (crew
    medical officer); 1 private action · Withheld by the astronaut: symptom
    (64), wellbeing (16)

Why templates: the report must work offline and must never invent medical
content. Every word comes from the packet (already filtered by the consent
gate), the action cards, or the fixed phrases in this file.

``build_report(member, packet, actions=())`` is pure: no clock, no I/O, the
same input gives the same text. Rules:

* Status: level, score (whole number) and mission day of the **latest**
  assessment in the packet. A packet without assessments says so.
* Reasons: ``MAX_REASONS`` (3) of the reasons the astronaut shares: first the
  strongest reason of each category (vital, sleep, lab, ..., events), so three
  vital signs do not hide a lab result, then the next strongest; shown by
  points, highest first. Every reason the consent gate made private is counted
  ("2 private reasons"), never listed. "your normal" becomes "normal": the
  reader is not the astronaut.
* Actions: a card's title and who it escalates to are listed only when all its
  ``triggers`` are in categories the astronaut shares (no triggers = always
  listed). Any other card is counted as a private action, because its title
  can reveal a symptom. These are the cards ORBIT advised; the report does
  not claim they were done.
* Withheld: the packet's exact ``withheld`` counts per category.
* One line, at most ``MAX_LENGTH`` (600) characters. If it would be longer,
  the actions are counted instead of listed, then the reasons are shortened.
"""

from __future__ import annotations

from collections.abc import Sequence

from orbit.core.interfaces import EarthPacket
from orbit.modules.consent import PRIVATE_LABEL
from orbit.schema import ActionCard, CrewMember, EscalationTarget, RiskAssessment, get_spec

MAX_LENGTH = 600
MAX_REASONS = 3
SEPARATOR = " · "
SHORT_REASON = 60  # characters per reason when the line must be shortened


def build_report(member: CrewMember, packet: EarthPacket,
                 actions: Sequence[ActionCard] = ()) -> str:
    """The one-line report for this packet. Pure: no clock, no I/O."""
    head = f"{member.astronaut_id} {member.callsign}"
    withheld = _withheld(packet)
    latest = _latest(packet)
    if latest is None:
        return _cut(SEPARATOR.join([head, "No assessment in this period", withheld]))

    status = [head, f"{latest.level.value.upper()} ({latest.score:.0f})",
              f"mission day {member.mission_day(latest.assessed_at)}"]
    shared, private = _split_actions(member, actions)
    listed = [_action_text(card) for card in shared]

    # Longest first; the first version that fits is used.
    for reason_length, list_actions in ((None, True), (None, False), (SHORT_REASON, False)):
        parts = [*status, _reasons(latest, reason_length),
                 _actions(listed if list_actions else None, len(shared), private), withheld]
        line = SEPARATOR.join(parts)
        if len(line) <= MAX_LENGTH:
            return line
    return _cut(line)


def _latest(packet: EarthPacket) -> RiskAssessment | None:
    if not packet.assessments:
        return None
    return max(packet.assessments, key=lambda a: (a.assessed_at, a.assessment_id))


def _reasons(assessment: RiskAssessment, max_length: int | None) -> str:
    reasons = assessment.contributors  # already sorted by points, highest first
    if not reasons:
        return "No findings"
    shared = [r for r in reasons if r.label != PRIVATE_LABEL]
    private = len(reasons) - len(shared)

    # The strongest reason of each category first, then the next strongest.
    picked: list[int] = []
    seen: set[str] = set()
    for i, reason in enumerate(shared):
        category = get_spec(reason.signal).category.value if reason.signal else "event"
        if category not in seen:
            seen.add(category)
            picked.append(i)
    picked = picked[:MAX_REASONS]
    picked += [i for i in range(len(shared)) if i not in picked][: MAX_REASONS - len(picked)]

    shown = [_for_reader(shared[i].label, max_length) for i in sorted(picked)]
    if private:
        shown.append(_count(private, "private reason"))
    return "; ".join(shown)


def _for_reader(label: str, max_length: int | None) -> str:
    text = label.replace("your normal", "normal").replace("in your check-in", "in the check-in")
    if max_length is not None and len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def _split_actions(member: CrewMember,
                   actions: Sequence[ActionCard]) -> tuple[list[ActionCard], int]:
    """(cards that may be named, number of private cards)."""
    shared, private = [], 0
    for card in actions:
        if all(member.shares(get_spec(signal).category) for signal in card.triggers):
            shared.append(card)
        else:
            private += 1
    return shared, private


def _action_text(card: ActionCard) -> str:
    if card.escalate_to is EscalationTarget.SELF:
        return card.title
    return f"{card.title} ({card.escalate_to.value.replace('_', ' ')})"


def _actions(listed: list[str] | None, shared: int, private: int) -> str:
    if shared + private == 0:
        return "Actions: none"
    if listed is None:  # counted, to save space
        items = [_count(shared, "action")] if shared else []
    else:
        items = list(listed)
    if private:
        items.append(_count(private, "private action"))
    return "Actions: " + "; ".join(items)


def _withheld(packet: EarthPacket) -> str:
    kept = {category: n for category, n in packet.withheld.items() if n > 0}
    if not kept:
        return "Nothing withheld by the astronaut"
    return "Withheld by the astronaut: " + ", ".join(
        f"{category} ({n})" for category, n in sorted(kept.items()))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _cut(line: str) -> str:
    return line if len(line) <= MAX_LENGTH else line[: MAX_LENGTH - 1].rstrip() + "…"
