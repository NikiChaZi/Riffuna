"""Standalone desktop now-playing surface. No audio engine, network or storage."""
from __future__ import annotations

import uuid
import weakref

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QSignalBlocker, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSlider, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from .icons import icon
from .lyrics_view import LyricsDocument, LyricsPane, LyricsState, document_from_payload
from .models import Track, time_label
from .motion import MotionPolicy, Tween
from .widgets import Cover, ElidedLabel, PointerSlider, icon_button, label


EXPANDED_STYLE = """
QWidget#expandedPlayer { background: #101214; }
QFrame#lyricsPane { background: #15181B; border: 1px solid #282D31; border-radius: 20px; }
QLabel#npTitle { font-size: 31px; font-weight: 700; letter-spacing: -1px; }
QLabel#npArtist { color: #A7ACB0; font-size: 17px; }
QStackedWidget#lyricsStack { background: transparent; }
QLabel#lyricsMessage { font-size: 26px; font-weight: 650; }
QPushButton#npPlay { background: #FF875F; color: #151A19; border: none; border-radius: 26px; padding: 0; }
QPushButton#npPlay:hover { background: #FFA080; }
QPushButton#npPlay:disabled { background: #70503F; }
QPushButton#motionToggle { background: transparent; color: #A0A7AC; border-color: transparent; font-size: 12px; padding: 7px 10px; }
QPushButton#motionToggle:hover { color: #F4F1E8; background: #20252A; }
QPushButton#motionToggle:checked { background: #2D3237; color: #F4F1E8; }
QFrame#focusTransport { background: #1B1F23; border: 1px solid #30363B; border-radius: 14px; }
QPushButton#lyricFocus { background: transparent; color: #BEC3C6; border-color: #343A40; font-size: 12px; padding: 7px 12px; }
QPushButton#lyricFocus:checked { color: #FFAD8E; background: #392B25; border-color: #704B3B; }
"""


def _draw_cover(painter, pixmap: QPixmap, rect: QRectF):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    radius = min(18.0, rect.width() * .08)
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)
    painter.fillRect(rect, QColor("#31443A"))
    if not pixmap.isNull():
        side = min(pixmap.width(), pixmap.height())
        source = QRectF((pixmap.width() - side) / 2, (pixmap.height() - side) / 2, side, side)
        painter.drawPixmap(rect, pixmap, source)
    else:
        size = max(20, round(rect.width() * .26))
        icon("note", "#C6D5BE", size).paint(painter, round(rect.center().x() - size / 2),
                                           round(rect.center().y() - size / 2), size, size)
    painter.restore()


class ArtworkSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.suppress_paint = False
        self.setFixedSize(300, 300)
        self.setAccessibleName("Обложка выбранной записи")

    def set_pixmap(self, pixmap: QPixmap):
        self.pixmap = QPixmap(pixmap)
        self.update()

    def paintEvent(self, event):
        if not self.suppress_paint:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _draw_cover(painter, self.pixmap, QRectF(self.rect()))


class ExpandableCover(Cover):
    """Drop-in small Cover with keyboard/click activation; artwork behavior intact."""
    activated = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Открыть большой плеер")
        self.setToolTip("Открыть большой плеер · Enter")

    def mousePressEvent(self, event):
        self._pressed = event.button() == Qt.MouseButton.LeftButton
        if self._pressed:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, False
        if pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            painter.setPen(QColor("#FF875F"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 6, 6)


class _CoverFlight(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pixmap = QPixmap()
        self.destination = QRectF()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw_cover(painter, self.pixmap, self.destination)


class ExpandedPlayer(QWidget):
    opened = Signal()
    closed = Signal()
    toggle_requested = Signal()
    previous_requested = Signal()
    next_requested = Signal()
    repeat_requested = Signal()
    shuffle_requested = Signal()
    seek_requested = Signal(int)
    volume_requested = Signal(int)
    like_requested = Signal(str)
    output_requested = Signal()
    queue_requested = Signal()
    version_requested = Signal(str)
    lyrics_requested = Signal(str, str)
    import_requested = Signal(str)

    def __init__(self, parent=None, *, policy: MotionPolicy | None = None):
        super().__init__(parent)
        self.setObjectName("expandedPlayer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(EXPANDED_STYLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.policy = policy or MotionPolicy(parent=self)
        self.track: Track | None = None
        self.request_token = ""
        self.position = 0
        self.duration = 0
        self.seekable = False
        self._desired_open = False
        self._lyrics_focus = False
        self._source_ref = None
        self._opened_notified = False
        self._build()
        self._fade = Tween(1.0, self.policy, self)
        self._fade.value_changed.connect(self.content_effect.setOpacity)
        self._travel = Tween(QRectF(), self.policy, self)
        self._travel.value_changed.connect(self._flight_frame)
        self._travel.settled.connect(self._finish_transition)
        self.policy.changed.connect(self._motion_changed)
        self._escape = QShortcut(QKeySequence("Escape"), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.activated.connect(self.collapse)
        self._focus_shortcut = QShortcut(QKeySequence("F2"), self)
        self._focus_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._focus_shortcut.activated.connect(lambda: self.focus_button.toggle())
        from .surface_motion import install_surface_motion
        install_surface_motion(self, self.policy)
        self.set_track(None)
        self.hide()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(20)
        header = QHBoxLayout()
        self.collapse_button = icon_button("chevron_down", "Свернуть плеер · Esc", 40)
        self.collapse_button.clicked.connect(self.collapse)
        header.addWidget(self.collapse_button)
        header.addWidget(label("СЕЙЧАС ИГРАЕТ", "eyebrow"), 1)
        self.focus_button = QPushButton("Фокус на тексте")
        self.focus_button.setObjectName("lyricFocus")
        self.focus_button.setCheckable(True)
        self.focus_button.setAccessibleName("Фокус на тексте песни")
        self.focus_button.setToolTip("Крупный текст и компактное управление · F2")
        self.focus_button.toggled.connect(self._set_lyrics_focus)
        header.addWidget(self.focus_button)
        self.motion_button = QPushButton("Меньше движения")
        self.motion_button.setObjectName("motionToggle")
        self.motion_button.setCheckable(True)
        self.motion_button.setChecked(self.policy.reduced)
        self.motion_button.toggled.connect(self.policy.set_reduced)
        header.addWidget(self.motion_button)
        self.queue_button = icon_button("queue", "Открыть очередь", 40)
        self.queue_button.clicked.connect(self.queue_requested)
        header.addWidget(self.queue_button)
        root.addLayout(header)
        self.content = QWidget()
        self.content_effect = QGraphicsOpacityEffect(self.content)
        self.content_effect.setOpacity(1.0)
        self.content.setGraphicsEffect(self.content_effect)
        body = QHBoxLayout(self.content)
        body.setContentsMargins(12, 0, 0, 0)
        body.setSpacing(36)
        self.left = QWidget()
        self.left.setMinimumWidth(340)
        self.left.setMaximumWidth(440)
        left = QVBoxLayout(self.left)
        left.setContentsMargins(4, 0, 4, 0)
        left.setSpacing(12)
        left.addStretch()
        self.cover = ArtworkSurface()
        left.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        left.addSpacing(4)
        title_row = QHBoxLayout()
        self.title = ElidedLabel("Выбери запись", "npTitle")
        title_row.addWidget(self.title, 1)
        self.like_button = icon_button("heart", "Мне нравится", 36)
        self.like_button.clicked.connect(lambda: self.like_requested.emit(self.track.video_id) if self.track else None)
        title_row.addWidget(self.like_button)
        left.addLayout(title_row)
        self.artist = ElidedLabel("", "npArtist")
        left.addWidget(self.artist)
        self.version_button = QPushButton("Другие записи")
        self.version_button.setToolTip("Выбрать другую загрузку этой песни")
        self.version_button.clicked.connect(lambda: self.version_requested.emit(self.track.video_id) if self.track else None)
        self.version_button.hide()
        left.addWidget(self.version_button, 0, Qt.AlignmentFlag.AlignLeft)
        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.elapsed = label("0:00", "tiny")
        self.elapsed.setMinimumWidth(36)
        progress.addWidget(self.elapsed)
        self.seek = PointerSlider(formatter=lambda value: time_label(value // 1000))
        self.seek.setAccessibleName("Позиция воспроизведения в большом плеере")
        self.seek.committed.connect(self.seek_requested)
        self.seek.sliderMoved.connect(lambda value: self.elapsed.setText(time_label(value // 1000)))
        progress.addWidget(self.seek, 1)
        self.total = label("—", "tiny")
        self.total.setMinimumWidth(36)
        progress.addWidget(self.total)
        left.addLayout(progress)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addStretch()
        self.shuffle_button = icon_button("shuffle", "Перемешать очередь", 36)
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.clicked.connect(self.shuffle_requested)
        controls.addWidget(self.shuffle_button)
        self.previous_button = icon_button("previous", "Предыдущая запись", 40)
        self.previous_button.clicked.connect(self.previous_requested)
        controls.addWidget(self.previous_button)
        self.play_button = icon_button("play", "Воспроизвести", 52)
        self.play_button.setObjectName("npPlay")
        self.play_button.clicked.connect(self.toggle_requested)
        controls.addWidget(self.play_button)
        self.next_button = icon_button("next", "Следующая запись", 40)
        self.next_button.clicked.connect(self.next_requested)
        controls.addWidget(self.next_button)
        self.repeat_button = icon_button("repeat", "Повтор выключен", 36)
        self.repeat_button.setCheckable(True)
        self.repeat_button.clicked.connect(self.repeat_requested)
        controls.addWidget(self.repeat_button)
        controls.addStretch()
        left.addLayout(controls)
        sound = QHBoxLayout()
        sound.setSpacing(8)
        self.status = label("Выбери запись", "tiny")
        sound.addWidget(self.status, 1)
        self.output_button = icon_button("volume", "Выбрать устройство вывода", 32)
        self.output_button.clicked.connect(self.output_requested)
        sound.addWidget(self.output_button)
        self.volume = PointerSlider(formatter=lambda value: f"{value}%")
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(88)
        self.volume.setAccessibleName("Громкость в большом плеере")
        self.volume.valueChanged.connect(self.volume_requested)
        sound.addWidget(self.volume)
        left.addLayout(sound)
        left.addStretch()
        body.addWidget(self.left, 4)
        self.lyrics = LyricsPane(self.policy)
        self.lyrics.retry_requested.connect(self.request_lyrics)
        self.lyrics.import_requested.connect(lambda: self.import_requested.emit(self.track.video_id) if self.track else None)
        self.lyrics.seek_requested.connect(self.seek_requested)
        body.addWidget(self.lyrics, 6)
        root.addWidget(self.content, 1)
        self.focus_transport = QFrame()
        self.focus_transport.setObjectName("focusTransport")
        transport = QHBoxLayout(self.focus_transport)
        transport.setContentsMargins(16,10,16,10)
        transport.setSpacing(12)
        self.focus_title = ElidedLabel("", "trackTitle")
        self.focus_title.setMaximumWidth(240)
        transport.addWidget(self.focus_title,1)
        self.focus_previous = icon_button("previous", "Предыдущая запись", 36)
        self.focus_previous.clicked.connect(self.previous_requested)
        transport.addWidget(self.focus_previous)
        self.focus_play = icon_button("play", "Воспроизвести", 40)
        self.focus_play.clicked.connect(self.toggle_requested)
        transport.addWidget(self.focus_play)
        self.focus_next = icon_button("next", "Следующая запись",36)
        self.focus_next.clicked.connect(self.next_requested)
        transport.addWidget(self.focus_next)
        self.focus_elapsed = label("0:00","tiny")
        transport.addWidget(self.focus_elapsed)
        self.focus_seek = PointerSlider(formatter=lambda value: time_label(value//1000))
        self.focus_seek.setAccessibleName("Позиция воспроизведения в режиме текста")
        self.focus_seek.committed.connect(self.seek_requested)
        transport.addWidget(self.focus_seek,2)
        self.focus_total = label("—","tiny")
        transport.addWidget(self.focus_total)
        self.focus_transport.hide()
        root.addWidget(self.focus_transport)
        self.flight = _CoverFlight(self)
        self.setTabOrder(self.collapse_button, self.motion_button)
        self.setTabOrder(self.motion_button, self.play_button)
        self.setTabOrder(self.play_button, self.seek)
        self.setTabOrder(self.seek, self.lyrics.canvas)

    def set_track(self, track: Track | None):
        previous_id = self.track.video_id if self.track else None
        self.track = track
        self.focus_title.set_full_text(track.title if track else "Выбери запись")
        self.focus_play.setEnabled(track is not None)
        self.focus_button.setEnabled(track is not None)
        self.title.set_full_text(track.title if track else "Выбери запись")
        self.artist.set_full_text(track.artist if track else "Музыка начинается с выбора")
        for control in (self.play_button, self.previous_button, self.next_button, self.like_button,
                        self.shuffle_button, self.repeat_button, self.volume, self.output_button):
            control.setEnabled(track is not None)
        self.lyrics.import_button.setEnabled(track is not None)
        self.lyrics.retry.setEnabled(track is not None)
        if (track.video_id if track else None) != previous_id or not self.request_token:
            self.position = 0
            self.set_liked(False)
            self.set_version_selection_available(False)
            self.elapsed.setText("0:00")
            self.cover.set_pixmap(QPixmap())
            self.flight.pixmap = QPixmap()
            self.set_duration(track.duration * 1000 if track else 0)
            self.set_seekable(False)
            self.lyrics.canvas.position = 0
            if track:
                self.request_lyrics()
            else:
                self.request_token = ""
                self.lyrics.set_document(LyricsDocument(LyricsState.NOTFOUND))
            if hasattr(self, "_travel") and self._travel.running:
                self._travel.finish()

    def request_lyrics(self):
        if self.track:
            self.request_token = uuid.uuid4().hex
            self.lyrics.set_document(LyricsDocument(LyricsState.LOADING))
            self.lyrics_requested.emit(self.track.video_id, self.request_token)

    def set_lyrics(self, recording_id: str, request_token: str, document: LyricsDocument) -> bool:
        if not self.track or recording_id != self.track.video_id or request_token != self.request_token:
            return False
        self.lyrics.set_document(document)
        self.lyrics.canvas.set_position(self.position, force=True)
        return True

    @Slot(str, object, result=bool)
    def apply_lyrics_payload(self, recording_id: str, payload: dict) -> bool:
        if not self.track or recording_id != self.track.video_id or payload.get("recording_id") != recording_id:
            return False
        try:
            document = document_from_payload(payload)
        except (ValueError, KeyError, TypeError):
            document = LyricsDocument(LyricsState.ERROR, text="Получены некорректные данные текста. Попробуй ещё раз.")
        accepted = self.set_lyrics(recording_id, self.request_token, document)
        if accepted and document.state == LyricsState.SYNCED and document.timing_confirmed:
            self.lyrics.footer.setText("Нажми на строку, чтобы перейти к ней" if any(cue.words for cue in document.cues)
                                       else "Подсветка слов по строкам · приблизительно")
        if accepted and payload.get("cache_stale"):
            self.lyrics.footer.setText("Сохранённый текст · сервис временно недоступен")
        return accepted

    def set_artwork(self, recording_id: str, pixmap: QPixmap):
        if self.track and recording_id == self.track.video_id:
            self.cover.set_pixmap(pixmap)
            self.flight.pixmap = QPixmap(pixmap)
            self.flight.update()

    @Slot("qlonglong")
    def set_position(self, milliseconds: int):
        self.position = max(0, int(milliseconds))
        if not self.focus_seek.isSliderDown():
            self.focus_seek.setValue(min(self.position,self.focus_seek.maximum()))
            self.focus_elapsed.setText(time_label(self.position//1000))
        if not self.seek.isSliderDown():
            self.seek.setValue(min(self.position, self.seek.maximum()))
            self.elapsed.setText(time_label(self.position // 1000))
        self.lyrics.canvas.set_position(self.position)

    def set_duration(self, milliseconds: int):
        self.duration = max(0, int(milliseconds))
        self.seek.setRange(0, min(self.duration, 2147483647))
        self.total.setText(time_label(self.duration // 1000) if self.duration else "—")
        self.focus_seek.setRange(0,min(self.duration,2147483647))
        self.focus_total.setText(self.total.text())
        self.focus_seek.setEnabled(self.seekable and self.duration>0)
        self.seek.setEnabled(self.seekable and self.duration > 0)

    def set_seekable(self, seekable: bool):
        self.seekable = bool(seekable)
        self.focus_seek.setEnabled(self.seekable and self.duration>0)
        self.seek.setEnabled(self.seekable and self.duration > 0)
        self.lyrics.canvas.seek_enabled = self.seekable

    def set_playback_state(self, state: str, *, wants_play: bool | None = None):
        playing = state == "playing" or (state == "loading" and wants_play is True)
        self.play_button.setIcon(icon("pause" if playing else "play", "#151A19", 28))
        self.play_button.setAccessibleName("Приостановить" if playing else "Воспроизвести")
        self.focus_play.setIcon(icon("pause" if playing else "play", "#FFAE8C", 24))
        self.focus_play.setAccessibleName("Приостановить" if playing else "Воспроизвести")
        self.status.setText({"playing": "Сейчас играет", "paused": "На паузе", "loading": "Подключаем запись…",
                             "error": "Запись недоступна", "stopped": "Готово к музыке"}.get(state, ""))
        self.lyrics.canvas.set_playing(state == "playing")
        if state == "error":
            self.set_seekable(False)

    def set_liked(self, liked: bool):
        self.like_button.setIcon(icon("heart_fill" if liked else "heart", "#FF875F" if liked else "#B2B8AF"))
        self.like_button.setAccessibleName("Убрать лайк" if liked else "Мне нравится")

    def set_repeat(self, mode: str):
        self.repeat_button.setChecked(mode != "off")
        self.repeat_button.setIcon(icon("repeat_one" if mode == "one" else "repeat", "#FF875F" if mode != "off" else "#B2B8AF"))
        title = {"off": "Повтор выключен", "one": "Повтор одной записи", "all": "Повтор всей очереди"}.get(mode, "Повтор")
        self.repeat_button.setAccessibleName(title)
        self.repeat_button.setToolTip(title)

    def set_shuffle(self, enabled: bool):
        self.shuffle_button.setChecked(enabled)
        self.shuffle_button.setIcon(icon("shuffle", "#FF875F" if enabled else "#B2B8AF"))

    def set_volume(self, percentage: int):
        blocker = QSignalBlocker(self.volume)
        self.volume.setValue(max(0, min(100, percentage)))
        del blocker

    def set_navigation(self, previous: bool, next_: bool):
        self.previous_button.setEnabled(previous)
        self.next_button.setEnabled(next_)
        self.focus_previous.setEnabled(previous)
        self.focus_next.setEnabled(next_)

    def set_version_selection_available(self, available: bool):
        self.version_button.setVisible(bool(available))

    def _set_lyrics_focus(self, enabled):
        self._lyrics_focus = bool(enabled)
        if hasattr(self,"left"):
            self.left.setVisible(not enabled)
            self.focus_transport.setVisible(enabled)
            self.content.layout().activate()
            self._adapt_cover()
            self.lyrics.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _cover_rect(self):
        return QRectF(self.cover.mapTo(self, QPoint(0, 0)), self.cover.size())

    def _source_rect(self):
        source = self._source_ref() if self._source_ref else None
        if source is not None and isValid(source):
            return QRectF(self.mapFromGlobal(source.mapToGlobal(QPoint(0, 0))), source.size())
        return self._cover_rect()

    def open_from(self, source: QWidget | None = None):
        if source is not None:
            self._source_ref = weakref.ref(source)
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        reopening = self.isVisible()
        self._desired_open = True
        self.show()
        self.raise_()
        self.layout().activate()
        self._adapt_cover()
        if not reopening:
            self._opened_notified = False
            self._travel.snap(self._source_rect())
            self._fade.snap(0.0)
            source_pixmap = getattr(source, "pixmap", None) if source is not None else None
            self.flight.pixmap = QPixmap(source_pixmap if isinstance(source_pixmap, QPixmap) and not source_pixmap.isNull()
                                         else self.cover.pixmap)
        self.cover.suppress_paint = True
        self.flight.setGeometry(self.rect())
        self.flight.show()
        self.flight.raise_()
        self._fade.animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.to(1.0, 160)
        self._travel.to(self._cover_rect(), 240)
        self.collapse_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def collapse(self):
        if not self.isVisible():
            return
        if self.focus_button.isChecked():
            self.focus_button.setChecked(False)
        self._desired_open = False
        self.cover.suppress_paint = True
        if not self._travel.running:
            self._travel.snap(self._cover_rect())
        self.flight.pixmap = QPixmap(self.cover.pixmap)
        self.flight.setGeometry(self.rect())
        self.flight.show()
        self.flight.raise_()
        self._fade.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.to(0.0, 160)
        self._travel.to(self._source_rect(), 200)

    def _flight_frame(self, rect):
        self.flight.destination = QRectF(rect)
        self.flight.update()

    def _finish_transition(self):
        if self._desired_open:
            self.cover.suppress_paint = False
            self.cover.update()
            self.flight.hide()
            if not self._opened_notified:
                self._opened_notified = True
                self.opened.emit()
        elif self.isVisible():
            self.hide()
            source = self._source_ref() if self._source_ref else None
            if source is not None and isValid(source) and source.isVisible():
                source.setFocus(Qt.FocusReason.OtherFocusReason)
            self.closed.emit()

    def _motion_changed(self, reduced):
        blocker = QSignalBlocker(self.motion_button)
        self.motion_button.setChecked(reduced)
        del blocker

    def _adapt_cover(self):
        size = min(340, max(180, self.height() - 430), max(180, self.left.width() - 16))
        self.cover.setFixedSize(size, size)
        self.layout().activate()
        self.content.layout().activate()
        self.left.layout().activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "cover"):
            self._adapt_cover()
            self.flight.setGeometry(self.rect())
            if hasattr(self, "_travel") and self._travel.running:
                if self._desired_open:
                    self._travel.snap(self._cover_rect())
                else:
                    self._travel.snap(self._source_rect())
                self._fade.finish()
                self._finish_transition()

    def hideEvent(self, event):
        if hasattr(self, "_travel"):
            self._travel.snap(self._travel.target)
            self._fade.snap(self._fade.target)
            self.cover.suppress_paint = False
            self.flight.hide()
        super().hideEvent(event)

    def focusNextPrevChild(self, next_: bool):
        if not self.isVisible():
            return super().focusNextPrevChild(next_)
        start = self.focusWidget() or self.collapse_button
        candidate = start.nextInFocusChain() if next_ else start.previousInFocusChain()
        while candidate is not start:
            if (self.isAncestorOf(candidate) and candidate.isVisibleTo(self) and candidate.isEnabled()
                    and candidate.focusPolicy() & Qt.FocusPolicy.TabFocus):
                candidate.setFocus(Qt.FocusReason.TabFocusReason if next_ else Qt.FocusReason.BacktabFocusReason)
                return True
            candidate = candidate.nextInFocusChain() if next_ else candidate.previousInFocusChain()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not isinstance(self.focusWidget(), (QAbstractButton, QAbstractSlider)):
            if self.track:
                self.toggle_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
