"""Visual-layout and identity regressions, with synthetic data and no audio."""
import json
import struct
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QPushButton

from musicdesk.appearance import APP_ID, app_icon, asset_path, configure_app, prepare_windows_identity, write_startup_report
from musicdesk.widgets import QueryCard
from test_ui_search import app, make_window, settled, tracks, wait_for


def test_windows_icon_contains_complete_nonoverlapping_frames(app):
    payload = asset_path("riffuna.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", payload)
    assert (reserved, kind) == (0, 1)
    dimensions = []
    previous_end = 6 + count * 16
    for index in range(count):
        width, height, _, _, planes, depth, length, offset = struct.unpack_from("<BBBBHHII", payload, 6 + index * 16)
        dimensions.append(width or 256)
        assert (width or 256) == (height or 256)
        assert (planes, depth) == (1, 32)
        assert offset == previous_end
        assert payload[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        previous_end = offset + length
    assert previous_end == len(payload)
    assert dimensions == [16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256]
    assert sorted(size.width() for size in app_icon().availableSizes()) == dimensions
    for size in (16, 24, 32, 48, 256):
        image = app_icon().pixmap(size, size).toImage()
        assert image.size() == QSize(size, size)
        assert image.pixelColor(0, 0).alpha() == 0
        colors = {image.pixelColor(x, y).name() for x in range(size) for y in range(size)}
        assert "#ff875f" in colors
        assert "#151a19" in colors


def test_window_and_application_load_the_same_icon(make_window, app, tmp_path):
    prepare_windows_identity()
    configure_app(app)
    window, source = make_window(lambda query, limit, order: [])
    report_path = tmp_path / "startup.json"
    write_startup_report(app, window, report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["application_icon"] and report["window_icon"] and report["icon_asset_exists"]
    assert {16, 24, 32, 48, 256} <= set(report["icon_sizes"])
    if sys.platform == "win32":
        assert report["windows_app_id"] == APP_ID
    assert window.windowIcon().pixmap(32, 32).toImage() == app.windowIcon().pixmap(32, 32).toImage()


@pytest.mark.parametrize("queue_open", [True, False])
def test_minimum_window_keeps_navigation_and_player_controls_inside(make_window, app, queue_open):
    window, source = make_window(lambda query, limit, order: tracks(3, "Very long recording title (Ultra Slowed Remix)"))
    window.resize(1000, 650)
    if not queue_open:
        window._hide_queue()
    window.search_query("test")
    wait_for(lambda: settled(window))
    app.processEvents()
    assert window.size() == QSize(1000, 650)
    assert not window.hero_art.isVisible()
    assert window.search_input.width() >= 200
    assert window.page_title.geometry().right() < window.play_all.geometry().left()
    assert window.play_all.parentWidget().rect().contains(window.play_all.geometry())
    for control in (window.search_input, window.queue_toggle, window.current_info, window.output_button, window.seek):
        assert control.parentWidget().rect().contains(control.geometry())
    assert window.search_order.isEnabled()
    assert window.current_info.geometry().right() < window.seek.mapTo(window.current_info.parentWidget(), window.seek.rect().topLeft()).x()


def test_version_badges_do_not_stretch_to_row_height(make_window):
    window, source = make_window(lambda query, limit, order: tracks(2, "Test (Ultra Slowed Remix)"))
    window.search_query("test")
    wait_for(lambda: settled(window))
    badges = [child for row in window.rows for child in row.findChildren(QLabel, "badge")]
    assert len(badges) == 2
    assert all(0 < badge.height() <= 20 for badge in badges)
    assert all(badge.parentWidget().rect().contains(badge.geometry()) for badge in badges)


def test_home_cards_have_height_and_preserve_existing_navigation(make_window, app, monkeypatch):
    window, source = make_window(lambda query, limit, order: [])
    app.processEvents()
    cards = window.home.findChildren(QueryCard)
    assert len(cards) == 4
    queries = []
    monkeypatch.setattr(window, "search_query", queries.append)
    cards[0].click()
    assert queries == ["Дора Втюрилась"]
    library_cards = window.home.findChildren(QPushButton, "libraryCard")
    assert len(library_cards) == 2
    assert all(card.height() >= 80 for card in library_cards)
    library_cards[0].click()
    assert window.view == "likes"
    library_cards[1].click()
    assert window.view == "history"


@pytest.mark.parametrize("kind", ["loading", "error", "likes"])
def test_empty_state_copy_is_not_vertically_clipped(make_window, app, kind):
    window, source = make_window(lambda query, limit, order: [])
    window.resize(1000, 650)
    window.show_view("search")
    if kind == "likes":
        window.show_view("likes")
    else:
        window._search_loading = kind == "loading"
        window._search_error = "Не удалось подключиться. Проверь интернет и повтори поиск." if kind == "error" else ""
        window._render_search()
    app.processEvents()
    copy = window.empty_text
    assert copy.height() >= copy.heightForWidth(copy.width())
    assert copy.parentWidget().rect().contains(copy.geometry())
    if kind == "error":
        assert window.retry.isVisible()
        assert copy.geometry().bottom() < window.retry.geometry().top()


def test_queue_current_display_does_not_add_to_queue(make_window, app):
    window, source = make_window(lambda query, limit, order: [])
    track = tracks(1, "Separate current recording")[0]
    window._on_track(track)
    app.processEvents()
    assert window.queue_now.isVisible()
    assert window.queue_current_title.toolTip() == track.title
    assert window.queue_caption.text() == "0"
    assert not window.playback.queue.tracks
    assert window.queue_list.count() == 0
    assert not window.library.history()
