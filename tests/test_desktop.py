import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import struct
import threading
import time
import wave
from pathlib import Path

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
        assert window.queue_list.count() == 0
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
    assert not restored.load_queue().tracks
    assert restored.load_current() == track
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


def test_direct_play_does_not_enqueue_and_preserves_explicit_queue(app, tmp_path, audio_url, monkeypatch):
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, TestSource(audio_url))
    monkeypatch.setattr(player, "_open_current", lambda: None)
    a, b, c = [Track(f"{i:011d}", str(i)) for i in range(3)]
    try:
        player.add(b)
        player.play(a)
        player.play(c)
        assert player.queue.tracks == [b]
        assert player.queue.index == -1
        assert player.current == c
        player.next()
        assert player.current == b
        player.remove(0)
        assert player.current == b
        assert not player.queue.tracks
        assert library.load_current() == b
    finally:
        player.shutdown()
        library.close()


def test_repeat_one_reuses_source_manual_next_advances_and_modes_persist(app, tmp_path, audio_url, monkeypatch):
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, TestSource(audio_url))
    opened, positions, starts = [], [], []
    monkeypatch.setattr(player, "_open_current", lambda: opened.append(player.current))
    monkeypatch.setattr(player.player, "setPosition", positions.append)
    monkeypatch.setattr(player.player, "play", lambda: starts.append(True))
    a, b = Track("aaaaaaaaaaa", "A"), Track("bbbbbbbbbbb", "B")
    try:
        player.play_all([a, b])
        player.cycle_repeat()
        assert player.repeat_mode == "one"
        assert library.get_setting("repeat_mode", "") == "one"
        player._expected_url = audio_url
        player._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert player.current == a
        player._want_play = True
        player._media_status(QMediaPlayer.MediaStatus.LoadedMedia)
        assert positions == [0] and starts == [True]
        assert opened == [a]
        player.next()
        assert player.current == b
        player.cycle_repeat()
        assert player.repeat_mode == "all"
        player.next()
        assert player.current == a
        player.cycle_repeat()
        assert player.repeat_mode == "off"
        player.play(b)
        player._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert player.current == b
    finally:
        player.shutdown()
        library.close()


def test_native_seek_waits_for_new_audio_then_restores_volume(app, tmp_path, audio_url):
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, TestSource(audio_url))
    player.output.setMuted(True)
    try:
        player.play(Track("aaaaaaaaaaa", "Native seek"))
        wait_for(lambda: player.player.position() > 300)
        player.seek(1800)
        assert player.output.volume() == 0
        wait_for(lambda: player.seek_guard.target is None)
        assert player.seek_guard.fresh
        assert abs(player.output.volume() - .65) < .001
        assert player.output.isMuted()
        assert player.player.position() >= 1800
        assert len(library.history()) == 1
    finally:
        player.shutdown()
        player.pool.waitForDone(2000)
        library.close()


def test_switching_next_previous_and_repeated_seeks_hold_silence_until_new_audio(app, tmp_path, audio_url, monkeypatch):
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, TestSource(audio_url))
    player.output.setMuted(True)
    a, b = Track("aaaaaaaaaaa", "First"), Track("bbbbbbbbbbb", "Second")
    source_events = []
    original_set_source = player.player.setSource
    def set_source(url):
        source_events.append((url.isEmpty(), player.output.volume()))
        original_set_source(url)
    monkeypatch.setattr(player.player, "setSource", set_source)
    try:
        player.play_all([a, b])
        wait_for(lambda: player.seek_guard.target is None)
        player.next()
        assert player.output.volume() == 0
        wait_for(lambda: player.seek_guard.target is None)
        assert player.current == b
        player.previous()
        assert player.output.volume() == 0
        wait_for(lambda: player.seek_guard.target is None)
        assert player.current == a
        player.seek(2100)
        player.seek(800)
        wait_for(lambda: player.seek_guard.target is None)
        assert player.player.position() >= 800
        assert all(volume == 0 for _, volume in source_events)
        assert player.output.isMuted()
        assert library.db.execute("SELECT COUNT(*) FROM plays").fetchone()[0] == 3
        player.seek(1200)
        player.set_volume(27)
    finally:
        player.shutdown()
        player.pool.waitForDone(2000)
    assert abs(float(library.get_setting("volume", "0")) - .27) < .001
    library.close()


def test_paused_seek_stays_silent_and_resumes_at_requested_position(app, tmp_path, audio_url):
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, TestSource(audio_url))
    player.output.setMuted(True)
    try:
        player.play(Track("aaaaaaaaaaa", "Paused seek"))
        wait_for(lambda: player.player.position() > 300 and player.seek_guard.target is None)
        player.toggle()
        player.seek(2200)
        wait_for(lambda: player._pending_seek is None)
        QTest.qWait(300)
        assert not player._want_play
        assert player.output.volume() == 0
        player.toggle()
        wait_for(lambda: player.seek_guard.target is None)
        assert player.player.position() >= 2200
        assert player.output.isMuted()
    finally:
        player.shutdown()
        player.pool.waitForDone(2000)
        library.close()


def test_native_seek_reopens_relay_without_redownloading_audio(app, tmp_path, audio_url):
    import re
    from musicdesk.relay import MediaRelay
    body = Path(QUrl(audio_url).toLocalFile()).read_bytes()
    calls = []
    class Response:
        def __init__(self, headers):
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", headers.get("Range", ""))
            self.start = int(match[1]) if match else 0
            self.end = min(len(body) - 1, int(match[2]) if match and match[2] else len(body) - 1)
            self.status_code = 206 if match else 200
            self.headers = {"Content-Type": "audio/wav", "Content-Length": str(self.end - self.start + 1)}
            if match:
                self.headers["Content-Range"] = f"bytes {self.start}-{self.end}/{len(body)}"
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield body[self.start:self.end + 1]
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append(kwargs["headers"].get("Range"))
            return Response(kwargs["headers"])
        head = get
    class RemoteSource(TestSource):
        def resolve(self, track): return AudioStream("https://fixture.googlevideo.com/audio")
    library = Library(tmp_path / "library.sqlite3")
    player = Playback(library, RemoteSource(audio_url))
    player.relay.close()
    player.relay = MediaRelay(Session)
    player.output.setMuted(True)
    try:
        player.play(Track("aaaaaaaaaaa", "Buffered relay seek"))
        wait_for(lambda: player.seek_guard.target is None)
        count = len(calls)
        assert count > 0
        player.seek(1800)
        wait_for(lambda: player.seek_guard.target is None)
        assert player.player.position() >= 1800
        assert len(calls) == count
    finally:
        player.shutdown()
        player.pool.waitForDone(2000)
        library.close()
