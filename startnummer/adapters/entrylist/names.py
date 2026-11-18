"""Detect roster name order before normalizing uppercase name parts."""

from startnummer.core.enums import NameOrder
from startnummer.core.interfaces import RosterName

_PARTICLES = {
    "al",
    "da",
    "das",
    "de",
    "del",
    "della",
    "den",
    "der",
    "di",
    "dos",
    "du",
    "el",
    "la",
    "le",
    "ten",
    "ter",
    "van",
    "von",
    "zu",
    "zum",
    "zur",
}


def _initial(word: str) -> bool:
    return len(word.rstrip(".")) == 1 and word.rstrip(".").isalpha()


def _surname_length(words: list[str]) -> int:
    index = 0
    while index < len(words) - 1 and words[index].casefold() in _PARTICLES:
        index += 1
    end = min(index + 1, len(words) - 1)
    if words[index].isupper() and not _initial(words[index]):
        while end < len(words) - 1 and words[end].isupper() and not _initial(words[end]):
            end += 1
    return end


def _parse_name_order(raw: str, order: NameOrder) -> tuple[str, RosterName]:
    order = NameOrder(order)
    source = " ".join(raw.split())
    if not source:
        raise ValueError("Roster entry has no name")
    details = RosterName(source_name=source, order=order)
    if order is NameOrder.AS_WRITTEN:
        return source, details
    if "," in source:
        first, _, second = source.partition(",")
        parts = (first, second) if order is NameOrder.GIVEN_FIRST else (second, first)
        details.order = NameOrder.GIVEN_FIRST if order is NameOrder.GIVEN_FIRST else NameOrder.SURNAME_FIRST
        return " ".join(part.strip() for part in parts if part.strip()), details
    words = source.split()
    if len(words) == 1:
        details.order = NameOrder.AS_WRITTEN
        return source, details
    surname_length = _surname_length(words)
    if order is NameOrder.AUTO:
        if _initial(words[-1]):
            # Younger athletes may be listed with just a surname initial.
            details.order = NameOrder.GIVEN_FIRST
            return source, details
        capitals = [i for i, word in enumerate(words) if word.isupper() and not _initial(word)]
        if capitals and capitals == list(range(capitals[0], capitals[-1] + 1)) and len(capitals) < len(words):
            start, end = capitals[0], capitals[-1] + 1
            while start > 0 and words[start - 1].casefold() in _PARTICLES:
                start -= 1
            if end == len(words) and start > 0:
                details.order = NameOrder.GIVEN_FIRST
                return source, details
            if start == 0 and end < len(words):
                surname_length = max(surname_length, end)
                details.order = NameOrder.SURNAME_FIRST
                details.needs_review = all(word.casefold() in _PARTICLES for word in words[:end])
        if details.order is NameOrder.AUTO:
            if all(word.isupper() for word in words):
                details.order, details.needs_review = NameOrder.AS_WRITTEN, True
                return source, details
            details.order = NameOrder.SURNAME_FIRST
            details.needs_review = not _initial(words[0])
    if details.order is NameOrder.GIVEN_FIRST:
        return source, details
    return " ".join(words[surname_length:] + words[:surname_length]), details


def parse_name(raw: str, order: NameOrder = NameOrder.AUTO) -> tuple[str, RosterName]:
    name, details = _parse_name_order(raw, order)
    normalized = []
    for word in name.split():
        if not word.isupper() or _initial(word):
            normalized.append(word)
        elif word.casefold() in _PARTICLES:
            normalized.append(word.lower())
        else:
            normalized.append(word.title())
    return " ".join(normalized), details
