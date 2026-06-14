"""Token aggregation: dedup, hex resolution, frequency rank, ΔE colour clustering.

Accepts either a single RawCapture or a list of them (multi-page mode). Pages
contribute additively to the frequency counters — the same selector appearing
across landing + pricing + features yields more weight to its computed values.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from math import sqrt

from .types import (
    ColorToken,
    DesignTokens,
    ElevationStep,
    LayoutTokens,
    MotionTokens,
    NamedToken,
    RawCapture,
    ScaleAnalysis,
    ShapeTokens,
    TypographyTokens,
)

# Try colormath2 for CIEDE2000; fall back to a sRGB-distance approximation.
try:
    from colormath2.color_conversions import convert_color
    from colormath2.color_diff import delta_e_cie2000
    from colormath2.color_objects import LabColor, sRGBColor

    _HAS_COLORMATH = True
except Exception:
    _HAS_COLORMATH = False


SYSTEM_FONT_TOKENS = {
    "-apple-system",
    "blinkmacsystemfont",
    "system-ui",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
    "segoe",
    "roboto",
    "helvetica",
    "arial",
    "sans-serif",
    "serif",
    "monospace",
    "cantarell",
    "noto",
    "oxygen",
    "ubuntu",
    "fira",
    "droid",
}


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _parse_color(raw: str) -> tuple[int, int, int, float] | None:
    """Parse rgb(), rgba(), hex, or transparent → (r, g, b, alpha)."""
    if not raw:
        return None
    s = raw.strip().lower()
    if s in ("transparent", "rgba(0, 0, 0, 0)", "currentcolor", "inherit"):
        return None
    m = re.match(
        r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)", s
    )
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4)) if m.group(4) else 1.0
        return r, g, b, a
    m = re.match(r"#([0-9a-f]{3})$", s)
    if m:
        h = m.group(1)
        return int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 1.0
    m = re.match(r"#([0-9a-f]{6})$", s)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = re.match(r"#([0-9a-f]{8})$", s)
    if m:
        h = m.group(1)
        return (
            int(h[0:2], 16),
            int(h[2:4], 16),
            int(h[4:6], 16),
            int(h[6:8], 16) / 255,
        )
    return None


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """ΔE-2000 if colormath available, otherwise weighted sRGB distance."""
    if _HAS_COLORMATH:
        try:
            la = convert_color(sRGBColor(a[0] / 255, a[1] / 255, a[2] / 255), LabColor)
            lb = convert_color(sRGBColor(b[0] / 255, b[1] / 255, b[2] / 255), LabColor)
            return float(delta_e_cie2000(la, lb))
        except Exception:
            pass
    # Cheap fallback — sufficient for "are these basically the same colour"
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return sqrt(0.3 * dr * dr + 0.59 * dg * dg + 0.11 * db * db)


def _cluster_colors(
    colors_with_meta: list[tuple[tuple[int, int, int], str, str]],
    threshold: float = 10.0,
) -> list[tuple[tuple[int, int, int], int, list[str]]]:
    """Cluster RGB triplets by perceptual distance.

    Returns list of (representative_rgb, frequency, source_selectors).
    """
    clusters: list[dict] = []
    for rgb, prop, sel in colors_with_meta:
        matched = None
        for c in clusters:
            if _color_distance(rgb, c["rgb"]) < threshold:
                matched = c
                break
        if matched is None:
            clusters.append({"rgb": rgb, "freq": 1, "sources": [f"{sel}.{prop}"]})
        else:
            matched["freq"] += 1
            matched["sources"].append(f"{sel}.{prop}")
    clusters.sort(key=lambda c: -c["freq"])
    return [(c["rgb"], c["freq"], c["sources"]) for c in clusters]


def _role_for_color(prop: str, sel: str) -> str:
    sel_l = sel.lower()
    if prop == "background-color":
        if sel == "body":
            return "background.primary"
        if sel in ("nav", "header", "aside", "[class*='sidebar']"):
            return "background.chrome"
        if "card" in sel_l or "modal" in sel_l or "alert" in sel_l:
            return "background.elevated"
        if "button" in sel_l:
            return "accent.surface"
        return "background.other"
    if prop == "color":
        if sel in ("body", "main", "p"):
            return "text.primary"
        if sel in ("small", "label"):
            return "text.secondary"
        if sel == "a" or "button" in sel_l:
            return "accent.text"
        if sel.startswith("h"):
            return "text.heading"
        return "text.other"
    if prop == "border-color":
        return "border"
    if prop == "outline-color":
        return "focus"
    return "other"


def _norm_font_stack(raw: str) -> str:
    return ", ".join(p.strip().strip("\"'") for p in raw.split(",") if p.strip())


def _font_role(stack: str) -> str:
    low = stack.lower()
    if any(t in low for t in ("mono", "code", "consolas", "menlo", "jetbrains")):
        return "mono"
    if any(t in low for t in ("serif",)) and "sans" not in low:
        return "serif"
    return "sans"


def _non_system_font_first(stack: str) -> str | None:
    parts = [p.strip().strip("\"'") for p in stack.split(",")]
    for p in parts:
        if p.lower() not in SYSTEM_FONT_TOKENS:
            return p
    return parts[0] if parts else None


def _is_dark(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 128


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _px(value: str) -> float | None:
    """Parse '24px' or '1.5rem' to a px float. Returns None on miss."""
    if not value:
        return None
    m = re.match(r"([\d.]+)px$", value.strip())
    if m:
        return float(m.group(1))
    m = re.match(r"([\d.]+)rem$", value.strip())
    if m:
        return float(m.group(1)) * 16.0  # rough; computed styles rarely use rem anyway
    return None


_SCALE_NAMES: list[tuple[float, str]] = [
    (1.067, "minor-second"),
    (1.125, "major-second"),
    (1.2, "minor-third"),
    (1.25, "major-third"),
    (1.333, "perfect-fourth"),
    (1.414, "augmented-fourth"),
    (1.5, "perfect-fifth"),
    (1.618, "golden"),
    (1.778, "major-sixth"),
    (2.0, "octave"),
]


def _name_for_ratio(r: float) -> str:
    if r <= 1.0:
        return ""
    best = min(_SCALE_NAMES, key=lambda x: abs(x[0] - r))
    return best[1] if abs(best[0] - r) < 0.05 else "custom"


def _detect_type_scale(sizes_px: list[float]) -> tuple[float, float, str]:
    """Return (base_px, modal_ratio, ratio_name) from a sorted ascending list."""
    if len(sizes_px) < 2:
        return (sizes_px[0] if sizes_px else 0.0, 0.0, "")
    ratios = [sizes_px[i + 1] / sizes_px[i] for i in range(len(sizes_px) - 1)]
    rounded = Counter(round(r * 100) / 100 for r in ratios)
    modal = rounded.most_common(1)[0][0]
    # Pick the size closest to 16px as the "base"
    base = min(sizes_px, key=lambda s: abs(s - 16.0))
    return base, modal, _name_for_ratio(modal)


def _detect_spacing_base(values_px: list[int]) -> tuple[int, list[int]]:
    if not values_px:
        return 0, []
    values = [v for v in values_px if v > 0]
    if not values:
        return 0, []
    # Try common bases in preference order; pick the largest that fits ≥70%.
    for base in (8, 4, 6, 16, 2):
        matches = [v for v in values if v % base == 0]
        if len(matches) >= len(values) * 0.7:
            multipliers = sorted({v // base for v in matches if v // base > 0})
            return base, multipliers[:10]
    return 0, []


def _layout_label(width_px: float | None) -> str:
    if width_px is None:
        return "unknown"
    if width_px <= 800:
        return "narrow-centered"
    if width_px <= 1100:
        return "standard-centered"
    if width_px <= 1400:
        return "wide-centered"
    return "edge-to-edge"


def _aggregate_layout(captures: list[RawCapture]) -> LayoutTokens:
    widths: Counter[str] = Counter()
    grid_patterns: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    section_pads: Counter[str] = Counter()

    for cap in captures:
        for sel_key, props in cap.layout_samples.items():
            sel = sel_key.split("#", 1)[0]
            mw = props.get("max-width", "").strip()
            if mw and mw not in ("none", "0px", "auto"):
                widths[mw] += 1
            gt = props.get("grid-template-columns", "").strip()
            if gt and gt != "none":
                # Trim long pixel-list expansions; keep the structural form.
                grid_patterns[gt[:80]] += 1
            for k in ("gap", "row-gap", "column-gap"):
                v = props.get(k, "").strip()
                if v and v not in ("normal", "0px"):
                    gaps[v] += 1
            if "section" in sel or "hero" in sel:
                pad = props.get("padding", "").strip()
                if pad and pad != "0px":
                    section_pads[pad] += 1

    most_common_width = widths.most_common(1)[0][0] if widths else ""
    label = _layout_label(_px(most_common_width))
    return LayoutTokens(
        max_content_width=most_common_width,
        container_widths=[v for v, _ in widths.most_common(4)],
        grid_patterns=[v for v, _ in grid_patterns.most_common(3)],
        common_gaps=[v for v, _ in gaps.most_common(4)],
        section_paddings=[v for v, _ in section_pads.most_common(3)],
        layout_label=label,
    )


def _detect_elevation_steps(captures: list[RawCapture]) -> list[ElevationStep]:
    bgs: list[tuple[tuple[int, int, int], str, str]] = []
    for cap in captures:
        for sel, props in cap.sampled_styles.items():
            raw = props.get("background-color", "")
            parsed = _parse_color(raw)
            if parsed is None:
                continue
            r, g, b, a = parsed
            if a < 0.9:
                continue
            bgs.append(((r, g, b), "background-color", sel))
    if not bgs:
        return []
    clusters = _cluster_colors(bgs, threshold=5.0)
    sorted_by_lum = sorted(clusters, key=lambda c: _luminance(c[0]))
    return [
        ElevationStep(hex=_rgb_to_hex(*rgb), step=i + 1, luminance=round(_luminance(rgb), 1))
        for i, (rgb, _freq, _sources) in enumerate(sorted_by_lum)
    ][:8]


_TOKEN_ROLE_KEYWORDS: list[tuple[str, list[str]]] = [
    # Order matters: first match wins. The more specific suffix-style roles
    # (radius / spacing / motion / typography) come before the catch-all colour
    # bucket so e.g. `--border-radius` resolves to radius, not colour.
    ("radius", ["radius", "rounded", "corner"]),
    ("spacing", ["spacing", "space", "gap", "pad", "margin", "inset", "offset"]),
    ("motion", ["duration", "speed", "timing", "ease", "transition", "animation"]),
    ("typography", ["font", "family", "weight", "leading", "tracking", "letter"]),
    ("size", ["size", "scale", "step", "width", "height", "max-w", "min-w"]),
    ("color", ["color", "colour", "bg", "background", "fg", "foreground", "accent",
                "primary", "secondary", "surface", "text", "ink", "border",
                "outline", "shadow", "ring", "tint", "fill", "stroke"]),
]


def _infer_token_role(name: str) -> str:
    n = name.lower().lstrip("-")
    for role, keywords in _TOKEN_ROLE_KEYWORDS:
        for kw in keywords:
            if kw in n:
                return role
    return "other"


_DISPLAY_ORDER = ["color", "typography", "spacing", "radius", "size", "motion", "other"]


def _harvest_named_tokens(captures: list[RawCapture]) -> list[NamedToken]:
    seen: dict[str, str] = {}
    for cap in captures:
        for name, value in cap.custom_props.items():
            if name not in seen:
                seen[name] = value
    tokens = [
        NamedToken(name=n, value=v, role=_infer_token_role(n)) for n, v in seen.items()
    ]
    # Display order prioritises palette + type since they carry the most design
    # signal; the inference order (above) is specificity-first to disambiguate
    # multi-word names like `--border-radius`.
    role_rank = {r: i for i, r in enumerate(_DISPLAY_ORDER)}
    tokens.sort(key=lambda t: (role_rank.get(t.role, 99), t.name))
    return tokens


def aggregate(captures: RawCapture | list[RawCapture]) -> DesignTokens:
    """Aggregate one or more captures into a DesignTokens.

    Multi-page mode passes captures from /pricing, /about, /docs etc.
    alongside the landing page so the secondary palette, form treatments,
    and deeper navigation contribute to the frequency-ranked output.
    """
    if isinstance(captures, RawCapture):
        captures = [captures]
    if not captures:
        raise ValueError("aggregate() requires at least one RawCapture")
    primary = captures[0]

    # ---- Colour ----
    color_meta: list[tuple[tuple[int, int, int], str, str]] = []
    for cap in captures:
        for sel, props in cap.sampled_styles.items():
            for prop in ("color", "background-color", "border-color", "outline-color"):
                raw = props.get(prop, "")
                parsed = _parse_color(raw)
                if parsed is None:
                    continue
                r, g, b, a = parsed
                if a < 0.05:
                    continue
                color_meta.append(((r, g, b), prop, sel))

    body_bg = _parse_color(primary.dom_signals.get("bodyBg", ""))
    is_dark = bool(body_bg and _is_dark(body_bg[:3]))

    clusters = _cluster_colors(color_meta, threshold=10.0)
    color_tokens: list[ColorToken] = []
    role_counter: defaultdict[str, int] = defaultdict(int)
    for rgb, freq, sources in clusters[:24]:
        # sources are formatted "selector.prop" — split from the right so a
        # selector containing '.' (e.g. `[class*='card']`) doesn't get clipped.
        first = sources[0]
        idx = first.rfind(".")
        sel0, prop0 = first[:idx], first[idx + 1 :]
        role = _role_for_color(prop0, sel0)
        role_counter[role] += 1
        suffix = f".{role_counter[role]}" if role_counter[role] > 1 else ""
        color_tokens.append(
            ColorToken(
                hex=_rgb_to_hex(*rgb),
                role=f"{role}{suffix}",
                frequency=freq,
                sources=sources[:5],
            )
        )

    # ---- Typography ----
    families_by_role: dict[str, Counter] = defaultdict(Counter)
    sizes: Counter[str] = Counter()
    weights: Counter[int] = Counter()
    line_heights: Counter[str] = Counter()
    letter_spacings: Counter[str] = Counter()

    for cap in captures:
        for _sel, props in cap.sampled_styles.items():
            ff = props.get("font-family", "")
            if ff:
                role = _font_role(ff)
                primary_font = _non_system_font_first(ff)
                if primary_font:
                    families_by_role[role][_norm_font_stack(ff)] += 1
            fs = props.get("font-size", "")
            if fs:
                sizes[fs.strip()] += 1
            fw_raw = props.get("font-weight", "")
            try:
                fw_int = int(fw_raw)
                weights[fw_int] += 1
            except ValueError:
                pass
            lh = props.get("line-height", "")
            if lh and lh != "normal":
                line_heights[lh] += 1
            ls = props.get("letter-spacing", "")
            if ls and ls != "normal":
                letter_spacings[ls] += 1

    fam_out: dict[str, str] = {}
    for role, ctr in families_by_role.items():
        if ctr:
            fam_out[role] = ctr.most_common(1)[0][0]

    def _sort_sizes(items: list[str]) -> list[str]:
        def keyfn(s: str) -> float:
            m = re.match(r"([\d.]+)", s)
            return float(m.group(1)) if m else 0.0

        return sorted(set(items), key=keyfn)

    size_scale = _sort_sizes([s for s, _ in sizes.most_common(12)])
    weights_sorted = sorted({w for w, _ in weights.most_common(8)})
    lh_top = [v for v, _ in line_heights.most_common(6)]
    ls_top = [v for v, _ in letter_spacings.most_common(4)]

    typography = TypographyTokens(
        font_families=fam_out,
        size_scale=size_scale,
        weights=weights_sorted,
        line_heights=lh_top,
        letter_spacings=ls_top,
    )

    # ---- Shape ----
    radii: Counter[str] = Counter()
    shadows: Counter[str] = Counter()
    spacings: Counter[str] = Counter()
    for cap in captures:
        for _sel, props in cap.sampled_styles.items():
            r = props.get("border-radius", "")
            if r and r != "0px":
                radii[r] += 1
            sh = props.get("box-shadow", "")
            if sh and sh != "none":
                shadows[sh] += 1
            pad = props.get("padding", "")
            if pad and pad != "0px":
                spacings[pad] += 1

    shape = ShapeTokens(
        radii=[v for v, _ in radii.most_common(8)],
        shadows=[v for v, _ in shadows.most_common(6)],
        spacings=[v for v, _ in spacings.most_common(6)],
    )

    # ---- Motion ----
    durations: Counter[str] = Counter()
    easings: Counter[str] = Counter()
    for cap in captures:
        for _sel, props in cap.sampled_styles.items():
            t = props.get("transition", "")
            if not t or t in ("all 0s ease 0s", "none"):
                continue
            for m in re.finditer(r"([\d.]+m?s)", t):
                durations[m.group(1)] += 1
            for kw in (
                "ease",
                "ease-in",
                "ease-out",
                "ease-in-out",
                "linear",
                "cubic-bezier",
            ):
                if kw in t:
                    m = re.search(r"cubic-bezier\([^)]+\)", t)
                    easings[m.group(0) if m and kw == "cubic-bezier" else kw] += 1
                    break

    motion = MotionTokens(
        durations=[v for v, _ in durations.most_common(6)],
        easings=[v for v, _ in easings.most_common(4)],
    )

    # ---- Scale analysis (derived ratios) ----
    type_sizes_px = sorted({_px(s) for s in size_scale if _px(s)})
    type_sizes_px = [s for s in type_sizes_px if s is not None]
    type_base, type_ratio, type_ratio_name = _detect_type_scale(type_sizes_px)

    # Spacing base from any single-axis padding/margin/gap value seen
    spacing_px: list[int] = []
    for cap in captures:
        for _sel, props in cap.sampled_styles.items():
            for key in ("padding", "margin"):
                v = props.get(key, "")
                if not v:
                    continue
                for tok in v.split():
                    px = _px(tok)
                    if px and px > 0:
                        spacing_px.append(round(px))
    spacing_base, spacing_multipliers = _detect_spacing_base(spacing_px)
    scale = ScaleAnalysis(
        type_base_px=type_base,
        type_ratio=type_ratio,
        type_ratio_name=type_ratio_name,
        spacing_base_px=spacing_base,
        spacing_multipliers=spacing_multipliers,
    )

    # ---- Layout, elevation, named tokens ----
    layout = _aggregate_layout(captures)
    elevation = _detect_elevation_steps(captures)
    named_tokens = _harvest_named_tokens(captures)

    return DesignTokens(
        url=primary.url,
        title=primary.title,
        scheme="dark" if is_dark else "light",
        colors=color_tokens,
        typography=typography,
        shape=shape,
        motion=motion,
        components=[],  # filled in by component_detector
        layout=layout,
        scale=scale,
        elevation=elevation,
        named_tokens=named_tokens,
        pages_rendered=[c.url for c in captures],
    )
