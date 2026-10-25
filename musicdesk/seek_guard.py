"""Keep transitions silent until packets from the new decoder have arrived."""
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioBufferOutput


class SeekAudioGuard(QObject):
    audio_buffer_received = Signal(object)

    def __init__(self, player, output, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.player = player
        self.output = output
        self.volume = output.volume()
        self.clock = clock
        self.target = None
        self.fresh = False
        self.fresh_at = None
        self.ramp_started = None
        self.generation = 0
        self.buffers = None
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)
        self.observe()

    def set_volume(self, value):
        self.volume = min(1.0, max(0.0, value))
        if self.target is None:
            self.output.setVolume(self.volume)

    def begin(self, milliseconds=0):
        """Call BEFORE stop/clear; never restore an old sink's volume."""
        self.generation += 1
        self.timer.stop()
        self.target = max(0, milliseconds)
        self.fresh = False
        self.fresh_at = None
        self.ramp_started = None
        self.output.setVolume(0)

    def observe(self):
        """Reconnect after source teardown; queued old callbacks keep old tokens."""
        if self.buffers is None:
            self.buffers = QAudioBufferOutput(self)
            self.player.setAudioBufferOutput(self.buffers)
        else:
            self.buffers.audioBufferReceived.disconnect(self._buffer_slot)
        generation = self.generation
        self._buffer_slot = lambda buffer, generation=generation: self._buffer(buffer, generation)
        self.buffers.audioBufferReceived.connect(self._buffer_slot)

    def _buffer(self, buffer, generation=None):
        if generation is not None and generation != self.generation:
            return
        self.audio_buffer_received.emit(buffer)
        if generation is not None and generation != self.generation:
            return
        if self.target is None or not buffer.isValid():
            return
        position = buffer.startTime() / 1000
        if self.target - 100 <= position <= self.target + 3000:
            if not self.fresh:
                self.fresh_at = self.clock()
            self.fresh = True
            self.timer.start()

    def _tick(self):
        if self.target is None or not self.fresh:
            return
        now = self.clock()
        if self.ramp_started is None:
            if now - self.fresh_at < .04:
                return
            self.ramp_started = now
        fraction = min(1.0, (now - self.ramp_started) / .06)
        self.output.setVolume(self.volume * fraction)
        if fraction >= 1:
            self.timer.stop()
            self.target = None
            self.ramp_started = None

    def reset(self):
        """Cancel callbacks and keep silence; requested volume is independent."""
        self.begin()
        self.target = None


class NativeAudioGuard(QObject):
    """Volume controls only; libmpv owns the continuous native audio stream."""
    audio_buffer_received = Signal(object)
    target = None
    fresh = True

    def __init__(self, player, output, parent=None):
        super().__init__(parent)
        self.output = output
        self.volume = output.volume()

    def set_volume(self, value):
        self.volume = min(1.0, max(0.0, value))
        self.output.setVolume(self.volume)

    def begin(self, milliseconds=0):
        pass

    def observe(self):
        pass

    def reset(self):
        pass
