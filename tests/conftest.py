import importlib.util
from pathlib import Path

import pytest

from profiler.config import DEFAULT_RC_NAMES, Settings

ROOT = Path(__file__).parents[1]


def load_script(name):
    path = ROOT / "deploy" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_settings(tmp_path, *homes, **overrides):
    return Settings(
        homes=tuple(homes),
        state_dir=tmp_path / "state",
        rc_names=dict(DEFAULT_RC_NAMES),
        poll_interval=overrides.pop("poll_interval", 5.0),
        debounce=overrides.pop("debounce", 0.0),
        backup_keep=overrides.pop("backup_keep", 3),
        validate=overrides.pop("validate", True),
        create_missing=overrides.pop("create_missing", True),
        dry_run=overrides.pop("dry_run", False),
        log_level=overrides.pop("log_level", "INFO"),
        rules_file=overrides.pop("rules_file", None),
    )


@pytest.fixture
def home(tmp_path):
    directory = tmp_path / "home"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(tmp_path, home):
    return make_settings(tmp_path, home)
