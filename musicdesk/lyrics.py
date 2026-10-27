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
import xml.etree.ElementTree as ET

import requests

from .models import Track
from .lyric_timing import TimedLine as LyricLine, WordCue, inline_words, parse_ttml

MAX_BYTES = 1024 * 1024
STAMPS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
TAGS = re.compile(r"\[(?:ar|ti|al|by|re|ve|length|offset):[^\]]*\]", re.I)


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
        plain, timed_words = inline_words(words, offset_ms)
        for stamp in stamps:
            minutes, seconds = int(stamp[1]), int(stamp[2])
            if seconds >= 60:
                continue
            fraction = int((stamp[3] or "").ljust(3, "0"))
            start = max(0, (minutes * 60 + seconds) * 1000 + fraction - offset_ms)
            if start <= 6 * 3600 * 1000:
                adjusted = timed_words if len(stamps) == 1 else ()
                rows.append(LyricLine(start, plain, adjusted,
                                     max(word.end_ms for word in adjusted) if adjusted else None))
        if len(rows) > 10000:
            raise ValueError("Too many timed lines")
    return tuple(sorted(dict.fromkeys(rows), key=lambda row: row.start_ms))


def active_line(lines: tuple[LyricLine, ...], position_ms: int) -> int:
    return bisect_right([line.start_ms for line in lines], max(0, position_ms)) - 1


def _clean(value: str) -> str:
    value = re.sub(r"\s*[-–—]\s*topic\s*$", "", value, flags=re.I)
    value = re.sub(r"[\[(](?:official\s+)?(?:audio|lyric video|lyrics|official video)[\])]", "", value, flags=re.I)
    return " ".join(value.split()).strip(" -–—")


def _song_title(title: str, artist: str) -> str:
    original = _clean(title)
    # Remove upload declarations, never musical processing such as slowed/remix.
    title = re.sub(r"[\[(]\s*(?:без\s+цензуры|uncensored|explicit|uncut|original(?:\s+version)?|оригинал(?:ьная\s+версия)?)\s*[\])]", "", original, flags=re.I).strip()
    if artist:
        title = re.sub(r"^" + re.escape(_clean(artist)) + r"\s+[-–—|]\s+", "", title, flags=re.I)
        title = re.sub(r"\s+[-–—|]\s+" + re.escape(_clean(artist)) + r"$", "", title, flags=re.I)
    return title.strip() or original


def _well_covered(payload, track):
    times = [line["start_ms"] for line in payload.get("lines", []) if any(c.isalpha() for c in line.get("text", ""))]
    return bool(times and track.duration > 0 and .8 * track.duration * 1000 <= max(times) <= track.duration * 1000 + 2000)


def _key(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", _clean(value)).casefold().replace("ё", "е")))


def _artist_key(value: str) -> str:
    # Exact phonetic equivalence only; this is not a fuzzy artist-name guess.
    table = str.maketrans({"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ж":"zh","з":"z",
        "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s",
        "т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"})
    return _key(value).translate(table)


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
            "lines": [dict(start_ms=row.start_ms, text=row.text,
                           **({"words": [asdict(word) for word in row.words], "end_ms": row.end_ms} if row.words else {})) for row in lines], "plain_text": plain_text,
            "source": source, "source_url": source_url, "timing_source": timing_source,
            "match_quality": match_quality, "message": message}


class LyricsUnavailable(RuntimeError):
    pass


class _TransientLyricsError(LyricsUnavailable):
    def __init__(self, message, delay=.3):
        super().__init__(message)
        self.delay = delay


class LRCLib:
    endpoint = "https://lrclib.net/api"

    def __init__(self, session_factory=requests.Session, sleeper=time.sleep):
        self.session_factory = session_factory
        self.sleeper = sleeper

    def _request(self, session, path, params):
        # One retry in the worker; never wait for a server-supplied long delay.
        for attempt in range(2):
            try:
                return self._request_once(session, path, params)
            except (_TransientLyricsError, requests.ConnectionError, requests.Timeout) as error:
                if attempt:
                    raise LyricsUnavailable("Сервис текстов временно недоступен. Сохранённый текст можно открыть из кэша.") from None
                self.sleeper(getattr(error, "delay", .3))

    def _request_once(self, session, path, params):
        with session.get(self.endpoint + path, params=params, stream=True, timeout=(4, 10),
                         headers={"User-Agent": "Riffuna lyrics client (+https://github.com/NikiChaZi/Riffuna)",
                                  "Accept": "application/json"}) as response:
            if response.status_code == 404:
                return None
            if response.status_code in (429, 500, 502, 503, 504):
                delay = .3
                try:
                    delay = max(.1, min(1., float(response.headers.get("Retry-After", .3))))
                except (TypeError, ValueError):
                    pass
                raise _TransientLyricsError("Сервис текстов занят. Повтори запрос позже.", delay)
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
        title, artist = _song_title(track.title, track.artist), _clean(track.artist)
        params = {"track_name": title, "artist_name": artist}
        if 1 <= track.duration <= 3600:
            params["duration"] = track.duration
        try:
            with self.session_factory() as session:
                exact = self._request(session, "/get", params)
                records = [exact] if isinstance(exact, dict) else []
                match = self._match(track, title, artist, records)
                if match and (match["state"] == "instrumental" or (match["state"] == "synced" and _well_covered(match, track))):
                    return match
                try:
                    found = self._request(session, "/search", {"track_name": title, "artist_name": artist})
                except LyricsUnavailable:
                    if match:
                        return match
                    raise
                if isinstance(found, list):
                    records.extend(found[:100])
                result = self._match(track, title, artist, records)
                if result and (result["state"] == "instrumental" or (result["state"] == "synced" and _well_covered(result, track))):
                    return result
                # Artist metadata may use a different alphabet in YouTube Music.
                # Search more broadly, then retain the same strict artist/edition gates.
                try:
                    found = self._request(session, "/search", {"track_name": title})
                except LyricsUnavailable:
                    if result:
                        return result
                    raise
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
            candidate_title = _song_title(row["trackName"], row["artistName"])
            status_title = re.sub(r"\s*[\[(](?:paused|playing|приостановлено)[\])]\s*$", "", candidate_title, flags=re.I).strip()
            if status_title != candidate_title and _key(status_title) == _key(title):
                # A leaked player-state suffix is accepted only when the words,
                # artist and duration corroborate an ordinary matching entry.
                row_words = _key(row.get("plainLyrics") or " ".join(line.text for line in parse_lrc(row.get("syncedLyrics") or "")))
                for reference in records:
                    if not isinstance(reference, dict) or _key(str(reference.get("trackName", ""))) != _key(title) or _artist_key(str(reference.get("artistName", ""))) != _artist_key(artist):
                        continue
                    reference_words = _key(reference.get("plainLyrics") or " ".join(line.text for line in parse_lrc(reference.get("syncedLyrics") or "")))
                    if row_words and reference_words and max(len(row_words.split()), len(reference_words.split())) <= 2000 and SequenceMatcher(None, row_words.split(), reference_words.split(), autojunk=False).ratio() >= .95:
                        candidate_title = status_title
                        break
            title_score = SequenceMatcher(None, _key(title), _key(candidate_title)).ratio()
            artist_score = SequenceMatcher(None, _key(artist), _key(row["artistName"])).ratio()
            if _artist_key(artist) == _artist_key(row["artistName"]):
                artist_score = 1.0
            if title_score < .9 or artist_score < .8:
                continue
            try:
                duration = float(row.get("duration", 0))
            except (TypeError, ValueError):
                continue
            delta = abs(duration - track.duration) if track.duration > 0 else float("inf")
            timed = parse_lrc(row.get("syncedLyrics") or "") if isinstance(row.get("syncedLyrics"), str) else ()
            meaningful = {line.start_ms for line in timed if line.text}
            usable_sync = len(meaningful) >= 2 and (track.duration <= 0 or max(meaningful) <= track.duration * 1000 + 2000)
            word_times = [line.start_ms for line in timed if any(c.isalpha() for c in line.text)]
            weak_coverage = not word_times or track.duration <= 0 or max(word_times) < .8 * track.duration * 1000
            usable = row.get("instrumental") is True or usable_sync or bool(row.get("plainLyrics")) or bool(timed)
            if usable:
                candidates.append((delta > 2, -title_score - artist_score, not usable_sync, weak_coverage, delta, -len(meaningful), row))
        if not candidates:
            return None
        candidates.sort(key=lambda value: value[:-1])
        _, _, _, _, delta, _, row = candidates[0]
        source_url = "https://lrclib.net/"
        if isinstance(row.get("id"), int):
            source_url += "api/get/" + str(row["id"])
        if row.get("instrumental") is True and delta <= 2:
            return packet(track, "instrumental", source="LRCLIB", source_url=source_url,
                          match_quality="metadata_duration")
        synced = row.get("syncedLyrics") if isinstance(row.get("syncedLyrics"), str) else ""
        plain = row.get("plainLyrics") if isinstance(row.get("plainLyrics"), str) else ""
        lines = parse_lrc(synced)
        starts = {line.start_ms for line in lines if line.text}
        if delta <= 2 and len(starts) >= 2 and max(starts) <= track.duration * 1000 + 2000:
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
        ttml = self.directory / (track.video_id + ".ttml")
        if ttml.is_file():
            return self._local(track, ttml)
        if override.is_file():
            return self._local(track, override)
        cache = self.directory / (track.video_id + ".json")
        saved = None
        if cache.is_file():
            try:
                if cache.stat().st_size <= MAX_BYTES:
                    record = json.loads(cache.read_text(encoding="utf-8"))
                    if record["signature"] == self._signature(track):
                        result = record["payload"]
                        if result["recording_id"] == track.video_id:
                            if result.get("state") in {"synced", "plain", "instrumental"}:
                                saved = result
                            reviewed = record.get("provider_revision") == 4
                            if not reviewed and result.get("state") == "synced" and not _well_covered(result, track):
                                # Keep words offline; do not retain a known-suspicious old clock.
                                saved = dict(result, state="plain", lines=[], timing_source="none", message="Таймкоды требуют повторной проверки")
                            valid_negative = reviewed
                            if not force and valid_negative and record["expires"] > self.clock():
                                return result
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            result = self.provider.fetch(track)
        except (LyricsUnavailable, requests.RequestException):
            if saved is None:
                raise
            return dict(saved, cache_stale=True, message="Сохранённый текст: сервис временно недоступен")
        ttl = 3600 if result["state"] == "not_found" else 30 * 86400
        record = {"signature": self._signature(track), "expires": self.clock() + ttl, "payload": result, "provider_revision": 4}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(".json.part")
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache)
        except OSError:
            pass  # Lyrics still work when caching is unavailable.
        return result

    def enrich_words(self, track, payload, force=False):
        """Keep the first line response fast; optional enrichment runs afterwards."""
        if payload.get("state") != "synced" or payload.get("source") == "local" or any(row.get("words") for row in payload.get("lines", ())):
            return payload
        cache = self.directory / (track.video_id + ".words.json")
        reference = json.dumps([payload.get("plain_text", ""), payload.get("lines", ())], ensure_ascii=False, sort_keys=True)
        signature = self._signature(track) + hashlib.sha256(reference.encode("utf-8")).hexdigest()
        if not force:
            try:
                if cache.stat().st_size <= MAX_BYTES:
                    record = json.loads(cache.read_text(encoding="utf-8"))
                    if isinstance(record, dict) and record.get("signature") == signature and record.get("expires", 0) > self.clock():
                        saved = record.get("payload")
                        if saved is None:
                            return payload
                        if isinstance(saved, dict) and saved.get("recording_id") == track.video_id and saved.get("state") == "synced":
                            from .word_lyrics import compatible_words
                            rows = tuple(LyricLine(row["start_ms"], row["text"],
                                         tuple(WordCue(**word) for word in row.get("words", ())), row.get("end_ms"))
                                         for row in saved.get("lines", ()))
                            if compatible_words(track, payload, rows):
                                return saved
            except (OSError, ValueError, TypeError, KeyError):
                pass
        from .word_lyrics import BetterWords
        enriched = BetterWords().enrich(track, payload)
        has_words = any(row.get("words") for row in enriched.get("lines", ()))
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            record = {"signature": signature, "expires": self.clock() + (30*86400 if has_words else 86400),
                      "payload": enriched if has_words else None}
            temporary = cache.with_suffix(".json.part")
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache)
        except OSError:
            pass
        return enriched

    def import_lrc(self, track, path):
        path = Path(path)
        result = self._local(track, path)
        self.directory.mkdir(parents=True, exist_ok=True)
        extension = ".ttml" if path.suffix.lower() in {".ttml", ".xml"} else ".lrc"
        target = self.directory / (track.video_id + extension)
        target.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
        other = self.directory / (track.video_id + (".lrc" if extension == ".ttml" else ".ttml"))
        other.unlink(missing_ok=True)
        return result

    def _local(self, track, path):
        if path.stat().st_size > MAX_BYTES:
            raise LyricsUnavailable("Файл текста слишком большой.")
        try:
            text = path.read_text(encoding="utf-8-sig")
            is_ttml = path.suffix.lower() in {".ttml", ".xml"}
            lines = parse_ttml(text) if is_ttml else parse_lrc(text)
        except (UnicodeError, ValueError, ET.ParseError):
            raise LyricsUnavailable("Не удалось прочитать LRC. Сохрани файл в UTF-8.") from None
        if not lines or not any(line.text for line in lines):
            raise LyricsUnavailable("В LRC нет строк с таймкодами.")
        return packet(track, "synced", lines=lines, plain_text="\n".join(line.text for line in lines),
                      source="local", timing_source="local_ttml" if is_ttml else "local_lrc", match_quality="user_import")
