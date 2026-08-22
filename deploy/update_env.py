#!/usr/bin/env python3
"""Read or atomically change an allowlisted systemd EnvironmentFile entry."""

import argparse
import os
import re
import tempfile
from pathlib import Path


def validate_key(key: str, pattern: str) -> None:
    if not re.fullmatch(pattern, key):
        raise ValueError(f"unsupported environment key: {key}")


def get_value(path: Path, key: str) -> str | None:
    prefix = f"{key}="
    for line in path.read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def set_value(path: Path, key: str, value: str, pattern: str) -> None:
    validate_key(key, pattern)
    if not value or any(char.isspace() for char in value):
        raise ValueError("environment values must be non-empty and contain no whitespace")
    prefix = f"{key}="
    replacement = f"{key}={value}"
    updated, replaced = [], False
    for line in path.read_text().splitlines():
        if line.startswith(prefix):
            if not replaced:
                updated.append(replacement)
                replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(replacement)
    file_stat = path.stat()
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write("\n".join(updated) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, file_stat.st_mode)
        os.chown(temporary, file_stat.st_uid, file_stat.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("get", "set"))
    parser.add_argument("path", type=Path)
    parser.add_argument("key")
    parser.add_argument("value", nargs="?")
    parser.add_argument("--key-pattern", required=True)
    args = parser.parse_args()
    try:
        validate_key(args.key, args.key_pattern)
        if args.action == "get":
            value = get_value(args.path, args.key)
            if value is None:
                raise SystemExit(1)
            print(value)
        else:
            if args.value is None:
                parser.error("set requires a value")
            set_value(args.path, args.key, args.value, args.key_pattern)
    except (OSError, re.error, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
