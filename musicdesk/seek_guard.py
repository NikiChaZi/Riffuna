"""Silence decoder discontinuities during a seek, then restore volume smoothly."""
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer


class SeekAudioGuard(QObject):
    def __init__(self, player, output, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.player = player
        self.output = output
        self.volume = output.volume()
        self.clock = clock
        self.target = None
        self.fresh = False
        self.ramp_started = None
        self.buffers = QAudioBufferOutput(self)
        player.setAudioBufferOutput(self.buffers)
        self.buffers.audioBufferReceived.connect(self._buffer)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def set_volume(self, value):
        self.volume = min(1.0, max(0.0, value))
        if self.target is None:
            self.output.setVolume(self.volume)

    def seek(self, milliseconds):
        self.target = max(0, milliseconds)
        self.started = self.clock()
        self.fresh = False
        self.ramp_started = None
        self.output.setVolume(0)
        self.player.setPosition(self.target)
        self.timer.start()

    def _buffer(self, buffer):
        if self.target is not None and buffer.isValid():
            position = buffer.startTime() / 1000
            # Ignore packets from the previous position still being drained.
            if self.target - 100 <= position <= self.target + 3000:
                self.fresh = True

    def _tick(self):
        if self.target is None:
            return
        now = self.clock()
        elapsed = now - self.started
        paused = self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        # Some backends do not emit decoded-buffer notifications. Their native
        # buffered state and position provide a bounded fallback after one second.
        ready = (self.player.mediaStatus() == QMediaPlayer.MediaStatus.BufferedMedia
                 and self.target - 100 <= self.player.position() <= self.target + 5000)
        if self.ramp_started is None:
            if elapsed < 0.12 or not (self.fresh or paused or (elapsed >= 1 and ready)):
                return
            self.ramp_started = now
        fraction = min(1.0, (now - self.ramp_started) / 0.08)
        self.output.setVolume(self.volume * fraction)
        if fraction >= 1:
            self.reset()

    def reset(self):
        self.timer.stop()
        self.target = None
        self.ramp_started = None
        self.output.setVolume(self.volume)
