"""Watch the configured home directories and resynchronize when a profile changes."""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import logging
import os
import select
import signal
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from profiler.config import SHELLS, Settings
from profiler.sync import Synchronizer

LOG = logging.getLogger("profiler.watch")

IN_MODIFY = 0x00000002
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_Q_OVERFLOW = 0x00004000
IN_NONBLOCK = 0o4000
WATCH_MASK = IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE
EVENT_HEADER = struct.Struct("iIII")


class InotifyUnavailable(RuntimeError):
    """The kernel interface could not be opened, so the watcher falls back to polling."""


@dataclass
class Event:
    """One filesystem notification, reduced to the directory and file name."""

    directory: Path
    name: str


class Inotify:
    """A very small ctypes binding for the handful of inotify calls we need."""

    def __init__(self) -> None:
        library = ctypes.util.find_library("c")
        self._libc = ctypes.CDLL(library or "libc.so.6", use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        descriptor = self._libc.inotify_init1(IN_NONBLOCK)
        if descriptor < 0:
            code = ctypes.get_errno()
            raise InotifyUnavailable(f"inotify_init1 failed: {os.strerror(code)}")
        self.fileno = descriptor
        self._watches: dict[int, Path] = {}

    def watch(self, directory: Path) -> None:
        handle = self._libc.inotify_add_watch(self.fileno, str(directory).encode(), WATCH_MASK)
        if handle < 0:
            code = ctypes.get_errno()
            LOG.warning("cannot watch %s: %s", directory, os.strerror(code))
            return
        self._watches[handle] = directory

    def read(self) -> list[Event]:
        """Drain every queued event. Never blocks."""
        events: list[Event] = []
        while True:
            try:
                buffer = os.read(self.fileno, 8192)
            except BlockingIOError:
                return events
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise
            offset = 0
            while offset + EVENT_HEADER.size <= len(buffer):
                handle, mask, _cookie, length = EVENT_HEADER.unpack_from(buffer, offset)
                offset += EVENT_HEADER.size
                raw = buffer[offset : offset + length]
                offset += length
                if mask & IN_Q_OVERFLOW:
                    LOG.warning("the inotify queue overflowed; forcing a full pass")
                    events.append(Event(Path("/"), ""))
                    continue
                directory = self._watches.get(handle)
                if directory is None:
                    continue
                events.append(Event(directory, raw.split(b"\0", 1)[0].decode(errors="replace")))

    def close(self) -> None:
        try:
            os.close(self.fileno)
        except OSError:
            pass


class Watcher:
    """Runs one synchronizer whenever a watched profile settles down."""

    def __init__(self, settings: Settings, synchronizer: Synchronizer | None = None) -> None:
        self.settings = settings
        self.synchronizer = synchronizer or Synchronizer(settings)
        self.names = {settings.rc_names[shell] for shell in SHELLS}
        self._stop = False
        self._forced = False

    def request_stop(self, *_signal_arguments) -> None:
        self._stop = True

    def request_pass(self, *_signal_arguments) -> None:
        self._forced = True

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGHUP, self.request_pass)

    def run(self, iterations: int | None = None) -> int:
        """Watch until stopped. ``iterations`` bounds the loop for tests."""
        notifier: Inotify | None = None
        try:
            notifier = Inotify()
            for home in self.settings.homes:
                notifier.watch(home)
            LOG.info("watching %s", ", ".join(str(home) for home in self.settings.homes))
        except InotifyUnavailable as exc:
            LOG.warning("%s; falling back to polling every %.1fs", exc, self.settings.poll_interval)

        self._pass("startup")
        pending_since: float | None = None
        next_poll = time.monotonic() + self.settings.poll_interval
        rounds = 0
        try:
            while not self._stop and (iterations is None or rounds < iterations):
                rounds += 1
                timeout = self._timeout(pending_since, next_poll)
                if notifier is not None:
                    ready, _, _ = select.select([notifier.fileno], [], [], timeout)
                    if ready and self._interesting(notifier.read()):
                        pending_since = time.monotonic()
                else:
                    time.sleep(max(timeout, 0.0))
                now = time.monotonic()
                if self._forced:
                    self._forced = False
                    pending_since = None
                    self._pass("SIGHUP")
                    next_poll = now + self.settings.poll_interval
                elif pending_since is not None and now - pending_since >= self.settings.debounce:
                    pending_since = None
                    self._pass("change")
                    next_poll = now + self.settings.poll_interval
                elif now >= next_poll:
                    self._pass("poll")
                    next_poll = now + self.settings.poll_interval
        finally:
            if notifier is not None:
                notifier.close()
        LOG.info("stopped")
        return 0

    def _timeout(self, pending_since: float | None, next_poll: float) -> float:
        now = time.monotonic()
        deadlines = [next_poll - now]
        if pending_since is not None:
            deadlines.append(pending_since + self.settings.debounce - now)
        return max(min(deadlines), 0.0)

    def _interesting(self, events: list[Event]) -> bool:
        return any(event.name in self.names or event.name == "" for event in events)

    def _pass(self, reason: str) -> None:
        try:
            report = self.synchronizer.run("sync")
        except Exception:  # a watcher must survive one bad pass
            LOG.exception("synchronization pass (%s) failed", reason)
            return
        if report.changed:
            LOG.debug("pass (%s) changed at least one profile", reason)
