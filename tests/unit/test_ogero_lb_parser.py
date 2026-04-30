"""Unit tests for the Ogero (Lebanon) HTML parsers."""

from pathlib import Path

import pytest
from carriers_sync.providers.base import UnknownFetchError
from carriers_sync.providers.ogero_lb import (
    parse_consumption,
    parse_number_list,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_number_list_extracts_phone_dsl_pairs():
    html = load("ogero_dashboard_response.html")
    pairs = parse_number_list(html)
    assert pairs == [
        ("09111111", "D100001"),
        ("09222222", "D100002"),
        ("09333333", "D100003"),
    ]


def test_parse_number_list_returns_empty_when_select_missing():
    html = "<html><body>no select</body></html>"
    assert parse_number_list(html) == []


def test_parse_consumption_gb():
    html = load("ogero_dashboard_response.html")
    consumed, quota = parse_consumption(html)
    assert consumed == pytest.approx(100.0)
    assert quota == pytest.approx(400.0)


def test_parse_consumption_handles_mb():
    """Hypothetical low-tier line might report MB, not GB."""
    html = """
    <div class="MyOgeroDashboardSection2Consumption">
      <b>Consumption</b>500 / 1024 MB FUP
    </div>
    """
    consumed, quota = parse_consumption(html)
    assert consumed == pytest.approx(500 / 1024, abs=0.001)
    assert quota == pytest.approx(1.0)


def test_parse_consumption_raises_when_section_missing():
    html = "<html><body>no consumption section</body></html>"
    with pytest.raises(UnknownFetchError, match="consumption section"):
        parse_consumption(html)


def test_parse_consumption_raises_when_section_present_but_unparseable():
    html = """
    <div class="MyOgeroDashboardSection2Consumption">
      <b>Consumption</b>(no data this cycle)
    </div>
    """
    with pytest.raises(UnknownFetchError):
        parse_consumption(html)
