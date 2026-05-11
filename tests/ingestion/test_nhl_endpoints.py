"""Tests for the season-handling helpers in
:mod:`puckbunny.ingestion.nhl.endpoints`.

The URL-builder helpers (``landing_url``, ``schedule_url``, etc.) are
covered indirectly by the loader test suites — they're thin enough
that direct tests would duplicate that coverage. The functions tested
here have richer behavior worth covering in isolation:

* :func:`format_season_id` — accepts ``int``, 8-digit ``str``, and
  ``YYYY-YY`` ``str``; rejects malformed and non-consecutive forms.
  Per D9 in ``docs/milestones/m2-nhl-ingestion.md`` this helper is
  the one place every CLI subcommand routes ``--season`` through, so
  its input contract is load-bearing.
* :func:`parse_season_range` — backfill CLI's range expansion.
* :func:`dates_in_season` — backfill CLI's day-walk discovery (D8).

The :func:`team_abbrevs` tests live in
``tests/ingestion/test_nhl_team_season.py`` next to the loader that
consumes them; not duplicated here.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import pytest

from puckbunny.ingestion.nhl.endpoints import (
    dates_in_season,
    format_season_id,
    parse_season_range,
)

# --------------------------------------------------------------------
# format_season_id
# --------------------------------------------------------------------


def test_format_season_id_accepts_int() -> None:
    assert format_season_id(20242025) == "20242025"


def test_format_season_id_accepts_eight_digit_string() -> None:
    assert format_season_id("20242025") == "20242025"


def test_format_season_id_accepts_yyyy_yy() -> None:
    """YYYY-YY is the human-readable form used in CLI flags."""
    assert format_season_id("2024-25") == "20242025"


def test_format_season_id_yyyy_yy_handles_decade_boundary() -> None:
    """Sanity check the ``(start_year + 1) % 100`` arithmetic at the
    century rollover. ``2099-00`` should normalize to ``20992100``."""
    assert format_season_id("2099-00") == "20992100"


def test_format_season_id_yyyy_yy_handles_zero_padded_suffix() -> None:
    """``2009-10`` is the historically real season and exercises the
    ``%02d``-padded suffix path."""
    assert format_season_id("2009-10") == "20092010"


def test_format_season_id_yyyy_yy_strips_whitespace() -> None:
    """Shells sometimes pass quoted args with stray whitespace; tolerate
    it rather than 404-ing on a malformed URL downstream."""
    assert format_season_id("  2024-25  ") == "20242025"


def test_format_season_id_yyyy_yy_rejects_non_consecutive() -> None:
    """Mismatched suffix (e.g. typo'd ``2024-26``) raises rather than
    silently re-normalizing — the user almost certainly meant
    ``2024-25`` and should know they got it wrong."""
    with pytest.raises(ValueError, match="non-consecutive suffix"):
        format_season_id("2024-26")


def test_format_season_id_eight_digit_rejects_non_consecutive() -> None:
    """Symmetry with the YYYY-YY branch: ``20242026`` is malformed and
    must raise, not silently produce a bogus URL."""
    with pytest.raises(ValueError, match="non-consecutive years"):
        format_season_id("20242026")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "2024",
        "abcdefgh",
        "2024_25",
        "2024-2025",
        "24-25",
        "2024-25-26",
    ],
)
def test_format_season_id_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        format_season_id(bad)


# --------------------------------------------------------------------
# parse_season_range
# --------------------------------------------------------------------


def test_parse_season_range_yyyy_yy_inclusive() -> None:
    """Both endpoints inclusive; YYYY-YY input."""
    assert parse_season_range("2015-16", "2017-18") == [
        "20152016",
        "20162017",
        "20172018",
    ]


def test_parse_season_range_eight_digit_inclusive() -> None:
    assert parse_season_range("20232024", "20242025") == ["20232024", "20242025"]


def test_parse_season_range_mixed_input_forms() -> None:
    """The two endpoints don't have to agree on shape."""
    assert parse_season_range("2015-16", 20172018) == [
        "20152016",
        "20162017",
        "20172018",
    ]


def test_parse_season_range_single_season() -> None:
    """``from`` == ``to`` returns a one-element list, not empty."""
    assert parse_season_range("2024-25", "2024-25") == ["20242025"]


def test_parse_season_range_rejects_reversed() -> None:
    """``to`` earlier than ``from`` is almost always a typo. Refuse
    rather than silently returning an empty list."""
    with pytest.raises(ValueError, match="earlier than"):
        parse_season_range("2024-25", "2015-16")


def test_parse_season_range_propagates_format_errors() -> None:
    """Malformed inputs raise from the underlying ``format_season_id``
    call — no swallowing."""
    with pytest.raises(ValueError):
        parse_season_range("not-a-season", "2024-25")


# --------------------------------------------------------------------
# dates_in_season
# --------------------------------------------------------------------


def test_dates_in_season_starts_sept_1() -> None:
    """First yielded date is Sept 1 of the start year — the wide-open
    window covers preseason cleanly."""
    first = next(iter(dates_in_season("2024-25")))
    assert first == date(2024, 9, 1)


def test_dates_in_season_ends_june_30() -> None:
    """Last yielded date is June 30 of the end year — wide enough to
    cover the Stanley Cup Final."""
    dates = list(dates_in_season("2024-25"))
    assert dates[-1] == date(2025, 6, 30)


def test_dates_in_season_is_inclusive_on_both_ends() -> None:
    """Sept 1 AND June 30 both appear in the list."""
    dates = list(dates_in_season("2024-25"))
    assert date(2024, 9, 1) in dates
    assert date(2025, 6, 30) in dates


def test_dates_in_season_count() -> None:
    """Sept 1 2024 → June 30 2025 inclusive is 303 days (30+31+30+31+
    31+28+31+30+31+30 = 303). 2024-25 spans Feb 2025 (28 days, not a
    leap year), confirming we're not off-by-one on either end."""
    dates = list(dates_in_season("2024-25"))
    assert len(dates) == 303


def test_dates_in_season_count_leap_year() -> None:
    """The 2023-24 season includes Feb 2024, which has 29 days. Count
    should be 304 instead of 303."""
    dates = list(dates_in_season("2023-24"))
    assert len(dates) == 304


def test_dates_in_season_chronological_order() -> None:
    """Yielded dates are strictly increasing by one day."""
    dates = list(dates_in_season("2024-25"))
    for prev, curr in pairwise(dates):
        assert (curr - prev).days == 1


def test_dates_in_season_accepts_eight_digit() -> None:
    """Same range whether you pass ``"20242025"`` or ``"2024-25"``."""
    assert list(dates_in_season("20242025")) == list(dates_in_season("2024-25"))


def test_dates_in_season_propagates_format_errors() -> None:
    with pytest.raises(ValueError):
        list(dates_in_season("not-a-season"))
