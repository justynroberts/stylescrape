"""Unit tests for discovery: JSON extraction, URL filtering, dedup."""

from __future__ import annotations

import pytest

from stylescrape.discovery import (
    DiscoveredSite,
    _extract_json,
    _looks_like_url,
    discover,
)
from stylescrape.prompt_builder import ClaudeError


class TestExtractJson:
    def test_plain_json(self):
        out = _extract_json('{"sites": [{"name": "x"}]}')
        assert out["sites"][0]["name"] == "x"

    def test_strips_markdown_fence(self):
        raw = '```json\n{"sites": []}\n```'
        out = _extract_json(raw)
        assert out == {"sites": []}

    def test_strips_bare_fence(self):
        raw = '```\n{"sites": [1]}\n```'
        out = _extract_json(raw)
        assert out == {"sites": [1]}

    def test_with_prose_around(self):
        raw = 'Sure, here is the list:\n\n{"sites": [{"a": 1}]}\n\nLet me know if you need more.'
        out = _extract_json(raw)
        assert out["sites"][0]["a"] == 1

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            _extract_json("not json at all")


class TestLooksLikeUrl:
    def test_https(self):
        assert _looks_like_url("https://example.com")

    def test_http(self):
        assert _looks_like_url("http://example.com")

    def test_ftp_rejected(self):
        assert not _looks_like_url("ftp://example.com")

    def test_no_scheme_rejected(self):
        assert not _looks_like_url("example.com")

    def test_empty(self):
        assert not _looks_like_url("")


class TestDiscover:
    def test_happy_path(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude",
            return_value='{"sites": ['
            '{"name": "Linear", "url": "https://linear.app", "rationale": "modern issue tracker"},'
            '{"name": "Notion", "url": "https://notion.so", "rationale": "wiki + db"}'
            "]}",
        )
        sites = discover("top 2 productivity tools", count=2)
        assert len(sites) == 2
        assert sites[0] == DiscoveredSite(
            name="Linear", url="https://linear.app", rationale="modern issue tracker"
        )
        assert sites[1].name == "Notion"

    def test_dedupes_by_host(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude",
            return_value='{"sites": ['
            '{"name": "Linear A", "url": "https://linear.app/", "rationale": "x"},'
            '{"name": "Linear B", "url": "https://linear.app/features", "rationale": "y"},'
            '{"name": "Notion", "url": "https://notion.so", "rationale": "z"}'
            "]}",
        )
        sites = discover("x", count=10)
        names = [s.name for s in sites]
        # Second linear.app entry is dropped
        assert names == ["Linear A", "Notion"]

    def test_drops_non_urls(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude",
            return_value='{"sites": ['
            '{"name": "Bad", "url": "not a url"},'
            '{"name": "Good", "url": "https://example.com"}'
            "]}",
        )
        sites = discover("x", count=5)
        assert len(sites) == 1
        assert sites[0].name == "Good"

    def test_respects_count_ceiling(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude",
            return_value='{"sites": [{"url": "https://a.com"}, {"url": "https://b.com"}, {"url": "https://c.com"}]}',
        )
        sites = discover("x", count=2)
        assert len(sites) == 2

    def test_raises_when_claude_missing(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=False)
        with pytest.raises(ClaudeError):
            discover("x")

    def test_raises_on_empty_list(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude", return_value='{"sites": []}'
        )
        with pytest.raises(ValueError):
            discover("x")

    def test_raises_when_all_filtered(self, mocker):
        mocker.patch("stylescrape.discovery.claude_available", return_value=True)
        mocker.patch(
            "stylescrape.discovery.run_claude",
            return_value='{"sites": [{"url": "not a url"}]}',
        )
        with pytest.raises(ValueError):
            discover("x")
