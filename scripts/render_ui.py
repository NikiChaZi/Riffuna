"""Render UI review fixtures offline. Never reads the user's library or YouTube."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from musicdesk.models import PlayQueue, Track
from musicdesk.appearance import configure_app
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.style import STYLE
from musicdesk.widgets import Artwork
from musicdesk.window import MainWindow


class OfflineSource:
    def search(self, query, limit=40, order="relevance"):
        return []

    def resolve(self, track):
        raise AssertionError("UI fixtures must not request audio")


def fixture_tracks():
    names = [
        ("Тихий город", "Студия 04", 204),
        ("Afterglow", "Paper Satellites", 187),
        ("Northbound (Extended Mix)", "Night Assembly", 312),
        ("Свет в окнах (Slowed)", "Студия 04", 243),
        ("Small Hours (Remix)", "Low Tide", 218),
        ("April Tape", "Paper Satellites", 165),
    ]
    return [Track(f"{i:011d}", title, artist, duration,
                  f"https://i.ytimg.com/vi/{i:011d}/hqdefault.jpg", 1250000 if i == 0 else None)
            for i, (title, artist, duration) in enumerate(names)]


def cover(index):
    backgrounds = ["#BB6647", "#476E69", "#B8A35E", "#6C7770", "#9C775D", "#597477"]
    image = QPixmap(256, 256)
    image.fill(QColor(backgrounds[index]))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#F3E9CE"), 5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for radius in (48, 76, 104):
        painter.drawEllipse(QRectF(128 - radius, 128 - radius, radius * 2, radius * 2))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1C2423"))
    painter.drawRect(QRectF(0, 165 + index * 4, 256, 92))
    painter.setBrush(QColor("#F3E9CE"))
    painter.drawEllipse(QRectF(119, 119, 18, 18))
    painter.end()
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setFont(QFont("Segoe UI", 10))
    configure_app(app)
    # This is a render fixture, not a playback test. No resolving or prebuffering.
    Playback.prefetch = lambda self, track: None
    Artwork.fetch = lambda self, url: None
    records = fixture_tracks()
    with tempfile.TemporaryDirectory(prefix="riffuna-ui-") as temporary:
        library = Library(Path(temporary) / "fixtures.sqlite3")
        for track in reversed(records):
            library.record_play(track)
        for track in records[:3]:
            library.like(track, True)
        library.save_queue(PlayQueue(records[1:5], -1))
        library.save_current(records[0])
        for name, selected in (("Ночная дорога", records[:4]), ("Ремиксы и slowed", records[2:])):
            collection = library.create_playlist(name)
            for track in selected:
                library.add_to_playlist(collection, track)
        window = MainWindow(library, OfflineSource())
        for i, track in enumerate(records):
            window.artwork.cache[track.thumbnail] = cover(i)
            window.artwork.loaded.emit(track.thumbnail, window.artwork.cache[track.thumbnail])
        window._on_track(records[0])
        window._refresh_queue()
        window.resize(1280, 800)
        window.show()

        def capture(name):
            app.processEvents()
            window.clearFocus()
            window.search_input.clearFocus()
            app.processEvents()
            if not window.grab().save(str(args.output / (name + ".png"))):
                raise RuntimeError("Could not render " + name)

        capture("01-home")
        window.show_view("playlists")
        capture("16-playlists")
        window._show_playlist(library.playlists()[0]["id"])
        capture("17-playlist-tracks")
        window.last_query = "вечерний плейлист"
        window.search_results = records
        window._search_limit = 40
        window.show_view("search")
        capture("02-search")
        window.show_view("likes")
        capture("03-likes")
        window.show_view("history")
        capture("04-history")
        window.search_results = []
        window.show_view("search")
        capture("05-empty")
        window.show_view("likes")
        window._hide_queue()
        capture("06-likes-no-queue")
        window.resize(window.minimumSize())
        window.queue_toggle.setChecked(True)
        window.queue_panel.show()
        window.show_view("search")
        window.search_results = records
        window._render_search()
        capture("07-minimum-queue")
        window._hide_queue()
        capture("08-minimum-no-queue")
        window.queue_toggle.setChecked(True)
        window.queue_panel.show()
        window.show_view("home")
        capture("12-minimum-home")
        window.show_view("likes")
        capture("13-minimum-likes")
        window.show_view("history")
        capture("14-minimum-history")
        window.search_results = []
        window.show_view("search")
        capture("15-minimum-empty")
        window._hide_queue()
        window.resize(1280, 800)
        window.search_results = []
        window._search_loading = True
        window._render_search()
        capture("09-loading")
        window._search_loading = False
        window._search_error = "Не удалось подключиться. Проверь интернет и повтори поиск."
        window._render_search()
        capture("10-error")
        for track in records[:3]:
            library.like(track, False)
        window.show_view("likes")
        capture("11-empty-likes")
        window.close()
        window.pool.waitForDone(2000)
        window.playback.pool.waitForDone(2000)
        app.processEvents()
        library.close()
    print(f"Rendered 17 offline fixture screens to {args.output}")


if __name__ == "__main__":
    main()
