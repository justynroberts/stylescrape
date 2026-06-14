"""StyleScrape CLI entrypoint."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import click
from rich.console import Console

from . import __version__
from .aggregator import aggregate
from .component_detector import detect
from .inspector import capture
from .prompt_builder import (
    ClaudeError,
    build,
    claude_available,
)
from .renderer import RenderError, rendered_page, screenshot
from .types import RenderOptions

console = Console(stderr=True)


def _normalise_url(raw: str) -> str:
    parsed = urlparse(raw)
    if not parsed.scheme:
        return f"https://{raw}"
    if parsed.scheme not in ("http", "https"):
        raise click.BadParameter(f"Unsupported URL scheme: {parsed.scheme}")
    return raw


async def _run_pipeline(
    url: str,
    opts: RenderOptions,
    selector: str | None,
    screenshot_path: str | None,
    verbose: bool,
):
    timings: dict[str, float] = {}

    t0 = time.monotonic()
    async with rendered_page(url, opts) as page:
        timings["render"] = time.monotonic() - t0
        if verbose:
            console.log(f"[dim]rendered in {timings['render']:.2f}s[/dim]")

        if selector:
            try:
                await page.wait_for_selector(selector, timeout=5000)
            except Exception:
                console.log(f"[yellow]warning:[/yellow] --selector {selector!r} not found")

        t1 = time.monotonic()
        cap = await capture(page)
        timings["inspect"] = time.monotonic() - t1
        if verbose:
            console.log(f"[dim]inspected in {timings['inspect']:.2f}s[/dim]")

        if screenshot_path:
            await screenshot(page, screenshot_path)
            cap.screenshot_path = screenshot_path
            if verbose:
                console.log(f"[dim]screenshot → {screenshot_path}[/dim]")

    t2 = time.monotonic()
    tokens = aggregate(cap)
    tokens.components = detect(cap)
    timings["aggregate"] = time.monotonic() - t2
    if verbose:
        console.log(f"[dim]aggregated in {timings['aggregate']:.2f}s[/dim]")

    return tokens, timings


@click.command(name="stylescrape")
@click.argument("url", type=str)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["prompt", "json", "markdown"]),
    default="prompt",
    help="Output format.",
)
@click.option(
    "--prompt-only",
    is_flag=True,
    help="Print the assembled Claude prompt without invoking `claude -p`.",
)
@click.option(
    "--no-claude",
    is_flag=True,
    help="Alias for --prompt-only; skip the `claude -p` calls entirely.",
)
@click.option("--wait", type=int, default=2000, help="Extra wait after load (ms).")
@click.option("--selector", type=str, default=None, help="Focus extraction on a CSS selector.")
@click.option("--dark", "dark", is_flag=True, help="Force prefers-color-scheme: dark.")
@click.option("--light", "light", is_flag=True, help="Force prefers-color-scheme: light.")
@click.option("--screenshot", "shot", type=click.Path(), default=None, help="Save a screenshot.")
@click.option("--verbose", is_flag=True, help="Show timing and skipped selectors.")
@click.option("--output", "outfile", type=click.Path(), default=None, help="Write to file.")
@click.option("--model", type=str, default=None, help="Override Claude model for `claude -p`.")
@click.version_option(__version__, prog_name="stylescrape")
def main(
    url: str,
    fmt: str,
    prompt_only: bool,
    no_claude: bool,
    wait: int,
    selector: str | None,
    dark: bool,
    light: bool,
    shot: str | None,
    verbose: bool,
    outfile: str | None,
    model: str | None,
):
    """Reverse-engineer the design system at URL into a Claude-ready prompt."""
    if dark and light:
        raise click.BadParameter("--dark and --light are mutually exclusive")

    url = _normalise_url(url)
    use_claude = not (prompt_only or no_claude)

    if fmt == "prompt" and use_claude and not claude_available():
        console.log(
            "[yellow]warning:[/yellow] `claude` not on PATH — falling back to --prompt-only"
        )
        use_claude = False

    color_scheme = "dark" if dark else "light" if light else "no-preference"
    opts = RenderOptions(color_scheme=color_scheme, extra_wait_ms=wait)

    try:
        tokens, timings = asyncio.run(
            _run_pipeline(url, opts, selector, shot, verbose)
        )
    except RenderError as exc:
        console.print(f"[red]error:[/red] {exc}")
        sys.exit(2)
    except KeyboardInterrupt:
        console.print("[yellow]aborted[/yellow]")
        sys.exit(130)

    try:
        out = build(tokens, fmt=fmt, use_claude=use_claude, model=model)
    except ClaudeError as exc:
        console.print(f"[red]claude error:[/red] {exc}")
        console.print("[dim]retry with --no-claude to print the raw prompt[/dim]")
        sys.exit(3)

    if outfile:
        Path(outfile).write_text(out, encoding="utf-8")
        console.log(f"[green]wrote[/green] {outfile} ({len(out)} chars)")
    else:
        click.echo(out)

    if verbose:
        total = sum(timings.values())
        console.log(f"[dim]total pipeline: {total:.2f}s[/dim]")


if __name__ == "__main__":
    main()
