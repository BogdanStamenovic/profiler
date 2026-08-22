"""The manifest, the unit file and the deployment layout must agree with each other.

Nothing here exercises the shell scripts; it only checks the paths they share, which is
exactly what drifts when one of the four files is edited on its own.
"""

import re
from pathlib import Path

import pytest
import yaml
from conftest import ROOT

from profiler.config import read_env_file

DEPLOY = ROOT / "deploy"
SCRIPT = re.compile(r"deploy/[\w.-]+\.sh")


@pytest.fixture(scope="module")
def manifest():
    return yaml.safe_load((ROOT / "ownbox.yaml").read_text())


@pytest.fixture(scope="module")
def project():
    return read_env_file(DEPLOY / "project.conf")


@pytest.fixture(scope="module")
def unit():
    return (DEPLOY / "profiler.service").read_text()


def commands(manifest, phase):
    value = manifest["install"][phase]
    return value["linux"] if isinstance(value, dict) else value


@pytest.mark.parametrize("phase", ["setup", "update", "remove"])
def test_every_script_the_manifest_runs_exists(manifest, phase):
    entries = commands(manifest, phase)
    assert entries, f"{phase} runs nothing"
    for entry in entries:
        for name in SCRIPT.findall(entry):
            assert (ROOT / name).is_file(), f"{phase} runs a missing script: {name}"


def test_the_manifest_launches_the_deployed_binary(manifest, project):
    command = manifest["command"]["linux"]

    assert f"{project['VENV_DIR']}/bin/profiler" in command
    assert project["ENVIRONMENT_FILE"] in command


def test_the_manifest_only_claims_platforms_the_deployment_supports(manifest):
    assert manifest["install"]["platforms"] == ["linux"]


def test_the_unit_runs_out_of_the_deployment(unit, project):
    assert f"ExecStart={project['VENV_DIR']}/bin/profiler watch" in unit
    assert f"EnvironmentFile={project['ENVIRONMENT_FILE']}" in unit
    assert f"WorkingDirectory={project['INSTALL_DIR']}" in unit
    assert f"ReadWritePaths={project['DATA_DIR']} {project['BACKUP_ROOT']}" in unit


def test_the_unit_may_write_the_directories_it_needs(unit, project):
    line = next(row for row in unit.splitlines() if row.startswith("ReadWritePaths="))
    writable = line.split("=", 1)[1].split()

    assert project["DATA_DIR"] in writable
    assert project["BACKUP_ROOT"] in writable
    assert "ProtectHome=false" in unit, "the service edits files inside home directories"


def test_the_service_name_matches_where_the_unit_is_installed(project):
    assert Path(project["SERVICE_DESTINATION"]).name == project["SERVICE_NAME"]
    assert project["SERVICE_SOURCE"] == "deploy/profiler.service"


def test_the_tracked_conf_and_its_example_describe_the_same_keys(project):
    example = read_env_file(DEPLOY / "project.conf.example")

    assert set(project) == set(example)


def test_every_seeded_environment_key_is_allowed_by_policy():
    import json

    pattern = json.loads((DEPLOY / "update_policy.json").read_text())["environment_key_pattern"]
    for key in read_env_file(DEPLOY / "profiler.env.example"):
        assert re.fullmatch(pattern, key), f"{key} could never be set by an update"


def test_the_seeded_state_directory_is_the_deployment_data_directory(project):
    seeded = read_env_file(DEPLOY / "profiler.env.example")

    assert seeded["PROFILER_STATE_DIR"] == project["DATA_DIR"]
