import pytest
from conftest import make_settings

from profiler import watcher
from profiler.sync import Synchronizer


def test_only_the_configured_profile_names_are_interesting(tmp_path, home):
    observer = watcher.Watcher(make_settings(tmp_path, home))

    assert observer._interesting([watcher.Event(home, ".bashrc")]) is True
    assert observer._interesting([watcher.Event(home, ".zshrc")]) is True
    assert observer._interesting([watcher.Event(home, ".viminfo")]) is False
    assert observer._interesting([watcher.Event(home, "")]) is True


def test_one_round_synchronizes_and_then_stops(tmp_path, home):
    settings = make_settings(tmp_path, home, poll_interval=0.01, debounce=0.0)
    (home / ".bashrc").write_text("export EDITOR=nvim\n")
    (home / ".zshrc").write_text("setopt AUTO_CD\n")
    Synchronizer(settings).run("sync")
    (home / ".bashrc").write_text("export EDITOR=nvim\nalias gs='git status'\n")

    observer = watcher.Watcher(settings)
    assert observer.run(iterations=2) == 0

    assert "alias gs='git status'" in (home / ".zshrc").read_text()


def test_a_failing_pass_does_not_stop_the_loop(tmp_path, home):
    settings = make_settings(tmp_path, home, poll_interval=0.01)
    observer = watcher.Watcher(settings)

    class Exploding:
        def run(self, mode):
            raise RuntimeError("boom")

    observer.synchronizer = Exploding()

    assert observer.run(iterations=1) == 0


def test_a_stop_request_ends_the_loop(tmp_path, home):
    settings = make_settings(tmp_path, home, poll_interval=0.01)
    observer = watcher.Watcher(settings)
    observer.request_stop()

    assert observer.run() == 0


@pytest.mark.skipif(not hasattr(watcher, "Inotify"), reason="no inotify binding")
def test_inotify_opens_and_closes(tmp_path):
    try:
        notifier = watcher.Inotify()
    except watcher.InotifyUnavailable:
        pytest.skip("inotify is unavailable in this environment")
    notifier.watch(tmp_path)
    assert notifier.read() == []
    notifier.close()
