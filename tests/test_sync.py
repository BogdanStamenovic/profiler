import shutil

import pytest
from conftest import make_settings

from profiler import block, state
from profiler.sync import (
    FAILED,
    KEEP_APART,
    UNDECIDED,
    WINNER,
    Synchronizer,
    paragraphs,
    slug,
    split_changes,
)

BASHRC = ".bashrc"
ZSHRC = ".zshrc"


def write(home, name, *lines):
    (home / name).write_text("".join(f"{line}\n" for line in lines))


def read(home, name):
    return (home / name).read_text()


def managed(home, name):
    return [line for line in block.parse(read(home, name)).managed if line.strip()]


def seed(settings, home, bash=(), zsh=()):
    """Create both profiles and record them, so the next pass sees real changes."""
    write(home, BASHRC, *bash)
    write(home, ZSHRC, *zsh)
    Synchronizer(settings).run("sync")


def test_split_changes_reports_additions_and_removals():
    added, removed = split_changes(["a", "b", "c"], ["a", "c", "d"])

    assert added == [["d"]]
    assert removed == ["b"]


def test_paragraphs_group_on_blank_lines():
    assert paragraphs(["a", "", "b", "c", ""]) == [["a"], ["b", "c"]]


def test_slug_flattens_a_home_path(tmp_path):
    assert slug(tmp_path / "home") == str(tmp_path / "home").strip("/").replace("/", "_")


def test_the_first_pass_only_records(settings, home):
    write(home, BASHRC, "export EDITOR=nvim")
    write(home, ZSHRC, "setopt AUTO_CD")

    report = Synchronizer(settings).run("sync")

    assert report.targets[0].seeded is True
    assert read(home, ZSHRC) == "setopt AUTO_CD\n"
    assert state.load(settings.state_file).target(home) is not None


def test_a_line_added_to_bashrc_reaches_zshrc(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")

    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == ["alias gs='git status'"]
    assert read(home, ZSHRC).startswith("setopt AUTO_CD")
    assert managed(home, BASHRC) == []


def test_a_line_added_to_zshrc_reaches_bashrc(settings, home):
    seed(settings, home, bash=["shopt -s histappend"], zsh=["setopt AUTO_CD"])
    write(home, ZSHRC, "setopt AUTO_CD", "export PAGER=less")

    Synchronizer(settings).run("sync")

    assert managed(home, BASHRC) == ["export PAGER=less"]


def test_shell_specific_lines_are_held_back(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, ZSHRC, "setopt AUTO_CD", "bindkey -v")

    report = Synchronizer(settings).run("sync")

    assert managed(home, BASHRC) == []
    held = [outcome.held_back for outcome in report.targets[0].files if outcome.shell == "bash"]
    assert held == [["bindkey -v"]]


def test_a_construct_with_a_shell_specific_line_travels_as_one_unit(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, ZSHRC, "setopt AUTO_CD", "reload() {", "  autoload -Uz compinit", "}")

    Synchronizer(settings).run("sync")

    assert managed(home, BASHRC) == []


def test_a_multi_line_function_arrives_intact(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "greet() {", "  echo hi", "", "  echo bye", "}")

    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == ["greet() {", "  echo hi", "  echo bye", "}"]
    assert "greet() {\n  echo hi\n\n  echo bye\n}" in read(home, ZSHRC)


def test_a_second_pass_changes_nothing(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    Synchronizer(settings).run("sync")
    before = read(home, BASHRC), read(home, ZSHRC)

    report = Synchronizer(settings).run("sync")

    assert report.changed is False
    assert (read(home, BASHRC), read(home, ZSHRC)) == before


def test_deleting_a_line_removes_the_mirrored_copy(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    Synchronizer(settings).run("sync")
    assert managed(home, ZSHRC) == ["alias gs='git status'"]

    write(home, BASHRC, "export EDITOR=nvim")
    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == []
    assert block.BEGIN not in read(home, ZSHRC)


def test_deleting_a_mirrored_line_removes_the_original_side_too(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    Synchronizer(settings).run("sync")
    kept = [line for line in read(home, ZSHRC).splitlines() if "alias gs=" not in line]
    (home / ZSHRC).write_text("".join(f"{line}\n" for line in kept))

    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == []
    assert "alias gs=" not in read(home, BASHRC)
    assert "export EDITOR=nvim" in read(home, BASHRC)


def test_deleting_the_whole_block_stops_mirroring_without_deleting_originals(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    Synchronizer(settings).run("sync")

    write(home, ZSHRC, "setopt AUTO_CD")
    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == []
    assert "alias gs='git status'" in read(home, BASHRC)


def test_a_line_the_other_profile_already_has_is_not_duplicated(settings, home):
    seed(settings, home, bash=["setopt_placeholder=1"], zsh=["export EDITOR=nvim"])
    write(home, BASHRC, "setopt_placeholder=1", "export EDITOR=nvim")

    Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == []
    assert read(home, ZSHRC).count("export EDITOR=nvim") == 1


def test_a_missing_profile_is_created(settings, home):
    write(home, BASHRC, "export EDITOR=nvim")
    Synchronizer(settings).run("sync")
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")

    Synchronizer(settings).run("sync")

    assert (home / ZSHRC).exists()
    assert managed(home, ZSHRC) == ["alias gs='git status'"]


def test_a_missing_profile_is_left_alone_when_creation_is_off(tmp_path, home):
    settings = make_settings(tmp_path, home, create_missing=False)
    write(home, BASHRC, "export EDITOR=nvim")
    Synchronizer(settings).run("sync")
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")

    Synchronizer(settings).run("sync")

    assert not (home / ZSHRC).exists()


def test_adopt_merges_what_both_profiles_already_hold(settings, home):
    write(home, BASHRC, "export EDITOR=nvim", "shopt -s histappend")
    write(home, ZSHRC, "setopt AUTO_CD", "export PAGER=less")

    Synchronizer(settings).run("adopt")

    assert managed(home, ZSHRC) == ["export EDITOR=nvim"]
    assert managed(home, BASHRC) == ["export PAGER=less"]


def test_cleanup_removes_the_blocks_and_the_state(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    Synchronizer(settings).run("sync")

    Synchronizer(settings).run("cleanup")

    assert read(home, ZSHRC) == "setopt AUTO_CD\n"
    assert state.load(settings.state_file).target(home) is None


def test_reseed_records_without_writing(settings, home):
    write(home, BASHRC, "export EDITOR=nvim")
    write(home, ZSHRC, "setopt AUTO_CD")

    report = Synchronizer(settings).run("reseed")

    assert report.changed is False
    assert state.load(settings.state_file).target(home).shells["bash"].own == ["export EDITOR=nvim"]


def test_dry_run_reports_without_touching_anything(tmp_path, home):
    live = make_settings(tmp_path, home)
    seed(live, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")
    planned = make_settings(tmp_path, home, dry_run=True)

    report = Synchronizer(planned).run("sync")

    assert report.changed is True
    assert block.BEGIN not in read(home, ZSHRC)


def test_a_result_that_would_not_parse_is_refused(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "if true; then")
    write(home, ZSHRC, "setopt AUTO_CD", "export PAGER=less")

    report = Synchronizer(settings).run("sync")

    outcome = next(item for item in report.targets[0].files if item.shell == "bash")
    assert outcome.action == FAILED
    assert "syntax error" in outcome.error
    assert block.BEGIN not in read(home, BASHRC)


def test_a_broken_managed_block_stops_the_target(settings, home):
    write(home, BASHRC, "export EDITOR=nvim", block.BEGIN, "alias gs='git status'")
    write(home, ZSHRC, "setopt AUTO_CD")

    report = Synchronizer(settings).run("sync")

    assert report.targets[0].error
    assert report.targets[0].failed is True


def test_writing_keeps_a_backup(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "alias gs='git status'")

    Synchronizer(settings).run("sync")

    copies = sorted((settings.backup_dir / slug(home)).glob("*-zsh"))
    assert copies and copies[-1].read_text() == "setopt AUTO_CD\n"


def test_backups_are_pruned_to_the_configured_count(tmp_path, home):
    settings = make_settings(tmp_path, home, backup_keep=2)
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    for index in range(4):
        write(home, BASHRC, "export EDITOR=nvim", *[f"alias a{n}=true" for n in range(index + 1)])
        Synchronizer(settings).run("sync")

    assert len(sorted((settings.backup_dir / slug(home)).glob("*-zsh"))) == 2


def test_a_home_that_is_not_a_directory_is_reported(tmp_path):
    settings = make_settings(tmp_path, tmp_path / "absent")

    report = Synchronizer(settings).run("sync")

    assert "not a directory" in report.targets[0].error


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")
def test_the_result_is_valid_zsh(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "greet() {", "  echo hi", "}")

    report = Synchronizer(settings).run("sync")

    assert report.failed is False
    assert managed(home, ZSHRC) == ["greet() {", "  echo hi", "}"]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["export EDITOR=nvim", "alias ll='ls -l'"], 2),
        (["greet() {", "  echo hi", "}"], 1),
        (["a=1", "greet() {", "  echo hi", "}", "b=2"], 3),
        (["if [ -d /opt ]; then", "  a=1", "fi"], 1),
        (["for i in a b c; do", "  echo $i", "done"], 1),
        (["if [ -d /opt ]; then a=1; fi", "b=2"], 2),
        (["case $x in", "  a) echo a;;", "esac"], 1),
        (["echo done", "echo fi"], 2),
        (["long=\\", "  continued", "next=1"], 2),
    ],
)
def test_segments_keep_constructs_whole(lines, expected):
    from profiler.sync import segments

    assert len(segments(lines)) == expected


def test_a_mixed_paragraph_of_statements_is_filtered_line_by_line(settings, home):
    seed(settings, home, bash=["placeholder=1"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "placeholder=1", "export EDITOR=nvim", "shopt -s histappend", "alias l=ls")

    report = Synchronizer(settings).run("sync")

    assert managed(home, ZSHRC) == ["export EDITOR=nvim", "alias l=ls"]
    outcome = next(item for item in report.targets[0].files if item.shell == "zsh")
    assert outcome.held_back == ["shopt -s histappend"]


def test_adopting_a_realistic_bashrc(settings, home):
    write(
        home,
        BASHRC,
        "# shell setup",
        "shopt -s histappend",
        "HISTCONTROL=ignoreboth",
        "export EDITOR=nvim",
        "alias ll='ls -alF'",
        "PS1='\\u@\\h:\\w\\$ '",
        "greet() {",
        "  echo hello",
        "}",
    )
    write(home, ZSHRC, "setopt AUTO_CD", "export PAGER=less")

    Synchronizer(settings).run("adopt")

    assert managed(home, ZSHRC) == [
        "# shell setup",
        "export EDITOR=nvim",
        "alias ll='ls -alF'",
        "greet() {",
        "  echo hello",
        "}",
    ]
    assert managed(home, BASHRC) == ["export PAGER=less"]


def test_dry_run_reports_a_refusal_instead_of_promising_a_write(settings, home):
    seed(settings, home, bash=["export EDITOR=nvim"], zsh=["setopt AUTO_CD"])
    write(home, BASHRC, "export EDITOR=nvim", "if true; then")
    write(home, ZSHRC, "setopt AUTO_CD", "export PAGER=less")
    planned = make_settings(settings.state_dir.parent, home, dry_run=True)

    report = Synchronizer(planned).run("sync")

    outcome = next(item for item in report.targets[0].files if item.shell == "bash")
    assert outcome.action == FAILED
    assert "syntax error" in outcome.error


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("alias ls='eza --icons'", "alias ls"),
        ("export EDITOR=nvim", "variable EDITOR"),
        ("EDITOR=nvim", "variable EDITOR"),
        ("greet() {", "function greet"),
        ("function greet() {", "function greet"),
        ('export PATH="$PATH:/opt/bin"', None),
        ('PATH="${PATH}:/opt/bin"', None),
        ("echo hello", None),
        ("# a comment", None),
    ],
)
def test_defines_names_what_a_line_declares(line, expected):
    from profiler.sync import defines

    assert defines(line) == expected


def test_a_conflicting_alias_is_not_mirrored_over_the_local_one(settings, home):
    write(home, BASHRC, "alias ls='ls --color=auto'")
    write(home, ZSHRC, "alias ls='eza --icons'")

    report = Synchronizer(settings).run("adopt")

    assert managed(home, BASHRC) == []
    assert managed(home, ZSHRC) == []
    assert "alias ls='ls --color=auto'" in read(home, BASHRC)
    assert "alias ls='eza --icons'" in read(home, ZSHRC)
    for outcome in report.targets[0].files:
        assert outcome.conflicts == ["alias ls"]


def test_an_identical_definition_on_both_sides_is_not_a_conflict(settings, home):
    write(home, BASHRC, "alias ls='ls --color=auto'", "export EDITOR=nvim")
    write(home, ZSHRC, "alias ls='ls --color=auto'")

    report = Synchronizer(settings).run("adopt")

    assert managed(home, ZSHRC) == ["export EDITOR=nvim"]
    assert not any(outcome.conflicts for outcome in report.targets[0].files)


def test_additive_path_lines_are_not_treated_as_conflicting(settings, home):
    write(home, BASHRC, 'export PATH="$PATH:/opt/a"')
    write(home, ZSHRC, 'export PATH="$PATH:/opt/b"')

    report = Synchronizer(settings).run("adopt")

    assert not any(outcome.conflicts for outcome in report.targets[0].files)
    assert managed(home, ZSHRC) == ['export PATH="$PATH:/opt/a"']


def conflicting(home):
    write(home, BASHRC, "alias ls='ls --color=auto'")
    write(home, ZSHRC, "alias ls='eza --icons'")


def test_a_resolver_is_asked_once_and_its_answer_is_remembered(settings, home):
    conflicting(home)
    asked = []

    def resolve(conflict):
        asked.append(conflict.name)
        return WINNER, conflict.versions["zsh"]

    Synchronizer(settings, resolver=resolve).run("adopt")

    assert asked == ["alias ls"]
    assert "alias ls='eza --icons'" in read(home, BASHRC)
    assert "alias ls='ls --color=auto'" not in read(home, BASHRC)

    write(home, BASHRC, read(home, BASHRC).rstrip("\n"), "alias gs='git status'")
    Synchronizer(settings, resolver=resolve).run("sync")

    assert asked == ["alias ls"], "a settled name must not be asked about again"


def test_keeping_them_apart_stops_the_question_for_good(settings, home):
    conflicting(home)
    asked = []

    def resolve(conflict):
        asked.append(conflict.name)
        return KEEP_APART, None

    Synchronizer(settings, resolver=resolve).run("adopt")

    assert "alias ls='ls --color=auto'" in read(home, BASHRC)
    assert "alias ls='eza --icons'" in read(home, ZSHRC)
    assert managed(home, BASHRC) == []

    Synchronizer(settings, resolver=resolve).run("sync")
    assert asked == ["alias ls"]


def test_skipping_leaves_the_conflict_pending(settings, home):
    conflicting(home)

    report = Synchronizer(settings, resolver=lambda c: (UNDECIDED, None)).run("adopt")

    assert [conflict.name for conflict in report.targets[0].pending] == ["alias ls"]
    assert managed(home, BASHRC) == []


def test_without_a_resolver_a_conflict_is_reported_not_guessed(settings, home):
    conflicting(home)

    report = Synchronizer(settings).run("adopt")

    pending = report.targets[0].pending
    assert [conflict.name for conflict in pending] == ["alias ls"]
    assert pending[0].versions == {
        "bash": "alias ls='ls --color=auto'",
        "zsh": "alias ls='eza --icons'",
    }
    assert managed(home, ZSHRC) == []


def test_a_decision_survives_a_reload_of_the_state(settings, home):
    conflicting(home)
    Synchronizer(settings, resolver=lambda c: (KEEP_APART, None)).run("adopt")

    stored = state.load(settings.state_file)

    assert stored.target(home).decisions == {"alias ls": {"mode": KEEP_APART, "line": None}}


def test_the_winning_definition_replaces_the_loser_and_backs_it_up(settings, home):
    conflicting(home)

    Synchronizer(settings, resolver=lambda c: (WINNER, c.versions["bash"])).run("adopt")

    assert "alias ls='eza --icons'" not in read(home, ZSHRC)
    assert "alias ls='ls --color=auto'" in read(home, ZSHRC)
    copies = sorted((settings.backup_dir / slug(home)).glob("*-zsh"))
    assert copies and "eza" in copies[-1].read_text()
