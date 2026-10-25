import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

from musicdesk.seek_guard import SeekAudioGuard


class Player:
    def __init__(self):
        self.positions = []
        self.position_value = 0
        self.state = QMediaPlayer.PlaybackState.PlayingState
        self.status = QMediaPlayer.MediaStatus.BufferingMedia

    def setAudioOutput(self, output):
        self.native_output = output

    def setAudioBufferOutput(self, output):
        self.buffer_output = output

    def setPosition(self, value):
        self.positions.append(value)
        self.position_value = value

    def position(self):
        return self.position_value

    def playbackState(self):
        return self.state

    def mediaStatus(self):
        return self.status


class Output:
    def __init__(self):
        self.value = .6
        self.muted = True

    def volume(self):
        return self.value

    def setVolume(self, value):
        self.value = value


class Buffer:
    def __init__(self, position):
        self.position = position

    def isValid(self):
        return True

    def startTime(self):
        return self.position * 1000

    def constData(self):
        return bytes(3840)



class Pcm(QObject):
    error = Signal(str)
    def __init__(self, output, parent):
        super().__init__(parent)
        self.frames = []
    def feed(self, data):
        self.frames.append(data)
        return True
    def transition(self):
        self.frames.clear()
    def set_volume(self, value):
        self.volume = value
    def close(self):
        pass


def test_seek_silences_old_packets_and_restores_latest_volume_smoothly():
    app = QApplication.instance() or QApplication([])
    now = [0.0]
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, clock=lambda: now[0], pcm_factory=Pcm)
    try:
        guard.begin(60000)
        guard.observe()
        player.setPosition(60000)
        assert output.value == 0
        guard._buffer(Buffer(2000))
        now[0] = .5
        guard._tick()
        assert output.value == 0
        guard._buffer(Buffer(60000))
        now[0] += .05
        guard._tick()
        guard.set_volume(.8)
        now[0] += .03
        guard._tick()
        assert .3 < output.value < .5
        now[0] += .05
        guard._tick()
        assert output.value == .8
        assert output.muted is True
        assert guard.target is None
    finally:
        guard.reset()


def test_new_seek_invalidates_old_target_and_paused_seek_stays_paused():
    app = QApplication.instance() or QApplication([])
    now = [0.0]
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, clock=lambda: now[0], pcm_factory=Pcm)
    try:
        guard.begin(60000)
        guard.observe()
        player.setPosition(60000)
        guard._buffer(Buffer(60000))
        old_generation = guard.generation
        guard.begin(10000)
        guard.observe()
        player.setPosition(10000)
        guard._buffer(Buffer(60000))
        now[0] = .5
        guard._tick()
        assert output.value == 0
        player.state = QMediaPlayer.PlaybackState.PausedState
        guard._tick()
        now[0] += 2
        guard._tick()
        assert output.value == 0
        guard._buffer(Buffer(10000), old_generation)
        guard._tick()
        assert not guard.fresh and output.value == 0
        player.state = QMediaPlayer.PlaybackState.PlayingState
        guard._buffer(Buffer(10000), guard.generation)
        now[0] += .05
        guard._tick()
        now[0] += .1
        guard._tick()
        assert output.value == .6
        assert player.state == QMediaPlayer.PlaybackState.PlayingState
        assert player.positions == [60000, 10000]
    finally:
        guard.reset()


def test_switch_and_stop_never_restore_volume_from_previous_generation():
    app = QApplication.instance() or QApplication([])
    now = [0.0]
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, clock=lambda: now[0], pcm_factory=Pcm)
    original_buffer_output = guard.buffers
    try:
        guard.begin(20000)
        guard.observe()
        old_generation = guard.generation
        guard._buffer(Buffer(20000), old_generation)
        guard.begin(0)
        guard.observe()
        assert guard.buffers is original_buffer_output
        guard._buffer(Buffer(0), old_generation)
        now[0] += 5
        guard._tick()
        assert not guard.fresh and output.value == 0
        guard.reset()
        assert guard.volume == .6
        assert output.value == 0
        assert output.muted is True
    finally:
        guard.reset()


def test_buffer_listener_starting_new_transition_cannot_unmute_from_old_packet():
    app = QApplication.instance() or QApplication([])
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, pcm_factory=Pcm)
    try:
        guard.begin(0)
        guard.observe()
        generation = guard.generation
        guard.audio_buffer_received.connect(lambda buffer: guard.begin(0))
        guard._buffer(Buffer(0), generation)
        assert not guard.fresh
        assert output.value == 0
    finally:
        guard.reset()


def test_decoded_audio_uses_only_owned_pcm_output_and_rejects_paused_frames():
    app = QApplication.instance() or QApplication([])
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, pcm_factory=Pcm)
    try:
        assert player.native_output is None
        guard.begin(3000)
        guard.observe()
        guard._buffer(Buffer(3000), guard.generation)
        assert len(guard.pcm.frames) == 1
        player.state = QMediaPlayer.PlaybackState.PausedState
        guard._buffer(Buffer(3020), guard.generation)
        assert len(guard.pcm.frames) == 1
    finally:
        guard.close()
