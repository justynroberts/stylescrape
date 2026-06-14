"""Unit tests for the aggregator — colour parsing, clustering, font role inference."""

from __future__ import annotations

from stylescrape.aggregator import (
    _cluster_colors,
    _color_distance,
    _font_role,
    _is_dark,
    _non_system_font_first,
    _parse_color,
    _rgb_to_hex,
    aggregate,
)
from stylescrape.types import RawCapture


class TestParseColor:
    def test_hex_six(self):
        assert _parse_color("#ff8800") == (255, 136, 0, 1.0)

    def test_hex_three(self):
        assert _parse_color("#f80") == (255, 136, 0, 1.0)

    def test_rgb(self):
        assert _parse_color("rgb(10, 20, 30)") == (10, 20, 30, 1.0)

    def test_rgba(self):
        r = _parse_color("rgba(10, 20, 30, 0.5)")
        assert r == (10, 20, 30, 0.5)

    def test_transparent(self):
        assert _parse_color("transparent") is None
        assert _parse_color("rgba(0, 0, 0, 0)") is None

    def test_blank(self):
        assert _parse_color("") is None
        assert _parse_color("inherit") is None


class TestRgbToHex:
    def test_basic(self):
        assert _rgb_to_hex(255, 136, 0) == "#FF8800"

    def test_round_trip(self):
        for hex_in in ("#0F0F11", "#5E6AD2", "#E8E8ED"):
            parsed = _parse_color(hex_in)
            assert parsed is not None
            assert _rgb_to_hex(*parsed[:3]) == hex_in


class TestColorDistance:
    def test_identical_is_zero(self):
        assert _color_distance((100, 100, 100), (100, 100, 100)) < 0.5

    def test_far_apart(self):
        # Black vs white: should be large under either metric
        assert _color_distance((0, 0, 0), (255, 255, 255)) > 50


class TestClustering:
    def test_near_duplicates_collapse(self):
        # Two near-identical near-blacks plus one distinct violet
        items = [
            ((15, 15, 17), "background-color", "body"),
            ((16, 16, 18), "background-color", "main"),
            ((94, 106, 210), "color", "a"),
        ]
        clusters = _cluster_colors(items, threshold=10.0)
        # Two clusters: the near-blacks merged, the violet on its own
        assert len(clusters) == 2
        # Most frequent (the merged blacks) sorts first
        assert clusters[0][1] == 2

    def test_distant_colours_stay_separate(self):
        items = [
            ((255, 0, 0), "color", "a"),
            ((0, 255, 0), "color", "b"),
            ((0, 0, 255), "color", "c"),
        ]
        clusters = _cluster_colors(items, threshold=10.0)
        assert len(clusters) == 3


class TestIsDark:
    def test_dark_bg(self):
        assert _is_dark((15, 15, 17))

    def test_light_bg(self):
        assert not _is_dark((250, 250, 250))


class TestFontRole:
    def test_mono(self):
        assert _font_role("JetBrains Mono, monospace") == "mono"
        assert _font_role("Consolas, monospace") == "mono"

    def test_sans(self):
        assert _font_role("Inter, -apple-system, sans-serif") == "sans"

    def test_serif(self):
        assert _font_role("Georgia, serif") == "serif"


class TestNonSystemFontFirst:
    def test_picks_branded_font(self):
        assert _non_system_font_first("Inter, -apple-system, sans-serif") == "Inter"

    def test_falls_back_when_all_system(self):
        assert _non_system_font_first("Arial, sans-serif") == "Arial"


def _fake_capture(sampled=None, dom_signals=None) -> RawCapture:
    return RawCapture(
        url="https://example.com",
        title="Example",
        sampled_styles=sampled or {},
        dom_signals=dom_signals or {"bodyBg": "rgb(255, 255, 255)"},
    )


class TestAggregateEndToEnd:
    def test_empty_capture_does_not_crash(self):
        tokens = aggregate(_fake_capture())
        assert tokens.url == "https://example.com"
        assert tokens.colors == []
        assert tokens.typography.size_scale == []

    def test_dark_scheme_detected_from_body(self):
        cap = _fake_capture(
            sampled={"body": {"background-color": "rgb(15, 15, 17)", "color": "rgb(232, 232, 237)"}},
            dom_signals={"bodyBg": "rgb(15, 15, 17)"},
        )
        tokens = aggregate(cap)
        assert tokens.scheme == "dark"
        # Body background made it into the palette
        hexes = {c.hex for c in tokens.colors}
        assert "#0F0F11" in hexes

    def test_typography_extracted(self):
        cap = _fake_capture(
            sampled={
                "body": {
                    "font-family": "Inter, sans-serif",
                    "font-size": "16px",
                    "font-weight": "400",
                    "line-height": "24px",
                },
                "h1": {
                    "font-family": "Inter, sans-serif",
                    "font-size": "32px",
                    "font-weight": "700",
                    "line-height": "40px",
                },
                "code": {
                    "font-family": "JetBrains Mono, monospace",
                    "font-size": "14px",
                    "font-weight": "400",
                    "line-height": "20px",
                },
            }
        )
        tokens = aggregate(cap)
        assert "sans" in tokens.typography.font_families
        assert "mono" in tokens.typography.font_families
        assert "16px" in tokens.typography.size_scale
        assert "32px" in tokens.typography.size_scale
        assert 400 in tokens.typography.weights
        assert 700 in tokens.typography.weights
        # Scale is sorted ascending
        nums = [int(s.replace("px", "")) for s in tokens.typography.size_scale if s.endswith("px")]
        assert nums == sorted(nums)

    def test_radii_and_shadows(self):
        cap = _fake_capture(
            sampled={
                "button:not([disabled])": {"border-radius": "6px", "box-shadow": "0 1px 2px rgba(0,0,0,.1)"},
                "[class*='card']": {"border-radius": "12px", "box-shadow": "0 4px 12px rgba(0,0,0,.2)"},
            }
        )
        tokens = aggregate(cap)
        assert "6px" in tokens.shape.radii
        assert "12px" in tokens.shape.radii
        assert len(tokens.shape.shadows) == 2

    def test_motion_extracted(self):
        cap = _fake_capture(
            sampled={
                "button:not([disabled])": {"transition": "background-color 200ms ease-in-out"},
                "a": {"transition": "color 150ms cubic-bezier(0.4, 0, 0.2, 1)"},
            }
        )
        tokens = aggregate(cap)
        assert "200ms" in tokens.motion.durations
        assert "150ms" in tokens.motion.durations
        # Either an ease keyword or cubic-bezier should be captured
        assert tokens.motion.easings
