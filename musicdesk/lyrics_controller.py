"""Bounded background lyric loading, with stale-recording results discarded."""
from __future__ import annotations
import uuid
from PySide6.QtCore import QObject, QThreadPool, Signal
from .lyrics import LyricsStore, packet
from .workers import Task


class LyricsController(QObject):
    changed = Signal(str, object)

    def __init__(self, directory, parent=None, store=None):
        super().__init__(parent)
        self.store = store if store is not None else LyricsStore(directory)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._tasks = {}
        self._pending = None
        self._enriching = {}
        self._force = False
        self._token = ""
        self._track = None
        self._closed = False

    def load(self, track, force=False):
        if self._closed or track is None:
            return
        self._track = track
        self._force = bool(force)
        self._token = uuid.uuid4().hex
        self.changed.emit(track.video_id, packet(track, "loading"))
        job = (self._token, track, force)
        self._pending = None
        if len(self._tasks) >= 2:
            self._pending = job
        else:
            self._start(job)

    def _start(self, job):
        token, track, force = job[:3]
        if len(job) == 4:
            self._enriching[token] = job[3]
            task = Task(token, lambda: self.store.enrich_words(track, job[3], force))
        else:
            task = Task(token, lambda: self.store.load(track, force))
        task.signals.finished.connect(self._finished)
        task.signals.failed.connect(self._failed)
        self._tasks[token] = task
        self.pool.start(task)

    def _finished(self, token, payload):
        self._tasks.pop(token, None)
        enriched = token in self._enriching
        original = self._enriching.pop(token, None)
        if enriched and payload == original:
            self._drain()
            return
        if not self._closed and token == self._token and self._track and payload.get("recording_id") == self._track.video_id:
            self.changed.emit(self._track.video_id, payload)
            if (not enriched and not self._closed and token == self._token and payload.get("state") == "synced"
                    and hasattr(self.store, "enrich_words") and not any(row.get("words") for row in payload.get("lines", ()))):
                self._start((token, self._track, self._force, payload))
        self._drain()

    def _failed(self, token, message):
        self._tasks.pop(token, None)
        enriched = token in self._enriching
        self._enriching.pop(token, None)
        if not enriched and not self._closed and token == self._token and self._track:
            self.changed.emit(self._track.video_id, packet(self._track, "error", message=message))
        self._drain()

    def _drain(self):
        job, self._pending = self._pending, None
        if not self._closed and job and job[0] == self._token:
            self._start(job)

    def import_lrc(self, track, path):
        if self._closed or track is None:
            return
        self._token = uuid.uuid4().hex
        self._pending = None
        self._track = track
        try:
            result = self.store.import_lrc(track, path)
        except (OSError, ValueError, RuntimeError) as error:
            result = packet(track, "error", message=str(error))
        self.changed.emit(track.video_id, result)

    def shutdown(self):
        self._closed = True
        self._token = ""
        self._pending = None
        self.pool.clear()
        self.pool.waitForDone(100)
