from conftest import make_settings

from profiler import cli


def test_sync_reports_what_it_moved(capsys, tmp_path, home):
    settings = make_settings(tmp_path, home)
    (home / ".bashrc").write_text("export EDITOR=nvim\n")
    (home / ".zshrc").write_text("setopt AUTO_CD\n")
    base = ["--state-dir", str(settings.state_dir), "--home", str(home)]
    assert cli.main([*base, "sync"]) == 0
    (home / ".bashrc").write_text("export EDITOR=nvim\nalias gs='git status'\n")

    assert cli.main([*base, "sync"]) == 0

    output = capsys.readouterr().out
    assert "+ alias gs='git status'" in output


def test_dry_run_leaves_the_files_alone(capsys, tmp_path, home):
    settings = make_settings(tmp_path, home)
    base = ["--state-dir", str(settings.state_dir), "--home", str(home)]
    (home / ".bashrc").write_text("export EDITOR=nvim\n")
    (home / ".zshrc").write_text("setopt AUTO_CD\n")
    cli.main([*base, "sync"])
    (home / ".bashrc").write_text("export EDITOR=nvim\nalias gs='git status'\n")

    assert cli.main([*base, "--dry-run", "sync"]) == 0

    assert "would add" in capsys.readouterr().out
    assert (home / ".zshrc").read_text() == "setopt AUTO_CD\n"


def test_status_describes_both_profiles(capsys, tmp_path, home):
    (home / ".bashrc").write_text("export EDITOR=nvim\n")
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]

    assert cli.main([*base, "status"]) == 0

    output = capsys.readouterr().out
    assert "1 own line(s)" in output
    assert ".zshrc: missing" in output


def test_doctor_reports_the_resolved_settings(capsys, tmp_path, home):
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]

    assert cli.main([*base, "doctor"]) == 0

    output = capsys.readouterr().out
    assert str(home) in output
    assert "syntax check" in output


def test_restore_lists_and_restores_a_backup(capsys, tmp_path, home):
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]
    (home / ".bashrc").write_text("export EDITOR=nvim\n")
    (home / ".zshrc").write_text("setopt AUTO_CD\n")
    cli.main([*base, "sync"])
    (home / ".bashrc").write_text("export EDITOR=nvim\nalias gs='git status'\n")
    cli.main([*base, "sync"])
    capsys.readouterr()

    assert cli.main([*base, "restore", "--list"]) == 0
    assert "-zsh" in capsys.readouterr().out

    assert cli.main([*base, "restore", "--shell", "zsh"]) == 0
    assert (home / ".zshrc").read_text() == "setopt AUTO_CD\n"


def test_an_unusable_configuration_exits_with_two(capsys, tmp_path, home, monkeypatch):
    monkeypatch.setenv("PROFILER_POLL_INTERVAL", "soon")

    assert cli.main(["--state-dir", str(tmp_path / "state"), "status"]) == 2

    assert "profiler:" in capsys.readouterr().err


def conflicted(home):
    (home / ".bashrc").write_text("alias ls='ls --color=auto'\n")
    (home / ".zshrc").write_text("alias ls='eza --icons'\n")


def test_a_conflict_is_asked_about_at_a_terminal(capsys, tmp_path, home, monkeypatch):
    conflicted(home)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]

    assert cli.main([*base, "adopt"]) == 0

    output = capsys.readouterr().out
    assert "define alias ls, differently" in output
    assert "1) .bashrc: alias ls='ls --color=auto'" in output
    assert "2) .zshrc: alias ls='eza --icons'" in output
    assert (home / ".bashrc").read_text().count("eza --icons") == 1


def test_a_conflict_is_only_reported_when_nobody_can_be_asked(capsys, tmp_path, home):
    conflicted(home)
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]

    assert cli.main([*base, "--on-conflict", "skip", "adopt"]) == 0

    output = capsys.readouterr().out
    assert "conflicting definitions, left as they are" in output
    assert "! alias ls" in output
    assert (home / ".zshrc").read_text() == "alias ls='eza --icons'\n"


def test_on_conflict_apart_settles_without_asking(capsys, tmp_path, home, monkeypatch):
    conflicted(home)

    def refuse(_prompt):
        raise AssertionError("nothing should be asked")

    monkeypatch.setattr("builtins.input", refuse)
    base = ["--state-dir", str(tmp_path / "state"), "--home", str(home)]

    assert cli.main([*base, "--on-conflict", "apart", "adopt"]) == 0

    assert (home / ".bashrc").read_text() == "alias ls='ls --color=auto'\n"
    assert (home / ".zshrc").read_text() == "alias ls='eza --icons'\n"
