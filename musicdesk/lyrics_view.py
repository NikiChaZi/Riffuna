"""Position-driven lyrics presentation and local LRC import; no provider or audio."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget, QPushButton

from .motion import MotionPolicy, Tween
from .lyric_timing import WordCue, estimated_words
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
    words: tuple[WordCue, ...] = ()
    end_ms: int | None = None

    def __post_init__(self):
        if type(self.at_ms) is not int or self.at_ms < 0:
            raise ValueError("Lyric cue position must be a nonnegative integer")
        if not isinstance(self.text, str):
            raise TypeError("Lyric cue text must be plain text")
        object.__setattr__(self, "words", tuple(self.words))
        if any(not isinstance(word, WordCue) for word in self.words):
            raise ValueError("Invalid lyric word")
        if any(a.start_ms > b.start_ms for a, b in zip(self.words,self.words[1:])):
            raise ValueError("Lyric words must be ordered")
        if self.end_ms is not None and (type(self.end_ms) is not int or self.end_ms < self.at_ms):
            raise ValueError("Invalid lyric line end")


@dataclass(frozen=True)
class LyricsDocument:
    state: LyricsState
    cues: tuple[LyricCue, ...] = ()
    text: str = ""
    source: str = ""
    timing_confirmed: bool = False
    word_timing: str = "none"

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
    cues = tuple(LyricCue(row["start_ms"], row["text"],
                          tuple(WordCue(**word) for word in row.get("words", ())), row.get("end_ms"))
                 for row in payload.get("lines", ()))
    confirmed = (payload.get("timing_source") in {"provider_lrc", "local_lrc", "provider_words", "local_ttml"}
                 and payload.get("match_quality") in {"metadata_duration", "user_import"})
    return LyricsDocument(state, cues=cues,
                          text=payload.get("message", "") if state == LyricsState.ERROR else payload.get("plain_text", ""),
                          source=("Локальный TTML" if payload.get("timing_source") == "local_ttml" else "Локальный LRC") if payload.get("source") == "local" else payload.get("source", ""), timing_confirmed=confirmed,
                          word_timing="provided" if any(cue.words for cue in cues) else "estimated" if state == LyricsState.SYNCED else "none")


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
        self.policy = policy
        self._layouts = []
        self._word_rows = []
        self._rows: list[QRectF] = []
        self._texts: list[str] = []
        self._times: list[int] = []
        self._old_active: tuple[int, ...] = ()
        self._scroll = Tween(0.0, policy, self)
        self._highlight = Tween(1.0, policy, self)
        self._word_position = Tween(0.0, policy, self)
        self._word_position.value_changed.connect(lambda value: self.update())
        self._scroll.value_changed.connect(lambda value: self.update())
        self._highlight.value_changed.connect(lambda value: self.update())
        self.setMinimumWidth(0)

    def _font(self):
        font = QFont("Segoe UI")
        font.setPixelSize(34 if self.width() >= 560 else 30 if self.width() >= 400 else 26)
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
        self._word_position.snap(float(self.position))
        self._layout_rows()
        self.set_position(self.position, force=True)

    def _layout_rows(self):
        self._rows.clear()
        self._layouts.clear()
        self._word_rows.clear()
        width = max(40, self.width() - 64)
        y = self.height() * .34 if self._times else 20.0
        for index,text in enumerate(self._texts):
            layout = QTextLayout(text or "···", self._font())
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
            layout.setTextOption(option)
            layout.beginLayout()
            local_y = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                line.setPosition(QPointF(0,local_y))
                local_y += line.height() * 1.13
            layout.endLayout()
            height = max(QFontMetricsF(self._font()).height(), local_y) + 16
            self._rows.append(QRectF(24,y,width,height))
            self._layouts.append(layout)
            if self._times:
                cue = self.document.cues[index]
                next_time = next((value for value in self._times[index+1:] if value > cue.at_ms), cue.at_ms+5000)
                words = cue.words or estimated_words(text,cue.at_ms,cue.end_ms or next_time)
            else:
                words = ()
            spans=[]
            cursor=0
            for word in words:
                value=word.text.strip()
                position=text.find(value,cursor) if value else -1
                if position >= 0:
                    left = len(text[:position].encode("utf-16-le"))//2
                    right = left + len(value.encode("utf-16-le"))//2
                    spans.append((word,left,right))
                    cursor=position+len(value)
            self._word_rows.append(spans)
            y += height + 18

    def word_progress(self, index, *, displayed=False):
        position = float(self._word_position.value) if displayed else self.position
        return tuple(word.progress(position) for word,_,_ in self._word_rows[index])

    def set_playing(self, playing: bool):
        self.playing = bool(playing)
        if not playing:
            self._scroll.finish()
            self._highlight.finish()
            self._word_position.finish()

    def set_position(self, milliseconds: int, *, force=False):
        previous_position = self.position
        self.position = max(0, int(milliseconds))
        jump = force or not self.isVisible() or not self.playing or self.position < previous_position or abs(self.position - previous_position) > 1500
        self._word_position.to(float(self.position), 0 if jump else min(100, max(30, abs(self.position-previous_position))))
        self.update()
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
        jump = force or not self.isVisible() or not self.playing or self.position < previous_position or abs(self.position - previous_position) > 1500
        self._highlight.snap(0.0)
        self._highlight.to(1.0, 0 if jump else 300)
        if self.follow:
            self._center_active(animate=not jump)

    def _center_active(self, *, animate: bool):
        if not self._rows:
            return
        focus = self.active_indices[0] if self.active_indices else 0
        target = max(0.0, self._rows[focus].center().y() - self.height() * .42)
        self._scroll.to(target, 360 if animate else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_rows()
        if self.follow:
            self._center_active(animate=False)

    def hideEvent(self, event):
        self._scroll.finish()
        self._highlight.finish()
        self._word_position.finish()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        position = float(self._word_position.value)
        phase = float(self._highlight.value)
        for index,row in enumerate(self._rows):
            rect=row.translated(0,-float(self._scroll.value))
            if rect.bottom() < 0 or rect.top() > self.height():
                continue
            active = index in self.active_indices
            departing = index in self._old_active
            weight = phase if active else 1-phase if departing else 0
            painter.save()
            painter.translate(rect.x(),rect.y() - (0 if self.policy.reduced else weight*2.5))
            if not self.policy.reduced:
                painter.scale(1+weight*.018,1+weight*.018)
            layout=self._layouts[index]
            base=QColor('#626C69' if self._times else '#CDCBC2')
            painter.setPen(base)
            layout.draw(painter,QPointF())
            if self._times:
                # Past rows settle to a quiet warm tone; only the active phrase fills.
                if not active and self._times[index] < self.position:
                    painter.setPen(QColor('#9A9E95'))
                    layout.draw(painter,QPointF())
                elif active:
                    for word,left,right in self._word_rows[index]:
                        progress=word.progress(position)
                        if progress <= 0:
                            continue
                        for line_index in range(layout.lineCount()):
                            line=layout.lineAt(line_index)
                            a=max(left,line.textStart())
                            b=min(right,line.textStart()+line.textLength())
                            if a >= b:
                                continue
                            x1=line.cursorToX(a)[0]
                            x2=line.cursorToX(b)[0]
                            # A provider segment can wrap; advance its full visual width.
                            segment_before=max(0,a-left)
                            segment_length=max(1,right-left)
                            local_progress=max(0.0,min(1.0,(progress*segment_length-segment_before)/max(1,b-a)))
                            if local_progress <= 0:
                                continue
                            width=abs(x2-x1)*local_progress
                            x=min(x1,x2) if x1<=x2 else max(x1,x2)-width
                            painter.save()
                            painter.setClipRect(QRectF(x-0.5,line.y()-2,width+1,line.height()+5))
                            painter.setPen(QColor('#F5F1E8'))
                            layout.draw(painter,QPointF())
                            painter.restore()
            if self.hasFocus() and index==self.cursor:
                painter.setPen(QPen(QColor('#FF875F'),1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(-8,-3,row.width()+16,row.height()-5),6,6)
            painter.restore()
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
        self.import_button = QPushButton("Открыть текст…")
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
        timing = "Пословно" if any(cue.words for cue in self.document.cues) else "Плавная подсветка" if state == LyricsState.SYNCED else captions[state]
        self.caption.setText(timing + (" · " + document.source if document.source.startswith("Локальный") else ""))
        self.caption.setToolTip(("Тайминги слов из источника" if any(cue.words for cue in self.document.cues)
                                 else "Подсветка слов рассчитана по таймкодам строк; точное совпадение с вокалом не гарантируется" if state == LyricsState.SYNCED else captions[state])
                                + (" · " + document.source if document.source else ""))
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
