"""Unit tests for prompt builder templates + claude -p plumbing."""

from __future__ import annotations

import json

import pytest

from stylescrape.prompt_builder import (
    ClaudeError,
    build,
    claude_available,
    render_design_prompt,
    render_markdown,
    render_personality_prompt,
    run_claude,
)
from stylescrape.types import (
    ColorToken,
    ComponentPattern,
    DesignTokens,
    MotionTokens,
    ShapeTokens,
    TypographyTokens,
)


def _tokens() -> DesignTokens:
    return DesignTokens(
        url="https://example.com",
        title="Example",
        scheme="dark",
        colors=[
            ColorToken(hex="#0F0F11", role="background.primary", frequency=12, sources=["body.bg"]),
            ColorToken(hex="#5E6AD2", role="accent.text", frequency=8, sources=["a.color"]),
            ColorToken(hex="#E8E8ED", role="text.primary", frequency=15, sources=["body.color"]),
        ],
        typography=TypographyTokens(
            font_families={"sans": "Inter, sans-serif", "mono": "JetBrains Mono, monospace"},
            size_scale=["12px", "14px", "16px", "20px", "32px"],
            weights=[400, 500, 700],
            line_heights=["20px", "24px"],
            letter_spacings=["-0.01em"],
        ),
        shape=ShapeTokens(
            radii=["4px", "8px", "12px"],
            shadows=["0 1px 2px rgba(0,0,0,.1)", "0 4px 12px rgba(0,0,0,.2)"],
            spacings=["8px 16px", "16px"],
        ),
        motion=MotionTokens(durations=["150ms", "200ms"], easings=["ease-in-out"]),
        components=[
            ComponentPattern(name="buttons", present=True, notes="42 buttons", treatment={"background-color": "#5E6AD2"}),
            ComponentPattern(name="cards", present=True, notes="6 cards", treatment={}),
            ComponentPattern(name="tabs", present=False, notes="absent", treatment={}),
        ],
    )


def test_personality_template_includes_colours_and_typography():
    out = render_personality_prompt(_tokens())
    assert "#0F0F11" in out
    assert "Inter, sans-serif" in out
    assert "Scheme: dark" in out


def test_design_prompt_template_has_required_sections():
    out = render_design_prompt(_tokens(), personality="A disciplined, dense dark interface.")
    for marker in ("URL:", "PERSONALITY", "COLOURS", "TYPOGRAPHY", "MOTION"):
        assert marker in out
    assert "#0F0F11" in out
    assert "A disciplined, dense dark interface." in out


def test_design_prompt_excludes_absent_components():
    out = render_design_prompt(_tokens(), personality="x")
    assert "buttons" in out
    assert "cards" in out
    # tabs is present=false so the loop skips it
    assert "tabs" not in out.split("COMPONENTS DETECTED:")[1]


def test_markdown_template_renders_table():
    out = render_markdown(_tokens())
    assert "| Hex | Role | Frequency |" in out
    assert "`#0F0F11`" in out
    assert "**sans**" in out


def test_build_json_round_trips():
    out = build(_tokens(), fmt="json")
    parsed = json.loads(out)
    assert parsed["url"] == "https://example.com"
    assert parsed["scheme"] == "dark"
    assert len(parsed["colors"]) == 3


def test_build_markdown_calls_template():
    out = build(_tokens(), fmt="markdown")
    assert "Design system: Example" in out


def test_build_prompt_no_claude_includes_both_stages():
    out = build(_tokens(), fmt="prompt", use_claude=False)
    assert "STAGE 1" in out
    assert "STAGE 2" in out


def test_run_claude_invokes_subprocess(mocker):
    fake = mocker.patch("stylescrape.prompt_builder.subprocess.run")
    fake.return_value = mocker.Mock(returncode=0, stdout="hello world\n", stderr="")
    mocker.patch("stylescrape.prompt_builder.claude_available", return_value=True)

    out = run_claude("hi", model="claude-opus-4-7")
    assert out == "hello world"
    args, kwargs = fake.call_args
    assert args[0] == ["claude", "-p", "--model", "claude-opus-4-7"]
    assert kwargs["input"] == "hi"


def test_run_claude_raises_when_missing(mocker):
    mocker.patch("stylescrape.prompt_builder.claude_available", return_value=False)
    with pytest.raises(ClaudeError):
        run_claude("hi")


def test_run_claude_propagates_nonzero(mocker):
    mocker.patch("stylescrape.prompt_builder.claude_available", return_value=True)
    fake = mocker.patch("stylescrape.prompt_builder.subprocess.run")
    fake.return_value = mocker.Mock(returncode=1, stdout="", stderr="boom")
    with pytest.raises(ClaudeError):
        run_claude("hi")


def test_build_with_claude_calls_twice(mocker):
    calls = []

    def fake(_prompt, model=None):
        calls.append(_prompt)
        if len(calls) == 1:
            return "A clean, disciplined dark UI."
        return "PERSONALITY\n...\n"

    mocker.patch("stylescrape.prompt_builder.run_claude", side_effect=fake)
    out = build(_tokens(), fmt="prompt", use_claude=True)
    assert len(calls) == 2
    # The second call receives the personality string embedded
    assert "A clean, disciplined dark UI." in calls[1]
    assert "PERSONALITY" in out


def test_claude_available_returns_bool():
    assert isinstance(claude_available(), bool)
