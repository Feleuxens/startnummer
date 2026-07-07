"""Entry-list parser for ergebnisse.leichtathletik.de Competitoroverview pages"""

from pathlib import Path

from bs4 import BeautifulSoup

from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete

DISCIPLINE_ABBREVIATIONS: dict[str, str] = {
    # "100": "100m",
    # "4x50": "4x50m",
    # "60H": "60mH",
    # "WEI": "Weitsprung",
    "100": "100m",
    "150": "150m",
    "200": "200m",
    "300": "300m",
    "400": "400m",
    "600": "600m",
    "800": "800m",
    "1K0": "1000m",
    "1K5": "1500m",
    "2000": "2000m",
    "3K0": "3000m",
    "5K0": "5000m",
    "10K": "10000m",
    "4x5": "4x50m",
    "4x7": "4x75m",
    "4x1": "4x100m",
    "4x2": "4x200m",
    "4x4": "4x400m",
    "3x8": "3x800m",
    "3x1": "3x1000m",
    "60H": "60mH",
    "80H": "80mH",
    "10H": "100mH",
    "11H": "110mH",
    "30H": "300mH",
    "40H": "400mH",
    "15H": "steeplechase",
    "2KH": "steeplechase",
    "3KH": "steeplechase",
    "WEI": "long_jump",
    "DRE": "triple_jump",
    "HOC": "high_jump",
    "STA": "pole_vault",
    "KUG": "shot_put",
    "SPE": "javelin",
    "DIS": "discus",
    "HAM": "hammer",
    "BAL": "ball",
    "5G": "5000mW",  # walking

}


def _reorder_name(raw: str) -> str:
    # "Lastname, Firstname" -> "Firstname Lastname"; anything without a comma
    # (some u12 rows) passes through unchanged.
    if "," in raw:
        last, _, first = raw.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    return " ".join(raw.split())


def _map_discipline(abbreviation: str, mapping: dict[str, str]) -> str:
    return mapping.get(abbreviation.strip(), abbreviation.strip())


class LeichtathletikDeEntryListParser:
    def __init__(self, abbreviations: dict[str, str] | None = None) -> None:
        self._abbreviations = abbreviations or DISCIPLINE_ABBREVIATIONS

    def parse(self, source: str) -> EntryList:
        html = self._load(source)
        return self._parse_html(html)

    def _load(self, source: str) -> str:
        if source.lstrip().startswith("<"):
            return source  # raw HTML
        path = Path(source)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        if source.startswith("http"):
            import httpx

            response = httpx.get(source, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            return response.text
        raise FileNotFoundError(source)

    def _parse_html(self, raw_html: str) -> EntryList:
        table = EntryList()
        try:
            html = BeautifulSoup(raw_html, features="html.parser")
            table.competition = "Test Comp"
            entries = html.find_all("div", {"class": "entryline"})
            for entry in entries:
                divs = entry.findAll("div")
                bib = divs[1].getText().strip()
                raw_name = divs[3].getText().strip().split()
                club = divs[4].getText().strip()
                year_birth = int(divs[7].getText().strip()) if divs[7].getText().strip() else None

                if year_birth:
                    name = " ".join(raw_name[1:]) + " " + raw_name[0]
                else:
                    name = " ".join(raw_name)

                disciplines = []
                for a in divs[8].findAll("a"):
                    discipline = a.getText().strip()
                    disciplines.append(_map_discipline(discipline, self._abbreviations))

                athlete = Athlete(name=name, bib=bib, club=club, year_birth=year_birth, entered_events=disciplines)
                table.athletes.append(athlete)
        except AttributeError as e:
            print(e)

        return table


__all__ = ["LeichtathletikDeEntryListParser", "DISCIPLINE_ABBREVIATIONS", "Athlete"]
