from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .widgets import SortComboBox
from .icons import icon
from .surface_motion import attach_surface_motion


class ListTools(QWidget):
    """Local list controls; emits intent and never mutates tracks or storage.

    The owner filters/sorts the full list and resolves selected records by ID.
    Search results retain server-side controls and only expose selection actions.
    """

    query_changed = Signal(str)
    sort_changed = Signal(str)
    queue_requested = Signal()
    playlist_requested = Signal()
    remove_requested = Signal()

    _CONTEXTS = frozenset({'search', 'likes', 'history', 'playlist', 'queue'})

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('listTools')
        self._context = 'history'
        self._selection_count = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.filter_row = QWidget(self)
        filters = QHBoxLayout(self.filter_row)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self.search_input = QLineEdit(self.filter_row)
        self.search_input.setObjectName('collectionFilter')
        self.search_input.setAccessibleName('Поиск в текущем списке')
        self.search_input.setPlaceholderText('Найти в списке')
        self.search_input.setToolTip('Искать по названию и исполнителю в этом списке')
        self.search_input.addAction(icon("search", "#8D98A1", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaxLength(500)
        self.search_input.setMinimumWidth(100)
        self.search_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_input.textChanged.connect(self.query_changed)
        filters.addWidget(self.search_input, 1)
        self.sort_order = SortComboBox(self.filter_row)
        self.sort_order.setObjectName('collectionOrder')
        self.sort_order.setAccessibleName('Сортировка текущего списка')
        for text, key in [('Порядок библиотеки', 'custom'), ('По названию', 'title'),
                          ('По исполнителю', 'artist'), ('По длительности', 'duration'),
                          ('Сначала новые', 'recent')]:
            self.sort_order.addItem(text, key)
        self.sort_order.setMinimumWidth(160)
        self.sort_order.currentIndexChanged.connect(
            lambda _index: self.sort_changed.emit(self.sort_order.currentData()))
        filters.addWidget(self.sort_order)
        outer.addWidget(self.filter_row)

        self.actions_row = QWidget(self)
        self.actions_row.setObjectName("batchActions")
        self.actions_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        actions = QHBoxLayout(self.actions_row)
        actions.setContentsMargins(10, 4, 8, 4)
        actions.setSpacing(6)
        self.selection_label = QLabel('Выбрано: 0', self.actions_row)
        self.selection_label.setObjectName('selectionCount')
        self.selection_label.setAccessibleName('Количество выбранных треков')
        actions.addWidget(self.selection_label)
        self.queue_button = QPushButton('В очередь', self.actions_row)
        self.queue_button.setAccessibleName('Добавить выбранные треки в очередь')
        self.queue_button.clicked.connect(self.queue_requested)
        actions.addWidget(self.queue_button)
        self.playlist_button = QPushButton('В плейлист', self.actions_row)
        self.playlist_button.setAccessibleName('Добавить выбранные треки в плейлист')
        self.playlist_button.clicked.connect(self.playlist_requested)
        actions.addWidget(self.playlist_button)
        self.remove_button = QPushButton('Убрать', self.actions_row)
        self.remove_button.clicked.connect(self.remove_requested)
        actions.addWidget(self.remove_button)
        for button, glyph in ((self.queue_button, 'queue'), (self.playlist_button, 'playlist'), (self.remove_button, 'close')):
            button.setObjectName('batchAction')
            button.setIcon(icon(glyph, '#D9C4B8', 16))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            attach_surface_motion(button)
        actions.addStretch(1)
        outer.addWidget(self.actions_row)
        self.selection_hint = QLabel('Ctrl / Shift — выбрать треки', self)
        self.selection_hint.setObjectName('muted')
        self.selection_hint.setWordWrap(True)
        outer.addWidget(self.selection_hint)
        self.set_context('history')

    @property
    def query(self) -> str:
        return self.search_input.text()

    @property
    def order(self) -> str:
        return self.sort_order.currentData()

    def set_context(self, context: str):
        if context not in self._CONTEXTS:
            raise ValueError(f'Unknown list context: {context}')
        self._context = context
        self.filter_row.setVisible(context != 'search')
        custom_label = 'Порядок плейлиста' if context == 'playlist' else (
            'Порядок очереди' if context == 'queue' else 'Порядок библиотеки')
        with QSignalBlocker(self.sort_order):
            self.sort_order.setItemText(self.sort_order.findData('custom'), custom_label)
            recent_index = self.sort_order.findData('recent')
            if context in {'playlist', 'queue'}:
                if recent_index >= 0:
                    self.sort_order.removeItem(recent_index)
            elif recent_index < 0:
                self.sort_order.addItem('Сначала новые', 'recent')
        remove_labels = {
            'likes': 'Убрать лайки', 'playlist': 'Из плейлиста', 'queue': 'Из очереди',
        }
        self.remove_button.setVisible(context in remove_labels)
        self.remove_button.setText(remove_labels.get(context, 'Убрать'))
        self.remove_button.setAccessibleName({
            'likes': 'Убрать лайки у выбранных треков',
            'playlist': 'Убрать выбранные треки из плейлиста',
            'queue': 'Убрать выбранные треки из очереди',
        }.get(context, 'Убрать выбранные треки'))
        self.queue_button.setVisible(context != 'queue')
        self.set_selection_count(0)

    def set_selection_count(self, count: int):
        self._selection_count = max(0, int(count))
        active = self._selection_count > 0
        self.selection_label.setText(f'Выбрано: {self._selection_count}')
        for button in (self.queue_button, self.playlist_button, self.remove_button):
            button.setEnabled(active)
        self.actions_row.setVisible(active)
        self.selection_hint.setVisible(not active)

    def reset(self, query: str = '', order: str = 'custom'):
        """Set a view's controls without emitting intermediate filter requests."""
        index = self.sort_order.findData(order)
        if index < 0:
            raise ValueError(f'Unknown list order: {order}')
        with QSignalBlocker(self.search_input), QSignalBlocker(self.sort_order):
            self.search_input.setText(query)
            self.sort_order.setCurrentIndex(index)
        self.set_selection_count(0)

    def focus_search(self):
        if self._context != 'search':
            self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_input.selectAll()
