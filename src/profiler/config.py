"""Resolved runtime settings, read from the process environment or an env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

SHELLS = ("bash", "zsh")
OTHER = {"bash": "zsh", "zsh": "bash"}
DEFAULT_RC_NAMES = {"bash": ".bashrc", "zsh": ".zshrc"}
SYSTEM_STATE_DIR = Path("/var/lib/profiler")
TRUE_WORDS = {"1", "true", "yes", "on"}
FALSE_WORDS = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """The environment does not describe a usable configuration."""


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a systemd-style ``KEY=value`` file into a plain mapping."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ConfigError(f"{path}:{number}: expected KEY=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _flag(values: dict[str, str], key: str, default: bool) -> bool:
    raw = values.get(key)
    if raw is None or not raw.strip():
        return default
    word = raw.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ConfigError(f"{key} must be a boolean, not {raw!r}")


def _number(values: dict[str, str], key: str, default: float, cast) -> float:
    raw = values.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        number = cast(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} must be numeric, not {raw!r}") from exc
    if number < 0:
        raise ConfigError(f"{key} must not be negative")
    return number


def default_state_dir() -> Path:
    if os.geteuid() == 0:
        return SYSTEM_STATE_DIR
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "profiler"


def _homes(values: dict[str, str]) -> tuple[Path, ...]:
    raw = values.get("PROFILER_HOMES", "").strip()
    if not raw:
        return (Path.home().resolve(),)
    homes = []
    for item in raw.replace(",", ":").split(":"):
        entry = item.strip()
        if not entry:
            continue
        path = Path(entry).expanduser()
        if not path.is_absolute():
            raise ConfigError(f"PROFILER_HOMES entries must be absolute: {entry}")
        if path not in homes:
            homes.append(path)
    if not homes:
        raise ConfigError("PROFILER_HOMES is set but lists no directory")
    return tuple(homes)


@dataclass(frozen=True)
class Settings:
    """Everything the synchronizer needs to know about its surroundings."""

    homes: tuple[Path, ...]
    state_dir: Path
    rc_names: dict[str, str]
    poll_interval: float
    debounce: float
    backup_keep: int
    validate: bool
    create_missing: bool
    dry_run: bool
    log_level: str
    rules_file: Path | None

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"

    def rc_path(self, home: Path, shell: str) -> Path:
        return home / self.rc_names[shell]

    def with_overrides(self, **changes) -> Settings:
        return replace(self, **{key: value for key, value in changes.items() if value is not None})


def load_settings(env_file: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Build settings from ``environ``, letting ``env_file`` fill in what is unset."""
    values = dict(os.environ if environ is None else environ)
    if env_file is not None:
        for key, value in read_env_file(env_file).items():
            values.setdefault(key, value)
    state_dir = values.get("PROFILER_STATE_DIR", "").strip()
    rules_file = values.get("PROFILER_RULES_FILE", "").strip()
    rc_names = {
        shell: values.get(f"PROFILER_{shell.upper()}RC_NAME", "").strip() or default
        for shell, default in DEFAULT_RC_NAMES.items()
    }
    for shell, name in rc_names.items():
        if "/" in name:
            raise ConfigError(f"the {shell} profile name must be a bare file name, not {name!r}")
    return Settings(
        homes=_homes(values),
        state_dir=Path(state_dir) if state_dir else default_state_dir(),
        rc_names=rc_names,
        poll_interval=_number(values, "PROFILER_POLL_INTERVAL", 5.0, float),
        debounce=_number(values, "PROFILER_DEBOUNCE", 0.75, float),
        backup_keep=int(_number(values, "PROFILER_BACKUP_KEEP", 20, int)),
        validate=_flag(values, "PROFILER_VALIDATE", True),
        create_missing=_flag(values, "PROFILER_CREATE_MISSING", True),
        dry_run=_flag(values, "PROFILER_DRY_RUN", False),
        log_level=values.get("PROFILER_LOG_LEVEL", "").strip().upper() or "INFO",
        rules_file=Path(rules_file) if rules_file else None,
    )
