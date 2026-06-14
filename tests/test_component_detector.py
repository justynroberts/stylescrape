"""Unit tests for component pattern detection."""

from __future__ import annotations

from stylescrape.component_detector import detect
from stylescrape.types import RawCapture


def _cap(counts=None, classes=None, has=None, styles=None) -> RawCapture:
    return RawCapture(
        url="https://example.com",
        final_url="https://example.com",
        title="x",
        color_scheme_detected="light",
        sampled_styles=styles or {},
        stylesheet_custom_props={},
        dom_signals={"counts": counts or {}, "classes": classes or {}, "has": has or {}},
    )


def _by_name(patterns):
    return {p.name: p for p in patterns}


def test_navigation_sidebar_preferred_over_topbar():
    p = _by_name(detect(_cap(counts={"nav": 1}, classes={"sidebar": 5})))
    assert p["navigation"].present
    assert "Sidebar" in p["navigation"].notes


def test_navigation_inline_only_when_nothing_present():
    p = _by_name(detect(_cap()))
    assert not p["navigation"].present


def test_tables_count_surfaced():
    p = _by_name(detect(_cap(counts={"table": 3})))
    assert p["tables"].present
    assert "3" in p["tables"].notes


def test_cards_from_classnames():
    p = _by_name(detect(_cap(classes={"card": 7})))
    assert p["cards"].present
    assert "7" in p["cards"].notes


def test_modals_from_dialog_role_or_class():
    p_role = _by_name(detect(_cap(counts={"dialog": 1})))
    p_cls = _by_name(detect(_cap(classes={"modal": 2})))
    assert p_role["modals"].present
    assert p_cls["modals"].present


def test_treatment_captured_for_button():
    styles = {
        "button:not([disabled])": {
            "background-color": "rgb(94, 106, 210)",
            "color": "rgb(255, 255, 255)",
            "border-radius": "6px",
            "padding": "8px 16px",
        }
    }
    p = _by_name(detect(_cap(counts={"button": 5}, styles=styles)))
    assert p["buttons"].present
    assert p["buttons"].treatment["background-color"] == "rgb(94, 106, 210)"
    assert p["buttons"].treatment["border-radius"] == "6px"


def test_breadcrumbs_progress_toggles_via_has():
    p = _by_name(
        detect(_cap(has={"breadcrumbs": True, "progress": True, "toggle": True}))
    )
    assert p["breadcrumbs"].present
    assert p["progress_indicators"].present
    assert p["toggles_switches"].present


def test_returns_all_standard_patterns_even_when_absent():
    p = _by_name(detect(_cap()))
    expected = {
        "navigation",
        "buttons",
        "forms",
        "tables",
        "cards",
        "badges_chips",
        "alerts_toasts",
        "modals",
        "tabs",
        "dropdowns",
        "breadcrumbs",
        "progress_indicators",
        "toggles_switches",
    }
    assert expected.issubset(p.keys())
