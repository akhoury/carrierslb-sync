"""Unit tests for the Touch (Lebanon) HTML parsers."""

from pathlib import Path

import pytest
from carriers_sync.providers.base import UnknownFetchError
from carriers_sync.providers.touch_lb import (
    parse_internet_usage,
    parse_number_list,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_number_list_extracts_all_options():
    html = load("touch_usage_response.html")
    numbers = parse_number_list(html)
    assert numbers == ["81111111", "81222222"]


def test_parse_number_list_returns_empty_when_select_missing():
    html = "<html><body>no select here</body></html>"
    assert parse_number_list(html) == []


def test_parse_internet_usage_gb_over_gb():
    html = load("touch_usage_response.html")
    consumed, quota = parse_internet_usage(html)
    assert consumed == pytest.approx(2.77)
    assert quota == pytest.approx(7.0)


def test_parse_internet_usage_mb_consumed_gb_quota():
    html = load("touch_usage_mb_response.html")
    consumed, quota = parse_internet_usage(html)
    # 10.31 MB → ~0.01 GB
    assert consumed == pytest.approx(10.31 / 1024, abs=0.001)
    assert quota == pytest.approx(25.0)


def test_parse_internet_usage_skips_voice_bundle_price():
    """The 'Local Minutes' bundle's <span class='price'>24 / 400 min</span>
    must NOT be picked up — only the Mobile Internet section's data line."""
    html = load("touch_usage_response.html")
    consumed, quota = parse_internet_usage(html)
    # If voice were picked up we'd see (24, 400) — confirm we got the data line.
    assert consumed != 24.0
    assert quota != 400.0


def test_parse_internet_usage_raises_when_no_internet_section():
    html = load("touch_no_internet_response.html")
    with pytest.raises(UnknownFetchError, match="Mobile Internet section"):
        parse_internet_usage(html)


def test_parse_internet_usage_raises_when_section_present_but_value_missing():
    html = """
    <html><body>
    <div class="unbilledInfo">
      <h5>Mobile Internet</h5>
      <p>(no usage data this billing cycle)</p>
    </div>
    </body></html>
    """
    with pytest.raises(UnknownFetchError):
        parse_internet_usage(html)
