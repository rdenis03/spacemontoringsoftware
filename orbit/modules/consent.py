"""Consent gate (slot ``sync``, team module M13).

Applies the astronaut's sharing choices before anything leaves the spacecraft:

* Readings are sent only for categories the astronaut shares
  (``CrewMember.share_with_earth``). Others stay onboard and are counted
  exactly per category (``EarthPacket.withheld``).
* Risk scores and levels are always sent so the flight surgeon sees the
  overall status, but reasons based on a private category are replaced by a
  neutral label (their points are kept, so the score still adds up).

Why the score always travels (a deliberate choice for the pitch): consent
covers the *details*, not the alarm. If the score could be hidden too, an
astronaut could, by mistake or under pressure, hide a real emergency from
the ground. Sending the number but not the private reasons keeps both the
astronaut's privacy and the crew's safety.

The same gate produces the crew's shared view (``GET /status?view=shared``,
M14). Around it, the API keeps the queue (M13): ``PUT /consent`` edits the
choices, ``POST /earth-packet/send`` packages a period and queues it in the
store's outbox with the one-way delay from ``[comms]`` in orbit.toml, and
``GET /outbox`` lists what left and whether it has arrived. The outbox is
the audit log. ``package()`` itself holds no state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone

from orbit.core.interfaces import EarthPacket
from orbit.core.registry import register
from orbit.schema import Contributor, CrewMember, Observation, RiskAssessment, get_spec

PRIVATE_LABEL = "Private signal (not shared by the astronaut)"


@register("sync", "consent_gate")
class ConsentGate:
    def package(
        self,
        member: CrewMember,
        observations: Sequence[Observation],
        assessments: Sequence[RiskAssessment],
    ) -> EarthPacket:
        shared, withheld = [], Counter()
        for obs in observations:
            if member.shares(obs.category):
                shared.append(obs)
            else:
                withheld[obs.category.value] += 1

        redacted = []
        for assessment in assessments:
            reasons = []
            for reason in assessment.contributors:
                if reason.signal is not None and not member.shares(get_spec(reason.signal).category):
                    reason = Contributor(label=PRIVATE_LABEL, points=reason.points)
                reasons.append(reason)
            redacted.append(assessment.model_copy(update={"contributors": tuple(reasons)}))

        return EarthPacket(
            astronaut_id=member.astronaut_id,
            created_at=datetime.now(timezone.utc),
            observations=tuple(shared),
            assessments=tuple(redacted),
            withheld=dict(withheld),
        )
