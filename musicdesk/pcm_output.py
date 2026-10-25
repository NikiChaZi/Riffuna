"""One continuous device stream, independent of the media decoder lifetime."""
import logging

from PySide6.QtCore import QIODevice, QObject, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from .pcm_buffer import PcmBuffer

log = logging.getLogger(__name__)


def pcm_format():
    result = QAudioFormat()
    result.setSampleRate(48000)
    result.setChannelCount(2)
    result.setSampleFormat(QAudioFormat.SampleFormat.Float)
    return result


class PcmReader(QIODevice):
    def __init__(self, buffer, parent=None):
        super().__init__(parent)
        self.buffer = buffer
        self.trace = None
        self.requests = 0
        self.max_request = 0
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def isSequential(self):
        return True

    def bytesAvailable(self):
        return 65536 + super().bytesAvailable()

    def atEnd(self):
        return False

    def readData(self, size):
        self.requests += 1
        self.max_request = max(self.max_request, size)
        data = self.buffer.read(size)
        if self.trace:
            self.trace(data)
        return data


class PcmOutput(QObject):
    error = Signal(str)

    def __init__(self, controls, parent=None):
        super().__init__(parent)
        self.controls = controls
        self.format = pcm_format()
        self.buffer = PcmBuffer()
        self.buffer.set_volume(controls.volume())
        self.buffer.set_muted(controls.isMuted())
        self.reader = PcmReader(self.buffer, self)
        self.sink = None
        self.start_count = 0
        self.paused = False
        self._pending = bytearray()
        self._priming = True
        self._prebuffer_bytes = self.format.bytesForDuration(60000)
        controls.mutedChanged.connect(self.buffer.set_muted)
        controls.deviceChanged.connect(self._device_changed)

    def set_volume(self, value):
        self.buffer.set_volume(value)

    def transition(self):
        self._pending.clear()
        self._priming = True
        self.buffer.transition()

    def set_paused(self, paused):
        if paused != self.paused:
            self.paused = paused
            self.transition()

    def _ensure_sink(self):
        if self.sink is not None:
            return True
        device = self.controls.device()
        if device.isNull():
            device = QMediaDevices.defaultAudioOutput()
        if not device.isFormatSupported(self.format):
            self.error.emit("Устройство не поддерживает формат аудиовыхода 48 кГц. Выбери другой выход.")
            return False
        sink = QAudioSink(device, self.format, self)
        sink.setBufferFrameCount(480)
        sink.setVolume(1.0)  # Gain and mute are applied to PCM before submission.
        sink.start(self.reader)
        if sink.error() != QtAudio.Error.NoError:
            sink.reset()
            sink.deleteLater()
            self.error.emit("Не удалось открыть звуковой выход. Проверь выбранное устройство.")
            return False
        self.sink = sink
        self.start_count += 1
        duration = self.format.durationForBytes(sink.bufferSize())
        self._prebuffer_bytes = self.format.bytesForDuration(max(60000, duration + 20000))
        log.info("Continuous PCM output: %s; buffer=%s bytes, prebuffer=%s bytes",
                 device.description(), sink.bufferSize(), self._prebuffer_bytes)
        return True

    def feed(self, data):
        if self.paused or not data:
            return False
        if not self._ensure_sink():
            return False
        if self._priming:
            self._pending.extend(data)
            if len(self._pending) < self._prebuffer_bytes:
                return True
            self.buffer.feed(self._pending)
            self._pending.clear()
            self._priming = False
        else:
            self.buffer.feed(data)
        return True

    def _device_changed(self):
        self._close_sink()
        self.buffer.clear()
        self._pending.clear()
        self._priming = True

    def _close_sink(self):
        sink, self.sink = self.sink, None
        if sink is not None:
            sink.reset()
            sink.deleteLater()

    def close(self):
        self._close_sink()
        self.buffer.clear()
        self._pending.clear()
