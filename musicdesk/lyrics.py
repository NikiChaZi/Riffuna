"""Recording-specific lyric lookup, real LRC timestamps and a local cache."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

import requests

from .models import Track

MAX_BYTES = 1024 * 1024
STAMPS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
TAGS = re.compile(r"\[(?:ar|ti|al|by|re|ve|length|offset):[^\]]*\]", re.I)


@dataclass(frozen=True)
class LyricLine:
    start_ms: int
    text: str


def parse_lrc(text: str) -> tuple[LyricLine, ...]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Lyric file is too large")
    offset = re.search(r"\[offset:\s*([+-]?\d+)\s*\]", text, re.I)
    offset_ms = int(offset[1]) if offset else 0
    rows = []
    for raw in text.lstrip("\ufeff").splitlines():
        stamps = list(STAMPS.finditer(raw))
        if not stamps:
            continue
        words = STAMPS.sub("", TAGS.sub("", raw)).strip()
        for stamp in stamps:
            minutes, seconds = int(stamp[1]), int(stamp[2])
            if seconds >= 60:
                continue
            fraction = int((stamp[3] or "").ljust(3, "0"))
            start = max(0, (minutes * 60 + seconds) * 1000 + fraction - offset_ms)
            if start <= 6 * 3600 * 1000:
                rows.append(LyricLine(start, words))
        if len(rows) > 10000:
            raise ValueError("Too many timed lines")
    return tuple(sorted(dict.fromkeys(rows), key=lambda row: row.start_ms))


def active_line(lines: tuple[LyricLine, ...], position_ms: int) -> int:
    return bisect_right([line.start_ms for line in lines], max(0, position_ms)) - 1


def _clean(value: str) -> str:
    value = re.sub(r"\s*-\s*topic\s*$", "", value, flags=re.I)
    value = re.sub(r"[\[(](?:official\s+)?(?:audio|lyric video|lyrics|official video)[\])]", "", value, flags=re.I)
    return " ".join(value.split()).strip(" -–—")


def _key(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", _clean(value)).casefold()))


def _editions(value: str) -> frozenset[str]:
    lowered = _key(value)
    markers = {"slowed": r"\b(?:slowed|замедлен\w*)\b", "ultra": r"\bultra\b",
               "super": r"\bsuper\b", "sped": r"\b(?:sped|speed|nightcore)\b",
               "mashup": r"\b(?:mashup|mash up|мэшап|мешап)\b", "remix": r"\b(?:remix|ремикс)\b",
               "instrumental": r"\b(?:instrumental|karaoke|инструментал|минус)\b",
               "live": r"\b(?:live|концерт)\b", "extended": r"\bextended\b"}
    return frozenset(name for name, pattern in markers.items() if re.search(pattern, lowered))


def packet(track: Track, state: str, *, lines=(), plain_text="", source="", source_url="",
           timing_source="none", match_quality="none", message="") -> dict:
    return {"recording_id": track.video_id, "state": state,
            "lines": [asdict(row) for row in lines], "plain_text": plain_text,
            "source": source, "source_url": source_url, "timing_source": timing_source,
            "match_quality": match_quality, "message": message}


class LyricsUnavailable(RuntimeError):
    pass


class LRCLib:
    endpoint = "https://lrclib.net/api"

    def __init__(self, session_factory=requests.Session):
        self.session_factory = session_factory

    def _request(self, session, path, params):
        with session.get(self.endpoint + path, params=params, stream=True, timeout=(4, 10),
                         headers={"User-Agent": "Riffuna lyrics client (+https://github.com/NikiChaZi/Riffuna)",
                                  "Accept": "application/json"}) as response:
            if response.status_code == 404:
                return None
            if response.status_code in (429, 503):
                raise LyricsUnavailable("Сервис текстов занят. Повтори запрос позже.")
            if response.status_code != 200:
                raise LyricsUnavailable("Не удалось получить текст песни.")
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise LyricsUnavailable("Сервис текстов вернул неожиданный ответ.")
            body = bytearray()
            for chunk in response.iter_content(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise LyricsUnavailable("Ответ сервиса текстов слишком большой.")
            try:
                return json.loads(body)
            except (ValueError, UnicodeError):
                raise LyricsUnavailable("Сервис текстов вернул некорректные данные.") from None

    def fetch(self, track: Track) -> dict:
        title, artist = _clean(track.title), _clean(track.artist)
        # Some upload titles repeat the artist; version markers are retained.
        if title.casefold().startswith(artist.casefold() + " - "):
            title = title[len(artist) + 3:]
        params = {"track_name": title, "artist_name": artist}
        if 1 <= track.duration <= 3600:
            params["duration"] = track.duration
        try:
            with self.session_factory() as session:
                exact = self._request(session, "/get", params)
                records = [exact] if isinstance(exact, dict) else []
                match = self._match(track, title, artist, records)
                if match and match["state"] in ("synced", "instrumental"):
                    return match
                found = self._request(session, "/search", {"track_name": title, "artist_name": artist})
                if isinstance(found, list):
                    records.extend(found[:100])
                return self._match(track, title, artist, records) or packet(track, "not_found", source="LRCLIB")
        except LyricsUnavailable:
            raise
        except (requests.RequestException, ValueError, TypeError, OverflowError):
            raise LyricsUnavailable("Не удалось подключиться к сервису текстов. Повтори попытку.") from None

    def _match(self, track, title, artist, records):
        candidates = []
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("trackName"), str) or not isinstance(row.get("artistName"), str):
                continue
            if _editions(title) != _editions(row["trackName"]):
                continue
            title_score = SequenceMatcher(None, _key(title), _key(row["trackName"])).ratio()
            artist_score = SequenceMatcher(None, _key(artist), _key(row["artistName"])).ratio()
            if title_score < .9 or artist_score < .8:
                continue
            try:
                duration = float(row.get("duration", 0))
            except (TypeError, ValueError):
                continue
            delta = abs(duration - track.duration) if track.duration > 0 else float("inf")
            timed = parse_lrc(row.get("syncedLyrics") or "") if isinstance(row.get("syncedLyrics"), str) else ()
            meaningful = {line.start_ms for line in timed if line.text}
            usable_sync = len(meaningful) >= 2
            usable = row.get("instrumental") is True or usable_sync or bool(row.get("plainLyrics")) or bool(timed)
            if usable:
                candidates.append((delta > 2, -title_score - artist_score, not usable_sync, delta, -len(meaningful), row))
        if not candidates:
            return None
        candidates.sort(key=lambda value: value[:-1])
        _, _, _, delta, _, row = candidates[0]
        source_url = "https://lrclib.net/"
        if isinstance(row.get("id"), int):
            source_url += "api/get/" + str(row["id"])
        if row.get("instrumental") is True and delta <= 2:
            return packet(track, "instrumental", source="LRCLIB", source_url=source_url,
                          match_quality="metadata_duration")
        synced = row.get("syncedLyrics") if isinstance(row.get("syncedLyrics"), str) else ""
        plain = row.get("plainLyrics") if isinstance(row.get("plainLyrics"), str) else ""
        lines = parse_lrc(synced)
        if delta <= 2 and len({line.start_ms for line in lines if line.text}) >= 2:
            return packet(track, "synced", lines=lines, plain_text=plain or "\n".join(line.text for line in lines),
                          source="LRCLIB", source_url=source_url, timing_source="provider_lrc",
                          match_quality="metadata_duration")
        plain = plain or "\n".join(line.text for line in lines)
        if plain.strip():
            return packet(track, "plain", plain_text=plain, source="LRCLIB", source_url=source_url,
                          message="Текст без точной синхронизации с этой записью")
        return None


class LyricsStore:
    def __init__(self, directory: Path, provider=None, clock=time.time):
        self.directory = Path(directory)
        self.provider = provider if provider is not None else LRCLib()
        self.clock = clock

    @staticmethod
    def _signature(track):
        text = json.dumps([track.video_id, track.title, track.artist, track.duration], ensure_ascii=False)
        return hashlib.sha256(text.encode()).hexdigest()

    def load(self, track, force=False):
        override = self.directory / (track.video_id + ".lrc")
        if override.is_file():
            return self._local(track, override)
        cache = self.directory / (track.video_id + ".json")
        if not force and cache.is_file():
            try:
                if cache.stat().st_size <= MAX_BYTES:
                    record = json.loads(cache.read_text(encoding="utf-8"))
                    if record["signature"] == self._signature(track) and record["expires"] > self.clock():
                        result = record["payload"]
                        if result["recording_id"] == track.video_id:
                            return result
            except (OSError, ValueError, KeyError, TypeError):
                pass
        result = self.provider.fetch(track)
        ttl = 3600 if result["state"] == "not_found" else 30 * 86400
        record = {"signature": self._signature(track), "expires": self.clock() + ttl, "payload": result}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(".json.part")
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache)
        except OSError:
            pass  # Lyrics still work when caching is unavailable.
        return result

    def import_lrc(self, track, path):
        path = Path(path)
        result = self._local(track, path)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / (track.video_id + ".lrc")).write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
        return result

    def _local(self, track, path):
        if path.stat().st_size > MAX_BYTES:
            raise LyricsUnavailable("Файл текста слишком большой.")
        try:
            text = path.read_text(encoding="utf-8-sig")
            lines = parse_lrc(text)
        except (UnicodeError, ValueError):
            raise LyricsUnavailable("Не удалось прочитать LRC. Сохрани файл в UTF-8.") from None
        if not lines or not any(line.text for line in lines):
            raise LyricsUnavailable("В LRC нет строк с таймкодами.")
        return packet(track, "synced", lines=lines, plain_text="\n".join(line.text for line in lines),
                      source="local", timing_source="local_lrc", match_quality="user_import")
