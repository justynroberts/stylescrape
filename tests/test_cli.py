"""CLI smoke tests — flag parsing, URL normalisation, error paths."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from stylescrape.cli import _normalise_url, main
from stylescrape.types import (
    ColorToken,
    ComponentPattern,
    DesignTokens,
    MotionTokens,
    ShapeTokens,
    TypographyTokens,
)


def test_normalise_url_adds_https():
    assert _normalise_url("example.com") == "https://example.com"


def test_normalise_url_keeps_scheme():
    assert _normalise_url("http://example.com") == "http://example.com"
    assert _normalise_url("https://example.com") == "https://example.com"


def _fake_tokens() -> DesignTokens:
    return DesignTokens(
        url="https://example.com",
        title="Example",
        scheme="light",
        colors=[ColorToken(hex="#FFFFFF", role="background.primary", frequency=1)],
        typography=TypographyTokens(
            font_families={"sans": "Inter"},
            size_scale=["16px"],
            weights=[400],
            line_heights=["24px"],
            letter_spacings=[],
        ),
        shape=ShapeTokens(radii=["4px"], shadows=[], spacings=["8px"]),
        motion=MotionTokens(durations=["200ms"], easings=["ease"]),
        components=[ComponentPattern(name="buttons", present=True, notes="42 buttons")],
    )


def _patch_pipeline():
    """Replace the async pipeline with a deterministic stub returning fake tokens."""
    async def fake(*_args, **_kwargs):
        return _fake_tokens(), {"render": 0.1, "inspect": 0.1, "aggregate": 0.1}

    return patch("stylescrape.cli._run_pipeline", new=AsyncMock(side_effect=fake))


def test_json_output():
    runner = CliRunner()
    with _patch_pipeline():
        result = runner.invoke(main, ["example.com", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["url"] == "https://example.com"


def test_markdown_output():
    runner = CliRunner()
    with _patch_pipeline():
        result = runner.invoke(main, ["example.com", "--format", "markdown"])
    assert result.exit_code == 0, result.output
    assert "# Design system:" in result.output


def test_prompt_only_flag_skips_claude():
    runner = CliRunner()
    with _patch_pipeline():
        result = runner.invoke(main, ["example.com", "--prompt-only"])
    assert result.exit_code == 0, result.output
    assert "STAGE 1" in result.output and "STAGE 2" in result.output


def test_dark_and_light_mutually_exclusive():
    runner = CliRunner()
    with _patch_pipeline():
        result = runner.invoke(main, ["example.com", "--dark", "--light"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_output_file(tmp_path):
    out = tmp_path / "x.md"
    runner = CliRunner()
    with _patch_pipeline():
        result = runner.invoke(
            main, ["example.com", "--format", "markdown", "--output", str(out)]
        )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "# Design system:" in out.read_text()


def test_falls_back_to_prompt_only_when_claude_missing():
    runner = CliRunner()
    with _patch_pipeline(), patch(
        "stylescrape.cli.claude_available", return_value=False
    ):
        result = runner.invoke(main, ["example.com"])
    assert result.exit_code == 0, result.output
    # Without claude, we emit the raw two-stage prompts
    assert "STAGE 1" in result.output


def test_no_args_shows_help():
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "stylescrape" in result.output.lower() or "url" in result.output.lower()


def test_batch_and_url_mutually_exclusive():
    runner = CliRunner()
    result = runner.invoke(
        main, ["example.com", "--batch", "top 5 CRM tools", "-o", "out"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_batch_requires_output():
    runner = CliRunner()
    result = runner.invoke(main, ["--batch", "top 5 CRM tools"])
    assert result.exit_code != 0
    assert "--output" in result.output


def test_batch_dry_run_lists_sites(tmp_path):
    from stylescrape.discovery import DiscoveredSite

    runner = CliRunner()
    with patch(
        "stylescrape.cli.discover",
        return_value=[
            DiscoveredSite("Linear", "https://linear.app", "issue tracker"),
            DiscoveredSite("Notion", "https://notion.so", "wiki + db"),
        ],
    ):
        result = runner.invoke(
            main,
            [
                "--batch",
                "top 2 productivity tools",
                "-o",
                str(tmp_path),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Linear" in result.output
    assert "Notion" in result.output
    # No actual files written in dry run
    assert not (tmp_path / "linear-app.md").exists()


def test_batch_end_to_end_with_mocked_render(tmp_path, mocker):
    from stylescrape.discovery import DiscoveredSite

    sites = [
        DiscoveredSite("Linear", "https://linear.app", "issue tracker"),
        DiscoveredSite("Notion", "https://notion.so", "wiki + db"),
    ]
    mocker.patch("stylescrape.cli.discover", return_value=sites)

    async def fake_scrape(url, _opts):
        return _fake_tokens()

    mocker.patch("stylescrape.batch._scrape", side_effect=fake_scrape)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--batch", "top 2 productivity tools", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "linear-app.md").exists()
    assert (tmp_path / "notion-so.md").exists()
    assert (tmp_path / "index.md").exists()
    index = (tmp_path / "index.md").read_text()
    assert "top 2 productivity tools" in index
    assert "linear-app.md" in index


def test_batch_count_out_of_range():
    runner = CliRunner()
    result = runner.invoke(main, ["--batch", "x", "-o", "out", "-n", "0"])
    assert result.exit_code != 0
    assert "1 and 50" in result.output


def test_batch_exits_nonzero_when_all_fail(tmp_path, mocker):
    from stylescrape.discovery import DiscoveredSite
    from stylescrape.renderer import RenderError

    mocker.patch(
        "stylescrape.cli.discover",
        return_value=[DiscoveredSite("X", "https://x.example.com", "")],
    )

    async def boom(_url, _opts):
        raise RenderError("could not load")

    mocker.patch("stylescrape.batch._scrape", side_effect=boom)

    runner = CliRunner()
    result = runner.invoke(main, ["--batch", "x", "-o", str(tmp_path)])
    # Exit 4 = all-failed signal
    assert result.exit_code == 4, result.output
