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
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / DATA_FOLDER


class Library:
    def __init__(self, path: Path | None = None):
        self.path = path or data_directory() / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
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
            PRAGMA user_version = 1;
        """)

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

    def get_setting(self, key: str, default: str) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))

    def close(self):
        self.db.close()

