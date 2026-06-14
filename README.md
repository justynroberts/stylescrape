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
    → Inspector: ~30 sample selectors × 18 computed CSS props
    → Aggregator: rgb()→hex, ΔE colour clustering, frequency rank
    → Component detector: heuristic DOM/ARIA/classname matching
    → Jinja2 prompt template
    → claude -p (stage 1: personality, stage 2: assembly)
    → stdout
```

The pipeline deliberately samples a fixed set of representative selectors rather than walking the entire DOM. It's faster, noise-controlled, and gets you a usable palette in seconds.

Two `claude -p` calls instead of one keeps each prompt small and focused: stage 1 turns raw tokens into a short personality paragraph, stage 2 embeds that paragraph into the full template and polishes the result into a design brief. Skip the whole LLM stage with `--no-claude`.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--format` | `prompt` | `prompt`, `json`, or `markdown` |
| `--prompt-only` | off | Print assembled prompt without calling claude |
| `--no-claude` | off | Alias for `--prompt-only` |
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
