"""Decide which profile lines may travel between bash and zsh."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SHARED = "shared"
BASH = "bash"
ZSH = "zsh"
NEVER = "never"

# Lines that mean something different in each shell, or that would make the two
# profiles source one another. They stay wherever their author put them.
NEVER_PATTERNS = (
    r"\.(bashrc|zshrc|bash_profile|zprofile|zshenv|zlogin|zlogout|bash_logout)\b",
    r"^(export\s+)?(PS0|PS1|PS2|PS3|PS4|PROMPT|RPROMPT|RPS1|RPS2|PROMPT_COMMAND)=",
    r"^(export\s+)?(SHELL|ZDOTDIR)=",
    r"^(precmd|preexec|prompt)\s*\(\)",
    r"^\s*(precmd|preexec)_functions",
)

BASH_PATTERNS = (
    r"^shopt\b",
    r"^complete\b",
    r"^compopt\b",
    r"^bind\s",
    r"^(export\s+)?(HISTCONTROL|HISTFILESIZE|HISTTIMEFORMAT|FIGNORE|GLOBIGNORE)=",
    r"^(export\s+)?BASH[A-Z_]*=",
    r"\bBASH_(SOURCE|VERSION|VERSINFO|REMATCH|COMPLETION[A-Z_]*)\b",
    r"bash[-_]completion",
    r"^\s*[.]\s+/(usr|etc)/share/bash",
    r"\b(init|hook|shellenv|completion|completions|integration)\s+bash\b",
    r"--shell[= ]bash\b",
)

ZSH_PATTERNS = (
    r"^(un)?setopt\b",
    r"^bindkey\b",
    r"^zstyle\b",
    r"^autoload\b",
    r"^zmodload\b",
    r"^comp(init|def|audit|install)\b",
    r"^zle\b",
    r"^emulate\b",
    r"^add-zsh-hook\b",
    r"^(zinit|zplug|zplugin|antigen|antidote)\b",
    r"^plugins=\(",
    r"^(export\s+)?(ZSH|SAVEHIST|LISTMAX|WORDCHARS|REPORTTIME)[A-Z_]*=",
    r"^(path|fpath|cdpath|manpath|infopath)=\(",
    r"^typeset\s+-U\b",
    r"^alias\s+-[gs]\b",
    r"\bZSH_(VERSION|NAME|THEME|CUSTOM|CACHE_DIR)\b",
    r"(oh-my-zsh|powerlevel10k|powerlevel9k|\bp10k\b|zsh-syntax-highlighting|zsh-autosuggestions)",
    r"\b(init|hook|shellenv|completion|completions|integration)\s+zsh\b",
    r"--shell[= ]zsh\b",
)


class RulesError(ValueError):
    """The extra-rules file could not be used."""


@dataclass(frozen=True)
class Rules:
    """Compiled classifiers, in the order they are consulted."""

    never: tuple[re.Pattern[str], ...]
    bash: tuple[re.Pattern[str], ...]
    zsh: tuple[re.Pattern[str], ...]

    def classify(self, line: str) -> str:
        """Return the shell a line belongs to, or ``SHARED``/``NEVER``."""
        text = line.strip()
        if not text:
            return SHARED
        # Comments are shared, unless they name a profile file: those are file headers.
        for pattern in self.never:
            if pattern.search(text):
                return NEVER
        if text.startswith("#"):
            return SHARED
        for pattern in self.bash:
            if pattern.search(text):
                return BASH
        for pattern in self.zsh:
            if pattern.search(text):
                return ZSH
        return SHARED

    def travels_to(self, line: str, shell: str) -> bool:
        """True when ``line`` may be mirrored into ``shell``'s profile."""
        return self.classify(line) in (SHARED, shell)


def _compile(patterns) -> tuple[re.Pattern[str], ...]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise RulesError(f"invalid pattern {pattern!r}: {exc}") from exc
    return tuple(compiled)


def load_rules(extra_file: Path | None = None) -> Rules:
    """Compile the built-in rules, extended by an optional JSON override file."""
    extra: dict[str, list[str]] = {}
    if extra_file is not None:
        try:
            extra = json.loads(extra_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RulesError(f"cannot read {extra_file}: {exc}") from exc
        if not isinstance(extra, dict):
            raise RulesError(f"{extra_file}: expected an object of pattern lists")
        unknown = set(extra) - {NEVER, BASH, ZSH}
        if unknown:
            raise RulesError(f"{extra_file}: unknown keys {sorted(unknown)}")
        for key, value in extra.items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise RulesError(f"{extra_file}: {key} must be a list of patterns")
    return Rules(
        never=_compile([*extra.get(NEVER, []), *NEVER_PATTERNS]),
        bash=_compile([*extra.get(BASH, []), *BASH_PATTERNS]),
        zsh=_compile([*extra.get(ZSH, []), *ZSH_PATTERNS]),
    )
