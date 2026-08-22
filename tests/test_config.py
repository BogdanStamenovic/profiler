from pathlib import Path

import pytest

from profiler import config


def test_defaults_fall_back_to_the_current_home():
    settings = config.load_settings(environ={})

    assert settings.homes == (Path.home().resolve(),)
    assert settings.rc_names == {"bash": ".bashrc", "zsh": ".zshrc"}
    assert settings.validate is True


def test_environment_values_win():
    settings = config.load_settings(
        environ={
            "PROFILER_HOMES": "/home/one:/home/two",
            "PROFILER_STATE_DIR": "/tmp/profiler",
            "PROFILER_POLL_INTERVAL": "12",
            "PROFILER_VALIDATE": "no",
            "PROFILER_BACKUP_KEEP": "4",
        }
    )

    assert settings.homes == (Path("/home/one"), Path("/home/two"))
    assert settings.state_file == Path("/tmp/profiler/state.json")
    assert settings.poll_interval == 12
    assert settings.validate is False
    assert settings.backup_keep == 4


def test_an_env_file_only_fills_in_what_is_unset(tmp_path):
    path = tmp_path / "profiler.env"
    path.write_text("# comment\nPROFILER_HOMES=/home/from-file\nPROFILER_LOG_LEVEL='debug'\n")

    settings = config.load_settings(path, environ={"PROFILER_HOMES": "/home/from-env"})

    assert settings.homes == (Path("/home/from-env"),)
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize(
    "environ",
    [
        {"PROFILER_HOMES": "relative/path"},
        {"PROFILER_POLL_INTERVAL": "soon"},
        {"PROFILER_VALIDATE": "maybe"},
        {"PROFILER_DEBOUNCE": "-1"},
        {"PROFILER_BASHRC_NAME": "sub/dir/.bashrc"},
    ],
)
def test_unusable_values_are_rejected(environ):
    with pytest.raises(config.ConfigError):
        config.load_settings(environ=environ)


def test_a_malformed_env_file_line_is_rejected(tmp_path):
    path = tmp_path / "profiler.env"
    path.write_text("PROFILER_HOMES\n")

    with pytest.raises(config.ConfigError):
        config.read_env_file(path)


def test_the_shipped_env_example_parses():
    values = config.read_env_file(Path(__file__).parents[1] / "deploy" / "profiler.env.example")
    settings = config.load_settings(environ=values)

    assert settings.homes == (Path("/home/youruser"),)
