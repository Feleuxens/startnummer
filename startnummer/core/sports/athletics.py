"""Athletics: disciplines, event model, labels, discipline tag, and entries-based
resolution of the concrete event.

The discipline enum holds only what vision can classify; the concrete event
("400m", "4x100m", "100mH") is resolved from competition entries, which core
assumes are already normalized to canonical form by the entry table adapter.
"""

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from startnummer.core.enums import Lang, Source, Sport
from startnummer.core.models import Confident, SportEvent, Subject, Tag, TagNamespace
from startnummer.core.sports.base import SportBase, register

ENTRY_CONFIDENCE = 0.9

# Canonical entry grammar (adapters emit this; core only validates and classifies):
#   flat    "{distance}m"          e.g. 400m
#   hurdles "{distance}mH"         e.g. 100mH
#   relay   "{count}x{distance}m"  e.g. 4x100m
_EVENT = re.compile(r"^(?:(\d+)x)?(\d+)m(H)?$")
_FLAT, _HURDLES, _RELAY = "flat", "hurdles", "relay"


class AthleticsDiscipline(StrEnum):
    SHOT_PUT = "shot_put"
    DISCUS = "discus"
    HAMMER = "hammer"
    JAVELIN = "javelin"
    HIGH_JUMP = "high_jump"
    POLE_VAULT = "pole_vault"
    LONG_JUMP = "long_jump"
    TRIPLE_JUMP = "triple_jump"
    HURDLES = "hurdles"  # visual class; exact event resolved from entries
    STEEPLECHASE = "steeplechase"
    TRACK_RACE = "track_race"  # all flat races; distance resolved from entries
    RELAY = "relay"  # visual class; exact event resolved from entries
    UNKNOWN = "unknown"


class AthleticsEvent(SportEvent):
    sport: Literal[Sport.ATHLETICS] = Sport.ATHLETICS
    discipline: Confident[AthleticsDiscipline] | None = None  # visual class
    resolved: Confident[str] | None = None  # concrete event from entries, e.g. "4x100m"


# Disciplines whose concrete value is resolved from entries, mapped to the canonical
# kind their entries must match. STEEPLECHASE is deliberately absent: it stays generic.
_RESOLVING: dict[AthleticsDiscipline, str] = {
    AthleticsDiscipline.TRACK_RACE: _FLAT,
    AthleticsDiscipline.HURDLES: _HURDLES,
    AthleticsDiscipline.RELAY: _RELAY,
}

# UNKNOWN intentionally absent from both maps: callers must not label it.
_EN: dict[AthleticsDiscipline, str] = {
    AthleticsDiscipline.SHOT_PUT: "Shot put",
    AthleticsDiscipline.DISCUS: "Discus throw",
    AthleticsDiscipline.HAMMER: "Hammer throw",
    AthleticsDiscipline.JAVELIN: "Javelin throw",
    AthleticsDiscipline.HIGH_JUMP: "High jump",
    AthleticsDiscipline.POLE_VAULT: "Pole vault",
    AthleticsDiscipline.LONG_JUMP: "Long jump",
    AthleticsDiscipline.TRIPLE_JUMP: "Triple jump",
    AthleticsDiscipline.HURDLES: "Hurdles",
    AthleticsDiscipline.STEEPLECHASE: "Steeplechase",
    AthleticsDiscipline.TRACK_RACE: "Track race",
    AthleticsDiscipline.RELAY: "Relay",
}

_DE: dict[AthleticsDiscipline, str] = {
    AthleticsDiscipline.SHOT_PUT: "Kugelstoßen",
    AthleticsDiscipline.DISCUS: "Diskuswurf",
    AthleticsDiscipline.HAMMER: "Hammerwurf",
    AthleticsDiscipline.JAVELIN: "Speerwurf",
    AthleticsDiscipline.HIGH_JUMP: "Hochsprung",
    AthleticsDiscipline.POLE_VAULT: "Stabhochsprung",
    AthleticsDiscipline.LONG_JUMP: "Weitsprung",
    AthleticsDiscipline.TRIPLE_JUMP: "Dreisprung",
    AthleticsDiscipline.HURDLES: "Hürdenlauf",
    AthleticsDiscipline.STEEPLECHASE: "Hindernislauf",
    AthleticsDiscipline.TRACK_RACE: "Lauf",
    AthleticsDiscipline.RELAY: "Staffel",
}


def _canonical_event(entry: str) -> tuple[str, str] | None:
    # Validates an already-normalized entry and classifies its kind.
    match = _EVENT.match(entry)
    if match is None:
        return None
    count, distance, hurdles = match.groups()
    if count:
        return _RELAY, f"{int(count)}x{int(distance)}m"
    if hurdles:
        return _HURDLES, f"{int(distance)}mH"
    return _FLAT, f"{int(distance)}m"


# Cue label -> discipline it implies. Only refines an unset / generic-track
# discipline; a confident field-event classification is never overridden.
CUE_CONFIDENCE = 0.7  # placeholder until validated against real photos
_CUE_DISCIPLINES: dict[str, AthleticsDiscipline] = {
    "baton": AthleticsDiscipline.RELAY,
    "hurdle": AthleticsDiscipline.HURDLES,
}
_REFINABLE = {AthleticsDiscipline.TRACK_RACE, AthleticsDiscipline.UNKNOWN}


class AthleticsModule(SportBase):
    sport = Sport.ATHLETICS

    def new_event(self) -> AthleticsEvent:
        return AthleticsEvent()

    def infer(self, event: AthleticsEvent, cues: Sequence[str]) -> AthleticsEvent:
        if event.discipline is not None and event.discipline.value not in _REFINABLE:
            return event
        for (
            cue,
            discipline,
        ) in _CUE_DISCIPLINES.items():  # fixed order: baton wins over hurdle
            if cue in cues:
                return event.model_copy(
                    update={
                        "discipline": Confident(
                            value=discipline,
                            confidence=CUE_CONFIDENCE,
                            source=Source.RULE,
                            note=f"{cue} visible",
                        )
                    }
                )
        return event

    def discipline_label(
        self, discipline: AthleticsDiscipline, lang: Lang
    ) -> str | None:
        return (_DE if lang is Lang.DE else _EN).get(discipline)

    def discipline_tag(self, event: AthleticsEvent) -> Tag | None:
        if event.resolved is not None:
            return Tag(TagNamespace.DISCIPLINE, event.resolved.value)  # e.g. "4x100m"
        if event.discipline is None:
            return None
        label = _EN.get(event.discipline.value)  # None for UNKNOWN
        return Tag(TagNamespace.DISCIPLINE, label) if label else None

    def resolve(self, event: AthleticsEvent, subjects: list[Subject]) -> AthleticsEvent:
        # Concrete event = intersection of matched athletes' entered events of the
        # matching kind; unique -> resolved, otherwise unchanged (falls back to label).
        if event.discipline is None:
            return event
        kind = _RESOLVING.get(event.discipline.value)
        if kind is None:
            return event  # steeplechase, throws, jumps: label only

        per_subject: list[set[str]] = []
        for subject in subjects:
            if subject.athlete is None:
                continue
            values = {
                parsed[1]
                for e in subject.athlete.value.entered_events
                if (parsed := _canonical_event(e)) and parsed[0] == kind
            }
            if values:
                per_subject.append(values)

        if not per_subject:
            return event
        common = set.intersection(*per_subject)
        if len(common) != 1:
            return event
        return event.model_copy(
            update={
                "resolved": Confident(
                    value=next(iter(common)),
                    confidence=ENTRY_CONFIDENCE,
                    source=Source.RULE,
                    note="resolved from competition entries",
                )
            }
        )


register(AthleticsModule())
