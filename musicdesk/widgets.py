from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QStyleOptionSlider, QToolTip, QSizePolicy, QVBoxLayout, QWidget

from .icons import icon
from .models import Track, time_label


def label(text: str, name: str = "", parent=None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def icon_button(name: str, tooltip: str, size: int = 36, parent=None) -> QPushButton:
    button = QPushButton(parent)
    button.setObjectName("iconButton")
    button.setFixedSize(size, size)
    button.setIcon(icon(name))
    button.setIconSize(QSize(19, 19))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class PointerSlider(QSlider):
    """Absolute pointer input, hover preview and one commit per user gesture."""

    committed = Signal(int)

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None, *, formatter=str):
        super().__init__(orientation, parent)
        self.formatter = formatter
        self._pointer_down = False
        self._drag_offset = 0
        self.setMouseTracking(True)

    def _geometry(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                      QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                      QStyle.SubControl.SC_SliderHandle, self)
        return option, groove, handle

    def value_at(self, position, *, drag=False):
        option, groove, handle = self._geometry()
        horizontal = self.orientation() == Qt.Orientation.Horizontal
        start = groove.x() if horizontal else groove.y()
        length = handle.width() if horizontal else handle.height()
        span = (groove.width() if horizontal else groove.height()) - length
        coordinate = position.x() if horizontal else position.y()
        offset = self._drag_offset if drag else 0
        pixel = round(coordinate - offset - start - length / 2)
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                             pixel, max(0, span), option.upsideDown)

    def _preview(self, position, global_position):
        text = self.formatter(self.value_at(position))
        QToolTip.showText(global_position, text, self)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        _, _, handle = self._geometry()
        point = event.position().toPoint()
        horizontal = self.orientation() == Qt.Orientation.Horizontal
        self._drag_offset = ((point.x() - handle.center().x()) if horizontal
                             else (point.y() - handle.center().y())) if handle.contains(point) else 0
        self._pointer_down = True
        self.setSliderDown(True)
        self.setSliderPosition(self.value_at(event.position(), drag=True))
        self._preview(event.position(), event.globalPosition().toPoint())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._pointer_down:
            self.setSliderPosition(self.value_at(event.position(), drag=True))
        self._preview(event.position(), event.globalPosition().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pointer_down:
            self.setSliderPosition(self.value_at(event.position(), drag=True))
            self._pointer_down = False
            self.setSliderDown(False)
            self.committed.emit(self.value())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        before = self.value()
        super().keyPressEvent(event)
        if self.value() != before:
            self.committed.emit(self.value())

    def wheelEvent(self, event):
        before = self.value()
        super().wheelEvent(event)
        if self.value() != before:
            self.committed.emit(self.value())

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            self._preview(event.pos(), event.globalPos())
            event.accept()
            return True
        return super().event(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class SortComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        icon("chevron_down", "#B2B8AF", 16).paint(painter, self.width() - 24,
                                                 (self.height() - 16) // 2, 16, 16)


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", name: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        if name:
            self.setObjectName(name)
        self.set_full_text(text)

    def set_full_text(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(20, self.width())))

    def resizeEvent(self, event):
        self._elide()
        super().resizeEvent(event)


class Artwork(QObject):
    loaded = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.cache: dict[str, QPixmap] = {}
        self.pending: set[str] = set()

    def fetch(self, url: str):
        if not url or url in self.pending or url in self.cache:
            return
        host = (urlparse(url).hostname or "").lower()
        if not url.startswith("https://") or not any(host == domain or host.endswith("." + domain) for domain in ("ytimg.com", "googleusercontent.com", "ggpht.com")):
            return
        self.pending.add(url)
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(10000)
        reply = self.network.get(request)
        reply.finished.connect(lambda: self._finished(url, reply))

    def _finished(self, url: str, reply: QNetworkReply):
        self.pending.discard(url)
        if reply.error() == QNetworkReply.NetworkError.NoError:
            payload = reply.read(4 * 1024 * 1024)
            pixmap = QPixmap()
            if pixmap.loadFromData(payload):
                if len(self.cache) >= 200:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[url] = pixmap
                self.loaded.emit(url, pixmap)
        reply.deleteLater()


class Cover(QWidget):
    def __init__(self, artwork: Artwork, size: int = 48, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.artwork = artwork
        self.url = ""
        self.pixmap = QPixmap()
        artwork.loaded.connect(self._loaded)

    def set_url(self, url: str):
        self.url = url
        self.pixmap = self.artwork.cache.get(url, QPixmap())
        self.artwork.fetch(url)
        self.update()

    def _loaded(self, url: str, pixmap: QPixmap):
        if url == self.url:
            self.pixmap = pixmap
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#343D31"))
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            icon("wave", "#B5C1A9", 25).paint(painter, (self.width() - 25) // 2, (self.height() - 25) // 2, 25, 25)


class TrackRow(QFrame):
    play_requested = Signal(object)
    like_requested = Signal(object)
    add_requested = Signal(object)
    hovered = Signal(object)

    def __init__(self, track: Track, artwork: Artwork, liked: bool, parent=None):
        super().__init__(parent)
        self.track = track
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._hover_timer.setInterval(300)
        self._hover_timer.timeout.connect(lambda: self.hovered.emit(self.track))
        self.setObjectName("trackRow")
        self.setProperty("current", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(12)
        self.play_button = icon_button("play", "Слушать: " + track.title, 32)
        self.play_button.clicked.connect(lambda: self.play_requested.emit(track))
        layout.addWidget(self.play_button)
        cover = Cover(artwork, 48)
        cover.set_url(track.thumbnail)
        layout.addWidget(cover)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(ElidedLabel(track.title, "trackTitle"))
        metadata = track.artist + " · YouTube"
        if track.view_count is not None and track.view_count >= 0:
            views = f"{track.view_count:,}".replace(",", "\u202f")
            metadata += f" · Просмотры: {views}"
        self.metadata = ElidedLabel(metadata, "muted")
        texts.addWidget(self.metadata)
        layout.addLayout(texts, 1)
        if track.version:
            layout.addWidget(label(track.version, "badge"))
        duration = label(time_label(track.duration) if track.duration else "—", "muted")
        duration.setFixedWidth(47)
        duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(duration)
        self.like_button = icon_button("heart", "Нравится: " + track.title)
        self.like_button.clicked.connect(lambda: self.like_requested.emit(track))
        self.set_liked(liked)
        layout.addWidget(self.like_button)
        add = icon_button("plus", "В очередь: " + track.title)
        add.clicked.connect(lambda: self.add_requested.emit(track))
        layout.addWidget(add)

    def enterEvent(self, event):
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.stop()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hover_timer.stop()
        super().hideEvent(event)

    def set_liked(self, liked: bool):
        self.like_button.setIcon(icon("heart_fill" if liked else "heart", "#FF875F" if liked else "#B2B8AF"))
        self.like_button.setAccessibleName(("Убрать лайк: " if liked else "Нравится: ") + self.track.title)

    def set_current(self, current: bool):
        self.setProperty("current", current)
        self.play_button.setIcon(icon("wave" if current else "play", "#FF875F" if current else "#B2B8AF"))
        self.style().unpolish(self)
        self.style().polish(self)


class QueueRow(QFrame):
    play_requested = Signal(object)
    remove_requested = Signal(int)

    def __init__(self, track: Track, index: int, current: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("trackRow")
        self.setProperty("current", current)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 7, 4, 7)
        layout.setSpacing(7)
        play = icon_button("wave" if current else "play", "Слушать: " + track.title, 28)
        play.setIcon(icon("wave" if current else "play", "#FF875F" if current else "#B2B8AF"))
        play.clicked.connect(lambda: self.play_requested.emit(track))
        layout.addWidget(play)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(ElidedLabel(track.title, "trackTitle"))
        texts.addWidget(ElidedLabel(track.artist, "tiny"))
        layout.addLayout(texts, 1)
        remove = icon_button("close", "Убрать из очереди: " + track.title, 28)
        remove.clicked.connect(lambda: self.remove_requested.emit(index))
        layout.addWidget(remove)
