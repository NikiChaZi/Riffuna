from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .branding import DATA_FOLDER
from .models import PlayQueue, Track


def data_directory() -> Path:
    override = os.environ.get("MUSICDESK_DATA_DIR")
    if override:
        return Path(override)
    # A profile folder is stable across Explorer and MSIX-hosted launchers.
    return Path.home() / ".riffuna"


class Library:
    def __init__(self, path: Path | None = None):
        self.path = path or data_directory() / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = DELETE")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                video_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                artist TEXT NOT NULL, duration INTEGER NOT NULL, thumbnail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS likes (
                video_id TEXT PRIMARY KEY REFERENCES tracks(video_id),
                liked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS plays (
                id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES tracks(video_id),
                played_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS queue (
                position INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES tracks(video_id)
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self._migrate_playlists()

    def _migrate_playlists(self):
        """Add playlist tables without rewriting the original library tables."""
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS user_playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 100)
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS playlist_items (
                    playlist_id INTEGER NOT NULL REFERENCES user_playlists(id) ON DELETE CASCADE,
                    video_id TEXT NOT NULL REFERENCES tracks(video_id),
                    position INTEGER NOT NULL CHECK(position >= 0),
                    PRIMARY KEY (playlist_id, video_id),
                    UNIQUE (playlist_id, position)
                )
            """)
            if version < 2:
                self.db.execute("PRAGMA user_version = 2")

    @staticmethod
    def _playlist_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("Playlist name must be text")
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Playlist name must contain 1 to 100 characters")
        return name

    def _require_playlist(self, playlist_id: int) -> None:
        if not self.db.execute("SELECT 1 FROM user_playlists WHERE id=?", (playlist_id,)).fetchone():
            raise ValueError("Unknown playlist")

    def playlists(self) -> list[dict]:
        """Return newest-created playlists first, including empty playlists."""
        return [dict(row) for row in self.db.execute("""
            SELECT p.id, p.name, COUNT(i.video_id) AS track_count,
                   COALESCE((SELECT t.thumbnail FROM playlist_items first_item
                             JOIN tracks t USING(video_id)
                             WHERE first_item.playlist_id=p.id
                             ORDER BY first_item.position LIMIT 1), '') AS thumbnail
            FROM user_playlists p LEFT JOIN playlist_items i ON i.playlist_id=p.id
            GROUP BY p.id, p.name ORDER BY p.id DESC
        """)]

    def create_playlist(self, name: str) -> int:
        name = self._playlist_name(name)
        with self.db:
            cursor = self.db.execute("INSERT INTO user_playlists(name) VALUES (?)", (name,))
        return int(cursor.lastrowid)

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        name = self._playlist_name(name)
        self._require_playlist(playlist_id)
        with self.db:
            self.db.execute("UPDATE user_playlists SET name=? WHERE id=?", (name, playlist_id))

    def delete_playlist(self, playlist_id: int) -> None:
        """Delete only playlist membership, retaining tracks, likes and history."""
        self._require_playlist(playlist_id)
        with self.db:
            self.db.execute("DELETE FROM user_playlists WHERE id=?", (playlist_id,))

    def playlist_tracks(self, playlist_id: int) -> list[Track]:
        """Unknown playlist IDs raise ValueError for this and all mutations."""
        self._require_playlist(playlist_id)
        return [self._track(row) for row in self.db.execute("""
            SELECT t.* FROM playlist_items i JOIN tracks t USING(video_id)
            WHERE i.playlist_id=? ORDER BY i.position
        """, (playlist_id,))]

    def add_to_playlist(self, playlist_id: int, track: Track) -> None:
        """Append a new video ID; duplicate additions preserve its position."""
        self._require_playlist(playlist_id)
        with self.db:
            self._upsert(track)
            self.db.execute("""
                INSERT OR IGNORE INTO playlist_items(playlist_id, video_id, position)
                SELECT ?, ?, COUNT(*) FROM playlist_items WHERE playlist_id=?
            """, (playlist_id, track.video_id, playlist_id))

    def _playlist_order(self, playlist_id: int) -> list[str]:
        self._require_playlist(playlist_id)
        return [row[0] for row in self.db.execute(
            "SELECT video_id FROM playlist_items WHERE playlist_id=? ORDER BY position", (playlist_id,))]

    def _replace_playlist_order(self, playlist_id: int, video_ids: list[str]) -> None:
        # Reinsert within one transaction to avoid UNIQUE-position collisions.
        with self.db:
            self.db.execute("DELETE FROM playlist_items WHERE playlist_id=?", (playlist_id,))
            self.db.executemany("INSERT INTO playlist_items(playlist_id, video_id, position) VALUES (?, ?, ?)",
                                ((playlist_id, video_id, position) for position, video_id in enumerate(video_ids)))

    def remove_from_playlist(self, playlist_id: int, video_id: str) -> None:
        """An absent video ID is a no-op in an existing playlist."""
        order = self._playlist_order(playlist_id)
        if video_id in order:
            order.remove(video_id)
            self._replace_playlist_order(playlist_id, order)

    def move_playlist_track(self, playlist_id: int, video_id: str, offset: int) -> None:
        """Move by -1/+1; missing tracks and moves past an edge are no-ops."""
        if offset not in (-1, 1):
            raise ValueError("Playlist move offset must be -1 or +1")
        order = self._playlist_order(playlist_id)
        if video_id not in order:
            return
        index = order.index(video_id)
        destination = index + offset
        if 0 <= destination < len(order):
            order[index], order[destination] = order[destination], order[index]
            self._replace_playlist_order(playlist_id, order)

    def _upsert(self, track: Track):
        self.db.execute("""
            INSERT INTO tracks VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,
            artist=excluded.artist, duration=excluded.duration, thumbnail=excluded.thumbnail
        """, (track.video_id, track.title, track.artist, track.duration, track.thumbnail))

    def like(self, track: Track, value: bool) -> None:
        with self.db:
            self._upsert(track)
            if value:
                self.db.execute("INSERT OR IGNORE INTO likes(video_id) VALUES (?)", (track.video_id,))
            else:
                self.db.execute("DELETE FROM likes WHERE video_id=?", (track.video_id,))

    def liked_ids(self) -> set[str]:
        return {row[0] for row in self.db.execute("SELECT video_id FROM likes")}

    @staticmethod
    def _track(row: sqlite3.Row) -> Track:
        return Track(**{key: row[key] for key in ("video_id", "title", "artist", "duration", "thumbnail")})

    def liked_tracks(self) -> list[Track]:
        return [self._track(row) for row in self.db.execute("""
            SELECT t.* FROM likes l JOIN tracks t USING(video_id)
            ORDER BY l.liked_at DESC, l.rowid DESC
        """)]

    def record_play(self, track: Track) -> None:
        with self.db:
            self._upsert(track)
            self.db.execute("INSERT INTO plays(video_id) VALUES (?)", (track.video_id,))

    def history(self, limit: int = 100) -> list[Track]:
        return [self._track(row) for row in self.db.execute("""
            SELECT t.* FROM tracks t JOIN
            (SELECT video_id, MAX(id) AS latest FROM plays GROUP BY video_id) p
            USING(video_id) ORDER BY p.latest DESC LIMIT ?
        """, (limit,))]

    def save_queue(self, queue: PlayQueue) -> None:
        with self.db:
            self.db.execute("DELETE FROM queue")
            for index, track in enumerate(queue.tracks):
                self._upsert(track)
                self.db.execute("INSERT INTO queue VALUES (?, ?)", (index, track.video_id))
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('queue_index', ?)", (str(queue.index),))

    def load_queue(self) -> PlayQueue:
        tracks = [self._track(row) for row in self.db.execute(
            "SELECT t.* FROM queue q JOIN tracks t USING(video_id) ORDER BY q.position"
        )]
        try:
            index = int(self.get_setting("queue_index", "-1"))
        except ValueError:
            index = -1
        if index < -1 or index >= len(tracks):
            index = -1
        return PlayQueue(tracks, index)

    def save_current(self, track: Track | None) -> None:
        with self.db:
            if track:
                self._upsert(track)
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('current_track', ?)",
                            (track.video_id if track else "",))

    def load_current(self) -> Track | None:
        video_id = self.get_setting("current_track", "")
        row = self.db.execute("SELECT * FROM tracks WHERE video_id=?", (video_id,)).fetchone()
        return self._track(row) if row else None

    def get_setting(self, key: str, default: str) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))

    def prefer_recording(self, original: Track, replacement: Track) -> None:
        # An explicit version choice never rewrites existing likes or history.
        from .recording_versions import work_key
        with self.db:
            self._upsert(original)
            self._upsert(replacement)
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)",
                            ("recording:" + work_key(original), replacement.video_id))

    def preferred_recording(self, track: Track) -> Track:
        from .recording_versions import work_key
        selected = self.get_setting("recording:" + work_key(track), "")
        row = self.db.execute("SELECT * FROM tracks WHERE video_id=?", (selected,)).fetchone() if selected else None
        return self._track(row) if row else track

    def close(self):
        self.db.close()

