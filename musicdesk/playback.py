from __future__ import annotations

import uuid
import logging
import time

from PySide6.QtCore import QObject, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .audio_devices import AudioRouting
from .models import PlayQueue, Track
from .relay import MediaRelay
from .seek_guard import SeekAudioGuard
from .storage import Library
from .stream_cache import StreamCache
from .workers import Task
from .youtube import AudioStream, YouTubeSource

log = logging.getLogger(__name__)


class Playback(QObject):
    repeat_changed = Signal(str)
    queue_changed = Signal()
    track_changed = Signal(object)
    state_changed = Signal(str)
    error = Signal(str)
    history_changed = Signal()
    position_changed = Signal("qlonglong")
    duration_changed = Signal("qlonglong")

    def __init__(self, library: Library, source: YouTubeSource, parent=None):
        super().__init__(parent)
        self.library = library
        self.source = source
        self.streams = StreamCache(source.resolve)
        self.queue = library.load_queue()
        self._current = library.load_current() or self.queue.current
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.prefetch_pool = QThreadPool(self)
        self.prefetch_pool.setMaxThreadCount(2)
        self._prefetch_tasks = {}
        self._prefetch_next = None
        self._closing = False
        self._opened_at = 0.0
        self.last_start_ms = None
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.routing = AudioRouting(self.output, library, self)
        self.relay = MediaRelay(cache_directory=library.path.parent / "audio-cache")
        self.player.setAudioOutput(self.output)
        try:
            volume = float(library.get_setting("volume", "0.65"))
        except ValueError:
            volume = 0.65
        self.output.setVolume(min(1.0, max(0.0, volume)))
        self.seek_guard = SeekAudioGuard(self.player, self.output, self)
        mode = library.get_setting("repeat_mode", "off")
        self.repeat_mode = mode if mode in ("off", "one", "all") else "off"
        self._token = ""
        self._expected_url = ""
        self._resolving = False
        self._want_play = False
        self._history_logged = False
        self._tasks: dict[str, Task] = {}
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._player_error)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        QTimer.singleShot(0, self._prepare_restored)

    @property
    def current(self) -> Track | None:
        return self._current

    @property
    def repeat(self):
        return self.repeat_mode == "all"

    def cycle_repeat(self):
        modes = ("off", "one", "all")
        self.repeat_mode = modes[(modes.index(self.repeat_mode) + 1) % len(modes)]
        self.library.set_setting("repeat_mode", self.repeat_mode)
        self.repeat_changed.emit(self.repeat_mode)

    def add(self, track: Track):
        self.queue.add(track)
        self._save_queue()

    def play(self, track: Track):
        # A direct selection is not an implicit request to enqueue it.
        self._current = track
        self.queue.index = next((i for i, queued in enumerate(self.queue.tracks)
                                 if queued.video_id == track.video_id), -1)
        self._save_queue()
        self._open_current()

    def play_all(self, tracks: list[Track]):
        if not tracks:
            return
        unique = {track.video_id: track for track in tracks}
        self.queue = PlayQueue(list(unique.values()), 0)
        self._current = self.queue.current
        self._save_queue()
        self._open_current()

    def _save_queue(self):
        self.library.save_queue(self.queue)
        self.library.save_current(self.current)
        self.queue_changed.emit()

    def _open_current(self):
        track = self.current
        if track is None:
            return
        self._token = uuid.uuid4().hex
        token = self._token
        self._expected_url = ""
        self._resolving = True
        self._want_play = True
        self._history_logged = False
        self._opened_at = time.perf_counter()
        self.last_start_ms = None
        self.seek_guard.reset()
        self.player.stop()
        self.player.setSource(QUrl())
        self.relay.clear()
        self.track_changed.emit(track)
        self.state_changed.emit("loading")
        cached = self.relay.cached(track.video_id) or self.streams.peek(track.video_id)
        if cached is not None:
            self._resolved(token, cached)
            return
        task = Task(token, lambda: self.streams.resolve(track))
        task.signals.finished.connect(self._resolved)
        task.signals.failed.connect(self._resolve_failed)
        self._tasks[token] = task
        self.pool.start(task)

    def prefetch(self, track: Track):
        """Prepare a likely selection and bounded audio read-ahead; never plays it."""
        if self._closing:
            return
        cached = self.relay.cached(track.video_id) or self.streams.peek(track.video_id)
        if cached is not None:
            self.relay.prepare(cached)
            return
        if self.streams.is_pending(track.video_id):
            return
        if any(video_id == track.video_id for video_id, _ in self._prefetch_tasks.values()):
            return
        if len(self._prefetch_tasks) >= 2:
            self._prefetch_next = track
            return
        token = uuid.uuid4().hex
        task = Task(token, lambda: self._prepare_stream(track))
        self._prefetch_tasks[token] = (track.video_id, task)
        task.signals.finished.connect(self._prefetch_finished)
        task.signals.failed.connect(self._prefetch_finished)
        self.prefetch_pool.start(task)

    def _prepare_stream(self, track):
        stream = self.streams.resolve(track)
        if not self._closing:
            self.relay.prepare(stream)
        return stream

    def _prefetch_finished(self, token, result):
        if self._prefetch_tasks.pop(token, None) is None:
            return
        following, self._prefetch_next = self._prefetch_next, None
        if following is not None and not self._closing:
            self.prefetch(following)

    def _prepare_restored(self):
        if not self._closing and self.current is not None:
            self.prefetch(self.current)
            self._prepare_next()

    def _prepare_next(self):
        index = self.queue.index + 1
        if index < len(self.queue.tracks):
            self.prefetch(self.queue.tracks[index])
        elif self.repeat and self.queue.tracks:
            self.prefetch(self.queue.tracks[0])

    def _resolved(self, token: str, stream: AudioStream):
        self._tasks.pop(token, None)
        if token != self._token:
            return
        self._resolving = False
        log.info("Stream resolved in %sms", round((time.perf_counter() - self._opened_at) * 1000))
        try:
            self._expected_url = self.relay.bind(stream) if stream.url.startswith("https://") else stream.url
            self.player.setSource(QUrl(self._expected_url))
        except Exception:
            self._resolve_failed(token, "Не удалось подключить аудиопоток к плееру. Повтори попытку.")
            return
        if self._want_play:
            self.player.play()
        else:
            self.state_changed.emit("paused")

    def _resolve_failed(self, token: str, message: str):
        self._tasks.pop(token, None)
        if token != self._token:
            return
        self._resolving = False
        self._want_play = False
        self.state_changed.emit("error")
        self.error.emit(message)

    def toggle(self):
        if self._resolving:
            self._want_play = not self._want_play
            self.state_changed.emit("loading" if self._want_play else "paused")
        elif not self._expected_url:
            if self.current is None and self.queue.tracks:
                self.queue.index = 0
                self._current = self.queue.current
                self._save_queue()
            self._open_current()
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._want_play = False
            self.player.pause()
        else:
            self._want_play = True
            self.player.play()

    def next(self):
        if self.queue.advance(repeat=self.repeat):
            self._current = self.queue.current
            self._save_queue()
            self._open_current()

    def previous(self):
        if self.player.position() > 3000 and self._expected_url:
            self.player.setPosition(0)
        elif self.queue.advance(-1, repeat=self.repeat):
            self._current = self.queue.current
            self._save_queue()
            self._open_current()

    def remove(self, index: int):
        was_current = self.queue.remove(index)
        if was_current:
            # Removing a queue entry does not stop the audio already playing.
            self.queue.index = -1
        self._save_queue()

    def stop(self):
        self._token = uuid.uuid4().hex  # Invalidate any late network result.
        self._resolving = False
        self._want_play = False
        self._expected_url = ""
        self.seek_guard.reset()
        self.player.stop()
        self.player.setSource(QUrl())
        self.relay.clear()
        self.state_changed.emit("stopped")

    def seek(self, milliseconds: int):
        if self._expected_url:
            self.seek_guard.seek(max(0, milliseconds))

    def set_volume(self, value: int):
        self.seek_guard.set_volume(value / 100)

    def _playback_state(self, state):
        if not self._expected_url:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            if not self._history_logged and self.current:
                self.last_start_ms = round((time.perf_counter() - self._opened_at) * 1000)
                log.info("Playback started in %sms", self.last_start_ms)
                self.library.record_play(self.current)
                self._history_logged = True
                self.history_changed.emit()
                self._prepare_next()
            self.state_changed.emit("playing")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.state_changed.emit("paused")
        else:
            self.state_changed.emit("stopped")

    def _media_status(self, status):
        if not self._expected_url:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_mode == "one":
                self.player.setPosition(0)
                self.player.play()
            elif self.queue.advance(repeat=self.repeat):
                self._current = self.queue.current
                self._save_queue()
                self._open_current()
        elif status == QMediaPlayer.MediaStatus.BufferedMedia:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.state_changed.emit("playing")
        elif status in (QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.BufferingMedia):
            if self._want_play:
                self.state_changed.emit("loading")

    def _player_error(self, error, message):
        if error == QMediaPlayer.Error.NoError or not self._expected_url:
            return
        self._expected_url = ""
        self._want_play = False
        self.seek_guard.reset()
        if self.current:
            self.relay.invalidate_cached(self.current.video_id)
            stream = self.streams.peek(self.current.video_id)
            if stream is not None:
                self.relay.invalidate(stream)
            self.streams.invalidate(self.current.video_id)
        self.state_changed.emit("error")
        self.error.emit("Плеер не смог открыть поток. Нажми воспроизведение для новой попытки или выбери другую запись.")

    def shutdown(self):
        self._closing = True
        self._prefetch_next = None
        self.stop()
        self.library.save_queue(self.queue)
        self.library.save_current(self.current)
        self.library.set_setting("volume", str(self.output.volume()))
        self.pool.clear()
        self.pool.waitForDone(100)
        self.prefetch_pool.clear()
        self.prefetch_pool.waitForDone(100)
        self.relay.close()

