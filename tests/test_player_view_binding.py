import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy
from test_ui_search import app

from musicdesk.expanded_player import ExpandedPlayer
from musicdesk.lyrics_view import LyricCue, LyricsDocument, LyricsState
from musicdesk.models import Track
from musicdesk.motion import MotionPolicy
from musicdesk.player_view_binding import ExpandedPlayerBinding


class FakePlayer(QObject):
    seekableChanged = Signal(bool)
    def duration(self): return 20000
    def position(self): return 0
    def isSeekable(self): return True
    def playbackState(self): return SimpleNamespace(name="PausedState")


class FakeOutput(QObject):
    volumeChanged = Signal(float)
    def volume(self): return .7


class FakePlayback(QObject):
    track_changed = Signal(object)
    position_changed = Signal("qlonglong")
    duration_changed = Signal("qlonglong")
    state_changed = Signal(str)
    repeat_changed = Signal(str)
    shuffle_changed = Signal(bool)
    queue_changed = Signal()

    def __init__(self):
        super().__init__()
        self.current = Track("aaaaaaaaaaa", "Тестовая запись", "Студия 04", 20, "fixture://first")
        self.player = FakePlayer(self)
        self.output = FakeOutput(self)
        self.queue = SimpleNamespace(index=-1)
        self.can_next = False
        self.repeat_mode = "off"
        self.shuffle = False
        self._want_play = False
        self.calls = []

    def toggle(self): self.calls.append(("toggle",))
    def previous(self): self.calls.append(("previous",))
    def next(self): self.calls.append(("next",))
    def seek(self, value): self.calls.append(("seek", value))
    def cycle_repeat(self): self.calls.append(("repeat",))
    def toggle_shuffle(self): self.calls.append(("shuffle",))
    def set_volume(self, value): self.calls.append(("volume", value))


class FakeArtwork(QObject):
    loaded = Signal(str, QPixmap)
    def __init__(self, pixmap):
        super().__init__()
        self.cache = {"fixture://first": pixmap}
        self.requested = []
    def fetch(self, url): self.requested.append(url)


def test_binding_has_no_autoplay_and_uses_actual_position_after_seek(app):
    view = ExpandedPlayer(policy=MotionPolicy(True))
    playback = FakePlayback()
    binding = ExpandedPlayerBinding(view, playback)
    try:
        cues = (LyricCue(0, "Первая выдуманная строка"), LyricCue(7000, "Следующая выдуманная строка"))
        view.set_lyrics(playback.current.video_id, view.request_token,
                        LyricsDocument(LyricsState.SYNCED, cues, timing_confirmed=True))
        assert not playback.calls
        view.open_from()
        assert not playback.calls
        view.seek_requested.emit(7000)
        assert playback.calls == [("seek", 7000)]
        assert view.lyrics.canvas.active_indices == (0,)
        playback.position_changed.emit(7000)
        assert view.lyrics.canvas.active_indices == (1,)
        playback.state_changed.emit("paused")
        playback.position_changed.emit(1000)
        assert view.lyrics.canvas.active_indices == (0,)
        assert view.position == 1000
        playback.output.volumeChanged.emit(.25)
        assert view.volume.value() == 25
        assert playback.calls == [("seek", 7000)]
        view.play_button.click()
        assert playback.calls[-1] == ("toggle",)
    finally:
        binding.disconnect()
        view.close()


def test_binding_disconnect_prevents_duplicate_intents_and_stale_updates(app):
    view = ExpandedPlayer(policy=MotionPolicy(True))
    playback = FakePlayback()
    binding = ExpandedPlayerBinding(view, playback)
    binding.disconnect()
    binding.disconnect()
    view.toggle_requested.emit()
    playback.position_changed.emit(12000)
    assert not playback.calls
    assert view.position == 0
    replacement = ExpandedPlayerBinding(view, playback)
    view.toggle_requested.emit()
    assert playback.calls == [("toggle",)]
    replacement.disconnect()
    view.close()


def test_binding_resets_text_on_track_change_and_ignores_old_art(app):
    view = ExpandedPlayer(policy=MotionPolicy(True))
    playback = FakePlayback()
    art = QPixmap(32, 32)
    art.fill(QColor("#FF875F"))
    artwork = FakeArtwork(art)
    binding = ExpandedPlayerBinding(view, playback, artwork=artwork)
    try:
        assert not view.cover.pixmap.isNull()
        playback.current = Track("bbbbbbbbbbb", "Тестовая запись", "Студия 04", 20, "fixture://second")
        playback.track_changed.emit(playback.current)
        assert view.lyrics.document.state == LyricsState.LOADING
        assert view.cover.pixmap.isNull()
        assert artwork.requested == ["fixture://second"]
        artwork.loaded.emit("fixture://first", art)
        assert view.cover.pixmap.isNull()
        artwork.loaded.emit("fixture://second", art)
        assert not view.cover.pixmap.isNull()
        assert not playback.calls
    finally:
        binding.disconnect()
        view.close()


def test_binding_repeat_shuffle_and_seekability_only_change_controls(app):
    view = ExpandedPlayer(policy=MotionPolicy(True))
    playback = FakePlayback()
    binding = ExpandedPlayerBinding(view, playback)
    try:
        playback.repeat_changed.emit("one")
        playback.shuffle_changed.emit(True)
        playback.player.seekableChanged.emit(False)
        assert view.repeat_button.isChecked()
        assert "одной" in view.repeat_button.accessibleName()
        assert view.shuffle_button.isChecked()
        assert not view.seek.isEnabled()
        assert not view.lyrics.canvas.seek_enabled
        assert not playback.calls
    finally:
        binding.disconnect()
        view.close()
