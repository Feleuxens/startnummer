"""Synthetic counterparts of the site's competitor, result, and relay layouts."""

from html import escape

import pytest

from startnummer.adapters.entrylist.ergebnisse_leichtathletik_de import LeichtathletikDeEntryListParser
from startnummer.adapters.entrylist.resultoverview import result_discipline


def competitor_row(*, bib="12", name="Example Alex", club="Example Club", year="2006", events=("100",)):
    links = "".join(f"<a>{escape(event)}</a>" for event in events)
    return f"""<div class="entryline">
    <div class="col-1"><div class="firstline">{escape(bib)}</div></div>
    <div class="col-2"><div class="firstline">{escape(name)}</div><div class="secondline">{escape(club)}</div></div>
    <div class="col-42p"><div class="firstline">U20</div><div class="secondline">{escape(year)}</div></div>
    <div class="col-last"><div>{links}</div></div></div>"""


def result_row(*, bib="12", name="Example Alex", club="Example Club", year="2006", rank="1"):
    return f"""<div class="entryline">
    <div class="col-1"><div class="firstline">{escape(rank)}</div><div class="secondline">{escape(bib)}</div></div>
    <div class="col-2"><div class="firstline"><a>{escape(name)}</a></div>
    <div class="secondline">{escape(club)}</div></div>
    <div class="col-3"><div class="firstline">U20</div><div class="secondline">{escape(year)}</div></div>
    <div class="col-4"><div class="firstline">12,34</div><div class="secondline">987</div></div>
    <div class="col-4"><div class="firstline">345</div></div>
    <div class="col-detailresult"><div class="firstline">5,00</div></div></div>"""


def result_section(heading, *rows):
    return f"""<div class="listheader"><div><div class="leftheader"><a>{escape(heading)}</a></div>
    <div class="rightheader">Results</div></div><div>01.06.2025 16:15</div></div>
    <div class="runblock classblock"><div class="resultblock">
    <div class="blocktable">{"".join(rows)}</div></div></div>"""


def results_html():
    return result_section("100m U20 Zeitläufe", result_row(bib="345")) + result_section(
        "Weitsprung U20 Vor/Endkampf", result_row(bib="345", rank="2")
    )


@pytest.mark.parametrize("bib", ["12", ""])
def test_competitor_pages_keep_existing_names_bibs_and_disciplines(bib):
    roster = LeichtathletikDeEntryListParser().parse_content(competitor_row(bib=bib, events=("100", "WEI")))
    athlete = roster.athletes[0]
    assert (athlete.name, athlete.bib, athlete.club, athlete.year_birth) == ("Alex Example", bib, "Example Club", 2006)
    assert athlete.entered_events == ["100m", "long_jump"]
    assert roster.competition == ""


@pytest.mark.parametrize(
    "html",
    [
        competitor_row(events=("60M", "60H")),
        result_section("60m Männliche Jugend U20 Finale", result_row())
        + result_section("60m Hürden Männliche Jugend U20 Finale", result_row()),
    ],
    ids=["competitoroverview", "resultoverview"],
)
def test_rosters_distinguish_60m_flat_from_60m_hurdles(html):
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert len(roster.athletes) == 1
    assert roster.athletes[0].entered_events == ["60m", "60mH"]


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (("50M", "75M", "80M", "80H"), ["50m", "75m", "80m", "80mH"]),
        (
            ("4X5", "4X7", "4X1", "4X2", "4X4", "3X8", "3X1"),
            [
                "4x50m",
                "4x75m",
                "4x100m",
                "4x200m",
                "4x400m",
                "3x800m",
                "3x1000m",
            ],
        ),
        (("4x1", "WEZ", "SCH", "1G", "3G"), ["4x100m", "long_jump", "ball", "walking", "walking"]),
    ],
    ids=["flat-races-and-hurdles", "uppercase-relays", "discipline-aliases"],
)
def test_competitor_pages_read_supported_discipline_codes(codes, expected):
    roster = LeichtathletikDeEntryListParser().parse_content(competitor_row(events=codes))
    assert roster.athletes[0].entered_events == expected


def test_results_read_the_bib_not_rank_and_combine_repeated_events():
    roster = LeichtathletikDeEntryListParser().parse_content(results_html())
    assert len(roster.athletes) == 1
    athlete = roster.athletes[0]
    assert (athlete.name, athlete.bib, athlete.club, athlete.year_birth) == (
        "Alex Example",
        "345",
        "Example Club",
        2006,
    )
    assert athlete.entered_events == ["100m", "long_jump"]
    assert roster.competition == ""


def test_multi_event_results_merge_class_and_overall_rows_without_inventing_a_discipline():
    html = "".join(
        result_section(event, result_row(), result_row())
        for event in (
            "100m Männliche Jugend U20 Zehnkampf",
            "Hochsprung U20 Zehnkampf",
            "Kugelstoß U20 Zehnkampf",
            "Zehnkampf U20",
        )
    )
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert len(roster.athletes) == 1
    assert roster.athletes[0].entered_events == ["100m", "high_jump", "shot_put"]


def test_different_bibs_are_kept_even_when_personal_details_match():
    html = result_section("100m Zeitläufe", result_row(bib="12"), result_row(bib="77"))
    assert [a.bib for a in LeichtathletikDeEntryListParser().parse_content(html).athletes] == ["12", "77"]


def test_result_bibs_can_keep_leading_zeros_and_do_not_require_a_finish_position():
    html = result_section("100m Zeitläufe", result_row(bib="0012", rank="n.a."))
    assert LeichtathletikDeEntryListParser().parse_content(html).athletes[0].bib == "0012"


def test_missing_result_bib_is_not_replaced_with_rank_and_repeated_names_are_consolidated():
    html = result_section("100m Zeitläufe", result_row(bib=""), result_row(bib="", rank="2"))
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert len(roster.athletes) == 1 and roster.athletes[0].bib is None


def test_shared_bib_with_conflicting_identity_is_rejected():
    html = result_section("100m Zeitläufe", result_row(), result_row(name="Other Sam"))
    with pytest.raises(ValueError, match="Conflicting athlete details"):
        LeichtathletikDeEntryListParser().parse_content(html)


def test_relays_merge_known_members_and_keep_relay_only_people_without_inventing_bibs():
    html = result_section("100m Zeitläufe", result_row()) + result_section(
        "4x100m U20 Zeitläufe",
        result_row(bib="", name="Example Club 1", year="", club="Example, Alex (2006); Other, Sam (2005);"),
    )
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert len(roster.athletes) == 2
    known, relay_only = roster.athletes
    assert known.name == "Alex Example" and known.bib == "12" and known.entered_events == ["100m", "4x100m"]
    assert relay_only.name == "Sam Other" and relay_only.bib is None
    assert relay_only.club == "Example Club" and relay_only.year_birth == 2005
    assert relay_only.entered_events == ["4x100m"]


def test_ambiguous_relay_identity_never_selects_one_of_two_bibs():
    html = result_section("100m Zeitläufe", result_row(bib="12"), result_row(bib="77")) + result_section(
        "4x100m Zeitläufe", result_row(bib="", name="Example Club", year="", club="Example, Alex (2006);")
    )
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert [a.bib for a in roster.athletes] == ["12", "77", None]
    assert roster.athletes[-1].entered_events == ["4x100m"]


def test_unsupported_relay_discipline_does_not_turn_a_team_into_an_athlete():
    html = result_section(
        "4x1500m Zeitläufe",
        result_row(bib="", name="Example Club", year="", club="Example, Alex (2006); Other, Sam (2005);"),
    )
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert [athlete.name for athlete in roster.athletes] == ["Alex Example", "Sam Other"]
    assert all(athlete.bib is None and athlete.entered_events == [] for athlete in roster.athletes)


def test_names_with_commas_and_multiple_given_names_are_preserved():
    html = result_section("100m Zeitläufe", result_row(name="von Example, Alex Sam"))
    assert LeichtathletikDeEntryListParser().parse_content(html).athletes[0].name == "Alex Sam von Example"


@pytest.mark.parametrize(
    "row",
    [
        '<div class="entryline"><div class="col-1"></div></div>',
        result_row(name=""),
        result_row(year="unknown"),
        result_row(bib="rank 1"),
    ],
)
def test_malformed_result_rows_fail_instead_of_becoming_incorrect_roster_entries(row):
    with pytest.raises(ValueError):
        LeichtathletikDeEntryListParser().parse_content(result_section("100m", row))


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("50m Kinder M11 Finale", "50m"),
        ("75m Jugend W13 Finale", "75m"),
        ("80m Finale", "80m"),
        ("80m Hürden Jugend M15 Finale", "80mH"),
        ("100m W, WJU20 Zeitläufe", "100m"),
        ("1500m M U20", "1500m"),
        ("100m Hürden Frauen", "100mH"),
        ("100m Hürdenlauf Frauen", "100mH"),
        ("110 m Hürden U18", "110mH"),
        ("2000m Hindernis U20", "steeplechase"),
        ("2000m Hindernislauf U20", "steeplechase"),
        ("5000m Bahngehen U20", "walking"),
        ("4 x 100 m Staffel U20", "4x100m"),
        ("Kugelstoß U20", "shot_put"),
        ("Stabhochsprung U20", "pole_vault"),
        ("Dreisprung U20", "triple_jump"),
        ("Schlagballwurf Kinder M11 Finale", "ball"),
        ("Siebenkampf Frauen", None),
        ("90m Hürden U16", None),
        ("Unbekannter Wettbewerb", None),
    ],
)
def test_result_discipline_names_only_map_supported_events(heading, expected):
    assert result_discipline(heading) == expected
