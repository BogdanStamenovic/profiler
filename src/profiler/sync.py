"""Mirror shared profile content between ``.bashrc`` and ``.zshrc``."""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from profiler import block, state
from profiler.block import BlockError, Profile
from profiler.config import OTHER, SHELLS, Settings
from profiler.rules import Rules, load_rules

LOG = logging.getLogger("profiler.sync")
MODES = ("sync", "adopt", "reseed", "cleanup")
SYNTAX_CHECK = {"bash": ("bash", "-n"), "zsh": ("zsh", "-n")}

UNCHANGED = "unchanged"
WRITTEN = "written"
SEEDED = "seeded"
FAILED = "failed"
PLANNED = "planned"


@dataclass
class FileOutcome:
    """What happened to one profile during one pass."""

    shell: str
    path: Path
    action: str = UNCHANGED
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    held_back: list[str] = field(default_factory=list)
    backup: Path | None = None
    error: str = ""

    @property
    def changed(self) -> bool:
        return self.action in (WRITTEN, PLANNED)


@dataclass
class TargetReport:
    """What happened to one home directory during one pass."""

    home: Path
    mode: str
    files: list[FileOutcome] = field(default_factory=list)
    seeded: bool = False
    error: str = ""

    @property
    def changed(self) -> bool:
        return any(outcome.changed for outcome in self.files)

    @property
    def failed(self) -> bool:
        return bool(self.error) or any(outcome.action == FAILED for outcome in self.files)


@dataclass
class SyncReport:
    """The result of one pass over every configured home directory."""

    mode: str
    targets: list[TargetReport] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(target.changed for target in self.targets)

    @property
    def failed(self) -> bool:
        return any(target.failed for target in self.targets)


def split_changes(old: list[str], new: list[str]) -> tuple[list[list[str]], list[str]]:
    """Return the paragraphs added to ``new`` and the individual lines dropped from ``old``."""
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    added: list[list[str]] = []
    removed: list[str] = []
    for tag, start_old, end_old, start_new, end_new in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(paragraphs(new[start_new:end_new]))
        if tag in ("delete", "replace"):
            removed.extend(line for line in old[start_old:end_old] if line.strip())
    return added, removed


def paragraphs(lines: list[str]) -> list[list[str]]:
    """Split a run of lines into blank-line separated groups, dropping empty ones."""
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


# Shell words that open and close a multi-line construct when they start a clause.
OPENING_WORDS = {"if", "for", "while", "until", "case", "select"}
CLOSING_WORDS = {"fi", "done", "esac"}
CLAUSES = re.compile(r"[;&|]+")


def balanced(text: str) -> bool:
    """True when the text closes every quote it opens and does not end in a continuation."""
    quote = ""
    escaped = False
    for character in text:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif quote:
            if character == quote:
                quote = ""
        elif character in "'\"":
            quote = character
    return not quote and not escaped


def depth_change(line: str) -> int:
    """How much deeper into a construct a line leaves the reader."""
    text = line.strip()
    if not text or text.startswith("#"):
        return 0
    depth = text.count("{") - text.count("}")
    for clause in CLAUSES.split(text):
        words = clause.split()
        if not words:
            continue
        if words[0] in OPENING_WORDS:
            depth += 1
        elif words[0] in CLOSING_WORDS:
            depth -= 1
    return depth


def segments(lines: list[str]) -> list[list[str]]:
    """Split lines into units: one per standalone statement, one per whole construct.

    Keeping a construct together is what stops a function from crossing over in halves, while
    splitting the statements around it is what lets a shell-specific line be left behind on its
    own rather than dragging its neighbours with it.
    """
    units: list[list[str]] = []
    current: list[str] = []
    depth = 0
    for line in lines:
        current.append(line)
        depth += depth_change(line)
        if depth <= 0 and balanced("\n".join(current)):
            units.append(current)
            current = []
            depth = 0
    if current:
        units.append(current)
    return units


class Synchronizer:
    """Applies one synchronization mode across the configured home directories."""

    def __init__(self, settings: Settings, rules: Rules | None = None) -> None:
        self.settings = settings
        self.rules = rules if rules is not None else load_rules(settings.rules_file)
        self._reported_errors: dict[tuple[str, str], str] = {}

    def run(self, mode: str = "sync") -> SyncReport:
        """Run ``mode`` over every configured home and persist the resulting snapshots."""
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
        stored = state.load(self.settings.state_file)
        report = SyncReport(mode=mode)
        for home in self.settings.homes:
            report.targets.append(self._run_target(home, mode, stored))
        if not self.settings.dry_run:
            state.save(self.settings.state_file, stored)
        return report

    # -- one home directory ------------------------------------------------

    def _run_target(self, home: Path, mode: str, stored: state.State) -> TargetReport:
        report = TargetReport(home=home, mode=mode)
        if not home.is_dir():
            report.error = f"{home} is not a directory"
            LOG.warning("skipping %s: %s", home, report.error)
            return report
        try:
            current = {shell: self._read(home, shell) for shell in SHELLS}
        except BlockError as exc:
            report.error = str(exc)
            self._log_once(home, "*", f"{home}: {exc}")
            return report

        if mode == "cleanup":
            for shell in SHELLS:
                report.files.append(self._cleanup(home, shell, current[shell]))
            if not self.settings.dry_run:
                stored.forget(home)
            return report

        if mode == "reseed":
            report.seeded = True
            for shell in SHELLS:
                report.files.append(FileOutcome(shell, self.settings.rc_path(home, shell), SEEDED))
            if not self.settings.dry_run:
                stored.record(home, current)
            return report

        previous = self._baseline(home, mode, stored, current)
        if previous is None:
            report.seeded = True
            for shell in SHELLS:
                report.files.append(FileOutcome(shell, self.settings.rc_path(home, shell), SEEDED))
            if not self.settings.dry_run:
                stored.record(home, current)
            LOG.info("recorded a first snapshot for %s; run 'profiler adopt' to merge", home)
            return report

        authored: dict[str, list[list[str]]] = {}
        dropped: dict[str, list[str]] = {}
        recalled: dict[str, list[str]] = {}
        for shell in SHELLS:
            own_added, own_removed = split_changes(previous[shell].own, current[shell].own)
            block_added, block_removed = self._block_changes(previous[shell], current[shell])
            authored[shell] = own_added + block_added
            # A line struck from a managed block is struck at its source too, since the block
            # holds nothing but copies. A line struck from the author's own region is only
            # withdrawn from the copies.
            dropped[shell] = own_removed + block_removed
            recalled[shell] = block_removed

        written: dict[str, Profile] = {}
        for shell in SHELLS:
            outcome, profile = self._apply(
                home,
                shell,
                current[shell],
                authored[OTHER[shell]],
                dropped[OTHER[shell]],
                recalled[OTHER[shell]],
            )
            report.files.append(outcome)
            written[shell] = profile if outcome.action != FAILED else previous[shell]

        if not self.settings.dry_run and not report.failed:
            stored.record(home, written)
        return report

    @staticmethod
    def _block_changes(previous: Profile, current: Profile) -> tuple[list[list[str]], list[str]]:
        """Compare managed blocks, reading a deleted block as opting out rather than deleting."""
        if previous.has_block and not current.has_block and not current.managed:
            return [], []
        return split_changes(previous.managed, current.managed)

    def _baseline(
        self, home: Path, mode: str, stored: state.State, current: dict[str, Profile]
    ) -> dict[str, Profile] | None:
        """The snapshot each shell is compared against, or ``None`` to seed and stop."""
        if mode == "adopt":
            return {
                shell: Profile(managed=list(current[shell].managed), exists=current[shell].exists)
                for shell in SHELLS
            }
        target = stored.target(home)
        if target is None or set(target.shells) != set(SHELLS):
            return None
        return {shell: target.shells[shell] for shell in SHELLS}

    # -- one profile -------------------------------------------------------

    def _apply(
        self,
        home: Path,
        shell: str,
        current: Profile,
        incoming: list[list[str]],
        removals: list[str],
        recalls: list[str],
    ) -> tuple[FileOutcome, Profile]:
        path = self.settings.rc_path(home, shell)
        outcome = FileOutcome(shell=shell, path=path)
        managed = list(current.managed)
        before, after = list(current.before), list(current.after)

        drop = {line for line in removals if line.strip()}
        if drop:
            outcome.removed = [line for line in managed if line in drop]
            managed = [line for line in managed if line not in drop]
        recall = {line for line in recalls if line.strip()}
        if recall:
            outcome.removed += [line for line in [*before, *after] if line in recall]
            before = [line for line in before if line not in recall]
            after = [line for line in after if line not in recall]

        present = {line for line in [*managed, *before, *after] if line.strip()}
        for group in incoming:
            for part in self._admissible(group, shell, outcome):
                body = [line for line in part if line.strip()]
                if not body or all(line in present for line in body):
                    continue
                if managed and len(part) > 1:
                    managed.append("")
                managed.extend(part)
                present.update(body)
                outcome.added.extend(body)

        if not outcome.added and not outcome.removed:
            outcome.action = UNCHANGED
            return outcome, current
        if not current.exists and not self.settings.create_missing:
            outcome.action = UNCHANGED
            outcome.held_back.extend(outcome.added)
            outcome.added.clear()
            LOG.debug("%s does not exist and PROFILER_CREATE_MISSING is off", path)
            return outcome, current

        updated = Profile(
            before=before,
            managed=managed,
            after=after,
            has_block=bool(managed),
            exists=True,
        )
        text = block.render(updated)
        self._commit(home, shell, path, text, outcome)
        return outcome, block.parse(text) if outcome.action != FAILED else current

    def _admissible(self, group: list[str], shell: str, outcome: FileOutcome) -> list[list[str]]:
        """Split a paragraph into the parts that may travel, recording what stayed behind."""
        body = [line for line in group if line.strip()]
        if not body:
            return []
        blocked = [line for line in body if not self.rules.travels_to(line, shell)]
        if not blocked:
            return [group]
        allowed: list[list[str]] = []
        for unit in segments(body):
            refused = [line for line in unit if not self.rules.travels_to(line, shell)]
            if refused:
                outcome.held_back.append(refused[0])
                continue
            allowed.append(unit)
        return allowed

    def _cleanup(self, home: Path, shell: str, current: Profile) -> FileOutcome:
        path = self.settings.rc_path(home, shell)
        outcome = FileOutcome(shell=shell, path=path)
        if not current.exists or not current.has_block:
            return outcome
        outcome.removed = [line for line in current.managed if line.strip()]
        cleaned = Profile(before=list(current.before), after=list(current.after), exists=True)
        self._commit(home, shell, path, block.render(cleaned), outcome)
        return outcome

    def _commit(self, home: Path, shell: str, path: Path, text: str, outcome: FileOutcome) -> None:
        if self.settings.dry_run:
            outcome.action = PLANNED
            return
        error = self._check_syntax(shell, path, text)
        if error:
            outcome.action = FAILED
            outcome.error = error
            self._log_once(home, shell, f"refusing to write {path}: {error}")
            return
        try:
            if path.exists():
                outcome.backup = self._backup(home, shell, path)
            self._write(home, path, text)
        except OSError as exc:
            outcome.action = FAILED
            outcome.error = str(exc)
            self._log_once(home, shell, f"cannot write {path}: {exc}")
            return
        outcome.action = WRITTEN
        self._reported_errors.pop((str(home), shell), None)
        LOG.info(
            "%s: +%d line(s), -%d line(s)%s",
            path,
            len(outcome.added),
            len(outcome.removed),
            f", {len(outcome.held_back)} held back" if outcome.held_back else "",
        )

    # -- filesystem --------------------------------------------------------

    def _read(self, home: Path, shell: str) -> Profile:
        path = self.settings.rc_path(home, shell)
        try:
            text = path.read_text()
        except FileNotFoundError:
            return Profile(exists=False)
        except OSError as exc:
            raise BlockError(f"cannot read {path}: {exc}") from exc
        try:
            profile = block.parse(text)
        except BlockError as exc:
            raise BlockError(f"{path}: {exc}") from exc
        profile.exists = True
        return profile

    def _check_syntax(self, shell: str, path: Path, text: str) -> str:
        """Ask the shell itself whether the new text parses. Empty string means fine."""
        if not self.settings.validate:
            return ""
        program, flag = SYNTAX_CHECK[shell]
        binary = shutil.which(program)
        if binary is None:
            LOG.debug("%s is not installed; skipping the syntax check for %s", program, path)
            return ""
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / path.name
            probe.write_text(text)
            try:
                result = subprocess.run(
                    [binary, flag, str(probe)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f"{program} could not check the result: {exc}"
        if result.returncode == 0:
            return ""
        detail = (result.stderr or result.stdout).strip().replace(str(probe), str(path))
        return (
            f"{program} reports a syntax error: {detail.splitlines()[0] if detail else 'unknown'}"
        )

    def _write(self, home: Path, path: Path, text: str) -> None:
        if path.exists():
            info = path.stat()
            mode, uid, gid = info.st_mode & 0o777, info.st_uid, info.st_gid
        else:
            info = home.stat()
            mode, uid, gid = 0o644, info.st_uid, info.st_gid
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if os.geteuid() == 0:
                os.chown(temporary, uid, gid)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _backup(self, home: Path, shell: str, path: Path) -> Path:
        directory = self.settings.backup_dir / slug(home)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        copy = directory / f"{stamp}-{shell}"
        shutil.copy2(path, copy)
        self._prune(directory, shell)
        return copy

    def _prune(self, directory: Path, shell: str) -> None:
        keep = self.settings.backup_keep
        if keep <= 0:
            return
        copies = sorted(directory.glob(f"*-{shell}"))
        for stale in copies[:-keep]:
            stale.unlink(missing_ok=True)

    def _log_once(self, home: Path, shell: str, message: str) -> None:
        key = (str(home), shell)
        if self._reported_errors.get(key) == message:
            LOG.debug("%s (unchanged since the last report)", message)
            return
        self._reported_errors[key] = message
        LOG.error("%s", message)


def slug(home: Path) -> str:
    """A flat, filesystem-safe name for a home directory."""
    return str(home).strip("/").replace("/", "_") or "root"
