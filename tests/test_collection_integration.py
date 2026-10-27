"""Real UI actions against an isolated library; no network or audio."""
from dataclasses import replace

from PySide6.QtCore import QItemSelectionModel, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from musicdesk.track_list import moved_order
from test_ui_search import app, make_window, tracks


def seed(window):
    records = [replace(t, title=title, artist=artist, duration=duration, view_count=None)
               for t, (title, artist, duration) in zip(tracks(4), (
                   ('Бета', 'Фонарь', 200), ('Альфа', 'Север', 150),
                   ('Гамма', 'Фонарь', 300), ('Дельта', 'Заря', 180)))]
    key = window.library.create_playlist('Подборка')
    window.library.add_tracks_to_playlist(key, records)
    return key, records


def select(window, rows):
    window.track_list.clearSelection()
    for row in rows:
        window.track_list.item(row).setSelected(True)


def test_local_filter_sort_and_play_use_visible_order_without_mutating_playlist(make_window, monkeypatch):
    window, source = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    window.list_tools.search_input.setText('фонарь')
    assert window.visible_tracks == [records[0], records[2]]
    assert not window.track_list.dragEnabled()
    window.list_tools.search_input.clear()
    window.list_tools.sort_order.setCurrentIndex(window.list_tools.sort_order.findData('title'))
    assert window.visible_tracks == [records[1], records[0], records[2], records[3]]
    opened = []
    monkeypatch.setattr(window.playback, '_open_current', lambda: opened.append(window.playback.current))
    window.rows[1].play_button.click()
    assert opened == [records[0]]
    assert window.playback.queue.tracks == window.visible_tracks
    assert window.library.playlist_tracks(key) == records
    assert not source.calls
    window.list_tools.search_input.setText('missing')
    assert not window.visible_tracks
    assert window.empty_title.text() == 'В этом списке ничего не найдено'
    assert not window.play_all.isEnabled()
    window.show_view('home')
    window._show_playlist(key)
    assert window.list_tools.query == 'missing'


def test_multi_select_batch_actions_deduplicate_and_keep_order(make_window):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    select(window, [0, 2])
    assert window._selected_tracks() == [records[0], records[2]]
    assert window.list_tools.selection_label.text() == 'Выбрано: 2'
    changes = QSignalSpy(window.playback.queue_changed)
    window.list_tools.queue_button.click()
    window.list_tools.queue_button.click()
    assert window.playback.queue.tracks == [records[0], records[2]]
    assert changes.count() == 1
    target = window.library.create_playlist('Копия выбранного')
    window._save_tracks_to_playlist(target, window._selected_tracks())
    assert window.library.playlist_tracks(target) == [records[0], records[2]]
    window.list_tools.remove_button.click()
    assert window.library.playlist_tracks(key) == [records[1], records[3]]
    assert window.playback.queue.tracks == [records[0], records[2]]


def test_playlist_reorder_persists_and_is_blocked_when_filtered(make_window, app):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    select(window, [1, 2])
    window.track_list.setFocus()
    QTest.keyClick(window.track_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert window.library.playlist_tracks(key) == [records[1], records[2], records[0], records[3]]
    assert {t.video_id for t in window._selected_tracks()} == {records[1].video_id, records[2].video_id}
    window.list_tools.search_input.setText('артист')
    window._reorder_playlist([r.video_id for r in records])
    assert window.library.playlist_tracks(key)[0] == records[1]


def test_queue_bulk_reorder_and_clear_preserve_current_audio(make_window, monkeypatch):
    window, _ = make_window(lambda *args: [])
    _, records = seed(window)
    window.playback.add_many(records)
    monkeypatch.setattr(window.playback, '_open_current', lambda: None)
    window.playback.play(records[1])
    window._reorder_queue([records[3].video_id, records[0].video_id, records[1].video_id, records[2].video_id])
    assert window.playback.queue.current == records[1]
    window.queue_list.item(0).setSelected(True)
    window.queue_list.item(1).setSelected(True)
    window.queue_remove_selected.click()
    assert window.playback.queue.tracks == [records[1], records[2]]
    window.queue_clear.click()
    assert not window.playback.queue.tracks
    assert window.playback.current == records[1]
    assert not window.queue_clear.isEnabled()


def test_next_context_action_and_artist_link(make_window, monkeypatch):
    window, _ = make_window(lambda *args: [])
    _, records = seed(window)
    window.playback.add_many(records)
    monkeypatch.setattr(window.playback, '_open_current', lambda: None)
    window.playback.play(records[0])
    menu = window._make_track_menu(records[3])
    actions = {a.text(): a for a in menu.actions()}
    actions['Слушать следующим'].trigger()
    window.playback.next()
    assert window.playback.current == records[3]
    actions['Копировать ссылку'].trigger()
    assert QApplication.clipboard().text() == records[3].url
    searched = []
    monkeypatch.setattr(window, 'search_query', searched.append)
    actions['Найти исполнителя'].trigger()
    assert searched == [records[3].artist]
    menu.deleteLater()


def test_navigation_returns_to_playlist_filter_and_survives_deleted_playlist(make_window):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    window.list_tools.search_input.setText('бета')
    window.show_view('likes')
    window.back_button.click()
    assert window.view == 'playlist' and window.visible_tracks == [records[0]]
    window.forward_button.click()
    assert window.view == 'likes'
    window.library.delete_playlist(key)
    window.back_button.click()
    assert window.view == 'home'


def test_like_batch_removes_membership_only_and_preserves_filter(make_window):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    for track in records:
        window.library.like(track, True)
    window.show_view('likes')
    window.list_tools.search_input.setText('фонарь')
    select(window, list(range(window.track_list.count())))
    window._remove_selected()
    assert window.list_tools.query == 'фонарь'
    assert not window.visible_tracks
    assert window.library.playlist_tracks(key) == records
    assert window.library.liked_ids() == {records[1].video_id, records[3].video_id}


def test_shortcuts_leave_text_navigation_enabled(make_window, app):
    window, _ = make_window(lambda *args: [])
    window.search_input.setFocus()
    app.processEvents()
    assert all(not s.isEnabled() for s in window._transport_shortcuts)
    window.nav["home"].setFocus()
    app.processEvents()
    assert all(s.isEnabled() for s in window._transport_shortcuts)


def test_reorder_boundaries_keep_selected_relative_order():
    assert moved_order(['a','b','c','d'], ['b','c'], 0) == ['b','c','a','d']
    assert moved_order(['a','b','c','d'], ['b','c'], 4) == ['a','d','b','c']
    assert moved_order(['a','b','c','d'], ['b','c'], 2) == ['a','b','c','d']
    assert moved_order(['a','b','c','d'], [], 4) == ['a','b','c','d']


def test_drop_intent_updates_playlist_without_qt_widget_model_move(make_window, app):
    from PySide6.QtCore import QByteArray, QMimeData
    import json
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    app.processEvents()
    listing = window.track_list
    mime = QMimeData()
    mime.setData(listing.MIME, QByteArray(json.dumps([records[3].video_id]).encode()))
    point = listing.visualItemRect(listing.item(0)).topLeft()
    class Drop:
        accepted = False
        def source(self): return listing
        def mimeData(self): return mime
        def position(self): return QPointF(point)
        def setDropAction(self, action): pass
        def accept(self): self.accepted = True
        def ignore(self): self.accepted = False
    event = Drop()
    listing.dropEvent(event)
    assert event.accepted
    assert window.library.playlist_tracks(key) == [records[3]] + records[:3]
    assert len(window.rows) == listing.count() == 4
    assert all(listing.itemWidget(listing.item(i)) is window.rows[i] for i in range(4))


def test_minimum_window_with_selection_keeps_all_actions_inside(make_window, app):
    window, _ = make_window(lambda *args: [])
    key, _ = seed(window)
    window.resize(1000,650)
    window._show_playlist(key)
    select(window,[0,1])
    app.processEvents()
    for widget in (window.list_tools.search_input, window.list_tools.sort_order,
                   window.list_tools.queue_button, window.list_tools.playlist_button,
                   window.list_tools.remove_button, window.queue_clear):
        assert widget.parentWidget().rect().contains(widget.geometry())
    assert window.size().width() == 1000
    assert window.track_list.height() >= 120


def test_space_toggles_playback_from_track_and_queue_lists(make_window, monkeypatch):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    calls = []
    # Connect a spy directly to the list intent: actual playback uses the same signal.
    window.track_list.toggle_requested.connect(lambda: calls.append('tracks'))
    window.queue_list.toggle_requested.connect(lambda: calls.append('queue'))
    QTest.keyClick(window.track_list, Qt.Key.Key_Space)
    QTest.keyClick(window.queue_list, Qt.Key.Key_Space)
    assert calls == ['tracks','queue']


def test_recording_choice_keeps_queue_anchor_and_original_highlight(make_window, monkeypatch):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    replacement = replace(records[1], video_id='zzzzzzzzzzz', title=records[1].title+' (Uncensored)')
    window._show_playlist(key)
    window.playback.add_many(records)
    monkeypatch.setattr(window.playback, '_open_current', lambda: None)
    window.playback.play(records[1])
    window._choose_recording(records[1], replacement)
    assert window.playback.queue.index == 1
    assert window.playback.queue.current.video_id == records[1].video_id
    # Model substitution happens in real _open_current; emulate only that boundary.
    window.playback._current = replacement
    window._on_track(replacement)
    assert window.rows[1].property('current')
    window.playback.next()
    assert window.playback.current.video_id == records[2].video_id


def test_context_play_obeys_filtered_sorted_playlist(make_window, monkeypatch):
    window, _ = make_window(lambda *args: [])
    key, records = seed(window)
    window._show_playlist(key)
    window.list_tools.search_input.setText('фонарь')
    window.list_tools.sort_order.setCurrentIndex(window.list_tools.sort_order.findData('duration'))
    monkeypatch.setattr(window.playback, '_open_current', lambda: None)
    menu = window._make_track_menu(records[0], key)
    next(a for a in menu.actions() if a.text() == 'Слушать').trigger()
    assert window.playback.queue.tracks == [records[0], records[2]]
    menu.deleteLater()
