"""Offline expanded-player QA; invented lyrics/art, no provider or audio engine."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from musicdesk.appearance import configure_app
from musicdesk.expanded_player import ExpandedPlayer, ExpandableCover
from musicdesk.lyrics_view import LyricCue, LyricsDocument, LyricsState
from musicdesk.lyric_timing import WordCue
from musicdesk.models import Track
from musicdesk.motion import MotionPolicy
from musicdesk.widgets import Artwork, label


WORDS = ("Тихий свет ложится на дома", "Город дышит медленнее ветра", "Мы оставим шум за поворотом",
         "И услышим утро за окном", "Там, где день рисует новые дороги", "Музыка становится теплом")
CUES = tuple(LyricCue(milliseconds, words) for milliseconds, words in zip((1000, 4500, 8000, 12000, 16000, 20000), WORDS))


def artwork():
    image = QPixmap(640, 640)
    image.fill(QColor("#34534D"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#E0C18D"))
    painter.drawEllipse(QRectF(182, 120, 270, 270))
    painter.setBrush(QColor("#172C29"))
    painter.drawRect(QRectF(0, 344, 640, 296))
    painter.setPen(QPen(QColor("#FF875F"), 12))
    for y in (408, 444, 480):
        painter.drawLine(86, y, 554, y)
    painter.setPen(QPen(QColor("#E0C18D"), 3))
    painter.drawLine(86, 544, 340, 544)
    painter.end()
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (font_dir / filename).exists():
            QFontDatabase.addApplicationFont(str(font_dir / filename))
    configure_app(app)
    host = QWidget()
    host.setObjectName("root")
    host.resize(1280, 800)
    source = ExpandableCover(Artwork(host), 56, host)
    source.move(24, 720)
    art = artwork()
    source.pixmap = art
    note = label("Офлайн-демонстрация · вымышленные строки и обложка", "muted", host)
    note.move(100, 740)
    host.show()
    panel = ExpandedPlayer(host, policy=MotionPolicy(True))
    track = Track("aaaaaaaaaaa", "Город после дождя", "Студия 04", 189)
    panel.set_track(track)
    panel.set_artwork(track.video_id, art)
    panel.set_duration(189000)
    panel.set_seekable(True)
    panel.set_volume(68)
    panel.set_repeat("one")
    panel.set_liked(True)
    panel.set_navigation(True, True)
    panel.open_from(source)

    def capture(name):
        app.processEvents()
        shot=host.grab().toImage()
        from PySide6.QtGui import QImage
        image=QImage(shot.width(),shot.height()+26,QImage.Format.Format_ARGB32)
        image.fill(QColor("#101214"))
        painter=QPainter(image);painter.drawImage(0,0,shot)
        painter.setPen(QColor("#A3A8AD"));painter.drawText(12,shot.height()+18,"OFFLINE UI FIXTURE — вымышленные строки и обложка")
        painter.end()
        if not image.save(str(args.output / (name + ".png"))):
            raise RuntimeError("Could not render " + name)

    for state in LyricsState:
        data = LyricsDocument(state, cues=CUES if state == LyricsState.SYNCED else (),
                              text="\n".join(WORDS) if state == LyricsState.PLAIN else "Сервис текста временно недоступен. Попробуй ещё раз.",
                              source="Синтетический LRC" if state in (LyricsState.SYNCED, LyricsState.PLAIN) else "",
                              timing_confirmed=state == LyricsState.SYNCED)
        panel.set_lyrics(track.video_id, panel.request_token, data)
        panel.set_position(8000)
        panel.set_playback_state("paused")
        capture("01-" + state.value)
    panel.set_lyrics(track.video_id, panel.request_token,
                     LyricsDocument(LyricsState.SYNCED, CUES, source="Синтетический LRC", timing_confirmed=True))
    panel.set_position(8000)
    panel.set_playback_state("playing")
    host.resize(1000, 650)
    panel.resize(host.size())
    capture("02-synced-minimum")
    host.resize(1280, 800)
    panel.resize(host.size())
    panel.policy.set_reduced(True)
    host.resize(1280,800)
    panel.resize(host.size())
    word_cues=[]
    for cue in CUES:
        chunks=cue.text.split()
        words=tuple(WordCue(cue.at_ms+i*500,cue.at_ms+(i+1)*500,word+(" " if i+1<len(chunks) else "")) for i,word in enumerate(chunks))
        word_cues.append(LyricCue(cue.at_ms,cue.text,words,words[-1].end_ms))
    panel.set_lyrics(track.video_id,panel.request_token,LyricsDocument(LyricsState.SYNCED,tuple(word_cues),source="Синтетические тайминги",timing_confirmed=True,word_timing="provided"))
    for position in (8200,8700,9200,9700):
        panel.set_position(position)
        capture(f"04-word-fill-{position}ms")
    panel.focus_button.setChecked(True)
    capture("05-word-focus")
    host.resize(1000,650);panel.resize(host.size())
    capture("06-word-focus-minimum")
    panel.focus_button.setChecked(False)
    panel.collapse()
    panel.policy.set_reduced(False)
    panel.open_from(source)
    for moment in (0, 120):
        panel._travel.animation.setCurrentTime(moment)
        panel._fade.animation.setCurrentTime(min(moment, 160))
        capture(f"03-cover-transition-{moment:03d}ms")
    panel.policy.set_reduced(True)
    capture("03-cover-transition-240ms")
    panel.collapse()
    host.close()
    print(f"Rendered {len(LyricsState) + 1} state/size screens and 3 transition frames to", args.output)


if __name__ == "__main__":
    main()
