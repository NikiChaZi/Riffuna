"""Offline search UI regressions: no YouTube calls or visible desktop windows."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, QThread, Qt
from PySide6.QtGui import QEnterEvent, QFont, QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from musicdesk.models import Track
from musicdesk.storage import Library
from musicdesk.style import STYLE
from musicdesk.window import MainWindow


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    # Windows' offscreen platform does not discover system fonts itself.
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        font_path = font_dir / filename
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    application.setFont(QFont("Segoe UI", 10))
    application.setStyleSheet(STYLE)
    return application


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Search UI did not settle")


def tracks(count, title="Track"):
    return [Track(f"{index:011d}", f"{title} {index}", "Artist", 180,
                  view_count=1234567 if index == 0 else 0 if index == 1 else None)
            for index in range(count)]


class SearchSource:
    def __init__(self, handler, app):
        self.handler = handler
        self.app = app
        self.calls = []

    def search(self, query, limit=40, order="relevance"):
        assert QThread.currentThread() != self.app.thread(), "Search must not block the GUI thread"
        self.calls.append((query, limit, order))
        return self.handler(query, limit, order)

    def resolve(self, track):
        raise AssertionError("Search UI tests must not resolve or play audio")


@pytest.fixture
def make_window(app, tmp_path):
    opened = []
    releases = []

    def make(handler, release=None):
        library = Library(tmp_path / f"library-{len(opened)}.sqlite3")
        source = SearchSource(handler, app)
        window = MainWindow(library, source)
        # Keep search/hover tests offline even when Playback can resolve streams.
        window.prefetched = []
        window.playback.prefetch = window.prefetched.append
        # Only offscreen Qt surfaces; never create an on-screen application.
        assert app.platformName() == "offscreen"
        window.show()
        opened.append((window, library))
        if release:
            releases.append(release)
        return window, source

    yield make
    for release in releases:
        release.set()
    for window, library in opened:
        window.close()
        window.pool.waitForDone(6000)
        window.playback.pool.waitForDone(6000)
        app.processEvents()
        library.close()
        window.deleteLater()
    app.processEvents()


def settled(window):
    return not window._search_loading and not window._search_tasks


def test_sorting_restarts_at_40_with_gui_snapshot(make_window, app, monkeypatch):
    window, source = make_window(lambda query, limit, order: tracks(limit, order))
    read_data = window.search_order.currentData

    def gui_data():
        assert QThread.currentThread() == app.thread()
        return read_data()

    monkeypatch.setattr(window.search_order, "currentData", gui_data)
    window.search_query("Дора")
    wait_for(lambda: settled(window))
    window.show_more.click()
    wait_for(lambda: settled(window))
    for index, order in [(1, "views")]:
        window.search_order.setCurrentIndex(index)
        wait_for(lambda: settled(window))
        assert source.calls[-1] == ("Дора", 40, order)
        assert len(window.search_results) == 40
        assert window.search_results[0].title.startswith(order)
    assert [window.search_order.itemData(i) for i in range(2)] == ["relevance", "views"]


def test_load_more_up_to_cap_preserves_selection_and_scroll(make_window, app, tmp_path):
    window, source = make_window(lambda query, limit, order: tracks(limit))
    window.search_query("Дора")
    wait_for(lambda: settled(window))
    assert window.show_more.isVisible()
    window.track_list.setCurrentRow(10)
    window.track_list.verticalScrollBar().setValue(300)
    scroll = window.track_list.verticalScrollBar().value()
    for count in (80, 120):
        window.show_more.click()
        wait_for(lambda: settled(window))
        assert window.track_list.count() == count
        assert len({track.video_id for track in window.search_results}) == count
        assert window.track_list.currentRow() == 10
        assert window.track_list.verticalScrollBar().value() == scroll
    assert not window.show_more.isVisible()
    assert "120" in window.search_status.text()
    window._load_more()
    assert [call[1] for call in source.calls] == [40, 80, 120]
    assert window.search_order.width() >= 188
    window.grab().save(str(tmp_path / "riffuna-search.png"))


@pytest.mark.parametrize("change", ["query", "sort"])
@pytest.mark.parametrize("late_error", [False, True])
def test_stale_page_cannot_replace_new_search(make_window, change, late_error):
    release = threading.Event()
    started = threading.Event()

    def handler(query, limit, order):
        if limit == 80:
            started.set()
            assert release.wait(5)
            if late_error:
                raise RuntimeError("obsolete failure")
        return tracks(limit, query + order)

    window, source = make_window(handler, release)
    window.search_query("old")
    wait_for(lambda: settled(window))
    window.show_more.click()
    wait_for(started.is_set)
    assert not window.show_more.isEnabled()
    assert window.play_all.isEnabled()
    if change == "query":
        window.search_query("new")
    else:
        window.search_order.setCurrentIndex(1)
    wait_for(lambda: not window._search_loading)
    expected = "newrelevance" if change == "query" else "oldviews"
    assert window.search_results[0].title.startswith(expected)
    release.set()
    wait_for(lambda: settled(window))
    assert window._search_limit == 40
    assert len(window.search_results) == 40
    assert window.search_results[0].title.startswith(expected)
    assert not window._search_error
    assert window.show_more.isEnabled()
    assert "obsolete" not in window.search_status.text()


def test_failed_load_more_keeps_results_and_retry_limit(make_window):
    release = threading.Event()
    started = threading.Event()
    attempts = Counter()

    def handler(query, limit, order):
        attempts[limit] += 1
        if limit == 80 and attempts[limit] == 1:
            started.set()
            assert release.wait(5)
            raise RuntimeError("Нет сети")
        return tracks(55 if limit == 80 else limit)

    window, source = make_window(handler, release)
    window.search_query("Дора")
    wait_for(lambda: settled(window))
    prepared = list(window.prefetched)
    assert prepared == window.search_results[:2]
    window.show_more.click()
    wait_for(started.is_set)
    window._load_more()
    window.show_more.click()
    window.search()
    assert window.track_list.count() == 40
    assert window._search_loading
    assert not window.show_more.isEnabled()
    release.set()
    wait_for(lambda: settled(window))
    assert window.track_list.count() == 40
    assert window.show_more.text() == "Повторить загрузку"
    assert "Нет сети" in window.search_status.text()
    assert window.prefetched == prepared
    window.show_more.click()
    wait_for(lambda: settled(window))
    assert window.track_list.count() == 55
    assert [call[1] for call in source.calls] == [40, 80, 80]
    assert not window.show_more.isVisible()
    assert not window._search_error
    assert window.prefetched == prepared


def test_navigation_during_search_preserves_library_and_loading_state(make_window):
    release = threading.Event()
    started = threading.Event()

    def handler(query, limit, order):
        started.set()
        assert release.wait(5)
        return tracks(3)

    window, source = make_window(handler, release)
    liked = Track("aaaaaaaaaaa", "Liked track")
    window.toggle_like(liked)
    window.playback.add(liked)
    window.search_query("Дора")
    wait_for(started.is_set)
    window.show_view("likes")
    assert window.visible_tracks == [liked]
    assert not window.search_controls.isVisible()
    window.show_view("search")
    assert "Ищем" in window.empty_title.text()
    assert not window.play_all.isEnabled()
    assert window.visible_tracks == []
    window.show_view("likes")
    release.set()
    wait_for(lambda: settled(window))
    assert window.visible_tracks == [liked]
    assert window.queue_list.count() == 1
    window.show_view("search")
    assert window.track_list.count() == 3
    assert window.search_controls.isVisible()
    assert window.search_footer.isVisible()
    assert not window.show_more.isVisible()


def test_initial_error_retry_and_empty_result(make_window):
    calls = 0

    def handler(query, limit, order):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Нет сети")
        return []

    window, source = make_window(handler)
    window.search_query("missing")
    wait_for(lambda: settled(window))
    assert window.empty_title.text() == "Не удалось выполнить поиск"
    assert window.retry.isVisible()
    assert not window.play_all.isEnabled()
    assert not window.search_footer.isVisible()
    window.show_view("history")
    window.show_view("search")
    assert window.empty_title.text() == "Не удалось выполнить поиск"
    window.retry.click()
    wait_for(lambda: settled(window))
    assert window.empty_title.text() == "Ничего не найдено"
    assert not window.retry.isVisible()
    assert not window.show_more.isVisible()
    assert not window.search_footer.isVisible()
    assert source.calls == [("missing", 40, "relevance")] * 2


@pytest.mark.parametrize("count", [100, 120])
def test_last_page_message_matches_actual_count(make_window, count):
    window, source = make_window(lambda query, limit, order: tracks(min(limit, count)))
    window.search_query("test")
    wait_for(lambda: settled(window))
    for _ in range(2):
        window.show_more.click()
        wait_for(lambda: settled(window))
    assert len(window.search_results) == count
    assert not window.show_more.isVisible()
    assert ("лимит" in window.search_status.text()) == (count == 120)


def test_metadata_shows_only_available_real_counts(make_window):
    window, source = make_window(lambda query, limit, order: tracks(3))
    window.search_query("test")
    wait_for(lambda: settled(window))
    assert "Просмотры: 1\u202f234\u202f567" in window.rows[0].metadata.toolTip()
    assert "Просмотры: 0" in window.rows[1].metadata.toolTip()
    assert window.rows[2].metadata.toolTip() == "Artist · YouTube"


def test_empty_query_does_not_submit_and_source_prefix_is_deduplicated(make_window):
    results = tracks(39)
    window, source = make_window(lambda query, limit, order: results + results[:1])
    window.search_query("  ")
    assert not source.calls
    window.search_query("test")
    wait_for(lambda: settled(window))
    assert len(window.search_results) == 39
    assert window.track_list.count() == 39
    assert not window.show_more.isVisible()



def enter_row(row):
    point = QPointF(12, 12)
    QApplication.sendEvent(row, QEnterEvent(point, point, point))


def test_hover_waits_300ms_cancels_on_leave_and_emits_once(make_window):
    window, source = make_window(lambda query, limit, order: tracks(3))
    window.search_query("test")
    wait_for(lambda: settled(window))
    window.prefetched.clear()
    row = window.rows[1]
    spy = QSignalSpy(row.hovered)
    enter_row(row)
    assert row._hover_timer.interval() == 300
    QTest.qWait(120)
    assert spy.count() == 0
    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    QTest.qWait(350)
    assert spy.count() == 0
    assert not window.prefetched
    enter_row(row)
    wait_for(lambda: spy.count() == 1)
    assert spy.at(0)[0] == row.track
    assert window.prefetched == [row.track]
    QTest.qWait(350)
    assert spy.count() == 1
    assert window.playback.current is None
    assert window.playback.player.source().isEmpty()
    assert not window.library.history()


@pytest.mark.parametrize("action", ["hide", "navigate", "close"])
def test_hidden_or_removed_row_cancels_pending_hover(make_window, action):
    window, source = make_window(lambda query, limit, order: tracks(2))
    window.search_query("test")
    wait_for(lambda: settled(window))
    window.prefetched.clear()
    row = window.rows[1]
    enter_row(row)
    if action == "hide":
        row.hide()
    elif action == "navigate":
        window.show_view("likes")
    else:
        window.close()
    QTest.qWait(350)
    assert not window.prefetched


def test_first_two_results_prefetched_only_for_fresh_successful_search(make_window):
    window, source = make_window(lambda query, limit, order: tracks(limit, query + order))
    window.search_query("first")
    wait_for(lambda: settled(window))
    prepared = list(window.search_results[:2])
    assert window.prefetched == prepared
    window.show_more.click()
    wait_for(lambda: settled(window))
    assert window.prefetched == prepared
    window.search_order.setCurrentIndex(1)
    wait_for(lambda: settled(window))
    prepared += window.search_results[:2]
    assert window.prefetched == prepared
    assert [track.title for track in prepared[-2:]] == ["firstviews 0", "firstviews 1"]
    window.search_query("second")
    wait_for(lambda: settled(window))
    prepared += window.search_results[:2]
    assert window.prefetched == prepared
    assert [track.title for track in prepared[-2:]] == ["secondviews 0", "secondviews 1"]
    assert window.playback.current is None
    assert not window.playback.queue.tracks
    assert window.playback.player.source().isEmpty()
    assert not window.library.history()


@pytest.mark.parametrize("count", [1, 2])
def test_small_result_set_prefetches_available_tracks_without_autoplay(make_window, count):
    window, source = make_window(lambda query, limit, order: tracks(count))
    window.search_query("test")
    wait_for(lambda: settled(window))
    assert len(window.prefetched) == count
    assert window.prefetched == window.search_results
    assert window.playback.current is None
    assert not window.playback.queue.tracks
    assert window.playback.player.source().isEmpty()
    assert not window.library.history()


@pytest.mark.parametrize("late_error", [False, True])
def test_stale_initial_search_does_not_prefetch(make_window, late_error):
    release = threading.Event()
    started = threading.Event()

    def handler(query, limit, order):
        if query == "old":
            started.set()
            assert release.wait(5)
            if late_error:
                raise RuntimeError("Obsolete search failure")
        return tracks(3, query)

    window, source = make_window(handler, release)
    window.search_query("old")
    wait_for(started.is_set)
    window.search_query("new")
    wait_for(lambda: not window._search_loading)
    prepared = list(window.prefetched)
    assert [track.title for track in prepared] == ["new 0", "new 1"]
    release.set()
    wait_for(lambda: settled(window))
    assert window.prefetched == prepared
    assert not window._search_error
    assert window.playback.current is None
    assert not window.playback.queue.tracks
    assert window.playback.player.source().isEmpty()
    assert not window.library.history()


def test_failed_or_empty_search_does_not_prefetch(make_window):
    def handler(query, limit, order):
        if query == "failed":
            raise RuntimeError("Нет сети")
        return []

    window, source = make_window(handler)
    for query in ("failed", "empty"):
        window.search_query(query)
        wait_for(lambda: settled(window))
        assert not window.prefetched
        assert window.playback.current is None
        assert not window.playback.queue.tracks
        assert window.playback.player.source().isEmpty()
        assert not window.library.history()


def test_views_tooltip_explains_candidate_scope(make_window):
    window, source = make_window(lambda query, limit, order: [])
    assert window.search_order.count() == 2
    tooltip = "Среди найденных музыкальных записей"
    assert window.search_order.itemData(1, Qt.ItemDataRole.ToolTipRole) == tooltip
    window.search_order.setCurrentIndex(1)
    assert window.search_order.toolTip() == tooltip
    window.search_order.setCurrentIndex(0)
    assert not window.search_order.toolTip()


def test_playing_low_queue_entry_preserves_scroll_and_selection(make_window, app, monkeypatch):
    window, _ = make_window(lambda query, limit, order: [])
    monkeypatch.setattr(window.playback, "_open_current", lambda: None)
    for track in tracks(35):
        window.playback.add(track)
    app.processEvents()
    item = window.queue_list.item(29)
    window.queue_list.setCurrentItem(item)
    window.queue_list.scrollToItem(item)
    app.processEvents()
    position = window.queue_list.verticalScrollBar().value()
    assert position > 0
    row = window.queue_list.itemWidget(item)
    row.play_requested.emit(item.data(Qt.ItemDataRole.UserRole))
    app.processEvents()
    assert window.queue_list.verticalScrollBar().value() == position
    assert window.queue_list.currentItem().data(Qt.ItemDataRole.UserRole) == tracks(35)[29]
    assert len(window.playback.queue.tracks) == 35


def test_history_refresh_does_not_jump_to_top(make_window, app):
    window, _ = make_window(lambda query, limit, order: [])
    for track in tracks(35):
        window.library.record_play(track)
    window.show_view("history")
    app.processEvents()
    window.track_list.verticalScrollBar().setValue(900)
    position = window.track_list.verticalScrollBar().value()
    assert position > 0
    window.library.record_play(tracks(35)[2])
    window._history_changed()
    app.processEvents()
    assert window.track_list.verticalScrollBar().value() == position


def test_repeat_button_cycles_off_one_all(make_window):
    window, _ = make_window(lambda query, limit, order: [])
    for mode, checked in (("one", True), ("all", True), ("off", False)):
        window.repeat_button.click()
        assert window.playback.repeat_mode == mode
        assert window.repeat_button.isChecked() == checked
        assert window.repeat_button.accessibleName()
