# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

StyleScrape is a local Python CLI that takes a URL, renders it with headless Chromium, extracts computed design tokens (colour, type, spacing, motion, components), and pipes a structured summary through `claude -p` to produce a reusable design-system prompt. The output is meant to be dropped into future UI generation prompts as a prefix.

Status: **v0.3.0 shipped**, single-site mode + batch mode both live. The README is the as-built doc; `SPEC.md` is the original draft (preserved). This file captures what a future session needs to operate without re-reading either.

## Architecture (planned)

The pipeline is linear and worth holding in your head as a whole because each stage's output shape constrains the next:

```
CLI → URL normalise → Playwright render → DOM inspector (computed styles)
    → aggregator (dedup, hex-resolve, cluster, frequency-rank)
    → component detector (heuristic DOM/ARIA/classname matching)
    → prompt builder (Jinja2 template)
    → two-stage claude -p (personality, then assembly)
    → stdout / file
```

Module layout the spec commits to:

- `renderer.py` — Playwright wrapper. Chromium headless, 1440×900, `networkidle` + extra wait. Exposes `color_scheme` so `--dark` / `--light` can force the media query.
- `inspector.py` — runs a single `page.evaluate()` over a fixed list of ~30 sample selectors (landmarks, headings, buttons, inputs, table cells, `[class*="card"]`-style probes) and pulls a fixed list of computed CSS properties. Do NOT walk the whole DOM — the sample-selector approach is deliberate for speed and noise control.
- `aggregator.py` — resolves `rgb()`→hex, clusters colours by ΔE<10 to find the real palette, frequency-ranks font sizes/radii/shadows, strips system fonts unless they're the only option.
- `component_detector.py` — heuristics over semantic elements, ARIA roles, classname patterns, and child structure. Output is a list of (pattern, visual treatment).
- `prompt_builder.py` — fills a Jinja2 template. Sections: personality, palette, typography, spacing/shape, elevation, motion, component inventory, usage instructions.
- `discovery.py` — turns a category prompt ("top 10 CRM tools") into a vetted list of URLs by piping a JSON-schema request through `claude -p`. Validates URLs, dedupes by host, respects the count ceiling.
- `batch.py` — orchestrates the discovery + per-site pipeline. Renders concurrently under a semaphore (default 3), isolates failures (one bad render does not kill the run), writes a markdown per site plus an `index.md` catalogue.

### Two-stage LLM pipeline

Stage 1 takes the raw token summary and asks `claude -p` for a 2–3 sentence personality paragraph. Stage 2 embeds that paragraph in the full filled template and runs `claude -p` again to polish the whole thing into a design brief. Keep both calls small and focused — don't collapse them into one mega-prompt.

### Output mode rules

- Default: render → extract → pipe through `claude -p` → print final prompt.
- `--prompt-only` / `--no-claude`: print the assembled prompt without calling `claude`. Use this when `claude` isn't on PATH or for review.
- `--json`: raw token dict, no LLM involvement.
- `--markdown`: human-readable summary, no LLM involvement.

The generated prompt must include **hex values, not CSS variable names**, and describe components in natural language, not CSS. It needs to be self-contained — no references the consuming model can't resolve.

## Tech stack (locked in by the spec)

| Layer | Choice |
| --- | --- |
| Runtime | Python 3.11+ |
| Headless browser | Playwright (Python), Chromium |
| CSS parsing | `cssutils` + Playwright computed styles |
| Colour | `colorthief` + `colormath` (for ΔE clustering) |
| Templating | Jinja2 |
| Terminal output | Rich |
| Packaging | pipx-installable package |

Don't substitute these without reason — Playwright over Puppeteer is a deliberate Python-ergonomics call, and ΔE clustering depends on `colormath`.

## Commands

```bash
# install
pipx install -e .
playwright install chromium

# single-site mode
stylescrape <url> [--format prompt|json|markdown] [--prompt-only]
            [--wait <ms>] [--selector <css>] [--dark|--light]
            [--screenshot] [--verbose] [--output <file>] [--no-claude]

# batch / promiscuous mode — uses claude -p for discovery, then renders
# each site concurrently and writes a markdown per site + index.md
stylescrape --batch "<query>" -o <dir> [-n <count>] [-c <concurrency>]
            [--format markdown|json|prompt] [--with-prompt] [--dry-run]
            [--dark|--light] [--verbose]
```

Full flag semantics are in the README / SPEC (FR-05).

## Non-goals (do not creep into these)

- Pixel-perfect layout recreation
- Content/copy extraction
- Auth-gated pages (deferred past v1)
- GUI
- SaaS / telemetry / accounts

## What's actually shipped (v0.3.0)

- Single-site mode: render → extract → aggregate → component detect → two-stage `claude -p` → stdout.
- Output formats: `prompt` (LLM-polished brief, default), `markdown` (offline catalogue), `json` (raw tokens).
- Batch mode (`--batch "<query>" -o <dir>`): `claude -p` discovers top N sites for a category, then each is rendered concurrently and written as a per-site file plus an `index.md` catalogue. Failures are isolated.
- Flags: `--dark`/`--light` colour-scheme forcing, `--selector` focus, `--screenshot`, `--no-claude` / `--prompt-only`, `--with-prompt` (batch + claude per site), `--dry-run` (discovery only), `--concurrency`, `--count`, `--model`, `--wait`, `--verbose`, `--output`.
- ΔE-2000 colour clustering via `colormath2` (sRGB-distance fallback).
- 86 unit tests, ruff-clean. Installs via `pipx install -e .` plus `playwright install chromium`.

## Spec features NOT shipped

- **CSS custom-property resolution.** v0.3 promised this; the inspector originally captured `:root` custom props but nothing in the aggregator consumed them, so the capture was removed in cleanup. Re-add the JS extract in `inspector.py` and wire `RawCapture.stylesheet_custom_props` back if you implement it.
- **Auth via `--cookie-file` / `--auth-header`.** Still v2 territory.
- **`--compare` mode.** Open question, not started.
- **ASCII wireframe in the prompt output.** Open question, not started.

When adding features, prefer the layered pipeline (renderer → inspector → aggregator → component_detector → prompt_builder) over plumbing new data flows directly to the CLI.

## Error-handling expectations

The spec commits to specific behaviours per failure mode — match these rather than improvising:

- URL unreachable → exit with clear error, suggest `--wait`.
- JS errors on page → log warnings, continue with partial extraction.
- Sample selector not found → skip silently, surface in `--verbose`.
- `claude` not on PATH → detect early, suggest `--prompt-only`.
- Playwright browsers missing → prompt user to run `playwright install chromium`.
- Idle-wait timeout → warn, proceed with what was captured.

## Repo conventions

- This project lives under `~/work/` and follows the brain-repo conventions in `~/work/CLAUDE.md` and `~/.claude/CLAUDE.md` (durable preferences go to `~/work/claude-code-environment/memory/`, not inline here).
- No git repo yet — initialise with `git init` before the first commit. Follow global attribution rules (no Claude co-author / signature lines).
