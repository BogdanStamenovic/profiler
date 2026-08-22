import json
import subprocess

import pytest
from conftest import ROOT, load_script

update_plan = load_script("update_plan")
POLICY = update_plan.load_policy(ROOT / "deploy" / "update_policy.json")


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def repository_with_commits(tmp_path, body):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "file").write_text("one")
    git(tmp_path, "add", "file")
    git(tmp_path, "commit", "-m", "base")
    old = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "file").write_text("two")
    git(tmp_path, "add", "file")
    git(tmp_path, "commit", "-m", "update", "-m", body)
    return old, git(tmp_path, "rev-parse", "HEAD")


def test_builds_canonical_allowlisted_plan(tmp_path):
    old, new = repository_with_commits(
        tmp_path,
        """!!!BEGIN UPDATE AUTO CHANGER!!!
SUMMARY: Add feature
AUTO: systemd
ADDENV: PROFILER_HOMES = $input
REPROCESS: profiles --mode=adopt
USER: Verify feature.
!!!END UPDATE AUTO CHANGER!!!""",
    )

    plan = update_plan.build_plan(tmp_path, old, new, POLICY)

    assert plan["automatic_modules"] == ["application", "systemd"]
    assert plan["add_env"] == ["PROFILER_HOMES=$input"]
    assert plan["reprocess"] == ["profiles --mode=adopt"]
    assert plan["user_actions"] == ["Verify feature."]


@pytest.mark.parametrize(
    "line",
    [
        "AUTO: arbitrary-shell",
        "ADDENV: PATH = /tmp",
        "ADDENV: PROFILER_HOMES = two homes",
        "REPROCESS: profiles --mode=adopt --execute=code",
        "SHELL: touch /tmp/pwned",
    ],
)
def test_rejects_non_allowlisted_instructions(tmp_path, line):
    old, new = repository_with_commits(
        tmp_path,
        f"!!!BEGIN UPDATE AUTO CHANGER!!!\n{line}\n!!!END UPDATE AUTO CHANGER!!!",
    )
    with pytest.raises(update_plan.UpdatePlanError):
        update_plan.build_plan(tmp_path, old, new, POLICY)


def test_policy_file_is_valid_json():
    policy = json.loads((ROOT / "deploy" / "update_policy.json").read_text())
    assert "application" in policy["automatic_modules"]
