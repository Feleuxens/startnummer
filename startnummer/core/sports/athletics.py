"""Athletics: kinds, concrete disciplines, event model, labels."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from startnummer.core.enums import Lang, Source, Sport
from startnummer.core.models import BaseDiscipline, Confident, SportEvent, Subject, Tag, TagNamespace
from startnummer.core.sports.base import SportBase, register

ENTRY_CONFIDENCE = 0.9


class AthleticsKind(StrEnum):
    # Visual families
    FLAT = ("flat", "Track race", "Lauf")
    HURDLES = ("hurdles", "Hurdles", "Hürdenlauf")
    RELAY = ("relay", "Relay", "Staffel")
    STEEPLECHASE = ("steeplechase", "Steeplechase", "Hindernislauf")
    WALKING = ("walking", "Race walking", "Gehen")
    JUMP = ("jump", "Jump", "Sprung")
    THROW = ("throw", "Throw", "Wurf")

    def __new__(cls, slug: str, en: str, de: str):
        member = str.__new__(cls, slug)
        member._value_ = slug
        member.en = en
        member.de = de
        return member

    def label(self, lang: Lang) -> str:
        return self.de if lang is Lang.DE else self.en


class AthleticsDiscipline(BaseDiscipline):
    # FLAT
    M_50 = ("50m", "50m", "50m", AthleticsKind.FLAT)
    M_60 = ("60m", "60m", "60m", AthleticsKind.FLAT)
    M_75 = ("75m", "75m", "75m", AthleticsKind.FLAT)
    M_80 = ("80m", "80m", "80m", AthleticsKind.FLAT)
    M_100 = ("100m", "100m", "100m", AthleticsKind.FLAT)
    M_150 = ("150m", "150m", "150m", AthleticsKind.FLAT)
    M_200 = ("200m", "200m", "200m", AthleticsKind.FLAT)
    M_300 = ("300m", "300m", "300m", AthleticsKind.FLAT)
    M_400 = ("400m", "400m", "400m", AthleticsKind.FLAT)
    M_600 = ("600m", "600m", "600m", AthleticsKind.FLAT)
    M_800 = ("800m", "800m", "800m", AthleticsKind.FLAT)
    M_1K = ("1000m", "1000m", "1000m", AthleticsKind.FLAT)
    M_1K5 = ("1500m", "1500m", "1500m", AthleticsKind.FLAT)
    M_2K = ("2000m", "2000m", "2000m", AthleticsKind.FLAT)
    M_3K = ("3000m", "3000m", "3000m", AthleticsKind.FLAT)
    M_5K = ("5000m", "5000m", "5000m", AthleticsKind.FLAT)
    M_10K = ("10000m", "10000", "10000m", AthleticsKind.FLAT)
    # HURDLES
    HURDLES_60 = ("60mH", "60m hurdles", "60m Hürden", AthleticsKind.HURDLES)
    HURDLES_80 = ("80mH", "80m hurdles", "80m Hürden", AthleticsKind.HURDLES)
    HURDLES_100 = ("100mH", "100m hurdles", "100m Hürden", AthleticsKind.HURDLES)
    HURDLES_110 = ("110mH", "110m hurdles", "110m Hürden", AthleticsKind.HURDLES)
    HURDLES_300 = ("300mH", "300m hurdles", "300m Hürden", AthleticsKind.HURDLES)
    HURDLES_400 = ("400mH", "400m hurdles", "400m Hürden", AthleticsKind.HURDLES)
    # RELAY
    RELAY_4x50 = ("4x50m", "4x50m relay", "4x50m Staffel", AthleticsKind.RELAY)
    RELAY_4x75 = ("4x75m", "4x75m relay", "4x75m Staffel", AthleticsKind.RELAY)
    RELAY_4x100 = ("4x100m", "4x100m relay", "4x100m Staffel", AthleticsKind.RELAY)
    RELAY_4x200 = ("4x200m", "4x200m relay", "4x200m Staffel", AthleticsKind.RELAY)
    RELAY_4x400 = ("4x400m", "4x400m relay", "4x400m Staffel", AthleticsKind.RELAY)
    RELAY_3x800 = ("3x800m", "3x800m relay", "3x800m Staffel", AthleticsKind.RELAY)
    RELAY_3x1K = ("3x1000m", "3x1000m relay", "3x1000m Staffel", AthleticsKind.RELAY)
    # STEEPLECHASE (kind carries the family; tagged generically)
    STEEPLECHASE = ("steeplechase", "steeplechase", "Hindernislauf", AthleticsKind.STEEPLECHASE)
    # WALKING
    WALKING = ("walking", "race walking", "Bahngehen", AthleticsKind.WALKING)
    # JUMP
    LONG_JUMP = ("long_jump", "Long jump", "Weitsprung", AthleticsKind.JUMP)
    HIGH_JUMP = ("high_jump", "High jump", "Hochsprung", AthleticsKind.JUMP)
    POLE_VAULT = ("pole_vault", "Pole vault", "Stabhochsprung", AthleticsKind.JUMP)
    TRIPLE_JUMP = ("triple_jump", "Triple jump", "Dreisprung", AthleticsKind.JUMP)
    # THROW
    SHOT_PUT = ("shot_put", "Shot put", "Kugelstoßen", AthleticsKind.THROW)
    JAVELIN = ("javelin", "Javelin", "Speerwurf", AthleticsKind.THROW)
    DISCUS = ("discus", "Discus throw", "Diskus", AthleticsKind.THROW)
    HAMMER = ("hammer", "Hammer throw", "Hammerwurf", AthleticsKind.THROW)
    BALL = ("ball", "Ball throw", "Ballwurf", AthleticsKind.THROW)
    # Fallback for unspecified event
    OTHER = ("other", None, None, None)

    def __new__(cls, slug: str, en: str | None, de: str | None, kind: AthleticsKind | None):
        member = str.__new__(cls, slug)
        member._value_ = slug
        member.en = en
        member.de = de
        member.kind = kind
        return member

    def label(self, lang: Lang) -> str | None:
        return self.de if lang is Lang.DE else self.en

    @classmethod
    def of_kind(cls, kind: "AthleticsKind") -> list["AthleticsDiscipline"]:
        return [d for d in cls if d.kind is kind]


class AthleticsEvent(SportEvent):
    sport: Literal[Sport.ATHLETICS] = Sport.ATHLETICS
    discipline: Confident[AthleticsDiscipline] | None = None  # concrete event, or None if undetected
    custom_kind: AthleticsKind | None = None  # only with discipline == OTHER
    custom_label: str | None = None  # free-text event, only with discipline == OTHER

    def event_kind(self) -> AthleticsKind | None:
        # The family, whether from a recognized discipline or a custom override.
        if self.discipline is None:
            return None
        return self.custom_kind if self.discipline.value is AthleticsDiscipline.OTHER \
            else self.discipline.value.kind


_BY_SLUG = {d.value: d for d in AthleticsDiscipline}


def _classify(entry: str) -> AthleticsDiscipline | None:
    # Clean canonical entry -> the concrete discipline member, or None if the
    # entry isn't one we tag (unknown slug). Adapter guarantees canonical form.
    return _BY_SLUG.get(entry)


def _entered_disciplines(subject: Subject) -> set[AthleticsDiscipline]:
    if subject.athlete is None:
        return set()
    return {d for e in subject.athlete.value.entered_events if (d := _classify(e))}


def _resolve_discipline(
    subjects: Sequence[Subject], *, kind: AthleticsKind | None = None
) -> AthleticsDiscipline | None:
    """Concrete event = intersection of matched athletes' entered disciplines
    (optionally filtered to one kind); unique -> that discipline, else None."""
    per_subject: list[set[AthleticsDiscipline]] = []
    for subject in subjects:
        entered = _entered_disciplines(subject)
        if kind is not None:
            entered = {d for d in entered if d.kind is kind}
        if entered:
            per_subject.append(entered)
    if not per_subject:
        return None
    common = set.intersection(*per_subject)
    return next(iter(common)) if len(common) == 1 else None


def _confident(value, source: Source, note: str, confidence: float = ENTRY_CONFIDENCE):
    return Confident(value=value, confidence=confidence, source=source, note=note)


class AthleticsModule(SportBase):
    sport = Sport.ATHLETICS

    def new_event(self) -> AthleticsEvent:
        return AthleticsEvent()

    def resolve(self, event: AthleticsEvent, subjects: list[Subject]) -> AthleticsEvent:
        # A concrete preset discipline (manual, prior pass) is authoritative.
        if event.discipline is not None and event.discipline.value is not AthleticsDiscipline.OTHER:
            return event

        # STEP 1 - entries first (only when nothing is set). Unique concrete event
        # across matched athletes' entries wins
        if event.discipline is None:
            discipline = _resolve_discipline(subjects)
            if discipline is not None:
                return event.model_copy(update={
                    "discipline": _confident(discipline, Source.ROSTER, "resolved from competition entries"),
                })

            # Step 2: Try to infer kind of discipline like running
            event = self._classify_visual(event)
            # Step 3: Try to infer from cues like baton or hurdles
            event = self._infer_from_cues(event)

        # If a visual step supplied only a family (via custom_kind on OTHER, or a
        # concrete member), entries constrained to that kind may now be unique.
        if event.discipline is not None:
            family = event.event_kind()
            if family is not None:
                narrowed = _resolve_discipline(subjects, kind=family)
                if narrowed is not None:
                    return event.model_copy(update={
                        "discipline": _confident(
                            narrowed, Source.ROSTER, "resolved from entries within visual family"
                        ),
                        "custom_kind": None,
                        "custom_label": None,
                    })
        return event

    def _classify_visual(self, event: AthleticsEvent) -> AthleticsEvent:
        # Placeholder for the DisciplineClassifier step.
        return event

    def _infer_from_cues(self, event: AthleticsEvent) -> AthleticsEvent:
        # Placeholder for the cue-object step.
        return event

    def infer(self, event: AthleticsEvent, cues: Sequence[str]) -> AthleticsEvent:
        if event.discipline is not None:
            return event
        cue_family = {"baton": AthleticsKind.RELAY, "hurdle": AthleticsKind.HURDLES}
        for cue, family in cue_family.items():
            if cue in cues:
                return event.model_copy(update={
                    "discipline": _confident(
                        AthleticsDiscipline.OTHER, Source.RULE, f"{cue} visible", 0.7
                    ),
                    "custom_kind": family,
                })
        return event

    def discipline_label(self, discipline: AthleticsDiscipline, lang: Lang) -> str | None:
        return discipline.label(lang)

    def discipline_tag(self, event: AthleticsEvent) -> Tag | None:
        if event.discipline is None:
            return None
        discipline = event.discipline.value
        if discipline is AthleticsDiscipline.OTHER:
            # Custom event: tag the free-text label if present.
            return Tag(TagNamespace.DISCIPLINE, event.custom_label) if event.custom_label else None
        label = discipline.en
        return Tag(TagNamespace.DISCIPLINE, label) if label else None


register(AthleticsModule())
