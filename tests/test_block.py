import pytest

from profiler import block


def test_parses_a_file_without_a_block():
    profile = block.parse("alias ll='ls -l'\nexport EDITOR=nvim\n")

    assert profile.has_block is False
    assert profile.managed == []
    assert profile.own == ["alias ll='ls -l'", "export EDITOR=nvim"]


def test_parses_and_drops_the_banner():
    text = "\n".join(
        ["setopt AUTO_CD", "", block.BEGIN, *block.BANNER, "export EDITOR=nvim", block.END, ""]
    )

    profile = block.parse(text)

    assert profile.has_block is True
    assert profile.managed == ["export EDITOR=nvim"]
    assert profile.before == ["setopt AUTO_CD", ""]
    assert profile.after == []


def test_render_round_trips_without_growing():
    profile = block.parse("setopt AUTO_CD\n")
    profile.managed = ["export EDITOR=nvim"]

    once = block.render(profile)
    twice = block.render(block.parse(once))

    assert once == twice
    assert block.BEGIN in once and block.END in once


def test_render_omits_an_empty_block():
    profile = block.parse("alias ll='ls -l'\n")

    assert block.render(profile) == "alias ll='ls -l'\n"


def test_render_keeps_content_written_after_the_block():
    text = f"a=1\n{block.BEGIN}\nb=2\n{block.END}\nc=3\n"

    rendered = block.render(block.parse(text))

    assert rendered.splitlines()[-1] == "c=3"
    assert "b=2" in rendered


def test_strip_block_removes_only_the_managed_region():
    text = f"a=1\n{block.BEGIN}\nb=2\n{block.END}\nc=3\n"

    assert block.strip_block(text) == "a=1\n\nc=3\n"


@pytest.mark.parametrize(
    "text",
    [
        f"{block.BEGIN}\na=1\n",
        f"a=1\n{block.END}\n",
        f"{block.BEGIN}\na=1\n{block.END}\n{block.BEGIN}\nb=2\n{block.END}\n",
        f"{block.END}\na=1\n{block.BEGIN}\n",
    ],
)
def test_rejects_broken_markers(text):
    with pytest.raises(block.BlockError):
        block.parse(text)
