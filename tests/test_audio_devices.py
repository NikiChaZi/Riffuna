from PySide6.QtCore import QObject, Signal

from musicdesk.audio_devices import AudioRouting
from musicdesk.storage import Library


class Device:
    def __init__(self, name):
        self.name = name
    def id(self):
        return self.name.encode()
    def description(self):
        return self.name


class Provider(QObject):
    audioOutputsChanged = Signal()
    def __init__(self):
        super().__init__()
        self.devices = [Device("speakers"), Device("headphones")]
        self.default = self.devices[0]
    def audioOutputs(self):
        return self.devices
    def defaultAudioOutput(self):
        return self.default


class Output:
    def setDevice(self, device):
        self.device = device


def test_selection_persists_and_system_default_is_followed(tmp_path):
    lib = Library(tmp_path / "test.sqlite3")
    provider, output = Provider(), Output()
    route = AudioRouting(output, lib, provider=provider)
    assert output.device.description() == "speakers"
    provider.default = provider.devices[1]
    provider.audioOutputsChanged.emit()
    assert output.device.description() == "headphones"
    speakers = route.device_id(provider.devices[0])
    assert route.select(speakers)
    provider.audioOutputsChanged.emit()
    assert output.device.description() == "speakers"
    restored = AudioRouting(Output(), lib, provider=provider)
    assert restored.selected_id == speakers
    assert restored.output.device.description() == "speakers"
    assert restored.select("")
    assert restored.output.device.description() == "headphones"
    lib.close()


def test_disconnect_falls_back_and_reconnect_restores_preference(tmp_path):
    lib = Library(tmp_path / "test.sqlite3")
    provider, output = Provider(), Output()
    route = AudioRouting(output, lib, provider=provider)
    headphones = provider.devices[1]
    wanted = route.device_id(headphones)
    assert route.select(wanted)
    provider.devices = provider.devices[:1]
    provider.audioOutputsChanged.emit()
    assert output.device.description() == "speakers"
    assert route.selected_id == ""
    assert lib.get_setting("audio_output", "") == wanted
    provider.devices.append(headphones)
    provider.audioOutputsChanged.emit()
    assert output.device.description() == "headphones"
    assert route.selected_id == wanted
    assert not route.select("missing-device")
    assert route.selected_id == wanted
    assert route.choices()[0][0] == ""
    lib.close()
