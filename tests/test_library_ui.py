from dataclasses import replace
from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton, QLabel
from musicdesk.widgets import Cover
from test_ui_search import app, make_window, tracks as original_tracks


def tracks(count):
    return [replace(track, view_count=None) for track in original_tracks(count)]


def test_queue_controls_start_existing_list_and_shuffle_without_reordering(make_window, monkeypatch):
    window, source = make_window(lambda query, limit, order: [])
    records = tracks(5)
    for record in records:
        window.playback.add(record)
    opened = []
    monkeypatch.setattr(window.playback, "_open_current", lambda: opened.append(window.playback.current))
    window.playback.play(records[3])
    window.queue_play.click()
    assert opened[-1] == records[0]
    assert window.playback.queue.tracks == records
    window.queue_shuffle.click()
    assert window.playback.shuffle and window.shuffle_button.isChecked()
    window.queue_play.click()
    chosen = [window.playback.current.video_id]
    for _ in range(4):
        window.next_button.click()
        chosen.append(window.playback.current.video_id)
    assert len(set(chosen)) == 5
    assert window.playback.queue.tracks == records
    assert not window.next_button.isEnabled()
    window.shuffle_button.click()
    assert not window.playback.shuffle and not window.queue_shuffle.isChecked()


def test_create_playlist_from_queue_edit_and_play(make_window, monkeypatch):
    window, source = make_window(lambda query, limit, order: [])
    records = tracks(3)
    for record in records:
        window.playback.add(record)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("  В дорогу  ", True))
    window.queue_save.click()
    playlist = window.library.playlists()[0]
    assert playlist["name"] == "В дорогу" and playlist["track_count"] == 3
    assert window.view == "playlist" and window.visible_tracks == records
    key = playlist["id"]
    window._add_to_playlist(key, records[0])
    assert window.library.playlist_tracks(key) == records
    window._move_playlist_track(key, records[2], -1)
    assert window.visible_tracks == [records[0], records[2], records[1]]
    opened_at = []
    monkeypatch.setattr(window.playback, "_open_current", lambda: opened_at.append(window.playback.current))
    window.rows[1].play_button.click()
    assert opened_at == [records[2]]
    assert window.playback.queue.tracks == window.visible_tracks
    assert window.playback.queue.index == 1
    window._remove_from_playlist(key, records[0])
    assert window.visible_tracks == [records[2], records[1]]
    opened = []
    monkeypatch.setattr(window.playback, "_open_current", lambda: opened.append(window.playback.current))
    window.play_all.click()
    assert opened == [records[2]]
    assert window.playback.queue.tracks == [records[2], records[1]]
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Новый заголовок", True))
    window._rename_playlist(key)
    assert window.page_title.toolTip() == "Новый заголовок"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window._delete_playlist(key)
    assert window.library.playlists()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._delete_playlist(key)
    assert not window.library.playlists() and window.view == "playlists"
    assert window.playback.queue.tracks == [records[2], records[1]]


def test_home_create_action_and_track_menu_add_playlist(make_window, monkeypatch):
    window, source = make_window(lambda query, limit, order: [])
    records = tracks(2)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Избранная подборка", True))
    menu = window._make_track_menu(records[0])
    actions = menu.actions()
    submenu = actions[3].menu()
    submenu.actions()[-1].trigger()
    playlist = window.library.playlists()[0]
    assert window.library.playlist_tracks(playlist["id"]) == [records[0]]
    window.library.like(records[1], True)
    window.show_view("home")
    assert window.home.findChildren(QPushButton, "trackTile")
    assert window.home.findChildren(Cover)
    labels = [child.text() for child in window.home.findChildren(QLabel)]
    assert "Отправная точка" not in labels
    assert "ПРИМЕРЫ ПОИСКА" not in labels
    window.show_view("playlists")
    tile = window.playlist_page.findChildren(QPushButton, "playlistTile")[0]
    tile.click()
    assert window.view == "playlist" and window.visible_tracks == [records[0]]


def test_cancel_and_invalid_playlist_names_leave_library_unchanged(make_window, monkeypatch):
    window, source = make_window(lambda query, limit, order: [])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Name", False))
    window._create_playlist()
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("   ", True))
    window._create_playlist()
    assert not window.library.playlists()
    assert window.notice.isVisible()
