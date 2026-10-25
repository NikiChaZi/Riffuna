"""Native-output lifecycle tests without opening physical audio devices."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from array import array
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudioFormat, QtAudio
from PySide6.QtWidgets import QApplication

import musicdesk.pcm_output as pcm_output


class Device:
    def __init__(self, name="Fixture device", supported=True, null=False):
        self.name, self.supported, self.null = name, supported, null

    def isNull(self):
        return self.null

    def isFormatSupported(self, format):
        assert format.sampleRate() == 48000
        assert format.channelCount() == 2
        assert format.sampleFormat() == QAudioFormat.SampleFormat.Float
        return self.supported

    def description(self):
        return self.name


class Controls(QObject):
    mutedChanged = Signal(bool)
    deviceChanged = Signal()

    def __init__(self, device=None):
        super().__init__()
        self.selected = device or Device()
        self.muted = False

    def volume(self):
        return .5

    def isMuted(self):
        return self.muted

    def device(self):
        return self.selected

    def set_muted(self, value):
        self.muted = value
        self.mutedChanged.emit(value)

    def select_device(self, device):
        self.selected = device
        self.deviceChanged.emit()


class Sink(QObject):
    instances = []
    next_error = QtAudio.Error.NoError

    def __init__(self, device, format, parent):
        super().__init__(parent)
        self.device, self.format = device, format
        self.starts = self.resets = self.deletions = 0
        self.frames = 0
        self.gain = None
        self.reader = None
        self.result_error = self.next_error
        type(self).next_error = QtAudio.Error.NoError
        self.instances.append(self)

    def setBufferFrameCount(self, count):
        self.frames = count

    def setVolume(self, value):
        self.gain = value

    def start(self, reader):
        self.starts += 1
        self.reader = reader

    def bufferSize(self):
        return self.frames * 8

    def error(self):
        return self.result_error

    def reset(self):
        self.resets += 1

    def deleteLater(self):
        self.deletions += 1
        super().deleteLater()


@pytest.fixture
def output_factory(monkeypatch):
    app = QApplication.instance() or QApplication([])
    Sink.instances = []
    Sink.next_error = QtAudio.Error.NoError
    monkeypatch.setattr(pcm_output, "QAudioSink", Sink)
    opened = []
    def create(controls=None):
        controls = controls or Controls()
        output = pcm_output.PcmOutput(controls)
        opened.append((controls, output))
        return controls, output
    yield create
    for _, output in opened:
        output.close()


def audio(value, frames):
    return (array("f", [value, value]) * frames).tobytes()


def samples(data):
    result = array("f")
    result.frombytes(data)
    return result


def prime(output, value=.8):
    frames = output._prebuffer_bytes // 8
    assert output.feed(audio(value, frames))
    assert not output._priming


def test_source_boundaries_share_one_continuous_sink_and_reader(output_factory):
    _, output = output_factory()
    prime(output)
    sink, reader = output.sink, output.reader
    assert sink.starts == output.start_count == 1
    assert sink.frames == 480 and sink.gain == 1.
    assert reader.isSequential() and not reader.atEnd()
    assert reader.bytesAvailable() > 0
    traces = []
    reader.trace = traces.append
    for value in (-.5, .7, -.2, .3):
        output.reader.readData(3840)
        output.transition()  # Used for play, next, previous and seek boundaries.
        prime(output, value)
        assert output.sink is sink and output.reader is reader
        assert sink.starts == 1 and sink.resets == 0
    assert len(Sink.instances) == output.start_count == 1
    assert reader.requests == 4 and reader.max_request == 3840
    assert all(len(chunk) == 3840 for chunk in traces)
    output.close()
    assert sink.resets == sink.deletions == 1
    assert output.sink is None and output.buffer.queued_bytes == 0
    assert not output._pending


def test_prebuffer_releases_only_when_ready_and_both_queues_stay_bounded(output_factory):
    _, output = output_factory()
    threshold = output._prebuffer_bytes
    chunk = audio(.4, threshold // 8 // 4)
    for _ in range(3):
        assert output.feed(chunk)
        assert output._priming
        assert 0 < len(output._pending) < threshold
        assert output.buffer.queued_bytes == 0
    assert output.feed(chunk)
    assert not output._priming and not output._pending
    assert output.buffer.queued_bytes == threshold
    assert output.feed(audio(-.3, 48000 * 3))
    assert output.buffer.queued_bytes <= output.buffer.max_bytes
    output.transition()
    assert not output._pending and output._priming
    assert output.buffer.queued_bytes == 0  # No samples had reached the device.
    assert output.sink.starts == 1 and output.sink.resets == 0


def test_pause_mute_volume_and_device_change_preserve_expected_lifecycle(output_factory):
    controls, output = output_factory()
    prime(output)
    first = output.sink
    steady = samples(output.reader.readData(960 * 8))
    assert steady[-1] == pytest.approx(.4)
    controls.set_muted(True)
    assert samples(output.reader.readData(480 * 8))[-1] == 0
    output.set_paused(True)
    assert output.paused and not output.feed(audio(.8, 5000))
    assert not any(output.reader.readData(960 * 8))
    assert first.starts == 1 and first.resets == 0
    output.set_paused(False)
    prime(output)
    controls.set_muted(False)
    assert samples(output.reader.readData(960 * 8))[-1] == pytest.approx(.4)
    output.set_volume(.25)
    assert samples(output.reader.readData(480 * 8))[-1] == pytest.approx(.2)
    second_device = Device("Second output")
    controls.select_device(second_device)
    assert first.resets == first.deletions == 1
    assert output.sink is None and output.buffer.queued_bytes == 0
    assert not output._pending and output._priming
    prime(output)
    assert output.sink.device is second_device
    assert len(Sink.instances) == output.start_count == 2
    assert output.sink.starts == 1


def test_unsupported_format_and_failed_sink_report_errors_without_stale_audio(output_factory, monkeypatch):
    unsupported = Device(supported=False)
    controls, output = output_factory(Controls(Device(null=True)))
    monkeypatch.setattr(pcm_output, "QMediaDevices", SimpleNamespace(defaultAudioOutput=lambda: unsupported))
    errors = []
    output.error.connect(errors.append)
    assert not output.feed(audio(.4, 5000))
    assert errors and "48" in errors[-1]
    assert not Sink.instances and output.sink is None
    assert output.buffer.queued_bytes == 0 and not output._pending
    controls.select_device(Device())
    Sink.next_error = QtAudio.Error.OpenError
    assert not output.feed(audio(.4, 5000))
    failed = Sink.instances[-1]
    assert failed.starts == failed.resets == failed.deletions == 1
    assert output.sink is None and output.start_count == 0
    assert "открыть" in errors[-1]
    assert output.feed(audio(.4, 5000))  # A later attempt may recover.
    assert output.sink is not failed and output.start_count == 1
