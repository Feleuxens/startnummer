"""Per-sport contract, no-op base, and registry.

SportModule is the structural contract. SportBase provides no-op defaults so a
sport only writes the methods it actually has rules for; the no-op resolve/tag/
label are inherited. Generic code dispatches through get(sport).
"""

from collections.abc import Sequence
from typing import Any, ClassVar, Protocol, TypeVar

from startnummer.core.enums import Lang, Sport
from startnummer.core.models import SportEvent, Subject, Tag

E = TypeVar("E", bound=SportEvent)


class SportModule(Protocol[E]):
    sport: Sport

    def discipline_label(self, discipline: Any, lang: Lang) -> str | None: ...

    def discipline_tag(self, event: E) -> Tag | None: ...

    # Returns the event with code-defined fields resolved (e.g. distance from entries).
    def resolve(self, event: E, subjects: list[Subject]) -> E: ...

    # Refines the event from visual cues (e.g. runner + baton -> relay). cues is
    # provisionally object labels; tightens to a structured type once the object
    # detector lands. No-op until per-sport rules are added.
    def infer(self, event: E, cues: Sequence[str]) -> E: ...


class SportBase:
    """No-op defaults. Subclasses set `sport` and override only what has rules."""

    sport: ClassVar[Sport]

    def discipline_label(self, discipline: Any, lang: Lang) -> str | None:
        return None

    def discipline_tag(self, event: Any) -> Tag | None:
        return None

    def resolve(self, event: E, subjects: list[Subject]) -> E:
        return event

    def infer(self, event: E, cues: Sequence[str]) -> E:
        return event


_REGISTRY: dict[Sport, SportModule[Any]] = {}


def register(module: SportModule[Any]) -> None:
    _REGISTRY[module.sport] = module


def get(sport: Sport) -> SportModule[Any]:
    return _REGISTRY[sport]
