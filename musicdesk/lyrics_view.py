"""Position-driven lyrics presentation and local LRC import; no provider or audio."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget, QPushButton

from .motion import MotionPolicy, Tween
from .widgets import label


class LyricsState(str, Enum):
    LOADING = "loading"
    SYNCED = "synced"
    PLAIN = "plain"
    INSTRUMENTAL = "instrumental"
    NOTFOUND = "notfound"
    ERROR = "error"


@dataclass(frozen=True)
class LyricCue:
    at_ms: int
    text: str

    def __post_init__(self):
        if type(self.at_ms) is not int or self.at_ms < 0:
            raise ValueError("Lyric cue position must be a nonnegative integer")
        if not isinstance(self.text, str):
            raise TypeError("Lyric cue text must be plain text")


@dataclass(frozen=True)
class LyricsDocument:
    state: LyricsState
    cues: tuple[LyricCue, ...] = ()
    text: str = ""
    source: str = ""
    timing_confirmed: bool = False

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.source, str):
            raise TypeError("Lyrics text and source must be plain strings")
        object.__setattr__(self, "state", LyricsState(self.state))
        object.__setattr__(self, "cues", tuple(self.cues))
        if any(a.at_ms > b.at_ms for a, b in zip(self.cues, self.cues[1:])):
            raise ValueError("Lyric cues must be ordered by position")
        if self.state == LyricsState.SYNCED and not self.cues:
            raise ValueError("Synchronized lyrics need actual cues")

    def for_display(self):
        if self.state == LyricsState.SYNCED and not self.timing_confirmed:
            return LyricsDocument(LyricsState.PLAIN, text=self.text or "\n".join(cue.text for cue in self.cues), source=self.source)
        return self


def document_from_payload(payload: dict) -> LyricsDocument:
    """Translate the controller contract; metadata matching is not acoustic proof."""
    state = LyricsState("notfound" if payload.get("state") == "not_found" else payload.get("state", "error"))
    cues = tuple(LyricCue(row["start_ms"], row["text"]) for row in payload.get("lines", ()))
    confirmed = (payload.get("timing_source") in {"provider_lrc", "local_lrc"}
                 and payload.get("match_quality") in {"metadata_duration", "user_import"})
    return LyricsDocument(state, cues=cues,
                          text=payload.get("message", "") if state == LyricsState.ERROR else payload.get("plain_text", ""),
                          source="Локальный LRC" if payload.get("source") == "local" else payload.get("source", ""), timing_confirmed=confirmed)


class LyricsCanvas(QWidget):
    seek_requested = Signal(int)
    follow_changed = Signal(bool)

    def __init__(self, policy: MotionPolicy, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Строки песни")
        self.setToolTip("↑ / ↓ — выбрать строку; Enter — перейти к её времени")
        self.document = LyricsDocument(LyricsState.NOTFOUND)
        self.active_indices: tuple[int, ...] = ()
        self.cursor = -1
        self.position = 0
        self.playing = False
        self.seek_enabled = True
        self.follow = True
        self._rows: list[QRectF] = []
        self._texts: list[str] = []
        self._times: list[int] = []
        self._old_active: tuple[int, ...] = ()
        self._scroll = Tween(0.0, policy, self)
        self._highlight = Tween(1.0, policy, self)
        self._scroll.value_changed.connect(lambda value: self.update())
        self._highlight.value_changed.connect(lambda value: self.update())
        self.setMinimumWidth(0)

    def _font(self):
        font = QFont("Segoe UI")
        font.setPixelSize(28 if self.width() >= 470 else 24)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def set_document(self, document: LyricsDocument):
        self.document = document.for_display()
        self.active_indices = self._old_active = ()
        self.setAccessibleDescription("")
        self.cursor = -1
        self.follow = True
        self.follow_changed.emit(True)
        self._times = [cue.at_ms for cue in self.document.cues] if self.document.state == LyricsState.SYNCED else []
        self._texts = ([cue.text for cue in self.document.cues] if self._times else self.document.text.splitlines())
        self._scroll.snap(0.0)
        self._highlight.snap(1.0)
        self._layout_rows()
        self.set_position(self.position, force=True)

    def _layout_rows(self):
        self._rows.clear()
        metrics = QFontMetricsF(self._font())
        width = max(40, self.width() - 48)
        y = self.height() * .34 if self._times else 20.0
        for text in self._texts:
            bounds = metrics.boundingRect(QRectF(0, 0, width, 10000), Qt.TextFlag.TextWordWrap, text or "…")
            height = max(metrics.height(), bounds.height()) + 20
            self._rows.append(QRectF(24, y, width, height))
            y += height + 12

    def set_playing(self, playing: bool):
        self.playing = bool(playing)
        if not playing:
            self._scroll.finish()
            self._highlight.finish()

    def set_position(self, milliseconds: int, *, force=False):
        previous_position = self.position
        self.position = max(0, int(milliseconds))
        if not self._times:
            self.active_indices = ()
            return
        end = bisect_right(self._times, self.position)
        if end:
            start = bisect_right(self._times, self._times[end - 1] - 1)
            active = tuple(range(start, end))
        else:
            active = ()
        if active == self.active_indices and not force:
            return
        self._old_active = self.active_indices
        self.active_indices = active
        if self.follow:
            self.cursor = -1
        self.setAccessibleDescription(" / ".join(self._texts[i] for i in active if self._texts[i]) or "Музыкальная пауза")
        jump = force or not self.isVisible() or not self.playing or abs(self.position - previous_position) > 1500
        self._highlight.snap(0.0)
        self._highlight.to(1.0, 0 if jump else 160)
        if self.follow:
            self._center_active(animate=not jump)

    def _center_active(self, *, animate: bool):
        if not self._rows:
            return
        focus = self.active_indices[0] if self.active_indices else 0
        target = max(0.0, self._rows[focus].center().y() - self.height() * .42)
        self._scroll.to(target, 180 if animate else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_rows()
        if self.follow:
            self._center_active(animate=False)

    def hideEvent(self, event):
        self._scroll.finish()
        self._highlight.finish()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font())
        muted, warm = QColor("#7F8E86"), QColor("#F4F1E8")
        for index, row in enumerate(self._rows):
            rect = row.translated(0, -float(self._scroll.value))
            if rect.bottom() < 0 or rect.top() > self.height():
                continue
            weight = 0.0
            phase = float(self._highlight.value)
            if index in self.active_indices:
                weight = phase
            elif index in self._old_active:
                weight = 1.0 - phase
            if not self._times:
                weight = .72
            color = QColor(*(round(a + (b - a) * weight) for a, b in zip(muted.getRgb()[:3], warm.getRgb()[:3])))
            painter.setPen(color)
            painter.drawText(rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, self._texts[index] or "···")
            if self.hasFocus() and index == self.cursor:
                painter.setPen(QPen(QColor("#FF875F"), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-8, -3, 8, -8), 6, 6)
        painter.end()

    def resume_follow(self):
        self.follow = True
        self.cursor = -1
        self.follow_changed.emit(True)
        self._center_active(animate=self.playing)

    def _select_cursor(self, index):
        self.follow = False
        self.follow_changed.emit(False)
        self.cursor = max(0, min(index, len(self._texts) - 1))
        row = self._rows[self.cursor]
        self._scroll.to(max(0.0, row.center().y() - self.height() * .42), 140)
        self.update()

    def keyPressEvent(self, event):
        if self._texts and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Home, Qt.Key.Key_End):
            current = self.cursor if self.cursor >= 0 else (self.active_indices[0] if self.active_indices else 0)
            target = {Qt.Key.Key_Down: current + 1, Qt.Key.Key_Up: current - 1,
                      Qt.Key.Key_Home: 0, Qt.Key.Key_End: len(self._texts) - 1}[event.key()]
            self._select_cursor(target)
            event.accept()
        elif self._times and self.seek_enabled and self.cursor >= 0 and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.seek_requested.emit(self._times[self.cursor])
            self.resume_follow()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            for index, row in enumerate(self._rows):
                if row.translated(0, -float(self._scroll.value)).contains(event.position()):
                    self.cursor = index
                    if self._times and self.seek_enabled:
                        self.seek_requested.emit(self._times[index])
                        self.resume_follow()
                    self.update()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self.follow = False
        self.follow_changed.emit(False)
        maximum = max(0.0, (self._rows[-1].bottom() if self._rows else 0) - self.height() * .6)
        target = max(0.0, min(maximum, float(self._scroll.target) - event.angleDelta().y() * .5))
        self._scroll.to(target, 100)
        event.accept()


class LyricsPane(QFrame):
    retry_requested = Signal()
    import_requested = Signal()
    seek_requested = Signal(int)

    def __init__(self, policy: MotionPolicy, parent=None):
        super().__init__(parent)
        self.setObjectName("lyricsPane")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label("Текст песни", "sectionTitle"), 1)
        self.import_button = QPushButton("Импорт LRC")
        self.import_button.setAccessibleName("Импортировать LRC для выбранной записи")
        self.import_button.clicked.connect(self.import_requested)
        heading.addWidget(self.import_button)
        outer.addLayout(heading)
        self.caption = label("", "cardSubtitle")
        self.caption.setWordWrap(True)
        outer.addWidget(self.caption)
        self.stack = QStackedWidget()
        self.stack.setObjectName("lyricsStack")
        self.canvas = LyricsCanvas(policy)
        self.canvas.seek_requested.connect(self.seek_requested)
        self.stack.addWidget(self.canvas)
        self.message = QWidget()
        layout = QVBoxLayout(self.message)
        layout.setSpacing(14)
        layout.addStretch()
        self.message_title = label("", "lyricsMessage")
        self.message_title.setWordWrap(True)
        self.message_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_title)
        self.message_copy = label("", "muted")
        self.message_copy.setWordWrap(True)
        self.message_copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_copy)
        self.retry = QPushButton("Повторить")
        self.retry.clicked.connect(self.retry_requested)
        layout.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.stack.addWidget(self.message)
        outer.addWidget(self.stack, 1)
        footer_row = QHBoxLayout()
        self.footer = label("Текст относится к выбранной записи", "tiny")
        self.footer.setWordWrap(True)
        footer_row.addWidget(self.footer, 1)
        self.follow_button = QPushButton("К текущей строке")
        self.follow_button.clicked.connect(self.canvas.resume_follow)
        self.follow_button.hide()
        self.canvas.follow_changed.connect(lambda follow: self.follow_button.setVisible(not follow and self.document.state == LyricsState.SYNCED))
        footer_row.addWidget(self.follow_button)
        outer.addLayout(footer_row)
        self.document = LyricsDocument(LyricsState.NOTFOUND)
        self.set_document(self.document)

    def set_document(self, document: LyricsDocument):
        self.document = document.for_display()
        self.footer.setText("Текст относится к выбранной записи")
        state = self.document.state
        captions = {LyricsState.SYNCED: "Синхронный текст", LyricsState.PLAIN: "Без синхронизации",
                    LyricsState.LOADING: "Ищем текст выбранной записи", LyricsState.INSTRUMENTAL: "Инструментальная запись",
                    LyricsState.NOTFOUND: "Текст пока не найден", LyricsState.ERROR: "Не удалось получить текст"}
        self.caption.setText(captions[state] + (" · " + document.source if document.source else ""))
        self.canvas.set_document(self.document)
        self.retry.setVisible(state in (LyricsState.ERROR, LyricsState.NOTFOUND))
        if state in (LyricsState.SYNCED, LyricsState.PLAIN):
            self.stack.setCurrentWidget(self.canvas)
        else:
            copy = {
                LyricsState.LOADING: ("Ищем нужные слова", "Продолжай слушать. Если текст доступен для выбранной записи, он появится здесь."),
                LyricsState.INSTRUMENTAL: ("Здесь говорит музыка", "Для этой записи отмечено отсутствие вокального текста."),
                LyricsState.NOTFOUND: ("Пока без текста", "Можно импортировать LRC, подходящий именно к выбранной записи."),
                LyricsState.ERROR: ("Текст не загрузился", self.document.text or "Попробуй ещё раз или импортируй свой LRC."),
            }
            self.message_title.setText(copy[state][0])
            self.message_copy.setText(copy[state][1])
            self.stack.setCurrentWidget(self.message)
