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
