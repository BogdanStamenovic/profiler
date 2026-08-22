#!/usr/bin/env python3
"""Parse declarative update instructions from Git commit messages."""

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path

BEGIN = "!!!BEGIN UPDATE AUTO CHANGER!!!"
END = "!!!END UPDATE AUTO CHANGER!!!"


class UpdatePlanError(ValueError):
    pass


def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text())
    if not isinstance(policy.get("automatic_modules"), list):
        raise UpdatePlanError("policy automatic_modules must be a list")
    if not isinstance(policy.get("reprocess_modules"), dict):
        raise UpdatePlanError("policy reprocess_modules must be an object")
    pattern = policy.get("environment_key_pattern")
    if not isinstance(pattern, str):
        raise UpdatePlanError("policy environment_key_pattern must be a string")
    re.compile(pattern)
    return policy


def commit_messages(repository: Path, old_revision: str, new_revision: str):
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "log",
            "--reverse",
            "--format=%H%x1f%B%x1e",
            f"{old_revision}..{new_revision}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if record:
            commit, separator, message = record.partition("\x1f")
            if not separator:
                raise UpdatePlanError("could not parse git log output")
            yield commit, message


def canonical_reprocess(commit: str, value: str, policy: dict) -> str:
    tokens = shlex.split(value)
    definitions = policy["reprocess_modules"]
    if not tokens or tokens[0] not in definitions:
        raise UpdatePlanError(f"commit {commit[:12]} requests unknown REPROCESS module")
    groups = definitions[tokens[0]].get("flag_groups", [])
    supplied = tokens[1:]
    allowed = {flag for group in groups for flag in group}
    if len(supplied) != len(set(supplied)) or not set(supplied) <= allowed:
        raise UpdatePlanError(f"commit {commit[:12]} has invalid REPROCESS subflags")
    canonical = [tokens[0]]
    for group in groups:
        selected = [flag for flag in group if flag in supplied]
        if len(selected) != 1:
            raise UpdatePlanError(f"commit {commit[:12]} must choose exactly one flag from {group}")
        canonical.extend(selected)
    if len(supplied) != len(groups):
        raise UpdatePlanError(f"commit {commit[:12]} has extra REPROCESS subflags")
    return " ".join(canonical)


def build_plan(repository: Path, old_revision: str, new_revision: str, policy: dict) -> dict:
    modules = ["application"]
    result = {
        "from_revision": old_revision,
        "to_revision": new_revision,
        "automatic_modules": modules,
        "summaries": [],
        "user_actions": [],
        "reprocess": [],
        "add_env": [],
        "marked_commits": [],
    }
    allowed_modules = set(policy["automatic_modules"])
    env_pattern = re.compile(policy["environment_key_pattern"])
    if "application" not in allowed_modules:
        raise UpdatePlanError("policy must whitelist the application module")

    for commit, message in commit_messages(repository, old_revision, new_revision):
        if message.count(BEGIN) != message.count(END):
            raise UpdatePlanError(f"commit {commit[:12]} has an incomplete update block")
        remainder = message
        found = False
        while BEGIN in remainder:
            _, remainder = remainder.split(BEGIN, 1)
            block, separator, remainder = remainder.partition(END)
            if not separator:
                raise UpdatePlanError(f"commit {commit[:12]} has an incomplete update block")
            found = True
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.partition(":")
                value = value.strip()
                if not separator or not value:
                    raise UpdatePlanError(f"commit {commit[:12]} has invalid line: {line}")
                if key == "AUTO":
                    if value not in allowed_modules:
                        raise UpdatePlanError(
                            f"commit {commit[:12]} requests unknown AUTO module: {value}"
                        )
                    if value not in modules:
                        modules.append(value)
                elif key == "SUMMARY":
                    result["summaries"].append(value)
                elif key == "USER":
                    result["user_actions"].append(value)
                elif key == "REPROCESS":
                    job = canonical_reprocess(commit, value, policy)
                    if job not in result["reprocess"]:
                        result["reprocess"].append(job)
                elif key == "ADDENV":
                    env_key, equals, env_value = value.partition("=")
                    env_key, env_value = env_key.strip(), env_value.strip()
                    if not equals or not env_pattern.fullmatch(env_key):
                        raise UpdatePlanError(f"commit {commit[:12]} has invalid ADDENV key")
                    if not env_value or any(char.isspace() for char in env_value):
                        raise UpdatePlanError(f"commit {commit[:12]} has invalid ADDENV value")
                    declaration = f"{env_key}={env_value}"
                    result["add_env"] = [
                        item for item in result["add_env"] if not item.startswith(f"{env_key}=")
                    ]
                    result["add_env"].append(declaration)
                else:
                    raise UpdatePlanError(f"commit {commit[:12]} has unknown key: {key}")
        if found:
            result["marked_commits"].append(commit)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("old_revision")
    parser.add_argument("new_revision")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--field",
        choices=("automatic_modules", "summaries", "user_actions", "reprocess", "add_env"),
    )
    args = parser.parse_args()
    try:
        plan = build_plan(
            args.repository, args.old_revision, args.new_revision, load_policy(args.policy)
        )
    except (
        OSError,
        json.JSONDecodeError,
        re.error,
        subprocess.CalledProcessError,
        UpdatePlanError,
    ) as exc:
        parser.error(str(exc))
    if args.field:
        print(*plan[args.field], sep="\n")
    else:
        print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
