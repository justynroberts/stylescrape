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
    layout_samples: dict[str, dict[str, str]] = field(default_factory=dict)
    custom_props: dict[str, str] = field(default_factory=dict)


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
class LayoutTokens:
    """Spatial structure — how the page lays itself out, not what's in it."""

    max_content_width: str = ""
    container_widths: list[str] = field(default_factory=list)
    grid_patterns: list[str] = field(default_factory=list)
    common_gaps: list[str] = field(default_factory=list)
    section_paddings: list[str] = field(default_factory=list)
    layout_label: str = ""  # narrow-centered / edge-to-edge / asymmetric / unknown


@dataclass
class ScaleAnalysis:
    """Derived ratios — turns raw size lists into a design decision."""

    type_base_px: float = 0.0
    type_ratio: float = 0.0
    type_ratio_name: str = ""  # e.g. 'major-third', 'perfect-fourth'
    spacing_base_px: int = 0
    spacing_multipliers: list[int] = field(default_factory=list)


@dataclass
class ElevationStep:
    """A distinct background-only tone — one rung in the surface ladder."""

    hex: str
    step: int  # 1 = base surface, 2 = elevated 1, ...
    luminance: float


@dataclass
class NamedToken:
    """A CSS custom property (--foo) declared on :root — design vocabulary."""

    name: str
    value: str
    role: str = ""  # color / spacing / radius / motion / typography / size / other


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
    layout: LayoutTokens = field(default_factory=LayoutTokens)
    scale: ScaleAnalysis = field(default_factory=ScaleAnalysis)
    elevation: list[ElevationStep] = field(default_factory=list)
    named_tokens: list[NamedToken] = field(default_factory=list)
    pages_rendered: list[str] = field(default_factory=list)

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
            "layout": self.layout.__dict__,
            "scale": self.scale.__dict__,
            "elevation": [e.__dict__ for e in self.elevation],
            "named_tokens": [t.__dict__ for t in self.named_tokens],
            "pages_rendered": self.pages_rendered,
        }
