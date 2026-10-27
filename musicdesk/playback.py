from __future__ import annotations

import os
import json
import uuid
import logging
import time

from PySide6.QtCore import QObject, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .audio_devices import AudioRouting
from .models import PlayQueue, ShuffleOrder, Track
from .relay import MediaRelay
from .seek_guard import SeekAudioGuard, NativeAudioGuard
from .storage import Library
from .stream_cache import StreamCache
from .workers import Task
from .youtube import AudioStream, YouTubeSource

log = logging.getLogger(__name__)


class Playback(QObject):
    shuffle_changed = Signal(bool)
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
        try:
            continuation = json.loads(library.get_setting("queue_continuation", "null"))
        except (ValueError, TypeError):
            continuation = None
        available = {track.video_id for track in self.queue.tracks}
        self._continuation = (list(dict.fromkeys(value for value in continuation
                              if isinstance(value, str) and value in available))
                              if isinstance(continuation, list) and self.queue.index == -1
                              and self._current else None)
        self._shuffle = library.get_setting("shuffle", "off") == "on"
        self._shuffle_order = ShuffleOrder()
        self._reset_shuffle()
        try:
            priority = json.loads(library.get_setting("queue_next_ids", "[]"))
        except (ValueError, TypeError):
            priority = []
        if isinstance(priority, list):
            self._shuffle_order.priority = list(dict.fromkeys(
                value for value in priority if isinstance(value, str)
                and value in self._shuffle_order.ids))
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.prefetch_pool = QThreadPool(self)
        self.prefetch_pool.setMaxThreadCount(2)
        self._prefetch_tasks = {}
        self._prefetch_next = None
        self._closing = False
        self._opened_at = 0.0
        self.last_start_ms = None
        from .mpv_player import MpvPlayer, library_path
        native = os.environ.get("RIFFUNA_AUDIO_BACKEND", "mpv") != "qt" and library_path().is_file()
        self.player = MpvPlayer(self) if native else QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.routing = AudioRouting(self.output, library, self)
        self.relay = MediaRelay(cache_directory=library.path.parent / "audio-cache")
        self.player.setAudioOutput(self.output)
        try:
            volume = float(library.get_setting("volume", "0.65"))
        except ValueError:
            volume = 0.65
        self.output.setVolume(min(1.0, max(0.0, volume)))
        self.seek_guard = (NativeAudioGuard if native else SeekAudioGuard)(self.player, self.output, self)
        mode = library.get_setting("repeat_mode", "off")
        self.repeat_mode = mode if mode in ("off", "one", "all") else "off"
        self._token = ""
        self._expected_url = ""
        self._resolving = False
        self._pending_seek = None
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
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def can_next(self) -> bool:
        if self.shuffle:
            self._sync_shuffle()
            return self._shuffle_order.peek(self.repeat) is not None
        return self._linear_next() is not None

    def _linear_next(self):
        available = {track.video_id: track for track in self.queue.tracks}
        priority = next((available[value] for value in self._shuffle_order.priority
                         if value in available), None)
        if priority is not None:
            return priority
        if self._continuation is not None:
            candidate = next((available[value] for value in self._continuation
                              if value in available), None)
            if candidate is not None:
                return candidate
        elif self.queue.index + 1 < len(self.queue.tracks):
            return self.queue.tracks[self.queue.index + 1]
        return self.queue.tracks[0] if self.repeat and self.queue.tracks else None

    def toggle_shuffle(self):
        self._shuffle = not self._shuffle
        if self._shuffle:
            self._reset_shuffle(preserve_priority=True)
        self.library.set_setting("shuffle", "on" if self._shuffle else "off")
        self.shuffle_changed.emit(self._shuffle)
        self._prepare_next()

    def _reset_shuffle(self, *, include_current=True, preserve_priority=False):
        priority = self._shuffle_order.priority.copy() if preserve_priority else []
        # A preferred recording has another ID; navigation still belongs to its
        # original queue entry, otherwise shuffle would play the original twice.
        anchor = self.queue.current or self.current
        current = anchor.video_id if include_current and anchor else None
        self._shuffle_order.reset([track.video_id for track in self.queue.tracks], current)
        self._shuffle_order.priority = [value for value in priority
                                        if value in self._shuffle_order.ids]

    def _sync_shuffle(self):
        self._shuffle_order.sync([track.video_id for track in self.queue.tracks])

    def _advance_queue(self, step=1):
        if not self.shuffle:
            track = self._linear_next() if step > 0 else self.queue.advance(step, repeat=self.repeat)
            if track is not None:
                self.queue.index = next(index for index, entry in enumerate(self.queue.tracks)
                                        if entry.video_id == track.video_id)
                self._continuation = None
                self._shuffle_order.select(track.video_id)
            return track
        self._sync_shuffle()
        video_id = self._shuffle_order.previous() if step < 0 else self._shuffle_order.next(self.repeat)
        if video_id is None:
            return None
        self.queue.index = next(index for index, track in enumerate(self.queue.tracks)
                                if track.video_id == video_id)
        self._continuation = None
        return self.queue.current

    def play_queue(self):
        """Restart the existing queue without replacing or rearranging it."""
        if not self.queue.tracks:
            return
        self._continuation = None
        self._reset_shuffle(include_current=False)
        if self.shuffle:
            self._advance_queue()
        else:
            self.queue.index = 0
        self._current = self.queue.current
        self._save_queue()
        self._open_current()

    @property
    def repeat(self):
        return self.repeat_mode == "all"

    def cycle_repeat(self):
        modes = ("off", "one", "all")
        self.repeat_mode = modes[(modes.index(self.repeat_mode) + 1) % len(modes)]
        self.library.set_setting("repeat_mode", self.repeat_mode)
        self.repeat_changed.emit(self.repeat_mode)
        self._prepare_next()

    def add(self, track: Track):
        self.add_many([track])

    def add_many(self, tracks: list[Track]) -> int:
        """Append distinct IDs with one persistence operation and one notification."""
        entries = list(tracks)
        if any(not isinstance(track, Track) for track in entries):
            raise TypeError("Queue entries must be Track objects")
        known = {track.video_id for track in self.queue.tracks}
        added = []
        for track in entries:
            if track.video_id not in known:
                known.add(track.video_id)
                added.append(track)
        if not added:
            return 0
        self.queue.tracks.extend(added)
        if self._continuation is not None:
            self._continuation.extend(track.video_id for track in added)
        self._sync_shuffle()
        self._save_queue()
        self._prepare_next()
        return len(added)

    def remove_many(self, video_ids: list[str]) -> int:
        """Remove matching IDs atomically, preserving audio and its continuation."""
        removed_ids = {value for value in video_ids if isinstance(value, str)}
        before = self.queue.tracks
        retained = [track for track in before if track.video_id not in removed_ids]
        removed_count = len(before) - len(retained)
        if not removed_count:
            return 0
        anchor = self.queue.current
        if anchor is not None and anchor.video_id in removed_ids:
            self._continuation = [track.video_id for track in before[self.queue.index + 1:]
                                  if track.video_id not in removed_ids]
            self.queue = PlayQueue(retained, -1)
        else:
            index = (next(i for i, track in enumerate(retained)
                          if track.video_id == anchor.video_id) if anchor is not None else -1)
            self.queue = PlayQueue(retained, index)
            if self._continuation is not None:
                self._continuation = [value for value in self._continuation
                                      if value not in removed_ids]
        self._sync_shuffle()
        self._save_queue()
        self._prepare_next()
        return removed_count

    def reorder_queue(self, video_ids: list[str]) -> bool:
        """Accept only an exact unique permutation; do not partially apply it."""
        requested = list(video_ids)
        entries = {track.video_id: track for track in self.queue.tracks}
        if (any(not isinstance(value, str) for value in requested)
                or len(requested) != len(entries) or len(set(requested)) != len(requested)
                or set(requested) != set(entries)
                or requested == [track.video_id for track in self.queue.tracks]):
            return False
        anchor = self.queue.current
        self.queue = PlayQueue([entries[value] for value in requested],
                               requested.index(anchor.video_id) if anchor is not None else -1)
        if self._continuation is not None:
            eligible = set(self._continuation)
            self._continuation = [value for value in requested if value in eligible]
        self._sync_shuffle()
        self._save_queue()
        self._prepare_next()
        return True

    def play_next(self, track: Track):
        """Queue a selection immediately next, including while shuffle is on."""
        if self.current and self.library.preferred_recording(track).video_id == self.current.video_id:
            return
        self.queue.insert_next(track)
        if self._continuation is not None:
            self._continuation = [track.video_id] + [value for value in self._continuation
                                                    if value != track.video_id]
        self._sync_shuffle()
        self._shuffle_order.prioritize(track.video_id)
        self._save_queue()
        self._prepare_next()

    def move_queue(self, source: int | str, destination: int) -> bool:
        """Move an entry by ID (preferred for UI) or index to a final index."""
        if not self.queue.move(source, destination):
            return False
        if self._continuation is not None:
            eligible = set(self._continuation)
            self._continuation = [track.video_id for track in self.queue.tracks
                                  if track.video_id in eligible]
        self._sync_shuffle()
        self._save_queue()
        self._prepare_next()
        return True

    def clear_queue(self):
        """Clear the list without stopping, seeking, or changing current audio."""
        self.queue = PlayQueue()
        self._continuation = None
        self._reset_shuffle()
        self._prefetch_next = None
        self._save_queue()

    def play(self, track: Track):
        # A direct selection is not an implicit request to enqueue it.
        self._current = track
        self._continuation = None
        self.queue.index = next((i for i, queued in enumerate(self.queue.tracks)
                                 if queued.video_id == track.video_id), -1)
        self._sync_shuffle()
        self._shuffle_order.select(track.video_id)
        self._save_queue()
        self._open_current()

    def play_from(self, tracks: list[Track], track: Track):
        """Play a selected playlist entry and continue within that playlist."""
        unique = list({entry.video_id: entry for entry in tracks}.values())
        selected = next((index for index, entry in enumerate(unique)
                         if entry.video_id == track.video_id), None)
        if selected is None:
            return
        self.queue = PlayQueue(unique, selected)
        self._continuation = None
        self._current = self.queue.current
        self._reset_shuffle()
        self._save_queue()
        self._open_current()

    def play_all(self, tracks: list[Track]):
        if not tracks:
            return
        unique = {track.video_id: track for track in tracks}
        self.queue = PlayQueue(list(unique.values()), 0)
        self.play_queue()

    def _save_queue(self):
        self.library.save_queue(self.queue)
        self.library.save_current(self.current)
        self.library.set_setting("queue_next_ids", json.dumps(self._shuffle_order.priority))
        self.library.set_setting("queue_continuation", json.dumps(self._continuation))
        self.queue_changed.emit()

    def _open_current(self):
        track = self.current
        if track is None:
            return
        preferred = self.library.preferred_recording(track)
        if preferred.video_id != track.video_id:
            self._current = track = preferred
            self.library.save_current(track)
        self._token = uuid.uuid4().hex
        token = self._token
        self._expected_url = ""
        self._resolving = True
        self._want_play = True
        self._history_logged = False
        self._opened_at = time.perf_counter()
        self.last_start_ms = None
        self._pending_seek = None
        self.seek_guard.begin()
        self.player.stop()
        self.player.setSource(QUrl())
        self.seek_guard.observe()
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
        track = self.library.preferred_recording(track)
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
        if self.shuffle:
            self._sync_shuffle()
            video_id = self._shuffle_order.peek(self.repeat)
            candidate = next((track for track in self.queue.tracks if track.video_id == video_id), None)
            if candidate is not None:
                self.prefetch(candidate)
            return
        candidate = self._linear_next()
        if candidate is not None:
            self.prefetch(candidate)

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
        self._pending_seek = None
        self._want_play = False
        self.state_changed.emit("error")
        self.error.emit(message)

    def toggle(self):
        if self._resolving or self._pending_seek is not None:
            self._want_play = not self._want_play
            self.state_changed.emit("loading" if self._want_play else "paused")
        elif not self._expected_url:
            if self.current is None and self.queue.tracks:
                self.play_queue()
            else:
                self._open_current()
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._want_play = False
            self.player.pause()
        else:
            self._want_play = True
            self.player.play()

    def next(self):
        if self._advance_queue():
            self._current = self.queue.current
            self._save_queue()
            self._open_current()

    def previous(self):
        if self.player.position() > 3000 and self._expected_url:
            self.seek(0)
        elif self._advance_queue(-1):
            self._current = self.queue.current
            self._save_queue()
            self._open_current()

    def remove(self, index: int):
        if 0 <= index < len(self.queue.tracks):
            self.remove_many([self.queue.tracks[index].video_id])

    def stop(self):
        self._token = uuid.uuid4().hex  # Invalidate any late network result.
        self._resolving = False
        self._pending_seek = None
        self._want_play = False
        self._expected_url = ""
        self.seek_guard.begin()
        self.player.stop()
        self.player.setSource(QUrl())
        self.seek_guard.reset()
        self.relay.clear()
        self.state_changed.emit("stopped")

    def seek(self, milliseconds: int):
        if not self._expected_url:
            return
        target = max(0, milliseconds)
        duration = self.player.duration()
        if duration > 0:
            target = min(target, duration)
        if getattr(self.player, "backend", "qt") == "mpv":
            self.player.setPosition(target)
            if self._want_play:
                self.player.play()
            return
        source = self._expected_url
        self._pending_seek = target
        self._expected_url = ""
        self.seek_guard.begin(target)
        self.player.stop()
        # Clearing the source destroys the old playback engine and waits for
        # its renderer threads; setPosition alone tears them down asynchronously.
        # The relay and its audio cache stay alive, so this does not re-resolve
        # YouTube or redownload a fully buffered track.
        self.player.setSource(QUrl())
        self.seek_guard.observe()
        self._expected_url = source
        self.state_changed.emit("loading" if self._want_play else "paused")
        self.player.setSource(QUrl(source))

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
        if self._pending_seek is not None:
            if status == QMediaPlayer.MediaStatus.LoadedMedia:
                target, self._pending_seek = self._pending_seek, None
                self.player.setPosition(target)
                if self._want_play:
                    self.player.play()
                else:
                    self.state_changed.emit("paused")
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_mode == "one":
                self.seek(0)
            elif self._advance_queue():
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
        self._pending_seek = None
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
        self.library.set_setting("volume", str(self.seek_guard.volume))
        self.pool.clear()
        self.pool.waitForDone(100)
        self.prefetch_pool.clear()
        self.prefetch_pool.waitForDone(100)
        self.relay.close()
        if hasattr(self.player, "shutdown"):
            self.player.shutdown()

