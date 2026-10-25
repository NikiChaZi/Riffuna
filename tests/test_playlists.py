"""User playlists and additive migration of real v1 library layouts."""
import sqlite3

import pytest

from musicdesk.models import PlayQueue, Track
from musicdesk.storage import Library


def track(index, thumbnail=None):
    return Track(f"{index:011d}", f"Track {index}", "Artist", 180,
                 f"https://images.example/{index}.jpg" if thumbnail is None else thumbnail)


def ids(library, playlist_id):
    return [value.video_id for value in library.playlist_tracks(playlist_id)]


def positions(library, playlist_id):
    return [row[0] for row in library.db.execute(
        "SELECT position FROM playlist_items WHERE playlist_id=? ORDER BY position", (playlist_id,))]


def test_v1_migration_preserves_existing_tracks_likes_history_queue_current_and_settings(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    a, b = track(1), track(2)
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE tracks (video_id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,
                             duration INTEGER NOT NULL, thumbnail TEXT NOT NULL);
        CREATE TABLE likes (video_id TEXT PRIMARY KEY REFERENCES tracks(video_id), liked_at TEXT NOT NULL);
        CREATE TABLE plays (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES tracks(video_id),
                            played_at TEXT NOT NULL);
        CREATE TABLE queue (position INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES tracks(video_id));
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        PRAGMA user_version=1;
    """)
    old.executemany("INSERT INTO tracks VALUES (?, ?, ?, ?, ?)",
                    [(t.video_id, t.title, t.artist, t.duration, t.thumbnail) for t in (a, b)])
    old.execute("INSERT INTO likes VALUES (?, ?)", (a.video_id, "2026-10-25T00:00:00Z"))
    old.executemany("INSERT INTO plays VALUES (?, ?, ?)",
                    [(1, a.video_id, "2026-10-25T00:00:00Z"), (2, b.video_id, "2026-10-25T00:01:00Z")])
    old.executemany("INSERT INTO queue VALUES (?, ?)", [(0, a.video_id), (1, b.video_id)])
    old.executemany("INSERT INTO settings VALUES (?, ?)",
                    [("queue_index", "1"), ("current_track", a.video_id), ("volume", "0.65")])
    old.commit()
    old.close()
    library = Library(path)
    try:
        assert library.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert library.playlists() == []
        assert library.liked_tracks() == [a]
        assert library.history() == [b, a]
        assert library.load_queue() == PlayQueue([a, b], 1)
        assert library.load_current() == a
        assert library.get_setting("volume", "") == "0.65"
        playlist = library.create_playlist("Migrated")
        library.add_to_playlist(playlist, a)
        library.delete_playlist(playlist)
        assert library.liked_ids() == {a.video_id}
        assert library.history() == [b, a]
        assert library.load_queue() == PlayQueue([a, b], 1)
        assert not library.db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        library.close()


def test_playlist_crud_validation_cascade_and_independent_membership(tmp_path):
    library = Library(tmp_path / "library.sqlite3")
    a, b = track(1), track(2)
    try:
        first = library.create_playlist("  В дорогу  ")
        second = library.create_playlist("В дорогу")
        assert first != second
        assert library.playlists() == [
            {"id": second, "name": "В дорогу", "track_count": 0, "thumbnail": ""},
            {"id": first, "name": "В дорогу", "track_count": 0, "thumbnail": ""},
        ]
        library.rename_playlist(first, " Ночное ")
        library.like(a, True)
        library.record_play(a)
        library.add_to_playlist(first, a)
        library.add_to_playlist(second, a)
        library.add_to_playlist(second, b)
        library.delete_playlist(first)
        assert len(library.playlists()) == 1
        assert ids(library, second) == [a.video_id, b.video_id]
        assert library.liked_tracks() == [a]
        assert library.history() == [a]
        assert library.db.execute("SELECT COUNT(*) FROM playlist_items WHERE playlist_id=?", (first,)).fetchone()[0] == 0
        for invalid in ("", "  ", "x" * 101, None):
            with pytest.raises(ValueError):
                library.create_playlist(invalid)
            with pytest.raises(ValueError):
                library.rename_playlist(second, invalid)
        valid = library.create_playlist("я" * 100)
        assert library.playlists()[0]["id"] == valid
        for operation in (lambda: library.playlist_tracks(first),
                          lambda: library.rename_playlist(first, "Missing"),
                          lambda: library.delete_playlist(first),
                          lambda: library.add_to_playlist(first, a),
                          lambda: library.remove_from_playlist(first, a.video_id),
                          lambda: library.move_playlist_track(first, a.video_id, 1)):
            with pytest.raises(ValueError, match="Unknown playlist"):
                operation()
    finally:
        library.close()


def test_deduplication_removal_reordering_thumbnail_and_reopening_preserve_order(tmp_path):
    path = tmp_path / "library.sqlite3"
    library = Library(path)
    a, b, c = track(1), track(2), track(3)
    try:
        playlist = library.create_playlist("Mix")
        for value in (a, b, a, c, b):
            library.add_to_playlist(playlist, value)
        assert ids(library, playlist) == [a.video_id, b.video_id, c.video_id]
        assert positions(library, playlist) == [0, 1, 2]
        assert library.playlists()[0] == {"id": playlist, "name": "Mix", "track_count": 3, "thumbnail": a.thumbnail}
        library.move_playlist_track(playlist, a.video_id, -1)
        library.move_playlist_track(playlist, c.video_id, 1)
        assert ids(library, playlist) == [a.video_id, b.video_id, c.video_id]
        library.move_playlist_track(playlist, b.video_id, -1)
        assert ids(library, playlist) == [b.video_id, a.video_id, c.video_id]
        assert library.playlists()[0]["thumbnail"] == b.thumbnail
        library.move_playlist_track(playlist, b.video_id, 1)
        library.remove_from_playlist(playlist, b.video_id)
        library.remove_from_playlist(playlist, track(9).video_id)
        library.move_playlist_track(playlist, track(9).video_id, 1)
        assert ids(library, playlist) == [a.video_id, c.video_id]
        assert positions(library, playlist) == [0, 1]
        library.add_to_playlist(playlist, b)
        library.rename_playlist(playlist, "Saved mix")
        with pytest.raises(ValueError):
            library.move_playlist_track(playlist, a.video_id, 2)
    finally:
        library.close()
    reopened = Library(path)
    try:
        assert ids(reopened, playlist) == [a.video_id, c.video_id, b.video_id]
        assert positions(reopened, playlist) == [0, 1, 2]
        assert reopened.playlists()[0]["name"] == "Saved mix"
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == 2
        reopened.remove_from_playlist(playlist, a.video_id)
        reopened.remove_from_playlist(playlist, c.video_id)
        reopened.remove_from_playlist(playlist, b.video_id)
        assert reopened.playlists()[0]["track_count"] == 0
        assert reopened.playlists()[0]["thumbnail"] == ""
        assert positions(reopened, playlist) == []
    finally:
        reopened.close()


def test_first_track_without_thumbnail_stays_empty_and_newer_schema_version_is_not_downgraded(tmp_path):
    path = tmp_path / "library.sqlite3"
    library = Library(path)
    try:
        playlist = library.create_playlist("No cover")
        library.add_to_playlist(playlist, track(1, thumbnail=""))
        library.add_to_playlist(playlist, track(2))
        assert library.playlists()[0]["thumbnail"] == ""
        library.db.execute("PRAGMA user_version=7")
    finally:
        library.close()
    reopened = Library(path)
    try:
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert len(reopened.playlist_tracks(playlist)) == 2
    finally:
        reopened.close()


def test_default_data_path_is_stable_across_packaged_launchers(tmp_path, monkeypatch):
    from musicdesk.storage import data_directory
    from pathlib import Path
    monkeypatch.delenv("MUSICDESK_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "ordinary-appdata"))
    normal = data_directory()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "codex-package" / "LocalCache" / "Local"))
    assert data_directory() == normal == tmp_path / "user" / ".riffuna"
    monkeypatch.setenv("MUSICDESK_DATA_DIR", str(tmp_path / "isolated-tests"))
    assert data_directory() == tmp_path / "isolated-tests"
