"""Remember what each profile looked like after the last successful pass."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from profiler.block import Profile
from profiler.config import SHELLS

VERSION = 1


class StateError(ValueError):
    """The stored state file cannot be interpreted."""


@dataclass
class TargetState:
    """The recorded shape of one home directory's two profiles."""

    shells: dict[str, Profile] = field(default_factory=dict)
    updated: str = ""

    def snapshot(self, shell: str) -> Profile | None:
        return self.shells.get(shell)


@dataclass
class State:
    """Recorded snapshots keyed by home directory."""

    targets: dict[str, TargetState] = field(default_factory=dict)

    def target(self, home: Path) -> TargetState | None:
        return self.targets.get(str(home))

    def record(self, home: Path, shells: dict[str, Profile]) -> None:
        self.targets[str(home)] = TargetState(
            shells=dict(shells),
            updated=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def forget(self, home: Path) -> None:
        self.targets.pop(str(home), None)


def _profile_from_json(payload: dict) -> Profile:
    if not isinstance(payload, dict):
        raise StateError("each shell entry must be an object")
    own = payload.get("own", [])
    managed = payload.get("managed", [])
    if not isinstance(own, list) or not isinstance(managed, list):
        raise StateError("'own' and 'managed' must be lists of lines")
    return Profile(
        before=[str(line) for line in own],
        managed=[str(line) for line in managed],
        has_block=bool(payload.get("has_block", bool(managed))),
        exists=bool(payload.get("exists", True)),
    )


def load(path: Path) -> State:
    """Read the state file, returning empty state when it does not exist yet."""
    if not path.exists():
        return State()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StateError(f"{path}: expected an object")
    version = payload.get("version")
    if version != VERSION:
        raise StateError(f"{path}: unsupported state version {version!r}")
    targets: dict[str, TargetState] = {}
    for home, entry in (payload.get("targets") or {}).items():
        if not isinstance(entry, dict):
            raise StateError(f"{path}: target {home} must be an object")
        shells = {
            shell: _profile_from_json(entry.get("shells", {})[shell])
            for shell in SHELLS
            if shell in (entry.get("shells") or {})
        }
        targets[home] = TargetState(shells=shells, updated=str(entry.get("updated", "")))
    return State(targets=targets)


def save(path: Path, state: State) -> None:
    """Write the state file atomically, readable only by its owner."""
    payload = {
        "version": VERSION,
        "targets": {
            home: {
                "updated": target.updated,
                "shells": {
                    shell: {
                        "exists": profile.exists,
                        "has_block": profile.has_block,
                        "own": profile.own,
                        "managed": profile.managed,
                    }
                    for shell, profile in target.shells.items()
                },
            }
            for home, target in sorted(state.targets.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, indent=2, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
