import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import struct
import threading
import time
import wave

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from musicdesk.models import Track
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.style import STYLE
from musicdesk.window import MainWindow
from musicdesk.youtube import AudioStream, SourceError


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    return application


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError("Condition did not become true")


@pytest.fixture
def audio_url(tmp_path):
    path = tmp_path / "test.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(300 * math.sin(2 * math.pi * 440 * n / 8000))) for n in range(8000 * 4)))
    return QUrl.fromLocalFile(str(path)).toString()


class TestSource:
    __test__ = False

    def __init__(self, url):
        self.url = url

    def search(self, query, limit=40, order="relevance"):
        return [Track("ewCPQeAtICk", "Втюрилась", "Дора", 4),
                Track("lCKU-tI-upI", "worry (ultra slowed)", "LONOWN", 4)]

    def resolve(self, track):
        return AudioStream(self.url)


def test_search_library_and_native_audio(app, tmp_path, audio_url):
    library = Library(tmp_path / "library.sqlite3")
    window = MainWindow(library, TestSource(audio_url))
    window.playback.output.setMuted(True)
    window.show()
    try:
        window.search_query("test fixture")
        wait_for(lambda: window.track_list.count() == 2)
        track = window.search_results[1]
        window.toggle_like(track)
        window.show_view("likes")
        assert window.track_list.count() == 1
        window.playback.play(track)
        wait_for(lambda: window.playback.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        wait_for(lambda: bool(library.history()))
        assert library.history() == [track]
        assert window.queue_list.count() == 1
        window.playback.toggle()
        wait_for(lambda: window.playback.player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        window.grab().save(str(tmp_path / "desktop.png"))
    finally:
        window.close()
        window.pool.waitForDone(2000)
        window.playback.pool.waitForDone(2000)
        library.close()
    restored = Library(tmp_path / "library.sqlite3")
    assert restored.liked_tracks() == [track]
    assert restored.load_queue().current == track
    restored.close()


def test_late_stream_does_not_replace_new_track(app, tmp_path, audio_url):
    release = threading.Event()
    started = threading.Event()
    class DelayedSource(TestSource):
        def resolve(self, track):
            if track.video_id == "ewCPQeAtICk":
                started.set()
                release.wait(5)
            return AudioStream(self.url)
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, DelayedSource(audio_url))
    player.output.setMuted(True)
    first = Track("ewCPQeAtICk", "First")
    second = Track("lCKU-tI-upI", "Second")
    try:
        player.play(first)
        wait_for(started.is_set)
        player.play(second)
        wait_for(lambda: player.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        release.set()
        wait_for(lambda: not player._tasks)
        assert player.current == second
        assert library.history() == [second]
    finally:
        release.set()
        player.shutdown()
        player.pool.waitForDone(2000)
        library.close()


def test_failed_resolution_does_not_create_history(app, tmp_path, audio_url):
    class BrokenSource(TestSource):
        def resolve(self, track):
            raise SourceError("Expected fixture failure")
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, BrokenSource(audio_url))
    errors = []
    player.error.connect(errors.append)
    try:
        player.play(Track("ewCPQeAtICk", "Unavailable"))
        wait_for(lambda: bool(errors))
        assert not library.history()
    finally:
        player.shutdown()
        player.pool.waitForDone(2000)
        library.close()


def test_prefetch_is_bounded_keeps_latest_hover_and_never_autoplays(app, tmp_path, audio_url):
    release = threading.Event()
    calls = []
    lock = threading.Lock()
    class BusySource(TestSource):
        def resolve(self, track):
            with lock:
                calls.append(track.video_id)
            release.wait(3)
            return AudioStream(self.url)
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, BusySource(audio_url))
    tracks = [Track(f"{i:011d}", f"Track {i}") for i in range(1, 5)]
    try:
        player.prefetch(tracks[0])
        player.prefetch(tracks[0])
        player.prefetch(tracks[1])
        player.prefetch(tracks[2])
        player.prefetch(tracks[3])
        wait_for(lambda: len(calls) == 2)
        assert len(player._prefetch_tasks) == 2
        release.set()
        wait_for(lambda: not player._prefetch_tasks)
        assert set(calls) == {tracks[i].video_id for i in (0, 1, 3)}
        assert len(calls) == 3
        assert not library.history()
        assert player.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    finally:
        release.set()
        player.shutdown()
        player.prefetch_pool.waitForDone(2000)
        library.close()


def test_restored_queue_is_prepared_without_autoplay(app, tmp_path, audio_url):
    from musicdesk.models import PlayQueue
    library = Library(tmp_path / "library.sqlite3")
    tracks = [Track(f"{i:011d}", f"Track {i}") for i in (1, 2)]
    library.save_queue(PlayQueue(tracks, 0))
    player = Playback(library, TestSource(audio_url))
    try:
        wait_for(lambda: all(player.streams.peek(track.video_id) for track in tracks))
        assert not library.history()
        assert player.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    finally:
        player.shutdown()
        player.prefetch_pool.waitForDone(2000)
        library.close()
