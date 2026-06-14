"""Shared dataclasses passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ColorScheme = Literal["light", "dark", "no-preference"]


@dataclass
class RenderOptions:
    color_scheme: ColorScheme = "no-preference"
    extra_wait_ms: int = 2000
    viewport_width: int = 1440
    viewport_height: int = 900
    timeout_ms: int = 30000


@dataclass
class RawCapture:
    """Everything the inspector pulled out of the live page."""

    url: str
    title: str
    sampled_styles: dict[str, dict[str, str]]
    dom_signals: dict[str, Any]


@dataclass
class ColorToken:
    hex: str
    role: str
    frequency: int
    sources: list[str] = field(default_factory=list)


@dataclass
class TypographyTokens:
    font_families: dict[str, str]  # role -> stack
    size_scale: list[str]
    weights: list[int]
    line_heights: list[str]
    letter_spacings: list[str]


@dataclass
class ShapeTokens:
    radii: list[str]
    shadows: list[str]
    spacings: list[str]


@dataclass
class MotionTokens:
    durations: list[str]
    easings: list[str]


@dataclass
class ComponentPattern:
    name: str
    present: bool
    notes: str
    treatment: dict[str, str] = field(default_factory=dict)


@dataclass
class DesignTokens:
    url: str
    title: str
    scheme: str
    colors: list[ColorToken]
    typography: TypographyTokens
    shape: ShapeTokens
    motion: MotionTokens
    components: list[ComponentPattern]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "scheme": self.scheme,
            "colors": [c.__dict__ for c in self.colors],
            "typography": self.typography.__dict__,
            "shape": self.shape.__dict__,
            "motion": self.motion.__dict__,
            "components": [c.__dict__ for c in self.components],
        }
