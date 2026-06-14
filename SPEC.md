# StyleScrape — Design Spec

**Status:** Draft v1.0 — June 2026 (preserved as original spec)
**Author:** Justyn Roberts

> **As-built note (v0.3.0 shipped):** This is the original draft. See `README.md` for the actual current behaviour. Most of the spec landed as written; two deltas worth flagging:
>
> - **Added:** batch / promiscuous mode (`stylescrape --batch "<query>" -o <dir>`) — uses `claude -p` to discover the top N sites for a category, then renders each concurrently and writes one markdown per site + an `index.md` catalogue. Not in the original FR list.
> - **Deferred:** CSS custom-property resolution (FR-02). The inspector originally captured `:root` custom props but nothing consumed them downstream, so the capture was removed in cleanup. Re-add if/when needed.

## Overview

StyleScrape is a local CLI that accepts a URL, fully renders the page using a headless browser, extracts computed visual design tokens (fonts, colours, spacing, components, motion), and pipes a structured summary through `claude -p` to produce a reusable prompt describing the site's design system. The output can be fed directly back to Claude to recreate or riff on the aesthetic in new UI work.

Core use case: you find an admin interface or marketing site with a design language you want to match or draw from. Instead of manually cataloguing it, you run `stylescrape https://example.com/admin` and get a ready-to-use design system prompt.

## Problem statement

Designing interfaces from scratch while trying to match an existing site's visual language is tedious. Browser devtools let you inspect individual elements, but building a coherent picture of the full design system requires manually hunting across stylesheets, computed styles, and component patterns. This is especially painful when:

- Working with SPAs where styles are injected at runtime
- Trying to match a client's existing admin UI
- Iterating quickly on UI prototypes that need to feel "on brand"

There's no tool that turns "a website" into "a design prompt" in one command.

## Goals

- Extract a complete, usable design token set from any rendered web page
- Work with modern SPAs (React, Vue, Angular), not just static HTML
- Produce output compatible with `claude -p` pipe mode (Max subscription, no API key needed)
- Run as a single command with a URL as the only required argument
- Produce a structured, reusable prompt — not just raw data
- Stay local: no SaaS, no accounts, no telemetry

## Non-goals

- Pixel-perfect recreation of layouts
- Extracting copy/content from pages
- Pages behind authentication (v1)
- A GUI

## Functional requirements

### FR-01 — Page rendering
- Headless browser (Playwright) to fully render including JS-injected styles
- Wait for network idle + DOM settled before extraction (configurable, default 5s)
- Handle SPAs by waiting for hydration signals
- Follow redirects

### FR-02 — Design token extraction
Extract from computed styles of key structural elements.

**Typography:** font families (display, body, mono, UI), sizes at each heading level + body, weights, line heights, letter spacing, text transforms.

**Colour:** backgrounds (body, cards, sidebars, navbars); text (primary, secondary, muted, on-dark); accent/brand from interactive elements; borders; shadows + opacity; whether the site is dark, light, or both.

**Spacing & layout:** border radii (buttons, cards, inputs, avatars); padding/margin on key layout containers; max content width; grid/flex patterns on main content.

**Elevation & depth:** box-shadow values; z-index layering (modals, dropdowns, tooltips).

**Motion:** transition durations, easings, animation keyframes referenced in stylesheets.

### FR-03 — Component pattern detection
Identify and describe common UI patterns: navigation (topbar, sidebar, tabs, breadcrumbs); data display (tables, cards, stat widgets); forms (inputs, selects, checkboxes, toggles); feedback (alerts, badges, toasts, progress); buttons (primary, secondary, ghost, destructive); modals/overlays. For each detected pattern, note the visual treatment.

### FR-04 — Output formats
- **Default — Claude prompt** via `claude -p`. Outputs a ready-to-use design system description prompt.
- **`--json`** — raw extracted tokens.
- **`--markdown`** — human-readable design system summary.
- **`--prompt-only` / `--no-claude`** — assembled prompt printed without invoking `claude -p`.

### FR-05 — CLI

```
stylescrape <url> [options]

  --format          prompt (default), json, markdown
  --prompt-only     print prompt without running claude
  --no-claude       alias for --prompt-only
  --wait <ms>       extra wait after page load (default 2000)
  --selector <css>  focus extraction on a container element
  --dark            force dark mode media query
  --light           force light mode media query
  --screenshot      save a screenshot alongside the output
  --verbose         show extraction steps and timing
  --output <file>   write output to file instead of stdout
  --model <name>    override the model used by claude -p
```

### FR-06 — Claude prompt quality
The generated prompt must be self-contained (no references the model can't resolve), include hex values rather than CSS variable names, describe components in natural language rather than CSS, include a "personality" framing, and be structured so it can be dropped into any UI generation request as a prefix.

## Technical design

### Architecture

```
CLI → URL normalise → Playwright render (networkidle)
    → Inspector (sample-selector computed styles)
    → Aggregator (dedup, hex, ΔE cluster, freq rank)
    → Component detector (DOM/ARIA/classname heuristics)
    → Prompt builder (Jinja2 template)
    → claude -p stage 1 (personality)
    → claude -p stage 2 (assembly)
    → stdout / file
```

### Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | Python 3.11+ | `claude -p` subprocess pipe, asyncio, ecosystem |
| Headless browser | Playwright (Python) | Full render, computed styles API, handles SPAs |
| Colour | `colormath2` | ΔE-2000 perceptual clustering |
| Templating | Jinja2 | Structured prompt assembly |
| Terminal output | Rich | Clean logging |
| Packaging | pipx-installable | Single install, isolated deps |

### Sampling strategy

`inspector.py` runs a single `page.evaluate()` over a fixed ~30-selector probe list. This is deliberate — walking the whole DOM is slow and noisy. Selectors cover structural landmarks (`body`, `main`, `nav`, …), headings (`h1`–`h4`), interactives (buttons, inputs, anchors), data (`table`, `th`, `td`), and class-shaped probes (`[class*="card"]`, `[class*="badge"]`, …).

### Two-stage LLM pipeline

Stage 1 takes ~200 tokens of raw token summary and asks `claude -p` for a 2–3 sentence personality paragraph. Stage 2 embeds that paragraph in the full filled template (~1000 tokens) and runs `claude -p` again. The stage-2 prompt instructs Claude to output a design brief rather than a spec sheet, so the result is natural to paste as a prefix prompt in future UI work.

### Error handling

| Scenario | Behaviour |
|---|---|
| URL unreachable | Exit with clear error, suggest `--wait` |
| Page renders but JS errors | Log warnings, continue with partial extraction |
| Selector not found | Skip silently, note in `--verbose` |
| `claude` not on PATH | Detect early, fall back to `--prompt-only` |
| Playwright browsers missing | Prompt user to run `playwright install chromium` |
| Idle-wait timeout | Warn, proceed with what was captured |

## Phased delivery

**v0.1 — Core extraction:** Playwright rendering, computed-style extraction, colour/font/radius/shadow tokens, basic `claude -p`, `--prompt-only` and `--json`.

**v0.2 — Component detection:** Heuristic pattern detection, two-stage LLM pipeline, `--selector` and `--screenshot`.

**v0.3 — Polish:** `--dark`/`--light` mode, ΔE clustering, CSS custom-property resolution, Jinja2 templates with multiple output styles, pipx packaging.

## Open questions

- Should we extract Google Fonts `@import` URLs and resolve them to family names? (Likely v0.2.)
- Auth support via `--cookie-file` or `--auth-header`? (Useful for admin UIs.)
- Should the prompt include an ASCII wireframe of the detected layout?
- A `--compare` mode: diff two URLs and describe how their design systems differ.

---

*Tags: tooling, design, cli, playwright, claude-p, design-systems, reverse-engineering*
