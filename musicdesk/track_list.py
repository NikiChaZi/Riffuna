from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QListWidget


def moved_order(order, selected, boundary):
    """Move a selection before a boundary in the original list, preserving order."""
    chosen = set(selected)
    moving = [key for key in order if key in chosen]
    if not moving:
        return list(order)
    boundary = max(0, min(int(boundary), len(order)))
    insertion = sum(key not in chosen for key in order[:boundary])
    rest = [key for key in order if key not in chosen]
    return rest[:insertion] + moving + rest[insertion:]


class TrackList(QListWidget):
    """Reorder by IDs; never let Qt move item widgets independently of storage."""
    order_requested = Signal(object)
    toggle_requested = Signal()
    MIME = 'application/x-riffuna-track-order'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manual_order = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.set_manual_order(False)
        self.itemSelectionChanged.connect(self._selection_surfaces)

    def _selection_surfaces(self):
        # The row widget paints above the item; mirror selection for contrast.
        for index in range(self.count()):
            item = self.item(index)
            row = self.itemWidget(item)
            if row is not None and row.property('selected') != item.isSelected():
                row.setProperty('selected', item.isSelected())
                row.style().unpolish(row)
                row.style().polish(row)
                row.update()

    def set_manual_order(self, enabled):
        self._manual_order = bool(enabled)
        self.setDragEnabled(self._manual_order)
        self.setAcceptDrops(self._manual_order)
        self.viewport().setAcceptDrops(self._manual_order)

    def ids(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole).video_id for i in range(self.count())]

    def startDrag(self, supported_actions):
        if not self._manual_order:
            return
        selected = [item.data(Qt.ItemDataRole.UserRole).video_id for item in self.selectedItems()]
        if not selected:
            return
        mime = self.mimeData(self.selectedItems())
        mime.setData(self.MIME, QByteArray(json.dumps(selected).encode('utf-8')))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def _accepts(self, event):
        return self._manual_order and event.source() is self and event.mimeData().hasFormat(self.MIME)

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
            # Keep native autoscroll while rejecting its item-model mutation.
            super().dragMoveEvent(event)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self._accepts(event):
            event.ignore()
            return
        try:
            selected = json.loads(bytes(event.mimeData().data(self.MIME)))
        except (ValueError, TypeError):
            event.ignore()
            return
        order = self.ids()
        if not isinstance(selected, list) or not all(isinstance(key, str) and key in order for key in selected):
            event.ignore()
            return
        point = event.position().toPoint()
        target = self.itemAt(point)
        boundary = self.row(target) if target else len(order)
        if target and point.y() > self.visualItemRect(target).center().y():
            boundary += 1
        result = moved_order(order, selected, boundary)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if result != order:
            self.order_requested.emit(result)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not event.isAutoRepeat():
                self.toggle_requested.emit()
            event.accept()
            return
        if self._manual_order and event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            rows = sorted(self.row(item) for item in self.selectedItems())
            if rows:
                boundary = rows[0] - 1 if event.key() == Qt.Key.Key_Up else rows[-1] + 2
                order = self.ids()
                selected = [order[row] for row in rows]
                result = moved_order(order, selected, boundary)
                if result != order:
                    self.order_requested.emit(result)
            event.accept()
            return
        super().keyPressEvent(event)
