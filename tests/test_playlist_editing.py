import sqlite3

import pytest

from musicdesk.models import PlayQueue, Track
from musicdesk.storage import Library


def t(index):
    return Track(f"{index:011d}", f"Track {index}", "Artist", 180)


def ids(library, playlist):
    return [track.video_id for track in library.playlist_tracks(playlist)]


@pytest.fixture
def library(tmp_path):
    value = Library(tmp_path / "library.sqlite3")
    yield value
    value.close()


def test_v2_migration_preserves_playlist_membership_details_and_future_schema(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE user_playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        INSERT INTO user_playlists VALUES (8, 'Old mix');
        PRAGMA user_version=2;
    """)
    old.close()
    library = Library(path)
    assert library.playlist_details(8)["description"] == ""
    assert library.playlists()[0]["name"] == "Old mix"
    assert library.db.execute("PRAGMA user_version").fetchone()[0] == 3
    library.update_playlist_details(8, " New name ", "  Personal selection  ")
    library.db.execute("PRAGMA user_version=7")
    library.close()
    reopened = Library(path)
    try:
        assert reopened.playlist_details(8)["description"] == "Personal selection"
        assert reopened.playlist_details(8)["name"] == "New name"
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert not reopened.db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        reopened.close()


def test_copy_bulk_edit_and_reorder_preserve_other_library_state(library):
    a, b, c = t(1), t(2), t(3)
    original = library.create_playlist("Mix")
    library.update_playlist_details(original, "Mix", "For a walk")
    library.like(a, True)
    library.record_play(a)
    library.save_queue(PlayQueue([a, b], 1))
    assert library.add_tracks_to_playlist(original, [a, a, b]) == 2
    assert library.add_tracks_to_playlist(original, [c, b]) == 1
    duplicate = library.duplicate_playlist(original)
    assert library.playlist_details(duplicate)["description"] == "For a walk"
    assert library.playlist_details(duplicate)["name"] == "Mix — копия"
    assert ids(library, duplicate) == [a.video_id, b.video_id, c.video_id]
    library.reorder_playlist(duplicate, [c.video_id, a.video_id, b.video_id])
    assert library.remove_tracks_from_playlist(duplicate, [a.video_id, a.video_id, t(9).video_id]) == 1
    assert ids(library, duplicate) == [c.video_id, b.video_id]
    assert ids(library, original) == [a.video_id, b.video_id, c.video_id]
    assert library.liked_ids() == {a.video_id}
    assert library.history() == [a]
    assert library.load_queue() == PlayQueue([a, b], 1)
    assert [row[0] for row in library.db.execute(
        "SELECT position FROM playlist_items WHERE playlist_id=? ORDER BY position", (duplicate,))] == [0, 1]


def test_invalid_edits_do_not_partially_modify_playlist(library):
    playlist = library.create_playlist("Safe")
    a, b = t(1), t(2)
    library.add_tracks_to_playlist(playlist, [a, b])
    for wrong in ([a.video_id], [a.video_id, a.video_id], [a.video_id, t(9).video_id], [None, b.video_id]):
        with pytest.raises(ValueError):
            library.reorder_playlist(playlist, wrong)
        assert ids(library, playlist) == [a.video_id, b.video_id]
    with pytest.raises(ValueError):
        library.add_tracks_to_playlist(playlist, [t(3), None])
    assert ids(library, playlist) == [a.video_id, b.video_id]
    assert not library.db.execute("SELECT 1 FROM tracks WHERE video_id=?", (t(3).video_id,)).fetchone()
    for description in (None, "x"*2001):
        with pytest.raises(ValueError):
            library.update_playlist_details(playlist, "Changed", description)
    assert library.playlist_details(playlist)["name"] == "Safe"
    with pytest.raises(ValueError):
        library.duplicate_playlist(playlist, " ")
    assert len(library.playlists()) == 1


def test_empty_and_missing_playlists_are_consistent(library):
    playlist = library.create_playlist("x"*100)
    copy = library.duplicate_playlist(playlist)
    assert len(library.playlist_details(copy)["name"]) == 100
    assert library.add_tracks_to_playlist(copy, []) == 0
    assert library.remove_tracks_from_playlist(copy, []) == 0
    library.reorder_playlist(copy, [])
    for operation in (lambda: library.playlist_details(900), lambda: library.duplicate_playlist(900),
                      lambda: library.add_tracks_to_playlist(900, []),
                      lambda: library.remove_tracks_from_playlist(900, []),
                      lambda: library.reorder_playlist(900, []),
                      lambda: library.update_playlist_details(900, "Missing", "")):
        with pytest.raises(ValueError, match="Unknown playlist"):
            operation()
