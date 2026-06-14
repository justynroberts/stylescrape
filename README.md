# StyleScrape

Point it at a URL. Get a Claude-ready design-system prompt.

StyleScrape is a local CLI that renders a page with headless Chromium, extracts computed design tokens (colour, type, spacing, motion, components), and pipes a structured summary through `claude -p` to produce a reusable design brief. The output is meant to be dropped into your next UI prompt as a prefix so the model builds in the right aesthetic.

No SaaS. No accounts. No API key — it uses your local `claude` CLI (Max subscription).

## Install

```bash
pipx install stylescrape
playwright install chromium
```

From source:

```bash
git clone https://github.com/justynroberts/stylescrape
cd stylescrape
pipx install -e .
playwright install chromium
```

Requirements:

- Python 3.11+
- `claude` CLI on PATH for the default mode (skip with `--no-claude`)
- Chromium installed via `playwright install`

## Use

### Single-site mode

```bash
stylescrape https://linear.app
```

This renders the page, extracts tokens, runs the two-stage `claude -p` pipeline, and prints a polished design brief to stdout.

Common variants:

```bash
# Just give me the raw tokens
stylescrape https://linear.app --format json

# Human-readable summary, no Claude calls
stylescrape https://linear.app --format markdown

# Print the prompt without running claude (useful for review or manual pipe)
stylescrape https://linear.app --no-claude

# Force the dark-mode media query when rendering
stylescrape https://stripe.com --dark

# Focus extraction on a specific element
stylescrape https://example.com/admin --selector ".dashboard"

# Save a screenshot alongside
stylescrape https://linear.app --screenshot linear.png

# Write to a file
stylescrape https://linear.app --output linear-system.md

# Show timings + skipped probes
stylescrape https://linear.app --verbose
```

### Batch / promiscuous mode

Point at a category instead of a URL. StyleScrape asks `claude -p` for the top N sites in that category, then renders each one concurrently and writes a markdown per site plus an `index.md` catalogue into the output directory.

```bash
stylescrape --batch "top 10 CRM tools" -o ./crm-systems

# tighter run with custom count + concurrency
stylescrape --batch "top 5 password managers" -n 5 -c 3 -o ./pw/

# discover only — see which sites would be rendered
stylescrape --batch "top 10 admin UI templates" -o ./out --dry-run

# also run the two-stage claude polish per site (slower, costs LLM calls)
stylescrape --batch "top 5 dev tool landing pages" --with-prompt -o ./out
```

You get back a directory like:

```
./crm-systems/
├── index.md            # catalogue with rationale + status per site
├── salesforce-com.md   # design system per site
├── hubspot-com.md
├── pipedrive-com.md
├── zoho-com.md
└── ...
```

Each site renders independently — one failure (timeout, blocked region, JS bomb) doesn't kill the run. The failure shows up in `index.md` with the reason.

Batch flags:

| Flag | Default | Notes |
|---|---|---|
| `--batch "<query>"` | — | Enables batch mode. Mutually exclusive with `<url>`. |
| `--count` / `-n` | `10` | Number of sites to discover and scrape. Max 50. |
| `--output` / `-o` | required | Output directory. |
| `--concurrency` / `-c` | `3` | Concurrent page renders. |
| `--format` | `markdown` | Per-site format: `markdown`, `json`, or `prompt`. |
| `--with-prompt` | off | Also run the two-stage `claude -p` per site. |
| `--dry-run` | off | Discover URLs and print them; skip rendering. |

## Examples

### Single-site lookups

```bash
# 1. Default: render, extract, run two-stage claude -p, print polished design brief
stylescrape https://linear.app

# 2. Just the raw tokens — pipe into jq or another tool
stylescrape https://linear.app --format json | jq '.colors[0:5]'

# 3. Human-readable summary, no LLM calls, costs nothing
stylescrape https://linear.app --format markdown

# 4. Print the assembled prompt without invoking claude
#    (review it first, then pipe it yourself, or save for later)
stylescrape https://linear.app --no-claude > linear-prompt.txt

# 5. Save the polished brief straight to a file you can use as a prompt prefix later
stylescrape https://linear.app --output linear-system.md

# 6. Force the dark-mode media query when rendering (sites that auto-detect)
stylescrape https://stripe.com --dark --output stripe-dark.md

# 7. Focus extraction on a specific container (e.g. the dashboard shell of an SPA)
stylescrape https://example.com/app --selector ".dashboard" --wait 4000

# 8. Save a screenshot alongside the design brief
stylescrape https://linear.app --screenshot linear.png --output linear-system.md

# 9. Verbose: see per-stage timings + skipped probes
stylescrape https://anthropic.com --verbose

# 9a. Multi-page render — auto-crawl /pricing, /about, /features, etc.
#     Richer extraction (more frequency data, wider size scale, named-token harvest).
stylescrape https://linear.app -p 3 --format markdown --output linear-deep.md
```

### Batch catalogues

```bash
# 10. Catalogue the top 10 CRM tool design systems into a directory
stylescrape --batch "top 10 CRM tools" -o ./design-systems-crm/

# 11. Tighter scope: top 5 password managers, higher concurrency for speed
stylescrape --batch "top 5 password managers" -n 5 -c 5 -o ./pw/

# 12. Dry-run first: see which sites claude picks before spending render time
stylescrape --batch "top 10 admin UI templates" -o ./admin/ --dry-run

# 13. Big sweep: top 20 dev-tool landing pages with verbose per-site progress
stylescrape --batch "top 20 developer tool landing pages" -n 20 -c 4 -v -o ./devtools/

# 14. Also generate the polished claude -p brief per site (slow, costs LLM calls)
stylescrape --batch "top 5 fintech landing pages" --with-prompt -o ./fintech/

# 15. Force dark-mode rendering across an entire batch
stylescrape --batch "top 10 terminal apps" --dark -o ./terminals/

# 16. JSON per site instead of markdown — for programmatic consumption
stylescrape --batch "top 10 SaaS pricing pages" --format json -o ./pricing/

# 16a. Deep batch — render 3 pages per site so the catalogue captures
#      layout DNA, named-token vocabularies, and stepped surface elevations.
#      ~3x slower per site; worth it for design-research depth.
stylescrape --batch "top 10 observability vendors" -p 3 -o ./obs-deep/
```

### Composing with other tools

```bash
# 17. Pipe the prompt straight into another claude call (no temp file)
stylescrape https://linear.app --no-claude | claude -p "Use this design system to build a sign-up form."

# 18. Extract just the palette as hex codes
stylescrape https://stripe.com --format json | jq -r '.colors[].hex'

# 19. Compare the palettes of two sites with diff
diff \
  <(stylescrape https://linear.app --format json | jq -r '.colors[].hex') \
  <(stylescrape https://notion.so --format json | jq -r '.colors[].hex')

# 20. Loop a small custom list (when batch discovery isn't what you want)
for url in https://linear.app https://notion.so https://figma.com; do
  stylescrape "$url" --format markdown --output "$(basename $url).md"
done
```

> Tip: in the default (polished prompt) mode, single-site renders take ~3–8s and use two `claude -p` calls. To skip both LLM calls entirely, add `--no-claude`. For batch runs, only the initial discovery call goes through `claude -p` unless you also pass `--with-prompt`.

## What you get back

Default mode produces something like:

```
PERSONALITY
This interface uses a disciplined dark design system built around near-black surfaces
and a single violet accent. The aesthetic is professional and dense, optimised for
power users who spend hours in the tool.

COLOUR PALETTE
- Background primary: #0F0F11
- Background elevated: #1A1A1F
- Text primary: #E8E8ED
- Accent violet: #5E6AD2
...

TYPOGRAPHY
- Display: Inter, -apple-system, sans-serif
- Mono: JetBrains Mono, monospace
- Scale: 11px / 12px / 13px / 14px / 16px / 20px / 24px / 32px
...
```

That whole block is designed to be pasted as a prefix into your next "build me a UI for X" prompt.

## How it works

```
URL → Playwright (Chromium, 1440×900, networkidle)
    → Inspector: ~30 styling probes + ~13 layout probes + :root custom-prop dump
    → (optional) Auto-crawl /pricing, /about, /features → render + capture each
    → Aggregator: rgb()→hex, ΔE colour clustering, frequency rank,
      scale-ratio detection, spacing-base detection, layout pattern,
      tighter background-only ΔE pass for elevation steps,
      named-token harvest with role inference
    → Component detector: heuristic DOM/ARIA/classname matching
    → Jinja2 prompt template (Layout, Scale, Elevation, Named Vocabulary
      sections in addition to palette/type/shape/motion/components)
    → claude -p (stage 1: personality, stage 2: assembly)
    → stdout
```

The pipeline deliberately samples a fixed set of representative selectors rather than walking the entire DOM. It's faster, noise-controlled, and gets you a usable palette in seconds.

Two `claude -p` calls instead of one keeps each prompt small and focused: stage 1 turns raw tokens into a short personality paragraph, stage 2 embeds that paragraph into the full template and polishes the result into a design brief. Skip the whole LLM stage with `--no-claude`.

### Depth: what you get vs. what you can get

| Flag | What happens | Typical wall clock |
|---|---|---|
| `-p 1` (default) | Renders the URL you gave. | 3–8s |
| `-p 2` | Adds one auto-discovered subpage (`/pricing` or `/about` if linked from the landing page). | +5–10s |
| `-p 3` | Three pages total — the richest catalogue without going crazy. | +10–20s |

Multi-page gives you a wider type scale, more named tokens, more component patterns, and frequency counts that actually reflect what's reused. Use `-p 3` when you want a brief detailed enough to drive "build me a comparable UI" prompts.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--format` | `prompt` | `prompt`, `json`, or `markdown` |
| `--prompt-only` | off | Print assembled prompt without calling claude |
| `--no-claude` | off | Alias for `--prompt-only` |
| `--pages <n>` / `-p` | `1` | Render this many same-origin pages (auto-crawls subpages) |
| `--wait <ms>` | `2000` | Extra wait after networkidle |
| `--selector <css>` | none | Focus extraction on a container |
| `--dark` / `--light` | off | Force prefers-color-scheme |
| `--screenshot <path>` | none | Save a full-page screenshot |
| `--verbose` | off | Show timings and skipped probes |
| `--output <path>` | stdout | Write output to a file |
| `--model <name>` | claude default | Override the model used by `claude -p` |

## What it doesn't do

- Pixel-perfect layout recreation — different problem
- Content / copy extraction
- Auth-gated pages (planned past v1)
- GUI

## Development

```bash
git clone https://github.com/justynroberts/stylescrape
cd stylescrape
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

pytest          # run unit tests (no network, no browser)
ruff check src tests
```

Module layout:

```
src/stylescrape/
  cli.py                  # Click entrypoint (single + batch modes)
  renderer.py             # Playwright wrapper
  inspector.py            # Sample selectors + computed-style probe
  aggregator.py           # ΔE clustering, frequency rank, role inference
  component_detector.py   # Heuristic component pattern matching
  prompt_builder.py       # Jinja2 + claude -p subprocess
  discovery.py            # claude -p → list of URLs for a category
  batch.py                # Orchestrate concurrent renders + write catalogue
  templates/              # *.j2 templates for personality, design brief, markdown
  types.py                # Dataclasses passed between stages
```

See [`SPEC.md`](SPEC.md) for the full design doc.

## License

MIT
