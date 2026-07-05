"""Handball: event model and discipline enum only. All behavior is inherited
no-ops from SportBase — no discipline tag, nothing to resolve from entries.
"""

from enum import StrEnum
from typing import Literal

from startnummer.core.enums import Sport
from startnummer.core.models import Confident, SportEvent
from startnummer.core.sports.base import SportBase, register


class HandballDiscipline(StrEnum):
    MATCH = "match"
    UNKNOWN = "unknown"


class HandballEvent(SportEvent):
    sport: Literal[Sport.HANDBALL] = Sport.HANDBALL
    discipline: Confident[HandballDiscipline] | None = None


class HandballModule(SportBase):
    sport = Sport.HANDBALL

    def new_event(self) -> HandballEvent:
        return HandballEvent()


register(HandballModule())
