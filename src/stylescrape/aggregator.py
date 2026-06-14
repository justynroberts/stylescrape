"""Token aggregation: dedup, hex resolution, frequency rank, ΔE colour clustering."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from math import sqrt

from .types import (
    ColorToken,
    DesignTokens,
    MotionTokens,
    RawCapture,
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


def aggregate(capture: RawCapture) -> DesignTokens:
    sampled = capture.sampled_styles

    # ---- Colour ----
    color_meta: list[tuple[tuple[int, int, int], str, str]] = []
    for sel, props in sampled.items():
        for prop in ("color", "background-color", "border-color", "outline-color"):
            raw = props.get(prop, "")
            parsed = _parse_color(raw)
            if parsed is None:
                continue
            r, g, b, a = parsed
            if a < 0.05:
                continue
            color_meta.append(((r, g, b), prop, sel))

    body_bg = _parse_color(capture.dom_signals.get("bodyBg", ""))
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

    for _sel, props in sampled.items():
        ff = props.get("font-family", "")
        if ff:
            role = _font_role(ff)
            primary = _non_system_font_first(ff)
            if primary:
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
    for _sel, props in sampled.items():
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
    for _sel, props in sampled.items():
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
                # capture full cubic-bezier(...) if present
                m = re.search(r"cubic-bezier\([^)]+\)", t)
                easings[m.group(0) if m and kw == "cubic-bezier" else kw] += 1
                break

    motion = MotionTokens(
        durations=[v for v, _ in durations.most_common(6)],
        easings=[v for v, _ in easings.most_common(4)],
    )

    return DesignTokens(
        url=capture.url,
        title=capture.title,
        scheme="dark" if is_dark else "light",
        colors=color_tokens,
        typography=typography,
        shape=shape,
        motion=motion,
        components=[],  # filled in by component_detector
    )
