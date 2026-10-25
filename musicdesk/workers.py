import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)


class TaskSignals(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)


class Task(QRunnable):
    def __init__(self, token: str, function: Callable):
        super().__init__()
        self.token = token
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            log.exception("Background task failed")
            self.signals.failed.emit(self.token, str(exc))
        else:
            self.signals.finished.emit(self.token, result)
