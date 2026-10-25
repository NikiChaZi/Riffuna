from __future__ import annotations

import re
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

