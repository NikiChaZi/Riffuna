"""Local collection operations using only the metadata actually available.

`recent` preserves input chronology: callers must supply newest-first records
(as Library.liked_tracks/history do). It never invents dates for playlist items.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from .models import Track


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")


def collection_tracks(tracks: Iterable[Track], query: str = "", order: str = "custom",
                      reverse: bool = False) -> list[Track]:
    """Filter all search words over title/artist, then stably sort a new list."""
    if order not in {"custom", "recent", "title", "artist", "duration"}:
        raise ValueError("Unknown collection order")
    terms = _text(query).split()
    result = [track for track in tracks
              if all(term in _text(track.title + " " + track.artist) for term in terms)]
    if order == "title":
        result.sort(key=lambda track: (_text(track.title), _text(track.artist)))
    elif order == "artist":
        result.sort(key=lambda track: (_text(track.artist), _text(track.title)))
    elif order == "duration":
        result.sort(key=lambda track: track.duration)
    if reverse:
        result.reverse()
    return result


def collection_summary(tracks: Iterable[Track]) -> dict[str, int]:
    """Count displayed records and known seconds; zero duration stays unknown."""
    values = list(tracks)
    return {"count": len(values), "duration": sum(max(0, track.duration) for track in values)}
