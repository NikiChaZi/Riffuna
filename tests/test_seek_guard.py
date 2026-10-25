import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

from musicdesk.seek_guard import SeekAudioGuard


class Player:
    def __init__(self):
        self.positions = []
        self.position_value = 0
        self.state = QMediaPlayer.PlaybackState.PlayingState
        self.status = QMediaPlayer.MediaStatus.BufferingMedia

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


def test_seek_silences_old_packets_and_restores_latest_volume_smoothly():
    app = QApplication.instance() or QApplication([])
    now = [0.0]
    player, output = Player(), Output()
    guard = SeekAudioGuard(player, output, clock=lambda: now[0])
    try:
        guard.seek(60000)
        assert output.value == 0
        guard._buffer(Buffer(2000))
        now[0] = .5
        guard._tick()
        assert output.value == 0
        guard._buffer(Buffer(60000))
        guard._tick()
        guard.set_volume(.8)
        now[0] += .04
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
    guard = SeekAudioGuard(player, output, clock=lambda: now[0])
    try:
        guard.seek(60000)
        guard._buffer(Buffer(60000))
        guard.seek(10000)
        guard._buffer(Buffer(60000))
        now[0] = .5
        guard._tick()
        assert output.value == 0
        player.state = QMediaPlayer.PlaybackState.PausedState
        guard._tick()
        now[0] += .1
        guard._tick()
        assert output.value == .6
        assert player.state == QMediaPlayer.PlaybackState.PausedState
        assert player.positions == [60000, 10000]
    finally:
        guard.reset()
