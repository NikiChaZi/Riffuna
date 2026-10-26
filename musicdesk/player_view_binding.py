"""Optional signal wiring only: does not create or replace any audio objects."""
from __future__ import annotations

from PySide6.QtCore import QObject


class ExpandedPlayerBinding(QObject):
    def __init__(self, view, playback, *, artwork=None):
        super().__init__(view)
        self.view = view
        self.playback = playback
        self.artwork = artwork
        self._connections = []
        for signal, slot in (
            (playback.track_changed, self._track_changed),
            (playback.position_changed, view.set_position),
            (playback.duration_changed, view.set_duration),
            (playback.state_changed, self._state_changed),
            (playback.player.seekableChanged, view.set_seekable),
            (playback.repeat_changed, view.set_repeat),
            (playback.shuffle_changed, view.set_shuffle),
            (playback.queue_changed, self._navigation_changed),
            (playback.output.volumeChanged, self._volume_changed),
            (view.toggle_requested, playback.toggle),
            (view.previous_requested, playback.previous),
            (view.next_requested, playback.next),
            (view.seek_requested, playback.seek),
            (view.repeat_requested, playback.cycle_repeat),
            (view.shuffle_requested, playback.toggle_shuffle),
            (view.volume_requested, playback.set_volume),
        ):
            self._connect(signal, slot)
        if artwork is not None:
            self._connect(artwork.loaded, self._artwork_loaded)
        self._track_changed(playback.current)
        view.set_duration(playback.player.duration())
        view.set_seekable(playback.player.isSeekable())
        view.set_position(playback.player.position())
        view.set_repeat(playback.repeat_mode)
        view.set_shuffle(playback.shuffle)
        self._volume_changed(playback.output.volume())
        state = getattr(playback.player.playbackState(), "name", "StoppedState")
        self._state_changed({"PlayingState": "playing", "PausedState": "paused"}.get(state, "stopped"))

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def disconnect(self):
        """Call before replacing this binding; signal wiring is not additive."""
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()

    def _track_changed(self, track):
        self.view.set_track(track)
        self._navigation_changed()
        if track and self.artwork:
            pixmap = self.artwork.cache.get(track.thumbnail)
            if pixmap is not None:
                self.view.set_artwork(track.video_id, pixmap)
            else:
                self.artwork.fetch(track.thumbnail)

    def _navigation_changed(self):
        self.view.set_navigation(self.playback.current is not None or self.playback.queue.index > 0,
                                 self.playback.can_next)

    def _state_changed(self, state):
        self.view.set_playback_state(state, wants_play=getattr(self.playback, "_want_play", state == "playing"))

    def _volume_changed(self, volume):
        self.view.set_volume(round(volume * 100))

    def _artwork_loaded(self, url, pixmap):
        track = self.view.track
        if track and track.thumbnail == url:
            self.view.set_artwork(track.video_id, pixmap)
