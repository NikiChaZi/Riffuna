"""Persistent output selection with automatic handling of device changes."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QMediaDevices


class AudioRouting(QObject):
    changed = Signal()

    def __init__(self, output, library, parent=None, provider=None):
        super().__init__(parent)
        self.output = output
        self.library = library
        self.provider = provider if provider is not None else QMediaDevices(self)
        self._preferred = library.get_setting("audio_output", "")
        self.provider.audioOutputsChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def device_id(device):
        return bytes(device.id()).hex()

    @property
    def selected_id(self):
        return self._preferred if any(self.device_id(d) == self._preferred
                                      for d in self.provider.audioOutputs()) else ""

    def choices(self):
        default = self.provider.defaultAudioOutput()
        return [("", "Системный выход — " + (default.description() or "нет устройства"))] + [
            (self.device_id(device), device.description()) for device in self.provider.audioOutputs()]

    def select(self, device_id):
        if device_id and not any(self.device_id(d) == device_id for d in self.provider.audioOutputs()):
            return False
        self._preferred = device_id
        self.library.set_setting("audio_output", device_id)
        self.refresh()
        return True

    def refresh(self):
        device = next((d for d in self.provider.audioOutputs()
                       if self.device_id(d) == self._preferred), self.provider.defaultAudioOutput())
        self.output.setDevice(device)
        self.changed.emit()
