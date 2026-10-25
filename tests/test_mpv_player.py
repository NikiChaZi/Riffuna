import os
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from musicdesk.mpv_player import library_path, device_name
from musicdesk.models import Track
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.youtube import AudioStream


def wait(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError("Native playback condition timed out")


def test_device_guid_matches_wasapi_endpoint():
    class Device:
        def id(self):
            return b"{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"
        def description(self):
            return "Buds3 FE"
    endpoint = "wasapi/{11111111-2222-3333-4444-555555555555}"
    assert device_name(Device(), [{"name": endpoint}]) == endpoint


@pytest.mark.skipif(not library_path().is_file(), reason="Optional native runtime not installed")
@pytest.mark.parametrize("over_relay", [False, True])
def test_native_seek_pause_skip_and_output(tmp_path, monkeypatch, over_relay):
    monkeypatch.setenv("RIFFUNA_AUDIO_BACKEND", "mpv")
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as f:
        f.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        f.writeframes(b"\x00" * 48000 * 4 * 8)
    # Optional real AAC probe stays local and is never committed as test data.
    path = Path(os.environ.get("RIFFUNA_TEST_AUDIO", str(path)))
    class Source:
        def resolve(self, track):
            return AudioStream("https://example.googlevideo.com/audio" if over_relay else QUrl.fromLocalFile(str(path)).toString())
    db = Library(tmp_path / "library.sqlite3")
    playback = Playback(db, Source())
    playback.output.setMuted(True)
    if over_relay:
        import test_audio_buffer as fixture
        from musicdesk.relay import MediaRelay
        monkeypatch.setattr(fixture, "BODY", path.read_bytes())
        playback.relay.close()
        playback.relay = MediaRelay(fixture.Session, cache_directory=tmp_path / "relay-cache")
    errors = []
    playback.error.connect(errors.append)
    try:
        assert playback.player.backend == "mpv"
        first, second = Track("aaaaaaaaaaa", "First"), Track("bbbbbbbbbbb", "Second")
        playback.play_all([first, second])
        wait(lambda: 150 < playback.player.position() < 2500)
        assert playback.player.duration() >= 7000
        assert playback.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        source = playback.player.source()
        playback.seek(4000)
        wait(lambda: 3900 <= playback.player.position() <= 5500)
        assert playback.player.source() == source
        assert playback._pending_seek is None
        playback.toggle()
        wait(lambda: playback.player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        held = playback.player.position()
        QTest.qWait(200)
        assert abs(playback.player.position() - held) < 150
        playback.seek(2000)
        wait(lambda: 1900 <= playback.player.position() <= 2200)
        assert playback.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        playback.toggle()
        wait(lambda: playback.player.position() > 2250)
        playback.next()
        wait(lambda: playback.current == second and 100 < playback.player.position() < 2200)
        playback.previous()
        wait(lambda: playback.current == first and 100 < playback.player.position() < 2200)
        assert first in db.history() and second in db.history()
        for key, description in playback.routing.choices()[1:]:
            assert playback.routing.select(key)
            expected = device_name(playback.output.device(), playback.player._devices)
            wait(lambda: playback.player._core.get_property("audio-device") == expected)
            assert playback.player._core.get_property("audio-stream-silence") == ("buds3 fe" in description.casefold())
            wait(lambda: playback.player._core.get_property("current-ao") == "wasapi")
        playback.repeat_mode = "one"
        playback.seek(playback.player.duration() - 200)
        wait(lambda: playback.player.position() < 1800, timeout=5)
        assert playback.current == first
        playback.set_volume(37)
        wait(lambda: abs(playback.player._core.get_property("volume") - 37) < .1)
        assert not errors
    finally:
        playback.shutdown()
        assert not playback.player._thread.is_alive()
        db.close()


@pytest.mark.skipif(not library_path().is_file(), reason="Optional native runtime not installed")
def test_native_engine_connects_to_main_window(tmp_path, monkeypatch):
    monkeypatch.setenv("RIFFUNA_AUDIO_BACKEND", "mpv")
    from musicdesk.window import MainWindow
    app = QApplication.instance() or QApplication([])
    db = Library(tmp_path / "ui.sqlite3")
    window = MainWindow(db)
    try:
        assert window.playback.player.backend == "mpv"
        window.show()
        QTest.qWait(100)
        assert not window.seek.isEnabled()
    finally:
        window.close()
        db.close()
