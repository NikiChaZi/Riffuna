"""Offline fixture screenshots for the library refresh. No user data or audio."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['RIFFUNA_AUDIO_BACKEND'] = 'qt'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from render_ui import OfflineSource, cover, fixture_tracks
from musicdesk.appearance import configure_app
from musicdesk.models import PlayQueue
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.surface_motion import install_surface_motion
from musicdesk.widgets import Artwork
from musicdesk.window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    configure_app(app)
    app.setFont(QFont('Segoe UI', 10))
    Playback.prefetch = lambda self, track: None
    Artwork.fetch = lambda self, url: None
    records = fixture_tracks()
    with tempfile.TemporaryDirectory(prefix='riffuna-library-fixture-') as temporary:
        library = Library(Path(temporary) / 'fixture.sqlite3')
        library.set_setting('reduced_motion', '1')
        for track in reversed(records):
            library.record_play(track)
        for track in records[:4]:
            library.like(track, True)
        library.save_current(records[0])
        library.save_queue(PlayQueue(records[1:5], -1))
        playlist_ids = []
        for title, items in (('Ночная дорога', records[:4]), ('Тихие часы', records[1:]), ('За городом', records[::2]), ('На повторе', records[2:])):
            key = library.create_playlist(title)
            playlist_ids.append(key)
            library.update_playlist_details(key, title, 'Проверочная библиотека для визуального аудита.')
            for track in items:
                library.add_to_playlist(key, track)
        window = MainWindow(library, OfflineSource())
        install_surface_motion(window, window.motion_policy)
        for i, track in enumerate(records):
            image = cover(i)
            window.artwork.cache[track.thumbnail] = image
            window.artwork.loaded.emit(track.thumbnail, image)
        window._on_track(records[0])
        window._refresh_queue()
        window.show()
        captured = []

        def capture(name):
            app.processEvents()
            window.clearFocus()
            window.search_input.clearFocus()
            app.processEvents()
            window.queue_list.doItemsLayout()
            window.track_list.doItemsLayout()
            app.processEvents()
            if name.startswith('home-queue') and window.queue_list.count():
                from PySide6.QtWidgets import QPushButton
                first = window.queue_list.item(0)
                row = window.queue_list.itemWidget(first)
                print(name, 'queue viewport/item/row:', window.queue_list.viewport().width(),
                      window.queue_list.visualItemRect(first).getRect(), row.geometry().getRect(),
                      'minimum:', row.minimumSize().toTuple(), row.minimumSizeHint().toTuple(), 'buttons:', [button.geometry().getRect() for button in row.findChildren(QPushButton)])
            shot = window.grab()
            canvas = QPixmap(shot.width(), shot.height() + 26)
            canvas.fill(QColor('#101214'))
            painter = QPainter(canvas)
            painter.drawPixmap(0, 0, shot)
            painter.setPen(QColor('#B9AAA0'))
            painter.drawText(12, shot.height() + 18, 'OFFLINE FIXTURE — вымышленные треки, оригинальные рисунки, временная библиотека')
            painter.end()
            path = args.output / ('refresh-' + name + '.png')
            if not canvas.save(str(path)):
                raise RuntimeError('Could not save ' + str(path))
            captured.append(path.name)

        for width, height in ((1280, 800), (1000, 650)):
            window.resize(width, height)
            window._hide_queue()
            window.show_view('home')
            window.home.verticalScrollBar().setValue(0)
            capture(f'home-{width}')
            window.show_view('playlists')
            capture(f'playlists-{width}')
            window._show_playlist(playlist_ids[0])
            capture(f'tracks-{width}')
            for index in (0, 2):
                window.track_list.item(index).setSelected(True)
            capture(f'selected-{width}')
            window.list_tools.search_input.setText('невозможное совпадение')
            capture(f'filter-empty-{width}')
            window.list_tools.search_input.clear()
            window.queue_toggle.setChecked(True)
            window.queue_panel.show()
            window.show_view('home')
            window.home.verticalScrollBar().setValue(0)
            capture(f'home-queue-{width}')
        window.resize(1280, 800)
        window._hide_queue()
        window.show_view('search')
        window.search_results = []
        window._search_loading = True
        window._render_search()
        capture('loading')
        window._search_loading = False
        window._search_error = 'Не удалось подключиться. Проверь интернет и повтори поиск.'
        window._render_search()
        capture('error')
        window.close()
        window.pool.waitForDone(2000)
        window.playback.pool.waitForDone(2000)
        library.close()
        empty_library = Library(Path(temporary) / 'empty.sqlite3')
        empty_library.set_setting('reduced_motion', '1')
        window = MainWindow(empty_library, OfflineSource())
        window.resize(1280, 800)
        window._hide_queue()
        window.show()
        window.show_view('home')
        capture('home-empty')
        window.close()
        window.pool.waitForDone(2000)
        window.playback.pool.waitForDone(2000)
        empty_library.close()
    print('Rendered', len(captured), 'OFFLINE FIXTURE screens:', ', '.join(captured))


if __name__ == '__main__':
    main()
