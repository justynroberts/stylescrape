"""Sample computed styles + structural signals from a rendered page.

The deliberate choice is to probe a fixed set of selectors rather than walk the
whole DOM. This is both faster and noise-controlled — see CLAUDE.md.
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
    """Pull computed styles and structural signals from the rendered page."""
    try:
        title = await page.title()
    except Exception:
        title = ""

    sampled = await page.evaluate(
        _JS_EXTRACT, {"selectors": SAMPLE_SELECTORS, "props": CSS_PROPS}
    )
    dom_signals = await page.evaluate(_JS_DOM_SIGNALS)

    return RawCapture(
        url=page.url,
        title=title,
        sampled_styles=sampled,
        dom_signals=dom_signals,
    )
