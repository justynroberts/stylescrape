"""Sample computed styles + structural signals from a rendered page.

The deliberate choice is to probe a fixed set of selectors rather than walk the
whole DOM. This is both faster and noise-controlled — see CLAUDE.md.

Three probe categories run as separate `page.evaluate` calls:
- styling probes: typography / colour / shape / motion props across landmarks
- layout probes: container widths, grid templates, gaps on structural elements
- DOM signal probes: counts and class-name patterns for component detection
- :root custom-prop dump: the design-vocabulary the team named
- subpage discovery: same-origin candidates for multi-page rendering
"""

from __future__ import annotations

from playwright.async_api import Page

from .types import RawCapture

SAMPLE_SELECTORS: list[str] = [
    # structural landmarks
    "body",
    "main",
    "nav",
    "header",
    "aside",
    "footer",
    # headings + text
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "label",
    "small",
    # interactive
    "button:not([disabled])",
    "a",
    "input[type='text']",
    "input[type='email']",
    "select",
    "textarea",
    # data
    "table",
    "th",
    "td",
    "li",
    "code",
    "pre",
    # component-shaped probes (class heuristics)
    "[class*='card']",
    "[class*='badge']",
    "[class*='alert']",
    "[class*='sidebar']",
    "[class*='modal']",
    "[class*='toast']",
    "[class*='chip']",
    "[class*='tag']",
    "[class*='avatar']",
    "[class*='dropdown']",
    "[class*='tooltip']",
    "[role='dialog']",
    "[role='alert']",
    "[role='navigation']",
    "[role='tablist']",
]

CSS_PROPS: list[str] = [
    "font-family",
    "font-size",
    "font-weight",
    "line-height",
    "letter-spacing",
    "text-transform",
    "color",
    "background-color",
    "border-color",
    "border-width",
    "border-style",
    "border-radius",
    "box-shadow",
    "padding",
    "margin",
    "transition",
    "opacity",
    "outline-color",
]

# Layout probes — structural containers, not styling surfaces. We sample these
# separately so type/colour aggregation isn't polluted by `<section>` defaults.
LAYOUT_SELECTORS: list[str] = [
    "main",
    "[class*='container']",
    "[class*='wrapper']",
    "[class*='content']",
    "[class*='inner']",
    "[class*='page']",
    "section",
    "header > div",
    "footer > div",
    "[class*='grid']",
    "[class*='hero']",
    "[class*='row']",
    "[class*='cols']",
]

LAYOUT_PROPS: list[str] = [
    "max-width",
    "width",
    "display",
    "grid-template-columns",
    "gap",
    "row-gap",
    "column-gap",
    "padding",
    "padding-top",
    "padding-bottom",
    "margin-left",
    "margin-right",
]


_JS_EXTRACT = """
(args) => {
  const { selectors, props } = args;
  const results = {};
  for (const sel of selectors) {
    let el;
    try { el = document.querySelector(sel); } catch (e) { continue; }
    if (!el) continue;
    const cs = window.getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p).trim();
    results[sel] = row;
  }
  return results;
}
"""

_JS_LAYOUT = """
(args) => {
  const { selectors, props } = args;
  const results = {};
  let key = 0;
  for (const sel of selectors) {
    let nodes;
    try { nodes = document.querySelectorAll(sel); } catch (e) { continue; }
    // Sample up to 3 distinct elements per selector — first few are usually
    // structural; deeper repetitions tend to repeat the same computed values.
    let n = 0;
    for (const el of nodes) {
      if (n >= 3) break;
      const cs = window.getComputedStyle(el);
      const row = {};
      for (const p of props) row[p] = cs.getPropertyValue(p).trim();
      results[`${sel}#${key++}`] = row;
      n++;
    }
  }
  return results;
}
"""

_JS_CUSTOM_PROPS = """
() => {
  const out = {};
  const cs = window.getComputedStyle(document.documentElement);
  // CSSStyleDeclaration iterator yields all declared properties including custom.
  for (const name of cs) {
    if (name.startsWith('--')) {
      const v = cs.getPropertyValue(name).trim();
      if (v) out[name] = v;
    }
  }
  return out;
}
"""

_JS_SUBPAGES = """
(maxCount) => {
  const patterns = [
    /\\/pricing\\/?$/i,
    /\\/about\\/?$/i,
    /\\/features\\/?$/i,
    /\\/product\\/?$/i,
    /\\/docs\\/?$/i,
    /\\/customers\\/?$/i,
    /\\/solutions\\/?$/i,
    /\\/why-[a-z0-9-]+\\/?$/i,
  ];
  const origin = window.location.origin;
  const here = window.location.pathname.replace(/\\/$/, '');
  const seen = new Set();
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    let url;
    try { url = new URL(a.href, window.location.href); } catch (e) { continue; }
    if (url.origin !== origin) continue;
    const path = url.pathname.replace(/\\/$/, '');
    if (!path || path === here || seen.has(path)) continue;
    for (const p of patterns) {
      if (p.test(path)) {
        seen.add(path);
        out.push(url.origin + path);
        break;
      }
    }
    if (out.length >= maxCount) break;
  }
  return out;
}
"""

_JS_DOM_SIGNALS = """
() => {
  const q = (s) => document.querySelectorAll(s).length;
  const cls = (re) => {
    let n = 0;
    document.querySelectorAll('[class]').forEach(el => {
      if (re.test(el.className)) n++;
    });
    return n;
  };
  const has = (s) => !!document.querySelector(s);
  return {
    counts: {
      nav: q('nav'),
      table: q('table'),
      form: q('form'),
      button: q('button'),
      input: q('input'),
      dialog: q('dialog, [role=dialog]'),
      tabs: q('[role=tablist]'),
      alert: q('[role=alert]'),
      tooltip: q('[role=tooltip]'),
    },
    classes: {
      card: cls(/\\bcard\\b/i),
      sidebar: cls(/\\bsidebar\\b/i),
      modal: cls(/\\bmodal\\b/i),
      badge: cls(/\\bbadge\\b/i),
      toast: cls(/\\btoast\\b/i),
      dropdown: cls(/\\bdropdown|menu\\b/i),
      chip: cls(/\\bchip|tag\\b/i),
      avatar: cls(/\\bavatar\\b/i),
    },
    has: {
      breadcrumbs: has('[class*=breadcrumb], nav[aria-label*=breadcrumb i]'),
      progress: has('progress, [role=progressbar]'),
      toggle: has('[role=switch], input[type=checkbox]'),
    },
    bodyBg: window.getComputedStyle(document.body).getPropertyValue('background-color'),
  };
}
"""


async def capture(page: Page) -> RawCapture:
    """Pull computed styles, layout, custom props, and structural signals."""
    try:
        title = await page.title()
    except Exception:
        title = ""

    sampled = await page.evaluate(
        _JS_EXTRACT, {"selectors": SAMPLE_SELECTORS, "props": CSS_PROPS}
    )
    layout = await page.evaluate(
        _JS_LAYOUT, {"selectors": LAYOUT_SELECTORS, "props": LAYOUT_PROPS}
    )
    try:
        custom_props = await page.evaluate(_JS_CUSTOM_PROPS)
    except Exception:
        custom_props = {}
    dom_signals = await page.evaluate(_JS_DOM_SIGNALS)

    return RawCapture(
        url=page.url,
        title=title,
        sampled_styles=sampled,
        dom_signals=dom_signals,
        layout_samples=layout,
        custom_props=custom_props,
    )


async def find_subpages(page: Page, max_count: int = 3) -> list[str]:
    """Find up to `max_count` same-origin subpages worth crawling.

    Used by multi-page mode to render `/pricing`, `/about`, `/features` etc.
    alongside the landing page so the aggregator sees the full design system.
    """
    if max_count <= 0:
        return []
    try:
        return await page.evaluate(_JS_SUBPAGES, max_count)
    except Exception:
        return []


async def capture_pages(
    url: str,
    opts,
    max_pages: int = 1,
    screenshot_path: str | None = None,
) -> list[RawCapture]:
    """Render `url` plus up to `max_pages - 1` discovered same-origin subpages.

    Returns the list of captures (main page first). Subpage failures are silently
    skipped — the main capture is what really matters; subpages are bonus signal.
    """
    from .renderer import rendered_page, screenshot

    captures: list[RawCapture] = []
    subpage_urls: list[str] = []

    async with rendered_page(url, opts) as page:
        cap = await capture(page)
        captures.append(cap)
        if screenshot_path:
            await screenshot(page, screenshot_path)
        if max_pages > 1:
            subpage_urls = await find_subpages(page, max_pages - 1)

    for sub_url in subpage_urls:
        try:
            async with rendered_page(sub_url, opts) as page:
                captures.append(await capture(page))
        except Exception:  # subpage failure is non-fatal, the main capture is what matters
            continue

    return captures
