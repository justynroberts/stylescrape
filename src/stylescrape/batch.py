"""Batch orchestration: discover N sites, render each, write a markdown per site + an index."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .aggregator import aggregate
from .component_detector import detect
from .discovery import DiscoveredSite
from .inspector import capture
from .prompt_builder import build
from .renderer import RenderError, rendered_page
from .types import DesignTokens, RenderOptions


@dataclass
class BatchResult:
    name: str
    url: str
    ok: bool
    slug: str = ""
    output_path: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    tokens: DesignTokens | None = None
    blocked: bool = False
    block_reason: str = ""


# Titles served by anti-bot interstitials, WAF blocks, captchas, and HTTP errors.
# We still capture and write the markdown — the user can inspect — but we flag it
# in the index so they don't treat a block page as a real design system.
_BLOCK_TITLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"access\s*denied", re.I), "access denied"),
    (re.compile(r"\b403\b"), "HTTP 403"),
    (re.compile(r"\b404\b"), "HTTP 404"),
    (re.compile(r"\b5\d{2}\b"), "HTTP 5xx"),
    (re.compile(r"\bforbidden\b", re.I), "forbidden"),
    (re.compile(r"just\s*a\s*moment", re.I), "Cloudflare challenge"),
    (re.compile(r"checking\s*your\s*browser", re.I), "browser check"),
    (re.compile(r"attention\s*required", re.I), "Cloudflare WAF"),
    (re.compile(r"are\s*you\s*(a\s*)?robot", re.I), "bot challenge"),
    (re.compile(r"\bcaptcha\b", re.I), "captcha"),
    (re.compile(r"please\s*verify", re.I), "verification page"),
    (re.compile(r"sorry,?\s*you\s*have\s*been\s*blocked", re.I), "WAF block"),
    (re.compile(r"pardon\s*our\s*interruption", re.I), "PerimeterX interruption"),
    (re.compile(r"site\s*can(no|')t\s*be\s*reached", re.I), "navigation error"),
]


def detect_block_signal(tokens: DesignTokens) -> tuple[bool, str]:
    """Return (is_likely_blocked, reason) for a rendered page.

    These pages capture cleanly — we got computed styles, the title is set —
    but the content is a bot block, captcha, or HTTP error page, not the
    real site's design system. The user wants these flagged distinctly so
    they don't treat the block page's stark palette as a real aesthetic.
    """
    title = (tokens.title or "").strip()
    if not title:
        return False, ""
    for pattern, reason in _BLOCK_TITLE_PATTERNS:
        if pattern.search(title):
            return True, reason
    return False, ""


def slugify(url_or_name: str) -> str:
    """Filesystem-safe slug from a hostname or arbitrary string."""
    parsed = urlparse(url_or_name)
    base = parsed.hostname or url_or_name
    base = base.lower().removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return slug or "site"


async def _scrape(url: str, opts: RenderOptions) -> DesignTokens:
    async with rendered_page(url, opts) as page:
        cap = await capture(page)
    tokens = aggregate(cap)
    tokens.components = detect(cap)
    return tokens


ProgressCb = Callable[[str, BatchResult], None]


async def run_batch(
    sites: list[DiscoveredSite],
    output_dir: Path,
    opts: RenderOptions,
    concurrency: int = 3,
    fmt: str = "markdown",
    use_claude: bool = False,
    model: str | None = None,
    on_progress: ProgressCb | None = None,
) -> list[BatchResult]:
    """Render each site concurrently and write its design-system file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    ext = {"markdown": "md", "json": "json", "prompt": "md"}[fmt]

    async def process(site: DiscoveredSite) -> BatchResult:
        result = BatchResult(name=site.name, url=site.url, ok=False)
        if on_progress:
            on_progress("start", result)
        async with sem:
            t0 = time.monotonic()
            try:
                tokens = await _scrape(site.url, opts)
            except RenderError as exc:
                result.error = str(exc)
                result.elapsed_s = time.monotonic() - t0
                if on_progress:
                    on_progress("error", result)
                return result
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                result.elapsed_s = time.monotonic() - t0
                if on_progress:
                    on_progress("error", result)
                return result

            try:
                rendered = build(tokens, fmt=fmt, use_claude=use_claude, model=model)
            except Exception as exc:
                result.error = f"build: {exc}"
                result.elapsed_s = time.monotonic() - t0
                if on_progress:
                    on_progress("error", result)
                return result

            slug = slugify(site.url) or slugify(site.name)
            path = output_dir / f"{slug}.{ext}"
            path.write_text(rendered, encoding="utf-8")

            blocked, reason = detect_block_signal(tokens)
            result.ok = True
            result.slug = slug
            result.output_path = str(path)
            result.tokens = tokens
            result.blocked = blocked
            result.block_reason = reason
            result.elapsed_s = time.monotonic() - t0
            if on_progress:
                on_progress("blocked" if blocked else "done", result)
            return result

    return await asyncio.gather(*(process(s) for s in sites))


def write_index(
    output_dir: Path,
    query: str,
    sites: list[DiscoveredSite],
    results: list[BatchResult],
    fmt_ext: str = "md",
) -> Path:
    """Write a catalogue index for the batch run."""
    output_dir = Path(output_dir)
    rationale_by_url = {s.url: s.rationale for s in sites}

    lines: list[str] = []
    lines.append(f"# Design systems: {query}")
    lines.append("")
    lines.append(f"Generated by `stylescrape batch` against {len(results)} site(s).")
    lines.append("")
    lines.append("| # | Name | URL | Why | System |")
    lines.append("|---|------|-----|-----|--------|")
    for i, r in enumerate(results, 1):
        why = rationale_by_url.get(r.url, "").replace("|", "\\|")
        if r.ok and r.blocked:
            link = (
                f"⚠ blocked ({r.block_reason}) — "
                f"[`{r.slug}.{fmt_ext}`]({r.slug}.{fmt_ext})"
            )
        elif r.ok:
            link = f"[`{r.slug}.{fmt_ext}`]({r.slug}.{fmt_ext})"
        else:
            # Collapse newlines + clip — markdown tables can't span multiple lines.
            err = re.sub(r"\s+", " ", r.error).strip()
            if len(err) > 120:
                err = err[:117] + "..."
            err = err.replace("|", "\\|")
            link = f"_failed_ — {err}"
        lines.append(f"| {i} | {r.name} | <{r.url}> | {why} | {link} |")
    lines.append("")

    clean = [r for r in results if r.ok and not r.blocked]
    blocked = [r for r in results if r.ok and r.blocked]
    failures = [r for r in results if not r.ok]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Clean captures: {len(clean)} / {len(results)}")
    if blocked:
        lines.append(f"- Blocked / interstitial: {len(blocked)}")
        for r in blocked:
            lines.append(f"  - {r.name} — {r.block_reason}")
    lines.append(f"- Failed: {len(failures)}")
    if clean:
        total = sum(r.elapsed_s for r in clean)
        avg = total / len(clean)
        lines.append(f"- Avg render+extract: {avg:.1f}s ({total:.1f}s total)")
    lines.append("")

    path = output_dir / "index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
