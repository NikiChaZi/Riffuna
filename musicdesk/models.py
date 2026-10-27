from __future__ import annotations

import re
import random
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id_from_url(value: str) -> str | None:
    """Accept actual YouTube URLs, never lookalike domains or arbitrary URLs."""
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            candidate = parsed.path.split("/")[2]
        else:
            return None
    else:
        return None
    return candidate if VIDEO_ID.fullmatch(candidate) else None


def parse_duration(value: object) -> int:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            parts = [int(p) for p in value.split(":")]
            if any(p < 0 for p in parts) or len(parts) > 3:
                return 0
            result = 0
            for part in parts:
                result = result * 60 + part
            return result
        except ValueError:
            pass
    return 0


def time_label(seconds: int | float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02}:{seconds % 60:02}"
    return f"{seconds // 60}:{seconds % 60:02}"


def version_label(title: str) -> str:
    lowered = title.lower()
    for words, label in [
        (("ultra slowed", "ultraslowed"), "ULTRA SLOWED"),
        (("super slowed",), "SUPER SLOWED"),
        (("slowed", "slow +", "замедлен"), "SLOWED"),
        (("mashup", "mash up", "мэшап", "мешап"), "MASHUP"),
        (("remix", "ремикс", "bootleg"), "REMIX"),
        (("sped up", "speed up", "nightcore"), "SPED UP"),
        (("live", "концерт"), "LIVE"),
    ]:
        if any(re.search(r"(?<!\w)" + re.escape(word) + ("" if word == "замедлен" else r"(?!\w)"), lowered) for word in words):
            return label
    return ""


@dataclass(frozen=True)
class Track:
    video_id: str
    title: str
    artist: str = "YouTube"
    duration: int = 0
    thumbnail: str = ""
    view_count: int | None = None
    published: str = ""

    def __post_init__(self):
        if not VIDEO_ID.fullmatch(self.video_id):
            raise ValueError("Invalid YouTube video ID")
        if not self.title.strip():
            raise ValueError("Track title must not be empty")

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def version(self) -> str:
        return version_label(self.title)


@dataclass
class PlayQueue:
    tracks: list[Track] = field(default_factory=list)
    index: int = -1

    @property
    def current(self) -> Track | None:
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    def add(self, track: Track) -> int:
        for index, existing in enumerate(self.tracks):
            if existing.video_id == track.video_id:
                return index
        self.tracks.append(track)
        return len(self.tracks) - 1

    def move(self, source: int | str, destination: int) -> bool:
        """Move an existing entry to a final index while retaining the current ID."""
        if isinstance(source, str):
            source = next((i for i, track in enumerate(self.tracks)
                           if track.video_id == source), -1)
        if not isinstance(source, int) or not isinstance(destination, int):
            return False
        if not (0 <= source < len(self.tracks) and 0 <= destination < len(self.tracks)):
            return False
        if source == destination:
            return False
        current = self.current
        track = self.tracks.pop(source)
        self.tracks.insert(destination, track)
        if current is not None:
            self.index = next(i for i, entry in enumerate(self.tracks)
                              if entry.video_id == current.video_id)
        return True

    def insert_next(self, track: Track) -> bool:
        """Insert or move a track after the current entry without duplicating it."""
        if self.current and self.current.video_id == track.video_id:
            return False
        existing = next((i for i, entry in enumerate(self.tracks)
                         if entry.video_id == track.video_id), None)
        target = self.index + 1 if self.current is not None else 0
        if existing is None:
            self.tracks.insert(target, track)
            return True
        if existing < target:
            target -= 1
        return self.move(existing, target)

    def select(self, track: Track) -> Track:
        self.index = self.add(track)
        return track

    def remove(self, index: int) -> bool:
        if not 0 <= index < len(self.tracks):
            return False
        was_current = index == self.index
        self.tracks.pop(index)
        if not self.tracks:
            self.index = -1
        elif index < self.index:
            self.index -= 1
        elif was_current:
            self.index = min(index, len(self.tracks) - 1)
        return was_current

    def advance(self, step: int = 1, repeat: bool = False) -> Track | None:
        if not self.tracks:
            return None
        target = self.index + step
        if repeat:
            target %= len(self.tracks)
        if not 0 <= target < len(self.tracks):
            return None
        self.index = target
        return self.current



class ShuffleOrder:
    """Random traversal independent of the visible queue and its saved order."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.ids = []
        self.pending = []
        self.priority = []
        self.seen = set()
        self.history = []
        self.cursor = -1

    def reset(self, ids, current=None):
        self.ids = list(dict.fromkeys(ids))
        self.pending = self.ids.copy()
        self.priority = []
        self.rng.shuffle(self.pending)
        self.seen = set()
        self.history = []
        self.cursor = -1
        if current is not None:
            self.select(current)

    def sync(self, ids):
        ids = list(dict.fromkeys(ids))
        available = set(ids)
        self.pending = [item for item in self.pending if item in available]
        self.priority = [item for item in self.priority if item in available]
        self.seen.intersection_update(available)
        for item in ids:
            if item not in self.ids:
                self.pending.insert(self.rng.randrange(len(self.pending) + 1), item)
        self.ids = ids

    def prioritize(self, item):
        if item in self.ids:
            self.priority = [item] + [entry for entry in self.priority if entry != item]

    def select(self, item):
        self.priority = [entry for entry in self.priority if entry != item]
        # Manual selections also become part of the navigation history, while
        # a track outside the queue is never implicitly added to it.
        if self.cursor < 0 or self.history[self.cursor] != item:
            del self.history[self.cursor + 1:]
            self.history.append(item)
            self.cursor = len(self.history) - 1
        if item in self.ids:
            self.seen.add(item)
            self.pending = [entry for entry in self.pending if entry != item]

    def _forward_index(self):
        return next((index for index in range(self.cursor + 1, len(self.history))
                     if self.history[index] in self.ids), None)

    def peek(self, repeat=False):
        if self.priority:
            return self.priority[0]
        forward = self._forward_index()
        if forward is not None:
            return self.history[forward]
        if not self.pending and repeat and self.ids:
            self.pending = self.ids.copy()
            self.rng.shuffle(self.pending)
            current = self.history[self.cursor] if self.cursor >= 0 else None
            if len(self.pending) > 1 and self.pending[0] == current:
                other = self.rng.randrange(1, len(self.pending))
                self.pending[0], self.pending[other] = self.pending[other], self.pending[0]
            self.seen.clear()
        return self.pending[0] if self.pending else None

    def next(self, repeat=False):
        item = self.peek(repeat)
        if item is None:
            return None
        if self.priority:
            self.select(item)
            return item
        forward = self._forward_index()
        if forward is not None:
            self.cursor = forward
        else:
            self.pending.pop(0)
            self.seen.add(item)
            self.history.append(item)
            self.cursor = len(self.history) - 1
        return item

    def previous(self):
        for index in range(self.cursor - 1, -1, -1):
            if self.history[index] in self.ids:
                self.cursor = index
                return self.history[index]
        return None
