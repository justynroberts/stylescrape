"""Playwright wrapper: render a page and surface a `Page` to the inspector."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import Page, async_playwright

from .types import RenderOptions


class RenderError(RuntimeError):
    """Raised when Playwright can't reach or render the URL."""


@asynccontextmanager
async def rendered_page(url: str, opts: RenderOptions):
    """Yield a Playwright `Page` that has loaded `url` and settled."""
    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception as exc:
                raise RenderError(
                    "Could not launch Chromium. Run: playwright install chromium"
                ) from exc

            context = await browser.new_context(
                color_scheme=opts.color_scheme,
                viewport={"width": opts.viewport_width, "height": opts.viewport_height},
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=opts.timeout_ms)
            except Exception as exc:
                # Soft-fail on timeout: caller gets whatever rendered so far.
                if "Timeout" not in str(exc):
                    raise RenderError(f"Failed to load {url}: {exc}") from exc

            if opts.extra_wait_ms > 0:
                await asyncio.sleep(opts.extra_wait_ms / 1000)

            try:
                yield page
            finally:
                await context.close()
                await browser.close()
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(str(exc)) from exc


async def screenshot(page: Page, path: str) -> str:
    """Save a full-page screenshot. Returns the path written."""
    await page.screenshot(path=path, full_page=True)
    return path
