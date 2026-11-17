"""Normalize individual and relay results from ergebnisse.leichtathletik.de."""

import re

from bs4 import BeautifulSoup, Tag

from startnummer.core.models import Athlete
from startnummer.core.sports.athletics import AthleticsDiscipline


def result_discipline(heading: str) -> AthleticsDiscipline | None:
    text = " ".join(heading.casefold().replace("×", "x").split())
    text = re.sub(r"(?<=\d)\s+(?=[mx])|(?<=x)\s+(?=\d)", "", text)
    family = re.match(r"^(\d+)m\s*(hürden(?:lauf)?|hindernis(?:lauf)?|(?:bahn)?gehen)\b", text)
    if family:
        if family[2].startswith("hindernis"):
            return AthleticsDiscipline.STEEPLECHASE
        if family[2].endswith("gehen"):
            return AthleticsDiscipline.WALKING
        return next((d for d in AthleticsDiscipline if d.value == family[1] + "mH"), None)
    labels = {d.de.casefold(): d for d in AthleticsDiscipline if d.de}
    labels.update({d.value.casefold(): d for d in AthleticsDiscipline if re.fullmatch(r"(?:[34]x)?\d+m", d.value)})
    labels["kugelstoß".casefold()] = AthleticsDiscipline.SHOT_PUT
    for label in sorted(labels, key=len, reverse=True):
        if text == label or text.startswith(label + " ") or text.startswith(label + ","):
            return labels[label]
    return None


def _text(column: Tag, line: str) -> str:
    element = column.find("div", class_=line, recursive=False)
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def _name(raw: str) -> str:
    if "," in raw:
        last, _, first = raw.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    words = raw.split()
    return " ".join(words[1:] + words[:1])


def _identity(athlete: Athlete) -> tuple[str, str, int | None]:
    return athlete.name.casefold(), (athlete.club or "").casefold(), athlete.year_birth


def _add_event(athlete: Athlete, discipline: AthleticsDiscipline | None) -> None:
    if discipline is not None and discipline.value not in athlete.entered_events:
        athlete.entered_events.append(discipline.value)


def _relay_members(raw: str, club: str) -> list[Athlete]:
    members = []
    for part in raw.split(";"):
        if not part.strip():
            continue
        match = re.fullmatch(r"(.+?,.+?)\s*\((\d{4})\)", part.strip())
        if match is None:
            raise ValueError("Malformed Resultoverview relay members")
        members.append(Athlete(name=_name(match[1]), club=club, year_birth=int(match[2])))
    if not members:
        raise ValueError("Resultoverview relay has no named members")
    return members


def parse_results(html: BeautifulSoup) -> list[Athlete]:
    athletes: list[Athlete] = []
    by_bib: dict[str, Athlete] = {}
    without_bib: dict[tuple[str, str, int | None], Athlete] = {}
    relays: list[tuple[Athlete, AthleticsDiscipline | None]] = []
    discipline = None
    relay = False
    for row in html.select(".listheader, .entryline"):
        if "listheader" in row.get("class", []):
            heading = row.select_one(".leftheader")
            text = (heading or row).get_text(" ", strip=True)
            discipline = result_discipline(text)
            relay = re.match(r"^\s*\d+\s*[x×]\s*\d+", text, re.I) is not None
            continue
        columns = [row.find("div", class_=f"col-{number}", recursive=False) for number in (1, 2, 3)]
        if any(column is None for column in columns):
            raise ValueError("Malformed Resultoverview entry row")
        number, person, birth = columns
        raw_name = _text(person, "firstline")
        bib = _text(number, "secondline") or None
        year = _text(birth, "secondline")
        club = _text(person, "secondline")
        if not raw_name:
            raise ValueError("Resultoverview entry has no name")
        if relay and not year:
            relays.extend((member, discipline) for member in _relay_members(club, raw_name))
            continue
        if (bib and not bib.isdecimal()) or (year and not re.fullmatch(r"\d{4}", year)):
            raise ValueError("Invalid Resultoverview bib or birth year")
        athlete = Athlete(name=_name(raw_name), bib=bib, club=club or None, year_birth=int(year) if year else None)
        existing = by_bib.get(bib) if bib else without_bib.get(_identity(athlete))
        if existing is not None:
            if _identity(existing) != _identity(athlete):
                raise ValueError(f"Conflicting athlete details for bib {bib} in Resultoverview")
            _add_event(existing, discipline)
            continue
        _add_event(athlete, discipline)
        athletes.append(athlete)
        if bib:
            by_bib[bib] = athlete
        else:
            without_bib[_identity(athlete)] = athlete

    clubs = {athlete.club for athlete in athletes if athlete.club}
    for member, event in relays:
        # Relay headings can append a team number. Remove it only when the page
        # also contains exactly one matching club name on an individual result.
        if member.club not in clubs:
            matches = [club for club in clubs if re.fullmatch(re.escape(club) + r" \d+", member.club or "")]
            if len(matches) == 1:
                member.club = matches[0]
        matches = [athlete for athlete in athletes if _identity(athlete) == _identity(member)]
        if len(matches) == 1:
            _add_event(matches[0], event)
        else:
            existing = without_bib.get(_identity(member))
            if existing is None:
                athletes.append(member)
                without_bib[_identity(member)] = member
                existing = member
            _add_event(existing, event)
    return athletes
