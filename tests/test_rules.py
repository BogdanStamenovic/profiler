import json

import pytest

from profiler import rules


@pytest.fixture(scope="module")
def default_rules():
    return rules.load_rules()


@pytest.mark.parametrize(
    "line",
    [
        "export EDITOR=nvim",
        "alias ll='ls -alF'",
        "# a plain comment",
        'PATH="$HOME/.local/bin:$PATH"',
        "greet() {",
    ],
)
def test_shared_lines_travel_both_ways(default_rules, line):
    assert default_rules.classify(line) == rules.SHARED
    assert default_rules.travels_to(line, "bash")
    assert default_rules.travels_to(line, "zsh")


@pytest.mark.parametrize(
    "line",
    ["shopt -s histappend", "complete -F _foo foo", "HISTCONTROL=ignoreboth", "bind 'set -o vi'"],
)
def test_bash_only_lines_never_reach_zsh(default_rules, line):
    assert default_rules.classify(line) == rules.BASH
    assert default_rules.travels_to(line, "bash")
    assert not default_rules.travels_to(line, "zsh")


@pytest.mark.parametrize(
    "line",
    [
        "setopt AUTO_CD",
        "bindkey -v",
        "zstyle ':completion:*' menu select",
        "autoload -Uz compinit",
        "plugins=(git docker)",
        "source $ZSH/oh-my-zsh.sh",
        "typeset -U path",
    ],
)
def test_zsh_only_lines_never_reach_bash(default_rules, line):
    assert default_rules.classify(line) == rules.ZSH
    assert default_rules.travels_to(line, "zsh")
    assert not default_rules.travels_to(line, "bash")


@pytest.mark.parametrize(
    "line",
    [
        "PS1='\\u@\\h \\w\\$ '",
        "PROMPT='%n@%m %~%# '",
        "export PROMPT_COMMAND=__update",
        "source ~/.bashrc",
        "[ -f ~/.zshrc ] && . ~/.zshrc",
    ],
)
def test_prompt_and_self_reference_lines_stay_put(default_rules, line):
    assert default_rules.classify(line) == rules.NEVER
    assert not default_rules.travels_to(line, "bash")
    assert not default_rules.travels_to(line, "zsh")


def test_extra_rules_file_extends_the_built_ins(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"never": [r"^export SECRET_"]}))

    extended = rules.load_rules(path)

    assert extended.classify("export SECRET_TOKEN=abc") == rules.NEVER
    assert extended.classify("export EDITOR=nvim") == rules.SHARED


@pytest.mark.parametrize(
    "payload", ["[]", json.dumps({"unknown": []}), json.dumps({"bash": "not-a-list"})]
)
def test_bad_rules_files_are_rejected(tmp_path, payload):
    path = tmp_path / "rules.json"
    path.write_text(payload)

    with pytest.raises(rules.RulesError):
        rules.load_rules(path)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('eval "$(starship init bash)"', rules.BASH),
        ('eval "$(zoxide init zsh)"', rules.ZSH),
        ('eval "$(direnv hook bash)"', rules.BASH),
        ("source <(kubectl completion zsh)", rules.ZSH),
        ('eval "$(starship init fish)"', rules.SHARED),
    ],
)
def test_shell_hooks_are_recognised_by_their_argument(default_rules, line, expected):
    assert default_rules.classify(line) == expected


def test_a_header_comment_naming_a_profile_stays_put(default_rules):
    assert default_rules.classify("# ~/.bashrc") == rules.NEVER
    assert default_rules.classify("# my aliases") == rules.SHARED
