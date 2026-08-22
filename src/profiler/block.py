"""Read and write the managed region that profiler owns inside a shell profile."""

from __future__ import annotations

from dataclasses import dataclass, field

BEGIN = "# >>> profiler managed block >>>"
END = "# <<< profiler managed block <<<"
BANNER = (
    "# Mirrored by profiler from the other shell profile. Edit or delete these",
    "# lines in either file; both sides are kept in step. Nothing else is touched.",
)


class BlockError(ValueError):
    """The file's managed markers are missing a partner or appear twice."""


@dataclass
class Profile:
    """A shell profile split into the parts profiler owns and the parts it does not."""

    before: list[str] = field(default_factory=list)
    managed: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    has_block: bool = False
    exists: bool = True

    @property
    def own(self) -> list[str]:
        """Every line the user wrote outside the managed block."""
        return [*self.before, *self.after]


def parse(text: str) -> Profile:
    """Split profile text around the managed markers."""
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [index for index, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return Profile(before=lines)
    if len(starts) != 1 or len(ends) != 1:
        raise BlockError("expected exactly one managed block")
    start, end = starts[0], ends[0]
    if end < start:
        raise BlockError("managed block ends before it begins")
    managed = lines[start + 1 : end]
    while managed and managed[0].strip() in {banner.strip() for banner in BANNER}:
        managed.pop(0)
    return Profile(
        before=lines[:start],
        managed=managed,
        after=lines[end + 1 :],
        has_block=True,
    )


def render(profile: Profile) -> str:
    """Rebuild profile text, emitting the managed block only when it has content."""
    head = list(profile.before)
    while head and not head[-1].strip():
        head.pop()
    tail = list(profile.after)
    while tail and not tail[0].strip():
        tail.pop(0)
    while tail and not tail[-1].strip():
        tail.pop()

    body = _trim(profile.managed)
    lines = list(head)
    if body:
        if lines:
            lines.append("")
        lines.extend([BEGIN, *BANNER, *body, END])
    if tail:
        if lines:
            lines.append("")
        lines.extend(tail)
    return "\n".join(lines) + "\n" if lines else ""


def _trim(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def strip_block(text: str) -> str:
    """Return the profile with the managed block removed entirely."""
    profile = parse(text)
    profile.managed = []
    profile.has_block = False
    return render(profile)
