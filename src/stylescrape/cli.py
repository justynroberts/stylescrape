"""StyleScrape CLI entrypoint.

Two modes via one command:

    stylescrape <url> [options]                            # single-site mode
    stylescrape --batch "<query>" --output <dir> [options] # batch mode
"""

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
from .batch import run_batch, write_index
from .component_detector import detect
from .discovery import discover
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
            if verbose:
                console.log(f"[dim]screenshot → {screenshot_path}[/dim]")

    t2 = time.monotonic()
    tokens = aggregate(cap)
    tokens.components = detect(cap)
    timings["aggregate"] = time.monotonic() - t2
    if verbose:
        console.log(f"[dim]aggregated in {timings['aggregate']:.2f}s[/dim]")

    return tokens, timings


def _run_single(
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
    if dark and light:
        raise click.BadParameter("--dark and --light are mutually exclusive")

    url = _normalise_url(url)
    use_claude = not (prompt_only or no_claude)

    if fmt == "prompt" and use_claude and not claude_available():
        console.log("[yellow]warning:[/yellow] `claude` not on PATH — falling back to --prompt-only")
        use_claude = False

    color_scheme = "dark" if dark else "light" if light else "no-preference"
    opts = RenderOptions(color_scheme=color_scheme, extra_wait_ms=wait)

    try:
        tokens, timings = asyncio.run(_run_pipeline(url, opts, selector, shot, verbose))
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


def _run_batch_mode(
    query: str,
    count: int,
    output_dir: str,
    fmt: str,
    concurrency: int,
    wait: int,
    dark: bool,
    light: bool,
    model: str | None,
    with_prompt: bool,
    dry_run: bool,
    verbose: bool,
):
    if dark and light:
        raise click.BadParameter("--dark and --light are mutually exclusive")
    if count < 1 or count > 50:
        raise click.BadParameter("--count must be between 1 and 50")

    console.log(f"[cyan]discovering[/cyan] top {count} for: {query!r}")
    try:
        sites = discover(query, count=count, model=model)
    except ClaudeError as exc:
        console.print(f"[red]discovery error:[/red] {exc}")
        sys.exit(3)
    except ValueError as exc:
        console.print(f"[red]discovery failed:[/red] {exc}")
        sys.exit(3)

    console.log(f"[green]found {len(sites)} site(s):[/green]")
    for i, s in enumerate(sites, 1):
        rationale = f" — [dim]{s.rationale}[/dim]" if s.rationale else ""
        console.log(f"  {i:2d}. [bold]{s.name}[/bold] {s.url}{rationale}")

    if dry_run:
        return

    out_dir = Path(output_dir)
    color_scheme = "dark" if dark else "light" if light else "no-preference"
    opts = RenderOptions(color_scheme=color_scheme, extra_wait_ms=wait)

    use_claude = with_prompt and fmt == "prompt"
    if with_prompt and not claude_available():
        console.log("[yellow]warning:[/yellow] --with-prompt requested but `claude` not on PATH")
        use_claude = False

    def on_progress(event: str, r):
        if event == "start":
            if verbose:
                console.log(f"[dim]→ {r.name}[/dim]")
        elif event == "done":
            console.log(f"[green]✓[/green] {r.name} ({r.elapsed_s:.1f}s) → {r.output_path}")
        elif event == "error":
            console.log(f"[red]✗[/red] {r.name} ({r.elapsed_s:.1f}s) — {r.error}")

    try:
        results = asyncio.run(
            run_batch(
                sites,
                output_dir=out_dir,
                opts=opts,
                concurrency=concurrency,
                fmt=fmt,
                use_claude=use_claude,
                model=model,
                on_progress=on_progress,
            )
        )
    except KeyboardInterrupt:
        console.print("[yellow]aborted[/yellow]")
        sys.exit(130)

    ext = {"markdown": "md", "json": "json", "prompt": "md"}[fmt]
    index_path = write_index(out_dir, query, sites, results, fmt_ext=ext)

    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok
    console.log(
        f"[bold]done[/bold]: {ok} succeeded, {fail} failed → "
        f"[green]{out_dir}[/green] (see {index_path.name})"
    )
    if fail and ok == 0:
        sys.exit(4)


@click.command(name="stylescrape")
@click.argument("url", required=False)
# ---- batch mode ----
@click.option(
    "--batch",
    "batch_query",
    type=str,
    default=None,
    metavar="QUERY",
    help='Batch mode: discover top N sites for QUERY (e.g. "top 10 CRM tools").',
)
@click.option("--count", "-n", type=int, default=10, help="[batch] Number of sites to discover.")
@click.option("--concurrency", "-c", type=int, default=3, help="[batch] Concurrent renders.")
@click.option("--with-prompt", is_flag=True, help="[batch] Also run two-stage `claude -p` per site.")
@click.option("--dry-run", is_flag=True, help="[batch] Discover URLs only; skip rendering.")
# ---- shared ----
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["prompt", "json", "markdown"]),
    default=None,
    help="Output format. Default: prompt (single) / markdown (batch).",
)
@click.option("--prompt-only", is_flag=True, help="Print the assembled Claude prompt without invoking `claude -p`.")
@click.option("--no-claude", is_flag=True, help="Alias for --prompt-only.")
@click.option("--wait", type=int, default=2000, help="Extra wait after load (ms).")
@click.option("--selector", type=str, default=None, help="[single] Focus extraction on a CSS selector.")
@click.option("--dark", "dark", is_flag=True, help="Force prefers-color-scheme: dark.")
@click.option("--light", "light", is_flag=True, help="Force prefers-color-scheme: light.")
@click.option("--screenshot", "shot", type=click.Path(), default=None, help="[single] Save a screenshot.")
@click.option("--verbose", is_flag=True, help="Show progress and timing.")
@click.option(
    "--output",
    "-o",
    "output",
    type=click.Path(),
    default=None,
    help="Output file (single mode) or directory (batch mode).",
)
@click.option("--model", type=str, default=None, help="Override Claude model.")
@click.version_option(__version__, prog_name="stylescrape")
@click.pass_context
def main(
    ctx: click.Context,
    url: str | None,
    batch_query: str | None,
    count: int,
    concurrency: int,
    with_prompt: bool,
    dry_run: bool,
    fmt: str | None,
    prompt_only: bool,
    no_claude: bool,
    wait: int,
    selector: str | None,
    dark: bool,
    light: bool,
    shot: str | None,
    verbose: bool,
    output: str | None,
    model: str | None,
):
    """Reverse-engineer a web design system into a Claude-ready prompt.

    Single-site mode:

        stylescrape https://linear.app

    Batch / promiscuous mode — discover the top N sites for a category and
    write one design-system markdown per site, plus an index.md:

        stylescrape --batch "top 10 CRM tools" -o ./crm-systems

    """
    if batch_query and url:
        raise click.BadParameter("URL and --batch are mutually exclusive")

    if batch_query:
        if not output:
            raise click.BadParameter("--batch requires --output / -o (a directory path)")
        _run_batch_mode(
            query=batch_query,
            count=count,
            output_dir=output,
            fmt=fmt or "markdown",
            concurrency=concurrency,
            wait=wait,
            dark=dark,
            light=light,
            model=model,
            with_prompt=with_prompt,
            dry_run=dry_run,
            verbose=verbose,
        )
        return

    if not url:
        click.echo(ctx.get_help())
        ctx.exit(0)

    _run_single(
        url=url,
        fmt=fmt or "prompt",
        prompt_only=prompt_only,
        no_claude=no_claude,
        wait=wait,
        selector=selector,
        dark=dark,
        light=light,
        shot=shot,
        verbose=verbose,
        outfile=output,
        model=model,
    )


if __name__ == "__main__":
    main()
