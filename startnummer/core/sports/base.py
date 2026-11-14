"""Sport-specific inference hooks and module registry."""

from collections.abc import Sequence
from typing import Any, ClassVar, Protocol, TypeVar

from startnummer.core.enums import Lang, Sport
from startnummer.core.models import SportEvent, Subject, Tag

E = TypeVar("E", bound=SportEvent)


class SportModule(Protocol[E]):
    sport: Sport

    # Fresh, empty event of this sport's type; the pipeline constructs one per
    # photo before infer/resolve fill it.
    def new_event(self) -> E: ...

    def discipline_label(self, discipline: Any, lang: Lang) -> str | None: ...

    def discipline_tag(self, event: E) -> Tag | None: ...

    # Returns the event with code-defined fields resolved (e.g. distance from entries).
    def resolve(self, event: E, subjects: list[Subject]) -> E: ...

    # Refine the event using detected object labels, such as "baton" or "hurdle".
    def infer(self, event: E, cues: Sequence[str]) -> E: ...

    # Localized event phrase for prose, ready to append after the athlete list:
    # None when the event has no discipline (award ceremony, group shot).
    def discipline_phrase(self, event: E, lang: Lang) -> str | None: ...


class SportBase:
    """Default hooks leave events unchanged and return no labels or tags.

    Subclasses set sport and implement new_event().
    """

    sport: ClassVar[Sport]

    def new_event(self) -> SportEvent:
        raise NotImplementedError(f"{type(self).__name__} must implement new_event")

    def discipline_label(self, discipline: Any, lang: Lang) -> str | None:
        return None

    def discipline_tag(self, event: Any) -> Tag | None:
        return None

    def resolve(self, event: E, subjects: list[Subject]) -> E:
        return event

    def infer(self, event: E, cues: Sequence[str]) -> E:
        return event

    def discipline_phrase(self, event: Any, lang: Lang) -> str | None:
        return None


_REGISTRY: dict[Sport, SportModule[Any]] = {}


def register(module: SportModule[Any]) -> None:
    _REGISTRY[module.sport] = module


def get(sport: Sport) -> SportModule[Any]:
    return _REGISTRY[sport]
