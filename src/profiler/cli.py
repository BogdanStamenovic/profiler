"""Command line entry point.

The subcommand names deliberately avoid ``update``, ``rollback``, ``uninstall``,
``remove``, ``info`` and ``where``, which Ownbox reserves for its own launcher.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from profiler import __version__, block, state
from profiler.config import SHELLS, ConfigError, Settings, load_settings
from profiler.rules import RulesError
from profiler.sync import (
    FAILED,
    KEEP_APART,
    SEEDED,
    UNCHANGED,
    UNDECIDED,
    WINNER,
    Conflict,
    Synchronizer,
    slug,
)
from profiler.watcher import Inotify, InotifyUnavailable

LOG = logging.getLogger("profiler")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profiler",
        description="Keep the shared parts of ~/.bashrc and ~/.zshrc identical.",
    )
    parser.add_argument("--version", action="version", version=f"profiler {__version__}")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="read PROFILER_* settings from this file before the environment defaults",
    )
    parser.add_argument(
        "--home",
        type=Path,
        action="append",
        dest="homes",
        help="operate on this home directory instead of the configured ones (repeatable)",
    )
    parser.add_argument("--state-dir", type=Path, help="override the state and backup directory")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change without writing"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="skip the 'bash -n' / 'zsh -n' check on the rewritten profile",
    )
    parser.add_argument(
        "--on-conflict",
        choices=("ask", "skip", "apart"),
        default="ask",
        help="when both profiles define the same name differently: ask (default, needs a "
        "terminal), skip and report it, or keep each file's own version for good",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log at debug level")
    parser.add_argument("-q", "--quiet", action="store_true", help="log warnings and errors only")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="propagate everything written since the last pass")
    commands.add_parser("adopt", help="one-time merge of the content both profiles already hold")
    commands.add_parser("reseed", help="record the current profiles without changing them")
    commands.add_parser("watch", help="stay resident and synchronize on every change")
    commands.add_parser("status", help="show what profiler currently manages")
    commands.add_parser("doctor", help="check the environment and report the resolved settings")
    commands.add_parser("cleanup", help="remove every managed block and forget the stored state")

    restore = commands.add_parser("restore", help="put a backed-up profile back in place")
    restore.add_argument("--list", action="store_true", help="list the available backups")
    restore.add_argument("--shell", choices=SHELLS, help="which profile to restore")
    restore.add_argument("--backup", help="a specific backup name instead of the newest one")
    return parser


def configure_logging(arguments: argparse.Namespace, settings: Settings) -> None:
    level = settings.log_level
    if arguments.verbose:
        level = "DEBUG"
    elif arguments.quiet:
        level = "WARNING"
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def resolve(arguments: argparse.Namespace) -> Settings:
    settings = load_settings(arguments.env_file)
    if arguments.homes:
        settings = settings.with_overrides(
            homes=tuple(dict.fromkeys(home.expanduser().resolve() for home in arguments.homes))
        )
    if arguments.state_dir:
        settings = settings.with_overrides(state_dir=arguments.state_dir.expanduser())
    if arguments.dry_run:
        settings = settings.with_overrides(dry_run=True)
    if arguments.no_validate:
        settings = settings.with_overrides(validate=False)
    return settings


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        settings = resolve(arguments)
    except ConfigError as exc:
        print(f"profiler: {exc}", file=sys.stderr)
        return 2
    configure_logging(arguments, settings)
    try:
        if arguments.command == "status":
            return command_status(settings)
        if arguments.command == "doctor":
            return command_doctor(settings)
        if arguments.command == "restore":
            return command_restore(settings, arguments)
        if arguments.command == "watch":
            return command_watch(settings)
        return command_pass(settings, arguments.command, arguments.on_conflict)
    except (ConfigError, RulesError, state.StateError) as exc:
        print(f"profiler: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def prompt_for_conflict(settings: Settings) -> object:
    """Ask which version of a contested name both profiles should carry."""

    def ask(conflict: Conflict) -> tuple[str, str | None]:
        shells = sorted(conflict.versions)
        print(f"\nBoth profiles in {conflict.home} define {conflict.name}, differently:")
        for index, shell in enumerate(shells, start=1):
            print(f"  {index}) {settings.rc_names[shell]}: {conflict.versions[shell].strip()}")
        print("  k) keep each file's own version, and stop asking about this name")
        print("  s) skip for now, and ask again next pass")
        while True:
            try:
                answer = input(f"Use which in both? [1-{len(shells)}/k/s] ").strip().lower()
            except EOFError:
                print()
                return UNDECIDED, None
            if answer.isdigit() and 1 <= int(answer) <= len(shells):
                return WINNER, conflict.versions[shells[int(answer) - 1]]
            if answer == "k":
                return KEEP_APART, None
            if answer in ("s", ""):
                return UNDECIDED, None
            print(f"Please answer 1-{len(shells)}, k or s.")

    return ask


def make_resolver(settings: Settings, choice: str) -> object:
    """A dry run cannot apply an answer, and a non-terminal has nobody to ask."""
    if choice == "apart":
        return lambda conflict: (KEEP_APART, None)
    if choice == "skip" or settings.dry_run or not sys.stdin.isatty():
        return None
    return prompt_for_conflict(settings)


def report_pending(settings: Settings, target) -> None:
    print("  conflicting definitions, left as they are:")
    for conflict in target.pending:
        print(f"    ! {conflict.name}")
        for shell, line in sorted(conflict.versions.items()):
            print(f"        {settings.rc_names[shell]}: {line.strip()}")
    print("    decide with 'profiler sync' in a terminal, or keep them separate for good")
    print("    with '--on-conflict apart'.")


def command_pass(settings: Settings, mode: str, on_conflict: str = "skip") -> int:
    report = Synchronizer(settings, resolver=make_resolver(settings, on_conflict)).run(mode)
    prefix = "would " if settings.dry_run else ""
    for target in report.targets:
        print(f"{target.home}")
        if target.error:
            print(f"  error: {target.error}")
            continue
        if target.seeded:
            print("  recorded the current profiles; nothing propagated")
        for outcome in target.files:
            name = outcome.path.name
            if outcome.action == FAILED:
                print(f"  {name}: failed - {outcome.error}")
                continue
            if (
                outcome.action in (UNCHANGED, SEEDED)
                and not outcome.held_back
                and not outcome.conflicts
            ):
                print(f"  {name}: no change")
                continue
            print(f"  {name}: {prefix}add {len(outcome.added)}, remove {len(outcome.removed)}")
            for line in outcome.added:
                print(f"    + {line.strip()}")
            for line in outcome.removed:
                print(f"    - {line.strip()}")
            for line in outcome.held_back:
                print(f"    ~ held back (shell specific): {line.strip()}")
            for clash in outcome.conflicts:
                print(f"    ! held back (conflict): {clash}")
            if outcome.backup:
                print(f"    backup: {outcome.backup}")
        if target.pending:
            report_pending(settings, target)
    return 1 if report.failed else 0


def command_watch(settings: Settings) -> int:
    from profiler.watcher import Watcher

    watcher = Watcher(settings)
    watcher.install_signal_handlers()
    return watcher.run()


def command_status(settings: Settings) -> int:
    stored = state.load(settings.state_file)
    print(f"state file: {settings.state_file}")
    for home in settings.homes:
        target = stored.target(home)
        seen = target.updated if target and target.updated else "never"
        print(f"{home}  (last pass: {seen})")
        for shell in SHELLS:
            path = settings.rc_path(home, shell)
            if not path.exists():
                print(f"  {path.name}: missing")
                continue
            try:
                profile = block.parse(path.read_text())
            except (OSError, block.BlockError) as exc:
                print(f"  {path.name}: unreadable - {exc}")
                continue
            managed = len([line for line in profile.managed if line.strip()])
            own = len([line for line in profile.own if line.strip()])
            marker = "managed block present" if profile.has_block else "no managed block"
            print(f"  {path.name}: {own} own line(s), {managed} mirrored line(s), {marker}")
    return 0


def command_doctor(settings: Settings) -> int:
    print(f"profiler {__version__}")
    print(f"homes           {', '.join(str(home) for home in settings.homes)}")
    print(f"state file      {settings.state_file}")
    print(f"backups         {settings.backup_dir} (keep {settings.backup_keep})")
    print(f"poll interval   {settings.poll_interval}s")
    print(f"debounce        {settings.debounce}s")
    print(f"create missing  {'yes' if settings.create_missing else 'no'}")
    print(f"dry run         {'yes' if settings.dry_run else 'no'}")
    print(f"extra rules     {settings.rules_file or 'built-in only'}")
    for shell in SHELLS:
        binary = shutil.which(shell)
        print(f"{shell + ' binary':<15} {binary or 'not installed (syntax check skipped)'}")
    print(f"syntax check    {'on' if settings.validate else 'off'}")
    try:
        notifier = Inotify()
        notifier.close()
        print("inotify         available")
    except InotifyUnavailable as exc:
        print(f"inotify         unavailable ({exc}); the watcher will poll")
    problems = 0
    for home in settings.homes:
        if not home.is_dir():
            print(f"problem         {home} is not a directory")
            problems += 1
    try:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.state_dir / ".profiler-write-test"
        probe.write_text("")
        probe.unlink()
    except OSError as exc:
        print(f"problem         cannot write to {settings.state_dir}: {exc}")
        problems += 1
    if shutil.which("systemctl"):
        result = subprocess.run(
            ["systemctl", "is-active", "profiler.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"service         profiler.service is {result.stdout.strip() or 'unknown'}")
    return 1 if problems else 0


def command_restore(settings: Settings, arguments: argparse.Namespace) -> int:
    for home in settings.homes:
        directory = settings.backup_dir / slug(home)
        copies = sorted(directory.glob("*")) if directory.is_dir() else []
        if arguments.list or not arguments.shell:
            print(f"{home}")
            if not copies:
                print("  no backups")
            for copy in copies:
                print(f"  {copy.name}")
            continue
        candidates = [copy for copy in copies if copy.name.endswith(f"-{arguments.shell}")]
        if arguments.backup:
            candidates = [copy for copy in candidates if copy.name == arguments.backup]
        if not candidates:
            print(f"profiler: no matching backup for {home}", file=sys.stderr)
            return 1
        source = candidates[-1]
        destination = settings.rc_path(home, arguments.shell)
        if settings.dry_run:
            print(f"would restore {source} to {destination}")
            continue
        shutil.copy2(source, destination)
        print(f"restored {destination} from {source.name}")
    if arguments.shell and not settings.dry_run:
        print("run 'profiler reseed' so the next pass starts from the restored content")
    return 0
