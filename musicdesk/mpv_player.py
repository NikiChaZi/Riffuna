"""Qt control adapter for libmpv; decoded audio never crosses Python."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import threading

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QMediaPlayer

from .mpv_api import MpvCore

log = logging.getLogger(__name__)


def library_path():
    override = os.environ.get("RIFFUNA_LIBMPV")
    return Path(override) if override else Path(__file__).resolve().parent.parent / "vendor/libmpv/libmpv-2.dll"


def device_name(device, available):
    endpoint = bytes(device.id()).decode("utf-8", errors="replace").rstrip("\0")
    guid = re.findall(r"\{[0-9a-fA-F-]{36}\}", endpoint)
    name = "wasapi/" + (guid[-1] if guid else endpoint)
    if any(entry.get("name") == name for entry in available):
        return name
    description = device.description().casefold()
    match = next((entry.get("name") for entry in available
                  if entry.get("description", "").casefold() == description
                  and entry.get("name", "").startswith("wasapi/")), None)
    return match or (name if endpoint else "auto")


class MpvPlayer(QObject):
    backend = "mpv"
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    positionChanged = Signal("qlonglong")
    durationChanged = Signal("qlonglong")
    audioReady = Signal("qlonglong")
    seekableChanged = Signal(bool)
    _native_event = Signal(object)

    def __init__(self, parent=None, core_factory=MpvCore):
        super().__init__(parent)
        self._source = QUrl()
        self._position = self._duration = 0
        self._seekable = False
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._status = QMediaPlayer.MediaStatus.NoMedia
        self._paused = True
        self._loading = False
        self._loaded = False
        self._closed = False
        self._controls = None
        self._core = core_factory(library_path(), {
            "config": "no", "load-scripts": "no", "ytdl": "no",
            "terminal": "no", "vo": "null", "vid": "no", "audio-display": "no",
            "idle": "yes", "keep-open": "yes", "pause": "yes", "volume": "0",
            "gapless-audio": "yes", "audio-samplerate": "48000",
            "audio-format": "float", "audio-channels": "stereo",
        })
        self._devices = self._core.get_property("audio-device-list") or []
        for name, kind in (("time-pos", "double"), ("duration", "double"),
                           ("pause", "flag"), ("paused-for-cache", "flag"),
                           ("seekable", "flag"), ("eof-reached", "flag")):
            self._core.observe(name, kind)
        self._native_event.connect(self._event)
        self._stop_events = threading.Event()
        self._thread = threading.Thread(target=self._events, name="mpv-events", daemon=True)
        self._thread.start()

    def _events(self):
        while not self._stop_events.is_set():
            try:
                event = self._core.wait_event(.15)
            except Exception:
                if not self._stop_events.is_set():
                    self._native_event.emit({"event": "client-error"})
                return
            if event.get("event") != "none":
                self._native_event.emit(event)

    def setAudioOutput(self, output):
        self._controls = output
        output.volumeChanged.connect(self._volume)
        output.mutedChanged.connect(self._mute)
        output.deviceChanged.connect(self._device)
        self._volume(output.volume())
        self._mute(output.isMuted())
        self._device()

    def _volume(self, value):
        if not self._closed:
            self._core.set_property("volume", max(0., min(100., value * 100)))

    def _mute(self, value):
        if not self._closed:
            self._core.set_property("mute", bool(value))

    def _device(self):
        if self._closed or self._controls is None:
            return
        device = self._controls.device()
        self._core.set_property("audio-device", device_name(device, self._devices))
        # Keep the tested Bluetooth device active during seeks and pause.
        # Other devices retain mpv's normal underrun/synchronization behavior.
        keep_alive = "buds3 fe" in device.description().casefold()
        self._core.set_property("audio-stream-silence", keep_alive)
        log.info("Audio engine=libmpv; output=%s; keep-alive=%s", device.description(), keep_alive)

    def setSource(self, source):
        self._source = QUrl(source)
        self._loaded = False
        self._loading = not source.isEmpty()
        self._position = self._duration = 0
        self._seekable = False
        self.seekableChanged.emit(False)
        self.positionChanged.emit(0)
        self.durationChanged.emit(0)
        if source.isEmpty():
            # Keep the native AO and its Bluetooth connection alive between files.
            self._core.set_property("pause", True)
            self._set_status(QMediaPlayer.MediaStatus.NoMedia)
            return
        self._set_status(QMediaPlayer.MediaStatus.LoadingMedia)
        path = source.toLocalFile() if source.isLocalFile() else source.toString()
        self._core.command(["loadfile", path, "replace"])

    def source(self):
        return QUrl(self._source)

    def play(self):
        self._paused = False
        self._core.set_property("pause", False)
        if self._loaded:
            self._set_state(QMediaPlayer.PlaybackState.PlayingState)

    def pause(self):
        self._paused = True
        self._core.set_property("pause", True)
        self._set_state(QMediaPlayer.PlaybackState.PausedState)

    def stop(self):
        self._paused = True
        self._core.set_property("pause", True)
        self._set_state(QMediaPlayer.PlaybackState.StoppedState)

    def setPosition(self, value):
        if not self._source.isEmpty():
            self._core.command(["seek", str(max(0, value) / 1000), "absolute+exact"])

    def position(self):
        return self._position

    def duration(self):
        return self._duration

    def isSeekable(self):
        return self._seekable

    def isAvailable(self):
        return not self._closed

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.playbackStateChanged.emit(state)

    def _set_status(self, status):
        if status != self._status:
            self._status = status
            self.mediaStatusChanged.emit(status)

    @Slot(object)
    def _event(self, event):
        if self._closed or self._source.isEmpty():
            return
        name = event.get("event")
        if name == "property-change":
            prop, value = event.get("name"), event.get("data")
            if value is None:
                return
            if prop == "time-pos":
                self._position = round(float(value) * 1000)
                self.positionChanged.emit(self._position)
            elif prop == "duration":
                self._duration = round(float(value) * 1000)
                self.durationChanged.emit(self._duration)
            elif prop == "seekable":
                self._seekable = bool(value)
                self.seekableChanged.emit(self._seekable)
            elif prop == "pause" and self._loaded:
                self._set_state(QMediaPlayer.PlaybackState.PausedState if value else QMediaPlayer.PlaybackState.PlayingState)
            elif prop == "paused-for-cache" and not self._loading:
                self._set_status(QMediaPlayer.MediaStatus.BufferingMedia if value else QMediaPlayer.MediaStatus.BufferedMedia)
            elif prop == "eof-reached" and value and self._loaded:
                self._set_status(QMediaPlayer.MediaStatus.EndOfMedia)
        elif name == "file-loaded":
            self._loaded = True
            self._loading = False
            try:
                self._seekable = bool(self._core.get_property("seekable"))
                self._duration = round(float(self._core.get_property("duration") or 0) * 1000)
            except RuntimeError:
                return
            self.durationChanged.emit(self._duration)
            self.seekableChanged.emit(self._seekable)
            self._set_status(QMediaPlayer.MediaStatus.LoadedMedia)
        elif name == "playback-restart" and self._loaded:
            self._set_status(QMediaPlayer.MediaStatus.BufferedMedia)
            self._set_state(QMediaPlayer.PlaybackState.PausedState if self._paused else QMediaPlayer.PlaybackState.PlayingState)
            self.audioReady.emit(self._position)
        elif name == "client-error" or (name == "end-file" and event.get("reason") == "error"):
            self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, "Нативный плеер не смог открыть аудио.")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._stop_events.set()
        self._thread.join(2)
        if self._thread.is_alive():
            log.error("Native audio event thread did not stop")
            return
        self._core.close()
