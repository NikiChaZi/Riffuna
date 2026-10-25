"""Keep transitions silent until packets from the new decoder have arrived."""
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer

from .pcm_output import PcmOutput, pcm_format


class SeekAudioGuard(QObject):
    audio_buffer_received = Signal(object)
    error = Signal(str)

    def __init__(self, player, output, parent=None, clock=time.monotonic, pcm_factory=PcmOutput):
        super().__init__(parent)
        self.player = player
        self.output = output
        self.volume = output.volume()
        self.clock = clock
        self.pcm = pcm_factory(output, self)
        self.pcm.error.connect(self.error)
        player.setAudioOutput(None)
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
        self.pcm.set_volume(self.volume)
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
        self.pcm.transition()

    def observe(self):
        """Reconnect after source teardown; queued old callbacks keep old tokens."""
        if self.buffers is None:
            self.buffers = QAudioBufferOutput(pcm_format(), self)
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
        if not buffer.isValid() or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        position = buffer.startTime() / 1000
        if self.target is None:
            self.pcm.feed(bytes(buffer.constData()))
        elif self.target - 100 <= position <= self.target + 3000:
            if not self.pcm.feed(bytes(buffer.constData())):
                return
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

    def close(self):
        self.timer.stop()
        self.pcm.close()
