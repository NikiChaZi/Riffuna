"""Non-modal, single-use picker for explicitly selected recording alternatives."""
from __future__ import annotations

import uuid

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
)
from shiboken6 import isValid

from .models import Track, time_label
from .recording_versions import RecordingVersion, VersionFinder
from .workers import Task


_STYLE = """
QDialog#recordingVersionsDialog { background: #111615; }
QLabel#versionsHeading { font-size: 22px; font-weight: 650; }
QLabel#versionRowTitle { font-size: 14px; font-weight: 600; }
QLabel#versionRowLabel { color: #E8C69B; font-size: 11px; font-weight: 600; }
QLabel#versionRowEvidence { color: #AFBAAF; font-size: 12px; }
QLabel#versionRowAssurance { color: #C6B99F; font-size: 11px; }
QListWidget#versionsList { border: 1px solid #344336; border-radius: 8px; }
QListWidget#versionsList::item { margin: 3px; }
QListWidget#versionsList::item:selected { background: #2D3B2D; }
QProgressBar#versionsBusy { background: #29332C; border: none; border-radius: 2px; }
QProgressBar#versionsBusy::chunk { background: #FF875F; }
"""


def _text(value: str, name: str = "") -> QLabel:
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


class _VersionList(QListWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class _VersionRow(QFrame):
    def __init__(self, version: RecordingVersion, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(5)
        top = QHBoxLayout()
        self.version_label = _text(version.label, "versionRowLabel")
        top.addWidget(self.version_label, 1)
        self.duration_label = _text(time_label(version.track.duration), "tiny")
        self.duration_label.setWordWrap(False)
        top.addWidget(self.duration_label)
        root.addLayout(top)
        self.title = _text(version.track.title, "versionRowTitle")
        self.artist = _text(version.track.artist, "muted")
        self.evidence = _text(version.evidence, "versionRowEvidence")
        self.assurance = _text(
            "Отсутствие цензуры не проверено" if not version.verified_uncensored
            else "Сведения о подтверждении — в описании версии",
            "versionRowAssurance",
        )
        for label in (self.title, self.artist, self.evidence, self.assurance):
            root.addWidget(label)

    def row_height(self, width: int) -> int:
        return max(142, self.layout().totalHeightForWidth(width))


class RecordingVersionsDialog(QDialog):
    """open() starts one request; explicit retry never overlaps a running job.

    The shared pool means closing/deleting a dialog never waits for its network
    request. Worker closures retain only the finder and immutable original track.
    Closed dialogs are single-use: create another instance for a new session.
    """

    selected = Signal(object, object)

    def __init__(self, track: Track, source, parent=None):
        super().__init__(parent)
        self.track = track
        self.finder = VersionFinder(source)
        self.pool = QThreadPool.globalInstance()
        self.state = "idle"
        self._started = False
        self._running = False
        self._closed = False
        self._selection_emitted = False
        self._active_token = ""
        self._task = None
        self._resizing = False
        self.setObjectName("recordingVersionsDialog")
        self.setWindowTitle("Другие записи · Riffuna")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setStyleSheet(_STYLE)
        self.resize(760, 650)
        self.setMinimumSize(540, 430)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addWidget(_text("Другие записи", "versionsHeading"))
        self.reference = _text(f"{self.track.artist} — {self.track.title} · {time_label(self.track.duration)}", "muted")
        root.addWidget(self.reference)
        self.notice = _text(
            "Название записи не подтверждает отсутствие цензуры. "
            "Автоматической проверки содержимого нет — выбери и прослушай подходящую загрузку.", "notice")
        root.addWidget(self.notice)
        self.status = _text("Поиск ещё не запущен", "sectionTitle")
        root.addWidget(self.status)
        self.busy = QProgressBar()
        self.busy.setObjectName("versionsBusy")
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(4)
        self.busy.hide()
        root.addWidget(self.busy)
        self.details = _text("", "muted")
        root.addWidget(self.details)
        self.results = _VersionList()
        self.results.setObjectName("versionsList")
        self.results.setAccessibleName("Другие записи выбранной композиции")
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setUniformItemSizes(False)
        self.results.currentItemChanged.connect(self._selection_changed)
        self.results.itemDoubleClicked.connect(self._double_clicked)
        self.results.resized.connect(self._resize_rows)
        self.results.hide()
        root.addWidget(self.results, 1)
        buttons = QHBoxLayout()
        self.retry_button = QPushButton("Повторить поиск")
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._start)
        self.retry_button.hide()
        buttons.addWidget(self.retry_button)
        buttons.addStretch()
        self.close_button = QPushButton("Закрыть")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.listen_button = QPushButton("Слушать")
        self.listen_button.setObjectName("primary")
        self.listen_button.setAutoDefault(False)
        self.listen_button.setDefault(False)
        self.listen_button.setEnabled(False)
        self.listen_button.clicked.connect(self._choose_current)
        buttons.addWidget(self.listen_button)
        root.addLayout(buttons)

    @Slot()
    def open(self):
        if self._closed:
            return
        # QDialog.open() makes the window modal, so deliberately use show().
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.show()
        self.raise_()
        if not self._started:
            self._started = True
            self._start()

    @Slot()
    def _start(self):
        if self._closed or self._running:
            return
        self._running = True
        self.state = "loading"
        self._active_token = uuid.uuid4().hex
        self.results.clear()
        self.results.hide()
        self.listen_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.retry_button.hide()
        self.status.setText("Ищем другие записи…")
        self.details.setText("Поиск идёт в фоне. Можно продолжать слушать музыку или закрыть этот диалог.")
        self.busy.show()
        finder, original = self.finder, self.track
        task = Task(self._active_token, lambda: finder.find(original, limit=12))
        task.signals.finished.connect(self._found, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self._task = task
        self.pool.start(task)

    def _finish(self, token: str) -> bool:
        if token != self._active_token:
            return False
        self._running = False
        self._task = None
        self._active_token = ""
        return not self._closed

    @Slot(str, object)
    def _found(self, token: str, payload):
        if not self._finish(token):
            return
        self.busy.hide()
        seen = {self.track.video_id}
        for version in payload or ():
            if not isinstance(version, RecordingVersion) or version.track.video_id in seen:
                continue
            seen.add(version.track.video_id)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, version)
            accessible = (f"{version.label}\n{version.track.artist} — {version.track.title}\n"
                          f"{time_label(version.track.duration)}\n{version.evidence}")
            item.setData(Qt.ItemDataRole.AccessibleTextRole, accessible)
            item.setToolTip(accessible)
            self.results.addItem(item)
            self.results.setItemWidget(item, _VersionRow(version))
        if not self.results.count():
            self.state = "empty"
            self.status.setText("Другие подходящие записи не найдены")
            self.details.setText("Название, исполнитель и длительность должны соответствовать выбранной композиции.")
            self.retry_button.setEnabled(True)
            self.retry_button.show()
            return
        self.state = "ready"
        self.status.setText(f"Найдено записей: {self.results.count()}")
        self.details.setText("Выбери запись и нажми «Слушать» или дважды нажми на неё в списке.")
        self.results.setCurrentRow(-1)
        self.results.show()
        self._resize_rows()
        # Giving focus to an empty-current QAbstractItemView selects row zero.
        # Keep the close action focused until the user enters the results.
        self.close_button.setFocus()
        self.results.setCurrentRow(-1)
        self.listen_button.setEnabled(False)

    @Slot(str, str)
    def _failed(self, token: str, _message: str):
        if not self._finish(token):
            return
        self.busy.hide()
        self.state = "error"
        self.status.setText("Не удалось найти другие записи")
        self.details.setText("Повтори попытку немного позже.")
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def _resize_rows(self):
        if self._resizing or self._closed:
            return
        self._resizing = True
        try:
            width = max(120, self.results.viewport().width() - 12)
            for index in range(self.results.count()):
                item = self.results.item(index)
                row = self.results.itemWidget(item)
                if row is not None:
                    item.setSizeHint(QSize(width, row.row_height(width)))
        finally:
            self._resizing = False

    def _selection_changed(self, current, previous):
        self.listen_button.setEnabled(not self._closed and self.state == "ready" and current is not None)

    @Slot()
    def _choose_current(self):
        self._choose(self.results.currentItem())

    def _double_clicked(self, item):
        self._choose(item)

    def _choose(self, item):
        if self._closed or self._selection_emitted or self.state != "ready" or item is None:
            return
        version = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(version, RecordingVersion) or version.track.video_id == self.track.video_id:
            return
        self._selection_emitted = True
        self.listen_button.setEnabled(False)
        self.selected.emit(self.track, version.track)
        if isValid(self) and not self._closed:
            self.accept()

    def done(self, result: int):
        self._invalidate()
        super().done(result)

    def closeEvent(self, event):
        self._invalidate()
        super().closeEvent(event)

    def _invalidate(self):
        self._closed = True
        self.state = "closed"
        self.listen_button.setEnabled(False)
        self.retry_button.setEnabled(False)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if focused in (self.listen_button, self.retry_button, self.close_button) and focused.isEnabled():
                focused.click()
            event.accept()
            return
        super().keyPressEvent(event)
