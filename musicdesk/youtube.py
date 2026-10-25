from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from itertools import islice
from threading import Lock
from time import monotonic
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL
from ytmusicapi import YTMusic

from .models import Track, parse_duration, video_id_from_url

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


class TimedSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", (6, 16))
        return super().request(*args, **kwargs)


class ExtractorLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


@dataclass(frozen=True)
class AudioStream:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


def _view_count(value: object) -> int | None:
    # Missing/abbreviated counts are unknown, not zero or a popularity score.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def track_from_music(row: dict) -> Track | None:
    if not isinstance(row, dict):
        return None
    try:
        artists = ", ".join(a.get("name", "") for a in row.get("artists", []) if a.get("name"))
        thumbs = row.get("thumbnails") or []
        thumb = min(thumbs, key=lambda t: abs((t.get("width") or 120) - 180)) if thumbs else {}
        return Track(row["videoId"], row["title"], artists or "YouTube",
                     parse_duration(row.get("duration_seconds") or row.get("duration")), thumb.get("url", ""),
                     _view_count(row.get("viewCount")), row.get("published") or "")
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def track_from_extract(row: dict) -> Track | None:
    if not isinstance(row, dict):
        return None
    try:
        thumbs = row.get("thumbnails") or []
        thumb = next((t.get("url", "") for t in thumbs if (t.get("height") or 0) >= 90), "")
        return Track(row["id"], row.get("title") or "Без названия",
                     row.get("artist") or row.get("uploader") or row.get("channel") or "YouTube",
                     parse_duration(row.get("duration")), row.get("thumbnail") or thumb,
                     _view_count(row.get("view_count")),
                     row.get("published") or row.get("upload_date") or row.get("release_date") or "")
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


_AUDIO_TYPE = "MUSIC_VIDEO_TYPE_ATV"
# Positive catalog classification is mandatory; these exclusions additionally
# remove live releases, spoken commentary and loops that can enter a catalog.
_NON_STUDIO = re.compile(
    r"\b(?:live|concert\w*|концерт\w*|клип\w*|clip|music\s+video|official\s+video|"
    r"reaction\w*|reacts?|reacting|реакци\w*|реагиру\w*|смотрит|смотрим|смотрят|"
    r"разбор\w*|обзор\w*|review\w*|analysis|tutorial\w*|lesson\w*|урок\w*|"
    r"cartoon\w*|episode\w*|мульт\w*|эпизод\w*|серии|серия|sfm|amv|gmv|gameplay|trailer|cutscene|visualizer|"
    r"выступлен\w*|исполнени\w*|festival|фестивал\w*|summer\s+sound|\d{1,2}[./]\d{1,2}[./](?:20)?\d{2}|vkfest|"
    r"loop(?:ed)?|repeat|зациклен\w*|петл\w*|\d+\s*(?:hours?|hrs?|час\w*|h))\b",
    re.IGNORECASE,
)
_QUERY_NOISE = {"official", "audio", "song", "music", "трек", "песня", "of", "the", "and", "feat", "ft"}
_MUSIC_VERSION = re.compile(
    r"\b(?:ost|soundtrack|extended|remix|mashup|slowed|sped\s*up|speed\s*up|"
    r"official\s+audio|audio|аудио|саундтрек|ремикс|мэшап|мешап)\b", re.IGNORECASE)


def _word_list(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    aliases = {"мэшап": "mashup", "мешап": "mashup", "ремикс": "remix", "speed": "sped"}
    words = []
    for token in re.findall(r"[^\W_]+", value):
        token = aliases.get(token, token)
        # A small general English plural rule: rules/nature must match rule/nature.
        if token.isascii() and len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        if token not in _QUERY_NOISE:
            words.append(token)
    return words


def _search_tokens(value: str) -> set[str]:
    return set(_word_list(value))


def _word_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if min(len(left), len(right)) < 4 or abs(len(left) - len(right)) > 2:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    return ratio if ratio >= 0.78 else 0.0


def _query_score(query: str, title: str, artist: str) -> float:
    required = _word_list(query)
    if not required:
        return 0.0
    title_words, artist_words = _word_list(title), _word_list(artist)
    available = title_words + artist_words
    if not available:
        return -1.0
    scores = [max((_word_similarity(word, candidate) for candidate in available), default=0) for word in required]
    if not all(scores):
        return -1.0
    # Require at least one ordered nearby query pair. A reversed bag of words
    # like 'Water ... Nature Rule' is not the phrase 'Rules of Nature'. Artist
    # and title can occur in either order, preserving mashup/reordered searches.
    if len(required) > 1:
        sequences = [title_words + artist_words, artist_words + title_words]
        pair_match = any(
            _word_similarity(left, words[pos]) and _word_similarity(right, words[end])
            for words in sequences for pos in range(len(words) - 1)
            for end in range(pos + 1, min(len(words), pos + 4))
            for left, right in zip(required, required[1:]))
        if not pair_match:
            return -1.0
    score = 100 * sum(scores) / len(scores)
    if title_words == required:
        score += 40
    if artist_words == required:
        score += 30
    if any(required == (title_words + artist_words)[i:i + len(required)]
           for i in range(len(available))):
        score += 20
    artist_matches = [word for word in required if any(_word_similarity(word, candidate) for candidate in artist_words)]
    title_query = [word for word in required if word not in artist_matches]
    if artist_matches and title_query == title_words:
        # Explicit artist credit plus exact song name is stronger than an
        # upload repeating the whole query in its title with a different owner.
        score += 80
    variants = r"\b(?:slowed|sped\s+up|speed\s+up|remix|mashup|nightcore|cover|кавер|instrumental|инструментал|фаст[- ]?флоу)\b"
    if re.search(variants, title, re.IGNORECASE) and not re.search(variants, query, re.IGNORECASE):
        score -= 10
    return score


def _studio_audio(row: dict, query: str = "") -> Track | None:
    """Accept catalog audio, never infer music from a video's title alone."""
    if not isinstance(row, dict) or row.get("resultType") != "song" or row.get("videoType") != _AUDIO_TYPE:
        return None
    if row.get("isAvailable") is False or row.get("live") or row.get("isLiveContent"):
        return None
    track = track_from_music(row)
    if not track or not 0 < track.duration <= 1200:
        return None
    album = row.get("album") if isinstance(row.get("album"), dict) else {}
    if _NON_STUDIO.search(track.title + " " + str(album.get("name") or "")):
        return None
    if _query_score(query, track.title, track.artist) < 0:
        return None
    return track


class YouTubeSource:
    def __init__(self):
        # Only sanitized counts/classification are cached, never stream URLs.
        self._count_cache: OrderedDict[str, tuple[float, int | None, bool]] = OrderedDict()
        self._count_lock = Lock()

    @staticmethod
    def _options(**extra) -> dict:
        options = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "socket_timeout": 14, "retries": 1, "extractor_retries": 1,
            "logger": ExtractorLogger(),
        }
        node = shutil.which("node")
        if node:
            options["js_runtimes"] = {"node": {"path": node}}
        options.update(extra)
        return options

    def search(self, query: str, limit: int = 40, order: str = "relevance") -> list[Track]:
        """Find catalog audio and verified musical OST/remix/extended uploads.

        Songs search follows continuations. Relevance matches phrases, plural
        forms and small spelling differences, rather than unordered word bags.
        A bounded video fallback requires a strong phrase match, UGC/ATV
        metadata and Music category; clips/live/reactions/loops remain excluded.
        Views ranks found recordings by real get_song viewCount, not globally.
        """
        if order not in {"relevance", "views", "date"}:
            raise ValueError("order must be relevance, views, or date")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        query = query.strip()
        if not query or limit <= 0:
            return []
        if order == "date":
            raise SourceError("Сортировка музыкального поиска по дате сейчас недоступна.")
        video_id = video_id_from_url(query)
        if video_id:
            return [self._direct_audio(video_id)]
        if query.startswith(("http://", "https://")):
            raise SourceError("Вставь ссылку на студийную аудиозапись YouTube или название композиции.")
        search_query = query
        if query.isalpha() and re.fullmatch(r"[\u0400-\u052f]+", query):
            search_query = f'"{query}"'
        try:
            with TimedSession() as session:
                rows = YTMusic(requests_session=session).search(
                    search_query, filter="songs", limit=max(80, limit * 3), ignore_spelling=False)
        except Exception as exc:
            log.warning("YouTube Music song search failed", exc_info=True)
            raise SourceError("Не удалось подключиться к YouTube Music. Повтори поиск немного позже.") from exc
        tracks: list[Track] = []
        seen: set[str] = set()
        for row in rows:
            track = _studio_audio(row, query)
            if track and track.video_id not in seen:
                seen.add(track.video_id)
                tracks.append(track)
        # A generic multi-word melody query may refer to an OST/fan upload
        # absent from the catalog. Single-artist browsing stays catalog-only.
        if len(_word_list(query)) >= 2 and (
                len(tracks) < 5 or _MUSIC_VERSION.search(query) or not re.search(r"[\u0400-\u052f]", query)):
            for track in self._music_fallback(query):
                if track.video_id not in seen:
                    seen.add(track.video_id)
                    tracks.append(track)
        if order == "relevance":
            tracks.sort(key=lambda track: _query_score(query, track.title, track.artist), reverse=True)
        if order == "views":
            # Bound metadata requests even when the service over-delivers rows.
            tracks = self._with_view_counts(tracks[:max(80, limit * 2)])
            if tracks and all(track.view_count is None for track in tracks):
                raise SourceError("Не удалось получить просмотры записей. Выбери поиск по соответствию запросу.")
            tracks.sort(key=lambda track: (track.view_count is not None,
                                           track.view_count if track.view_count is not None else -1), reverse=True)
        return tracks[:limit]

    @staticmethod
    def _audio_from_metadata(payload: dict, video_id: str, query: str = "", upload: Track | None = None) -> Track | None:
        details = payload.get("videoDetails") or {}
        if details.get("videoId") and details["videoId"] != video_id:
            return None
        if upload and _NON_STUDIO.search(upload.title + " " + upload.artist):
            return None
        microformat = payload.get("microformat") or {}
        metadata = microformat.get("microformatDataRenderer") or microformat.get("playerMicroformatRenderer") or {}
        row = {"resultType": "song", "videoType": details.get("musicVideoType"),
               "videoId": video_id, "title": details.get("title"),
               "artists": [{"name": details.get("author") or "YouTube"}],
               "duration_seconds": details.get("lengthSeconds"),
               "thumbnails": (details.get("thumbnail") or {}).get("thumbnails", []),
               "viewCount": details.get("viewCount"), "isLiveContent": details.get("isLiveContent"),
               "published": metadata.get("uploadDate") or metadata.get("publishDate") or ""}
        if upload:
            # The player API may replace an upload title with a canonical song
            # title and omit featured artists. Keep the actual search evidence.
            row["title"] = upload.title
            row["artists"] = [{"name": upload.artist}]
        if row["videoType"] == _AUDIO_TYPE:
            return _studio_audio(row, query)
        # Independent Music classification plus a strong phrase match is
        # positive evidence for a musical UGC upload, even without a remix tag.
        # OMV also labels some Official Audio releases: admit only that explicit
        # published audio declaration, while raw clip/live exclusions win above.
        category_is_music = str(metadata.get("category", "")).casefold() == "music"
        explicit_audio = re.search(r"\b(?:official\s+audio|audio\s+only|audio|аудио)\b", row.get("title") or "", re.IGNORECASE)
        allowed_type = row["videoType"] == "MUSIC_VIDEO_TYPE_UGC" or (row["videoType"] == "MUSIC_VIDEO_TYPE_OMV" and explicit_audio)
        if not category_is_music or not allowed_type or row["isLiveContent"]:
            return None
        if upload:
            # A conventional 'Artist - Title' credit is stronger than the name
            # of a reupload channel. Do not mistake an OST/game prefix for artist.
            parts = re.split(r"\s+[-–—]\s+", upload.title, maxsplit=1)
            if len(parts) == 2 and len(_word_list(parts[0])) <= 5 and not _MUSIC_VERSION.search(parts[0]):
                credited_artist, credited_title = parts
                words = _word_list(query)
                def side_match(value):
                    return sum(max((_word_similarity(word, candidate) for candidate in _word_list(value)), default=0)
                               for word in words)
                if (side_match(credited_title) > side_match(credited_artist)
                        and _query_score(query, credited_title, credited_artist) >= 0):
                    row["title"] = credited_title
                    row["artists"] = [{"name": credited_artist}]
        # Reuse duration/query/exclusion validation after positive UGC proof.
        row["videoType"] = _AUDIO_TYPE
        return _studio_audio(row, query)

    def _music_fallback(self, query: str) -> list[Track]:
        candidates = []
        try:
            with YoutubeDL(self._options(extract_flat=True)) as extractor:
                result = extractor.extract_info(f"ytsearch16:{query}", download=False, process=False)
                for row in islice((result or {}).get("entries") or (), 16):
                    track = track_from_extract(row)
                    if (track and 0 < track.duration <= 1200 and not _NON_STUDIO.search(track.title)
                            and _query_score(query, track.title, track.artist) >= 0):
                        candidates.append(track)
            # Hard cap on validation calls; do not resolve/download media here.
            tracks = []
            with TimedSession() as session:
                music = YTMusic(requests_session=session)
                for candidate in candidates[:6]:
                    try:
                        track = self._audio_from_metadata(music.get_song(candidate.video_id), candidate.video_id, query, candidate)
                        if track:
                            tracks.append(track)
                    except Exception:
                        continue
            return tracks
        except Exception as exc:
            log.info("Music upload search unavailable (%s)", type(exc).__name__)
            return []

    def _direct_audio(self, video_id: str) -> Track:
        try:
            with TimedSession() as session:
                track = self._audio_from_metadata(YTMusic(requests_session=session).get_song(video_id), video_id)
        except Exception as exc:
            raise SourceError("Не удалось проверить аудиозапись YouTube Music.") from exc
        if not track:
            raise SourceError("По этой ссылке нет подходящей аудиозаписи. Клипы, live и длинные петли исключены.")
        return track

    def _with_view_counts(self, tracks: list[Track]) -> list[Track]:
        if not tracks:
            return []
        updates: dict[str, tuple[int | None, bool]] = {}
        pending: list[Track] = []
        now = monotonic()
        with self._count_lock:
            for track in tracks:
                if track.view_count is not None:
                    updates[track.video_id] = (track.view_count, True)
                    continue
                cached = self._count_cache.get(track.video_id)
                if cached and now - cached[0] < (300 if cached[1] is not None else 20):
                    updates[track.video_id] = (cached[1], cached[2])
                    self._count_cache.move_to_end(track.video_id)
                else:
                    pending.append(track)

        def fetch_batch(batch):
            # Each worker owns its HTTP session. Neither Session nor YTMusic
            # is shared between threads. Four workers cap network concurrency.
            result = {}
            try:
                with TimedSession() as session:
                    music = YTMusic(requests_session=session)
                    for track in batch:
                        try:
                            details = music.get_song(track.video_id).get("videoDetails", {})
                            allowed = not details.get("isLiveContent") and details.get("musicVideoType", _AUDIO_TYPE) == _AUDIO_TYPE
                            result[track.video_id] = (_view_count(details.get("viewCount")), allowed)
                        except Exception:
                            result[track.video_id] = (track.view_count, True)
            except Exception:
                result.update({track.video_id: (track.view_count, True) for track in batch})
            return result

        if pending:
            workers = min(4, len(pending))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="music-counts") as pool:
                for batch_result in pool.map(fetch_batch, [pending[i::workers] for i in range(workers)]):
                    updates.update(batch_result)
            with self._count_lock:
                for track in pending:
                    count, allowed = updates[track.video_id]
                    self._count_cache[track.video_id] = (monotonic(), count, allowed)
                    self._count_cache.move_to_end(track.video_id)
                while len(self._count_cache) > 2048:
                    self._count_cache.popitem(last=False)
        return [replace(track, view_count=updates[track.video_id][0]) for track in tracks
                if updates[track.video_id][1]]

    def track(self, video_id: str) -> Track:
        try:
            with TimedSession() as session:
                details = YTMusic(requests_session=session).get_song(video_id).get("videoDetails", {})
            if details.get("title"):
                thumbs = details.get("thumbnail", {}).get("thumbnails", [])
                return Track(video_id, details["title"], details.get("author", "YouTube"),
                             parse_duration(details.get("lengthSeconds")), thumbs[0].get("url", "") if thumbs else "",
                             _view_count(details.get("viewCount")))
        except Exception:
            pass
        try:
            with YoutubeDL(self._options(skip_download=True)) as extractor:
                result = extractor.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            track = track_from_extract(result or {})
            if track:
                return track
        except Exception as exc:
            raise SourceError("Не удалось открыть ролик. Возможно, запись удалена или недоступна в регионе.") from exc
        raise SourceError("У этого ролика не удалось получить название.")

    @staticmethod
    def _audio_format() -> str:
        # Prefer YouTube's original/default track across containers before
        # bitrate. The m4a preference must not select an alternate over original.
        audio = "bestaudio[protocol=https]"
        return "/".join([
            audio + "[language_preference>=10][ext=m4a]", audio + "[language_preference>=10]",
            audio + "[language_preference>=5][ext=m4a]", audio + "[language_preference>=5]",
            audio + "[ext=m4a]", audio, "best[protocol=https]",
        ])

    @staticmethod
    def _stream_from_extract(result: dict, video_id: str) -> AudioStream:
        if not result or result.get("id") != video_id:
            raise SourceError("YouTube вернул другую запись вместо выбранной.")
        url = result.get("url") or ""
        host = (urlparse(url).hostname or "").lower()
        if not url.startswith("https://") or not (host == "googlevideo.com" or host.endswith(".googlevideo.com")):
            raise SourceError("YouTube не предоставил подходящий аудиопоток.")
        headers = {key: value for key, value in (result.get("http_headers") or {}).items()
                   if key.lower() in {"user-agent", "accept", "accept-language", "referer", "origin"}}
        return AudioStream(url, headers)

    def resolve(self, track: Track) -> AudioStream:
        # Keep the initial webpage: omitting it caused bot verification in live
        # checks. Config/next requests and other clients are unnecessary here.
        fast = self._options(format=self._audio_format(), extractor_args={"youtube": {
            "player_client": ["visionos"], "player_skip": ["configs", "initial_data"],
            "skip": ["hls", "dash"],
        }})
        fallback = self._options(format=self._audio_format())
        last_error = None
        for options in (fast, fallback):
            try:
                with YoutubeDL(options) as extractor:
                    result = extractor.extract_info(track.url, download=False)
                return self._stream_from_extract(result, track.video_id)
            except Exception as exc:
                last_error = exc
                # Extractor exceptions can contain signed URLs. Log only type.
                log.info("Audio extraction attempt failed for %s (%s)", track.video_id, type(exc).__name__)
        raise SourceError("Не удалось получить аудиопоток YouTube. Повтори попытку или выбери другую загрузку композиции.") from last_error
