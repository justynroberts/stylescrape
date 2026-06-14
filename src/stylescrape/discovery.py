"""Turn a category prompt ("top 10 CRM tools") into a vetted list of URLs via `claude -p`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .prompt_builder import ClaudeError, claude_available, run_claude


@dataclass
class DiscoveredSite:
    name: str
    url: str
    rationale: str = ""


_PROMPT = """\
Return a JSON object listing the top {count} websites for the category below. \
Respond with valid JSON only — no markdown fences, no preamble, no trailing prose.

Category: {query}

Output schema:
{{
  "sites": [
    {{"name": "Notion", "url": "https://notion.so", "rationale": "leading team wiki"}}
  ]
}}

Rules:
- Exactly {count} entries.
- Established, currently-live products only.
- Use the marketing/landing URL (e.g. https://linear.app), not the app or login page.
- HTTPS URLs only. No paths unless required.
- No duplicates. No defunct or paywalled-by-default sites.
- Keep "rationale" under 12 words.
"""


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip ```json fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # Find the outermost {...} block
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"discovery: no JSON object in response: {raw[:200]}")
    return json.loads(raw[start : end + 1])


def _looks_like_url(s: str) -> bool:
    try:
        p = urlparse(s)
        return p.scheme in ("https", "http") and bool(p.netloc)
    except Exception:
        return False


def discover(
    query: str,
    count: int = 10,
    model: str | None = None,
    timeout: int = 120,
) -> list[DiscoveredSite]:
    """Ask `claude -p` for the top `count` sites for `query`."""
    if not claude_available():
        raise ClaudeError(
            "`claude` CLI not found — batch discovery requires the Max-subscription CLI."
        )
    prompt = _PROMPT.format(query=query.strip(), count=count)
    raw = run_claude(prompt, model=model, timeout=timeout)
    data = _extract_json(raw)
    items = data.get("sites") or []
    if not items:
        raise ValueError("discovery: claude returned no sites")

    out: list[DiscoveredSite] = []
    seen: set[str] = set()
    for it in items:
        url = (it.get("url") or "").strip()
        name = (it.get("name") or "").strip() or url
        rationale = (it.get("rationale") or "").strip()
        if not _looks_like_url(url):
            continue
        host = urlparse(url).hostname or url
        if host in seen:
            continue
        seen.add(host)
        out.append(DiscoveredSite(name=name, url=url, rationale=rationale))
        if len(out) >= count:
            break
    if not out:
        raise ValueError("discovery: no valid URLs after filtering")
    return out
