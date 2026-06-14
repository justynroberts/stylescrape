# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

StyleScrape is a local Python CLI that takes a URL, renders it with headless Chromium, extracts computed design tokens (colour, type, spacing, motion, components), and pipes a structured summary through `claude -p` to produce a reusable design-system prompt. The output is meant to be dropped into future UI generation prompts as a prefix.

Status: **draft spec, no code yet**. The spec lives in this directory as the source of truth — see the README/spec for full functional requirements. This file captures the bits that future sessions need to operate without re-reading the whole spec.

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

## Commands (once implemented)

```bash
# install
pipx install -e .
playwright install chromium

# run
stylescrape <url> [--format prompt|json|markdown] [--prompt-only]
            [--wait <ms>] [--selector <css>] [--dark|--light]
            [--screenshot] [--verbose] [--output <file>] [--no-claude]
```

Full flag semantics are in the spec (FR-05).

## Non-goals (do not creep into these)

- Pixel-perfect layout recreation
- Content/copy extraction
- Auth-gated pages (deferred past v1)
- GUI
- SaaS / telemetry / accounts

## Phasing

- v0.1: rendering + computed-style extraction, colour/font/radius/shadow tokens, basic `claude -p`, `--prompt-only` and `--json`.
- v0.2: component detection, two-stage LLM pipeline, `--selector`, `--screenshot`.
- v0.3: `--dark`/`--light`, ΔE clustering, CSS custom property resolution, Jinja2 templates, pipx packaging.

When adding features, check which phase they belong to and whether the prerequisite phase is in.

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
