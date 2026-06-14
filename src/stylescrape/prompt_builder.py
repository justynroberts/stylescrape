"""Fill Jinja2 templates from extracted tokens and (optionally) run claude -p."""

from __future__ import annotations

import shutil
import subprocess
from importlib import resources
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .types import DesignTokens


def _env() -> Environment:
    path = resources.files("stylescrape").joinpath("templates")
    return Environment(
        loader=FileSystemLoader(str(path)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_personality_prompt(tokens: DesignTokens) -> str:
    return _env().get_template("personality.j2").render(tokens=tokens)


def render_design_prompt(tokens: DesignTokens, personality: str) -> str:
    return (
        _env()
        .get_template("design_prompt.j2")
        .render(tokens=tokens, personality=personality.strip())
    )


def render_markdown(tokens: DesignTokens) -> str:
    return _env().get_template("markdown.j2").render(tokens=tokens)


def claude_available() -> bool:
    return shutil.which("claude") is not None


class ClaudeError(RuntimeError):
    pass


def run_claude(prompt: str, model: str | None = None, timeout: int = 120) -> str:
    """Pipe `prompt` into `claude -p` and return the model's reply.

    Uses the user's Max subscription via the local `claude` CLI — no API key.
    """
    if not claude_available():
        raise ClaudeError("`claude` CLI not found on PATH. Use --no-claude to skip.")
    cmd = ["claude", "-p"]
    if model:
        cmd += ["--model", model]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeError(f"`claude -p` timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise ClaudeError(
            f"`claude -p` exited with code {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


OutputFormat = Literal["prompt", "json", "markdown"]


def build(
    tokens: DesignTokens,
    fmt: OutputFormat = "prompt",
    use_claude: bool = True,
    model: str | None = None,
) -> str:
    """End-to-end builder. Returns the final string for the chosen format."""
    if fmt == "json":
        import json

        return json.dumps(tokens.to_dict(), indent=2)

    if fmt == "markdown":
        return render_markdown(tokens)

    # fmt == "prompt"
    personality_in = render_personality_prompt(tokens)
    final_in = render_design_prompt(tokens, personality="")

    if not use_claude:
        # Concatenate the two prompts the user would otherwise pipe.
        return (
            "# ---- STAGE 1: PERSONALITY PROMPT (pipe to `claude -p`) ----\n\n"
            + personality_in
            + "\n\n# ---- STAGE 2: ASSEMBLY PROMPT (pipe to `claude -p`) ----\n\n"
            + final_in
        )

    personality = run_claude(personality_in, model=model)
    final_prompt = render_design_prompt(tokens, personality=personality)
    return run_claude(final_prompt, model=model)
