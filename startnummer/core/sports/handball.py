"""Handball: event model and discipline enum only. All behavior is inherited
no-ops from SportBase — no discipline tag, nothing to resolve from entries.
"""

from enum import StrEnum
from typing import Literal

from startnummer.core.enums import Sport, Lang
from startnummer.core.models import BaseDiscipline, Confident, SportEvent
from startnummer.core.sports.base import SportBase, register


class HandballDiscipline(BaseDiscipline):
    MATCH = ("match", "Match", "Spiel")
    OTHER = ("other", None, None)
    NO_EVENT = ("no_event", None, None)

    def __new__(cls, slug: str, en: str | None, de: str | None):
        member = str.__new__(cls, slug)
        member._value_ = slug
        member.en = en
        member.de = de
        return member

    def label(self, lang: Lang) -> str | None:
        return self.de if lang is Lang.DE else self.en
    
    
class HandballEvent(SportEvent):
    sport: Literal[Sport.HANDBALL] = Sport.HANDBALL
    discipline: Confident[HandballDiscipline] | None = None


class HandballModule(SportBase):
    sport = Sport.HANDBALL

    def new_event(self) -> HandballEvent:
        return HandballEvent()


register(HandballModule())
