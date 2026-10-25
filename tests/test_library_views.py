"""Offline library dashboard geometry, navigation and refresh regressions."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton
import pytest

from musicdesk.library_views import HomePage, PlaylistPage
from musicdesk.models import Track
from musicdesk.widgets import Artwork, Cover, ElidedLabel
from test_ui_search import app, make_window


def library_tracks(count=6):
    return [Track(f"{index:011d}", "Очень длинное название композиции " * 4 + str(index),
                  "Длинное имя исполнителя " * 3, 180, f"https://i.ytimg.com/vi/{index:011d}/hqdefault.jpg")
            for index in range(count)]


def cache_art(artwork, tracks):
    for track in tracks:
        image = QPixmap(160, 160)
        image.fill(QColor("#FF875F"))
        artwork.cache[track.thumbnail] = image


def visible_tiles(page, name="trackTile"):
    return [tile for tile in page.findChildren(QPushButton, name) if tile.isVisible()]


def assert_tile_contents_fit(tile):
    assert tile.height() >= 200, "A QPushButton with a child layout needs an explicit card height"
    children = tile.findChildren(Cover) + tile.findChildren(ElidedLabel)
    assert len(children) == 3
    for child in children:
        top_left = child.mapTo(tile, QPoint())
        assert top_left.x() >= 0 and top_left.y() >= 0
        assert top_left.x() + child.width() <= tile.width()
        assert top_left.y() + child.height() <= tile.height()
        assert child.width() > 0 and child.height() > 0
    cover = tile.findChild(Cover)
    assert not cover.pixmap.isNull(), "The real cached cover should render rather than a placeholder"
    assert cover.width() == cover.height() == 128


@pytest.mark.parametrize("width", [1000, 1280])
def test_dashboard_cards_fit_with_open_queue(make_window, app, width):
    window, _ = make_window(lambda *args: [])
    tracks = library_tracks()
    cache_art(window.artwork, tracks)
    for track in tracks:
        window.library.record_play(track)
        window.library.like(track, True)
    playlist_id = window.library.create_playlist("Мои треки")
    window.library.add_to_playlist(playlist_id, tracks[0])
    window.resize(width, 800)
    window.queue_toggle.setChecked(True)
    window.queue_panel.show()
    window.show_view("home")
    app.processEvents()
    QTest.qWait(20)
    tiles = visible_tiles(window.home)
    assert len(tiles) == 12
    assert window.home.horizontalScrollBar().maximum() == 0
    for tile in tiles + visible_tiles(window.home, "playlistTile"):
        assert_tile_contents_fit(tile)
    assert window.home._columns == 3


def test_responsive_columns_keep_covers_inside_cards(app):
    artwork = Artwork()
    tracks = library_tracks()
    cache_art(artwork, tracks)
    page = HomePage(artwork)
    page.refresh(tracks, [], [], None, 0)
    page.resize(560, 800)
    page.show()
    app.processEvents()
    assert page._columns == 3
    for tile in visible_tiles(page):
        assert_tile_contents_fit(tile)
    page.resize(430, 800)
    app.processEvents()
    assert page._columns == 2
    assert page.horizontalScrollBar().maximum() == 0
    for tile in visible_tiles(page):
        assert_tile_contents_fit(tile)
    page.close()
    page.deleteLater()


def test_empty_dashboard_and_playlist_actions_emit_navigation(app):
    artwork = Artwork()
    page = HomePage(artwork)
    page.refresh([], [], [], None, 0)
    navigation = QSignalSpy(page.view_requested)
    create = QSignalSpy(page.create_requested)
    buttons = page.findChildren(QPushButton)
    next(button for button in buttons if button.text() == "Найти музыку").click()
    next(button for button in buttons if button.text() == "Создать плейлист").click()
    assert navigation.count() == 1 and navigation.at(0) == ["search"]
    assert create.count() == 1
    playlists = PlaylistPage(artwork)
    playlists.refresh([])
    created = QSignalSpy(playlists.create_requested)
    create_buttons = [button for button in playlists.findChildren(QPushButton)
                      if button.text() == "Создать плейлист"]
    assert len(create_buttons) == 2
    for button in create_buttons:
        button.click()
    assert created.count() == 2
    page.deleteLater()
    playlists.deleteLater()
    app.processEvents()


def test_unchanged_refresh_preserves_cards_and_scroll(app):
    artwork = Artwork()
    tracks = library_tracks()
    cache_art(artwork, tracks)
    playlists = [dict(id=i, name=f"Подборка {i}", track_count=3, thumbnail=tracks[0].thumbnail)
                 for i in range(10)]
    page = PlaylistPage(artwork)
    page.resize(560, 450)
    page.refresh(playlists)
    page.show()
    app.processEvents()
    before = visible_tiles(page, "playlistTile")
    page.verticalScrollBar().setValue(190)
    saved = page.verticalScrollBar().value()
    assert saved > 0
    page.refresh([dict(item) for item in playlists])
    app.processEvents()
    assert visible_tiles(page, "playlistTile") == before
    assert page.verticalScrollBar().value() == saved
    selected = QSignalSpy(page.playlist_requested)
    before[-1].click()
    assert selected.at(0) == [9]
    page.close()
    page.deleteLater()


def test_track_card_navigation_and_unchanged_home_identity(app):
    artwork = Artwork()
    tracks = library_tracks()
    cache_art(artwork, tracks)
    page = HomePage(artwork)
    page.resize(560, 450)
    page.refresh(tracks, tracks, [], tracks[0], 2)
    page.show()
    app.processEvents()
    before = visible_tiles(page)
    page.verticalScrollBar().setValue(130)
    saved = page.verticalScrollBar().value()
    selected = QSignalSpy(page.track_requested)
    page.refresh(list(tracks), list(tracks), [], tracks[0], 2)
    app.processEvents()
    assert visible_tiles(page) == before
    assert page.verticalScrollBar().value() == saved
    before[0].click()
    assert selected.at(0)[0] == tracks[0]
    page.close()
    page.deleteLater()
