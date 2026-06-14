"""Unit tests for batch orchestration."""

from __future__ import annotations

import asyncio

from stylescrape import batch as batch_mod
from stylescrape.batch import (
    BatchResult,
    detect_block_signal,
    run_batch,
    slugify,
    write_index,
)
from stylescrape.discovery import DiscoveredSite
from stylescrape.types import (
    ColorToken,
    DesignTokens,
    MotionTokens,
    RenderOptions,
    ShapeTokens,
    TypographyTokens,
)


def _fake_tokens(url: str) -> DesignTokens:
    return DesignTokens(
        url=url,
        title=url,
        scheme="dark",
        colors=[ColorToken(hex="#000000", role="text.primary", frequency=1)],
        typography=TypographyTokens(
            font_families={"sans": "Inter"},
            size_scale=["16px"],
            weights=[400],
            line_heights=["24px"],
            letter_spacings=[],
        ),
        shape=ShapeTokens(radii=["4px"], shadows=[], spacings=["8px"]),
        motion=MotionTokens(durations=["200ms"], easings=["ease"]),
        components=[],
    )


class TestSlugify:
    def test_strips_protocol_and_www(self):
        assert slugify("https://www.example.com") == "example-com"

    def test_handles_path(self):
        assert slugify("https://example.com/some/path") == "example-com"

    def test_subdomain_kept(self):
        assert slugify("https://app.example.com") == "app-example-com"

    def test_punctuation_collapsed(self):
        assert slugify("Foo!! Bar??") == "foo-bar"

    def test_falls_back_when_empty(self):
        assert slugify("") == "site"


class TestRunBatch:
    def test_writes_one_file_per_success(self, tmp_path, mocker):
        async def fake_scrape(url, _opts):
            return _fake_tokens(url)

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)

        sites = [
            DiscoveredSite(name="Linear", url="https://linear.app", rationale="x"),
            DiscoveredSite(name="Notion", url="https://notion.so", rationale="y"),
        ]
        results = asyncio.run(
            run_batch(
                sites,
                output_dir=tmp_path,
                opts=RenderOptions(),
                concurrency=2,
                fmt="markdown",
            )
        )
        assert all(r.ok for r in results)
        assert (tmp_path / "linear-app.md").exists()
        assert (tmp_path / "notion-so.md").exists()
        body = (tmp_path / "linear-app.md").read_text()
        assert "Design system" in body

    def test_failure_isolated(self, tmp_path, mocker):
        from stylescrape.renderer import RenderError

        async def fake_scrape(url, _opts):
            if "broken" in url:
                raise RenderError("could not load")
            return _fake_tokens(url)

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)

        sites = [
            DiscoveredSite(name="OK", url="https://ok.example.com", rationale=""),
            DiscoveredSite(name="Bad", url="https://broken.example.com", rationale=""),
        ]
        results = asyncio.run(
            run_batch(sites, output_dir=tmp_path, opts=RenderOptions(), concurrency=2)
        )
        ok = [r for r in results if r.ok]
        bad = [r for r in results if not r.ok]
        assert len(ok) == 1 and len(bad) == 1
        assert "could not load" in bad[0].error
        assert (tmp_path / "ok-example-com.md").exists()
        # No file written for the failure
        assert not (tmp_path / "broken-example-com.md").exists()

    def test_progress_callback_fires(self, tmp_path, mocker):
        async def fake_scrape(url, _opts):
            return _fake_tokens(url)

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)

        events = []

        def cb(event, r):
            events.append((event, r.name))

        sites = [DiscoveredSite(name="A", url="https://a.example.com")]
        asyncio.run(
            run_batch(
                sites,
                output_dir=tmp_path,
                opts=RenderOptions(),
                concurrency=1,
                on_progress=cb,
            )
        )
        names = {e[0] for e in events}
        assert "start" in names and "done" in names

    def test_concurrency_bounded_by_semaphore(self, tmp_path, mocker):
        in_flight = 0
        peak = 0

        async def fake_scrape(url, _opts):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return _fake_tokens(url)

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)

        sites = [DiscoveredSite(name=str(i), url=f"https://s{i}.example.com") for i in range(8)]
        asyncio.run(
            run_batch(sites, output_dir=tmp_path, opts=RenderOptions(), concurrency=2)
        )
        # Two-slot semaphore must never let more than 2 run at once
        assert peak <= 2


class TestDetectBlockSignal:
    def _tokens_with_title(self, title: str) -> DesignTokens:
        t = _fake_tokens("https://example.com")
        t.title = title
        return t

    def test_clean_title_not_blocked(self):
        blocked, reason = detect_block_signal(self._tokens_with_title("Linear — Plan and build products"))
        assert not blocked
        assert reason == ""

    def test_access_denied(self):
        blocked, reason = detect_block_signal(self._tokens_with_title("Access Denied"))
        assert blocked
        assert "access denied" in reason

    def test_cloudflare_challenge(self):
        blocked, reason = detect_block_signal(self._tokens_with_title("Just a moment..."))
        assert blocked
        assert "Cloudflare" in reason

    def test_cloudflare_waf(self):
        blocked, reason = detect_block_signal(self._tokens_with_title("Attention Required! | Cloudflare"))
        assert blocked
        assert "Cloudflare" in reason

    def test_perimeterx(self):
        blocked, _ = detect_block_signal(self._tokens_with_title("Pardon Our Interruption"))
        assert blocked

    def test_captcha(self):
        blocked, _ = detect_block_signal(self._tokens_with_title("Please complete the CAPTCHA"))
        assert blocked

    def test_403(self):
        blocked, reason = detect_block_signal(self._tokens_with_title("403 Forbidden"))
        assert blocked
        assert "403" in reason or "forbidden" in reason.lower()

    def test_404(self):
        blocked, _ = detect_block_signal(self._tokens_with_title("404 Not Found"))
        assert blocked

    def test_bot_block(self):
        blocked, _ = detect_block_signal(
            self._tokens_with_title("Sorry, you have been blocked")
        )
        assert blocked

    def test_empty_title_not_blocked(self):
        # Empty title is suspicious but not a positive block signal — many SPAs
        # lazy-set the title. Don't false-flag.
        blocked, _ = detect_block_signal(self._tokens_with_title(""))
        assert not blocked


class TestRunBatchBlockedFlow:
    def test_blocked_capture_writes_file_and_flags_result(self, tmp_path, mocker):
        async def fake_scrape(url, _opts):
            t = _fake_tokens(url)
            t.title = "Access Denied"
            return t

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)
        sites = [DiscoveredSite(name="Locked", url="https://locked.example.com")]
        results = asyncio.run(
            run_batch(sites, output_dir=tmp_path, opts=RenderOptions(), concurrency=1)
        )
        assert results[0].ok is True
        assert results[0].blocked is True
        assert "access denied" in results[0].block_reason
        # Markdown is still written — the user can inspect what came back
        assert (tmp_path / "locked-example-com.md").exists()

    def test_progress_emits_blocked_event(self, tmp_path, mocker):
        async def fake_scrape(url, _opts):
            t = _fake_tokens(url)
            t.title = "Just a moment..."
            return t

        mocker.patch.object(batch_mod, "_scrape", side_effect=fake_scrape)
        events = []

        def cb(event, _r):
            events.append(event)

        asyncio.run(
            run_batch(
                [DiscoveredSite(name="X", url="https://x.example.com")],
                output_dir=tmp_path,
                opts=RenderOptions(),
                concurrency=1,
                on_progress=cb,
            )
        )
        assert "blocked" in events
        assert "done" not in events


class TestWriteIndex:
    def test_index_lists_successes_and_failures(self, tmp_path):
        sites = [
            DiscoveredSite(name="Linear", url="https://linear.app", rationale="issue tracker"),
            DiscoveredSite(name="Broken", url="https://broken.example", rationale="dead"),
        ]
        results = [
            BatchResult(
                name="Linear",
                url="https://linear.app",
                ok=True,
                slug="linear-app",
                output_path=str(tmp_path / "linear-app.md"),
                elapsed_s=2.1,
            ),
            BatchResult(
                name="Broken",
                url="https://broken.example",
                ok=False,
                error="timeout",
                elapsed_s=5.0,
            ),
        ]
        path = write_index(tmp_path, "top 2 productivity tools", sites, results)
        body = path.read_text()
        assert "top 2 productivity tools" in body
        assert "linear-app.md" in body
        assert "issue tracker" in body
        assert "_failed_" in body
        assert "timeout" in body
        # Summary numbers
        assert "Clean captures: 1 / 2" in body
        assert "Failed: 1" in body

    def test_index_flags_blocked_entries(self, tmp_path):
        sites = [
            DiscoveredSite(name="Linear", url="https://linear.app", rationale="x"),
            DiscoveredSite(name="ServiceNow", url="https://servicenow.com", rationale="y"),
        ]
        results = [
            BatchResult(
                name="Linear",
                url="https://linear.app",
                ok=True,
                slug="linear-app",
                output_path=str(tmp_path / "linear-app.md"),
                elapsed_s=2.1,
            ),
            BatchResult(
                name="ServiceNow",
                url="https://servicenow.com",
                ok=True,
                blocked=True,
                block_reason="access denied",
                slug="servicenow-com",
                output_path=str(tmp_path / "servicenow-com.md"),
                elapsed_s=3.0,
            ),
        ]
        body = write_index(tmp_path, "x", sites, results).read_text()
        assert "⚠ blocked" in body
        assert "access denied" in body
        # Summary breaks out the block reason
        assert "Blocked / interstitial: 1" in body
        assert "ServiceNow — access denied" in body
        # Clean tally excludes blocked
        assert "Clean captures: 1 / 2" in body
