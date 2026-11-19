"""Competition rosters from ergebnisse.leichtathletik.de entries or results."""

from pathlib import Path

from bs4 import BeautifulSoup

from startnummer.adapters.entrylist.names import parse_name
from startnummer.adapters.entrylist.resultoverview import parse_results
from startnummer.core.enums import NameOrder
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete
from startnummer.core.sports.athletics import AthleticsDiscipline

DISCIPLINE_ABBREVIATIONS: dict[str, AthleticsDiscipline] = {
    "50M": AthleticsDiscipline.M_50,
    "60M": AthleticsDiscipline.M_60,
    "75M": AthleticsDiscipline.M_75,
    "80M": AthleticsDiscipline.M_80,
    "100": AthleticsDiscipline.M_100,
    "150": AthleticsDiscipline.M_150,
    "200": AthleticsDiscipline.M_200,
    "300": AthleticsDiscipline.M_300,
    "400": AthleticsDiscipline.M_400,
    "600": AthleticsDiscipline.M_600,
    "800": AthleticsDiscipline.M_800,
    "1K0": AthleticsDiscipline.M_1K,
    "1K5": AthleticsDiscipline.M_1K5,
    "2000": AthleticsDiscipline.M_2K,
    "3K0": AthleticsDiscipline.M_3K,
    "5K0": AthleticsDiscipline.M_5K,
    "10K": AthleticsDiscipline.M_10K,
    "4x5": AthleticsDiscipline.RELAY_4x50,
    "4x7": AthleticsDiscipline.RELAY_4x75,
    "4x1": AthleticsDiscipline.RELAY_4x100,
    "4x2": AthleticsDiscipline.RELAY_4x200,
    "4x4": AthleticsDiscipline.RELAY_4x400,
    "3x8": AthleticsDiscipline.RELAY_3x800,
    "3x1": AthleticsDiscipline.RELAY_3x1K,
    "60H": AthleticsDiscipline.HURDLES_60,
    "80H": AthleticsDiscipline.HURDLES_80,
    "10H": AthleticsDiscipline.HURDLES_100,
    "11H": AthleticsDiscipline.HURDLES_110,
    "30H": AthleticsDiscipline.HURDLES_300,
    "40H": AthleticsDiscipline.HURDLES_400,
    "15H": AthleticsDiscipline.STEEPLECHASE,
    "2KH": AthleticsDiscipline.STEEPLECHASE,
    "3KH": AthleticsDiscipline.STEEPLECHASE,
    "WEI": AthleticsDiscipline.LONG_JUMP,
    "WEZ": AthleticsDiscipline.LONG_JUMP,
    "DRE": AthleticsDiscipline.TRIPLE_JUMP,
    "HOC": AthleticsDiscipline.HIGH_JUMP,
    "STA": AthleticsDiscipline.POLE_VAULT,
    "KUG": AthleticsDiscipline.SHOT_PUT,
    "SPE": AthleticsDiscipline.JAVELIN,
    "DIS": AthleticsDiscipline.DISCUS,
    "HAM": AthleticsDiscipline.HAMMER,
    "BAL": AthleticsDiscipline.BALL,
    "SCH": AthleticsDiscipline.BALL,
    "1G": AthleticsDiscipline.WALKING,
    "3G": AthleticsDiscipline.WALKING,
    "5G": AthleticsDiscipline.WALKING,
}


def _map_discipline(abbreviation: str, mapping: dict[str, AthleticsDiscipline]) -> AthleticsDiscipline:
    code = abbreviation.strip()
    return mapping.get(code) or mapping.get(code.replace("X", "x"), AthleticsDiscipline.OTHER)


class UnsupportedRosterPage(ValueError):
    pass


class LeichtathletikDeEntryListParser:
    def __init__(self, abbreviations: dict[str, AthleticsDiscipline] | None = None) -> None:
        self._abbreviations = abbreviations or DISCIPLINE_ABBREVIATIONS

    def parse(self, source: str, *, name_order: NameOrder = NameOrder.AUTO) -> EntryList:
        html = self._load(source)
        return self.parse_content(html, name_order=name_order)

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
        return self.parse_content(raw_html)

    def parse_content(self, raw_html: str, *, name_order: NameOrder = NameOrder.AUTO) -> EntryList:
        """Parse already-fetched HTML; transport belongs to the app boundary."""
        table = EntryList(name_order=name_order)
        try:
            html = BeautifulSoup(raw_html, features="html.parser")
            table.competition = ""
            if html.select_one(".listheader, .entryline > .col-3") is not None:
                table.athletes, table.name_parsing = parse_results(html, name_order=name_order)
                return table
            entries = html.find_all("div", {"class": "entryline"})
            if not entries and not html.select_one("#seltecdlv, .blocktable") and html.get_text(strip=True):
                raise UnsupportedRosterPage("Unsupported roster page")
            for entry in entries:
                divs = entry.find_all("div")
                if len(divs) < 9:
                    raise ValueError("Malformed Competitoroverview entry row")
                bib = divs[1].get_text().strip()
                raw_name = divs[3].get_text(" ", strip=True)
                club = divs[4].get_text().strip()
                year_birth = int(divs[7].get_text().strip()) if divs[7].get_text().strip() else None

                name, parsed_name = parse_name(raw_name, name_order)

                disciplines: list[AthleticsDiscipline] = []
                for a in divs[8].find_all("a"):
                    discipline = a.get_text().strip()
                    disciplines.append(_map_discipline(discipline, self._abbreviations))

                athlete = Athlete(name=name, bib=bib, club=club, year_birth=year_birth, entered_events=disciplines)
                table.athletes.append(athlete)
                table.name_parsing.append(parsed_name)
        except (AttributeError, IndexError) as e:
            raise ValueError("Malformed Competitoroverview HTML") from e

        return table


__all__ = ["LeichtathletikDeEntryListParser", "DISCIPLINE_ABBREVIATIONS", "Athlete"]
