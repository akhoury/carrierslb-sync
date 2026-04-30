import pytest
from carriers_sync.providers import PROVIDERS, get_provider
from carriers_sync.providers.alfa_lb import AlfaLbProvider
from carriers_sync.providers.ogero_lb import OgeroLbProvider
from carriers_sync.providers.touch_lb import TouchLbProvider


def test_alfa_registered():
    assert "alfa-lb" in PROVIDERS
    assert PROVIDERS["alfa-lb"] is AlfaLbProvider


def test_touch_registered():
    assert "touch-lb" in PROVIDERS
    assert PROVIDERS["touch-lb"] is TouchLbProvider


def test_ogero_registered():
    assert "ogero-lb" in PROVIDERS
    assert PROVIDERS["ogero-lb"] is OgeroLbProvider


def test_get_provider_returns_instance():
    p = get_provider("alfa-lb")
    assert isinstance(p, AlfaLbProvider)
    p2 = get_provider("touch-lb")
    assert isinstance(p2, TouchLbProvider)
    p3 = get_provider("ogero-lb")
    assert isinstance(p3, OgeroLbProvider)


def test_unknown_provider_raises():
    with pytest.raises(KeyError, match="unknown provider"):
        get_provider("nonexistent")


def test_touch_provider_has_correct_metadata():
    p = TouchLbProvider()
    assert p.id == "touch-lb"
    assert p.display_name == "Touch (Lebanon)"


def test_ogero_provider_has_correct_metadata():
    p = OgeroLbProvider()
    assert p.id == "ogero-lb"
    assert p.display_name == "Ogero (Lebanon)"
