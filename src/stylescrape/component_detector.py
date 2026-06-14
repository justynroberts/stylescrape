"""Heuristic component pattern detection over DOM signals + sampled styles."""

from __future__ import annotations

from .types import ComponentPattern, RawCapture


def detect(capture: RawCapture) -> list[ComponentPattern]:
    counts = capture.dom_signals.get("counts", {})
    classes = capture.dom_signals.get("classes", {})
    has = capture.dom_signals.get("has", {})
    styles = capture.sampled_styles

    def style_for(sel: str) -> dict[str, str]:
        s = styles.get(sel, {})
        return {
            k: s[k]
            for k in (
                "background-color",
                "color",
                "border-radius",
                "border-color",
                "box-shadow",
                "padding",
            )
            if s.get(k)
        }

    patterns: list[ComponentPattern] = []

    patterns.append(
        ComponentPattern(
            name="navigation",
            present=counts.get("nav", 0) > 0 or classes.get("sidebar", 0) > 0,
            notes=(
                "Sidebar layout"
                if classes.get("sidebar", 0) > 0
                else "Top navigation bar"
                if counts.get("nav", 0)
                else "Inline links only"
            ),
            treatment=style_for("nav"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="buttons",
            present=counts.get("button", 0) > 0,
            notes=f"{counts.get('button', 0)} button elements on page",
            treatment=style_for("button:not([disabled])"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="forms",
            present=counts.get("form", 0) > 0 or counts.get("input", 0) > 0,
            notes=f"{counts.get('input', 0)} input(s), {counts.get('form', 0)} form(s)",
            treatment=style_for("input[type='text']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="tables",
            present=counts.get("table", 0) > 0,
            notes=f"{counts.get('table', 0)} table(s) — likely data display surface"
            if counts.get("table", 0)
            else "No tables detected",
            treatment=style_for("table"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="cards",
            present=classes.get("card", 0) > 0,
            notes=f"~{classes.get('card', 0)} card-like containers"
            if classes.get("card", 0)
            else "No card pattern detected",
            treatment=style_for("[class*='card']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="badges_chips",
            present=classes.get("badge", 0) + classes.get("chip", 0) > 0,
            notes=f"badges={classes.get('badge', 0)}, chips/tags={classes.get('chip', 0)}",
            treatment=style_for("[class*='badge']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="alerts_toasts",
            present=counts.get("alert", 0) + classes.get("toast", 0) > 0,
            notes=f"alerts={counts.get('alert', 0)}, toasts={classes.get('toast', 0)}",
            treatment=style_for("[role='alert']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="modals",
            present=counts.get("dialog", 0) + classes.get("modal", 0) > 0,
            notes=f"dialogs={counts.get('dialog', 0)}, modal classes={classes.get('modal', 0)}",
            treatment=style_for("[role='dialog']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="tabs",
            present=counts.get("tabs", 0) > 0,
            notes=f"{counts.get('tabs', 0)} tablist(s)",
            treatment=style_for("[role='tablist']"),
        )
    )

    patterns.append(
        ComponentPattern(
            name="dropdowns",
            present=classes.get("dropdown", 0) > 0,
            notes=f"~{classes.get('dropdown', 0)} dropdown/menu containers",
            treatment={},
        )
    )

    patterns.append(
        ComponentPattern(
            name="breadcrumbs",
            present=bool(has.get("breadcrumbs")),
            notes="Breadcrumb navigation present" if has.get("breadcrumbs") else "Absent",
            treatment={},
        )
    )

    patterns.append(
        ComponentPattern(
            name="progress_indicators",
            present=bool(has.get("progress")),
            notes="Progress bar / spinner present" if has.get("progress") else "Absent",
            treatment={},
        )
    )

    patterns.append(
        ComponentPattern(
            name="toggles_switches",
            present=bool(has.get("toggle")),
            notes="Switch or checkbox controls present" if has.get("toggle") else "Absent",
            treatment={},
        )
    )

    return patterns
