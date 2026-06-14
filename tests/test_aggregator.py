"""Unit tests for the aggregator — colour parsing, clustering, font role inference."""

from __future__ import annotations

from stylescrape.aggregator import (
    _aggregate_layout,
    _cluster_colors,
    _color_distance,
    _detect_elevation_steps,
    _detect_spacing_base,
    _detect_type_scale,
    _font_role,
    _harvest_named_tokens,
    _infer_token_role,
    _is_dark,
    _layout_label,
    _name_for_ratio,
    _non_system_font_first,
    _parse_color,
    _px,
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


class TestPxParse:
    def test_px(self):
        assert _px("24px") == 24.0
        assert _px("1.5px") == 1.5

    def test_rem(self):
        assert _px("1rem") == 16.0

    def test_none(self):
        assert _px("auto") is None
        assert _px("") is None


class TestScaleNames:
    def test_major_third(self):
        assert _name_for_ratio(1.25) == "major-third"

    def test_perfect_fourth(self):
        assert _name_for_ratio(1.333) == "perfect-fourth"

    def test_golden_ratio(self):
        assert _name_for_ratio(1.618) == "golden"

    def test_arbitrary_ratio_is_custom(self):
        # Both values sit >0.05 from every named ratio so they fall through.
        assert _name_for_ratio(1.7) == "custom"
        assert _name_for_ratio(1.85) == "custom"

    def test_below_one(self):
        assert _name_for_ratio(0.9) == ""


class TestTypeScaleDetection:
    def test_major_third_scale(self):
        # 16, 20, 25 — major-third (1.25x)
        base, ratio, name = _detect_type_scale([16.0, 20.0, 25.0])
        assert base == 16.0
        assert 1.24 < ratio < 1.26
        assert name == "major-third"

    def test_perfect_fourth_scale(self):
        # 12, 16, 21.33 — perfect-fourth (1.333x)
        _base, ratio, name = _detect_type_scale([12.0, 16.0, 21.33])
        assert 1.32 < ratio < 1.35
        assert name == "perfect-fourth"

    def test_insufficient_data(self):
        _base, ratio, name = _detect_type_scale([16.0])
        assert ratio == 0.0 and name == ""


class TestSpacingBaseDetection:
    def test_eight_base(self):
        base, mults = _detect_spacing_base([8, 16, 24, 32, 48])
        assert base == 8
        assert set(mults) >= {1, 2, 3, 4, 6}

    def test_four_base(self):
        base, mults = _detect_spacing_base([4, 8, 12, 20])
        # Could be detected as 4 (preferred) or 8
        assert base in (4, 8)
        assert mults

    def test_no_consistent_base(self):
        base, _mults = _detect_spacing_base([3, 7, 11, 19])
        # No common base under our thresholds — should return 0
        assert base == 0


class TestLayoutLabel:
    def test_narrow(self):
        assert _layout_label(768.0) == "narrow-centered"

    def test_standard(self):
        assert _layout_label(1024.0) == "standard-centered"

    def test_wide(self):
        assert _layout_label(1280.0) == "wide-centered"

    def test_edge_to_edge(self):
        assert _layout_label(1920.0) == "edge-to-edge"

    def test_unknown(self):
        assert _layout_label(None) == "unknown"


class TestLayoutAggregate:
    def test_extracts_max_width_and_label(self):
        cap = RawCapture(
            url="https://x", title="x",
            sampled_styles={}, dom_signals={"bodyBg": "rgb(255,255,255)"},
            layout_samples={
                "main#0": {"max-width": "1024px", "display": "block"},
                "[class*='container']#1": {"max-width": "1024px"},
                "[class*='grid']#2": {"display": "grid", "grid-template-columns": "repeat(3, 1fr)", "gap": "24px"},
            },
        )
        layout = _aggregate_layout([cap])
        assert layout.max_content_width == "1024px"
        assert layout.layout_label == "standard-centered"
        assert "repeat(3, 1fr)" in layout.grid_patterns[0]
        assert "24px" in layout.common_gaps


class TestElevation:
    def test_steps_sorted_by_luminance(self):
        # Use background tones spaced widely enough that ΔE<5 won't collapse them.
        cap = RawCapture(
            url="https://x", title="x",
            sampled_styles={
                "body": {"background-color": "rgb(15, 15, 17)"},
                "main": {"background-color": "rgb(80, 80, 80)"},
                "[class*='card']": {"background-color": "rgb(200, 200, 200)"},
            },
            dom_signals={"bodyBg": "rgb(15, 15, 17)"},
        )
        steps = _detect_elevation_steps([cap])
        assert len(steps) >= 2  # At least the darks vs lights should split
        # Sorted dark→light
        assert steps[0].luminance < steps[-1].luminance
        assert steps[0].step == 1

    def test_no_backgrounds_returns_empty(self):
        cap = RawCapture(
            url="https://x", title="x",
            sampled_styles={"body": {"color": "rgb(0,0,0)"}},
            dom_signals={},
        )
        assert _detect_elevation_steps([cap]) == []


class TestNamedTokens:
    def test_infer_role(self):
        assert _infer_token_role("--color-primary") == "color"
        assert _infer_token_role("--bg-elevated") == "color"
        assert _infer_token_role("--space-3") == "spacing"
        assert _infer_token_role("--radius-md") == "radius"
        assert _infer_token_role("--duration-fast") == "motion"
        assert _infer_token_role("--font-sans") == "typography"
        assert _infer_token_role("--unknown-thing") == "other"

    def test_spacing_keyword_matches_spacing_suffix(self):
        # Regression: 'space' substring doesn't match 'spacing' literally — the
        # keyword list needs 'spacing' too. Real-world: Linear's
        # --editor-block-spacing used to fall into 'other'.
        assert _infer_token_role("--editor-block-spacing") == "spacing"
        assert _infer_token_role("--row-spacing") == "spacing"

    def test_border_radius_resolves_to_radius_not_color(self):
        # Regression: 'border' is a colour keyword and 'radius' is a radius
        # keyword; first match wins, so radius must be checked first.
        assert _infer_token_role("--border-radius") == "radius"
        assert _infer_token_role("--border-radius-sm") == "radius"

    def test_text_ambiguity_resolves_to_color(self):
        # 'text-*' tokens are usually text colour ("text-primary", "text-muted").
        # 'text' lives in the colour keyword list. Size tokens carry a size noun.
        assert _infer_token_role("--text-primary") == "color"
        assert _infer_token_role("--text-muted") == "color"

    def test_harvest_dedupes_and_sorts_by_display_role(self):
        cap1 = RawCapture(
            url="https://x", title="x", sampled_styles={}, dom_signals={},
            custom_props={
                "--space-3": "12px",
                "--color-primary": "#5E6AD2",
                "--unknown": "...",
            },
        )
        cap2 = RawCapture(
            url="https://x/pricing", title="x", sampled_styles={}, dom_signals={},
            custom_props={
                "--color-primary": "different",  # dedup keeps the first-seen value
                "--radius-md": "8px",
            },
        )
        tokens = _harvest_named_tokens([cap1, cap2])
        names = [t.name for t in tokens]
        # Display order: color → typography → spacing → radius → size → motion → other
        assert names.index("--color-primary") < names.index("--space-3")
        assert names.index("--space-3") < names.index("--radius-md")
        # Dedup preserved first value
        col = next(t for t in tokens if t.name == "--color-primary")
        assert col.value == "#5E6AD2"


class TestMultiPageAggregation:
    def test_accepts_list_and_pools_observations(self):
        # Landing page sees Inter at 16px; pricing also sees Inter at 16px;
        # together that gives weight 2 to that combination.
        cap_landing = RawCapture(
            url="https://x", title="X home",
            sampled_styles={
                "body": {"font-family": "Inter", "font-size": "16px", "font-weight": "400"},
            },
            dom_signals={"bodyBg": "rgb(255, 255, 255)"},
        )
        cap_pricing = RawCapture(
            url="https://x/pricing", title="Pricing",
            sampled_styles={
                "body": {"font-family": "Inter", "font-size": "16px", "font-weight": "400"},
                "h1": {"font-family": "Inter", "font-size": "48px", "font-weight": "700"},
            },
            dom_signals={"bodyBg": "rgb(255, 255, 255)"},
        )
        tokens = aggregate([cap_landing, cap_pricing])
        # h1 from pricing made it into the scale
        assert "48px" in tokens.typography.size_scale
        # Pages rendered tracks both
        assert tokens.pages_rendered == ["https://x", "https://x/pricing"]
        # url uses the first (primary) capture
        assert tokens.url == "https://x"

    def test_empty_list_raises(self):
        import pytest
        with pytest.raises(ValueError):
            aggregate([])
