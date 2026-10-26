"""Bounded discovery of other uploads of a musical work.

The injected source owns music/category validation. This module adds recording
identity checks; it never resolves streams, downloads audio, or verifies lyrics.
``find`` is synchronous and must be called from the application's worker task.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import islice
from typing import Protocol

from .models import Track
from .youtube import SourceError, _NON_STUDIO

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingVersion:
    track: Track
    label: str
    evidence: str
    verified_uncensored: bool = False


class _SearchSource(Protocol):
    def search(self, query: str, limit: int = 40, order: str = "relevance") -> list[Track]: ...


# Strip service declarations as annotations, not words inside a song name.
_SERVICE = re.compile(r"^(?:official\s+audio|audio|official|lyrics?|hd|hq|4k|аудио|официальное\s+аудио)$", re.I)
_UNCENSORED = re.compile(r"\b(?:uncensored|uncut|explicit|без\s+цензуры|нецензурн\w*)\b", re.I)
_ORIGINAL = re.compile(r"\b(?:original(?:\s+version)?|оригинал(?:ьная\s+версия)?)\b", re.I)
_CLEAN = re.compile(r"\b(?:clean(?:\s+version)?|censored|цензурирован\w*)\b", re.I)
_CLAIM_ANNOTATION = re.compile(
    r"^(?:uncensored|uncut|explicit|без\s+цензуры|нецензурная\s+версия|"
    r"original(?:\s+version)?|оригинал(?:ьная\s+версия)?|clean(?:\s+version)?|censored|цензурированная\s+версия)$", re.I)
_SUFFIX = re.compile(
    r"(?:\s*[-–—|:]\s*|\s+)(official\s+audio|официальное\s+аудио|uncensored|uncut|explicit|"
    r"без\s+цензуры|original\s+version|original|оригинальная\s+версия|оригинал|clean\s+version|clean|censored)\s*$", re.I)
_BRACKETS = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
_PROFILE_PATTERNS = (
    ("ULTRA SLOWED", r"\b(?:ultra\s+slowed|ultraslowed)\b"),
    ("SUPER SLOWED", r"\b(?:super\s+slowed|superslowed)\b"),
    ("SLOWED", r"\b(?:slowed|slow\s*\+|замедлен\w*)\b"),
    ("SPED UP", r"\b(?:sped\s*up|speed\s*up|nightcore|ускорен\w*)\b"),
    ("MASHUP", r"\b(?:mash\s*up|м[эе]шап)\b"),
    ("REMIX", r"\b(?:remix|ремикс|bootleg)\b"),
    ("INSTRUMENTAL", r"\b(?:instrumental|инструментал\w*|караоке|karaoke)\b"),
    ("EXTENDED", r"\b(?:extended|расширенная\s+версия)\b"),
    ("REMASTER", r"\b(?:remaster(?:ed)?|ремастер\w*)\b"),
    ("ACOUSTIC", r"\b(?:acoustic|акустическ\w*)\b"),
)
_PROFILE = [(label, re.compile(pattern, re.I)) for label, pattern in _PROFILE_PATTERNS]
_UNKNOWN_ARTISTS = {"", "youtube", "unknown", "неизвестный исполнитель"}


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")))


def _display_artist(value: str) -> str:
    return re.sub(r"\s*[-–—]\s*topic\s*$", "", value, flags=re.I).strip()


def _artist(value: str) -> str:
    return _normalize(_display_artist(value))


def _without_declarations(title: str) -> str:
    def annotation(match):
        text = (match.group(1) if match.group(1) is not None else match.group(2)).strip()
        declaration = re.sub(r"\b(?:19|20)\d{2}\b", "", text).strip(" ,–—-|")
        return " " if _SERVICE.fullmatch(declaration) or _CLAIM_ANNOTATION.fullmatch(declaration) else match.group(0)
    title = _BRACKETS.sub(annotation, title)
    while True:
        shortened = _SUFFIX.sub("", title).strip()
        if not shortened or shortened == title:
            return title.strip()
        title = shortened


def _strip_artist_prefix(title: str, artist: str) -> str:
    parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    if len(parts) == 2 and _artist(parts[0]) == _artist(artist):
        return parts[1]
    return title


def _profile(title: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    labels = [label for label, pattern in _PROFILE if pattern.search(normalized)]
    if "ULTRA SLOWED" in labels or "SUPER SLOWED" in labels:
        labels = [label for label in labels if label != "SLOWED"]
    return tuple(labels)


def _composition_title(title: str) -> str:
    def annotation(match):
        text = match.group(1) if match.group(1) is not None else match.group(2)
        return " " if _profile(text) or re.fullmatch(r"\s*(?:19|20)\d{2}\s*", text) else match.group(0)
    title = _BRACKETS.sub(annotation, _without_declarations(title))
    # Unbracketed musical annotations are common. Strip only a suffix;
    # a song named 'Remix of My Life' must keep its meaningful words.
    for _, pattern in _PROFILE:
        match = pattern.search(title)
        if match and (not title[match.end():].strip(" -–—|:") or title[:match.start()].rstrip().endswith(("-", "–", "—", "|"))):
            prefix = title[:match.start()].strip(" -–—|:")
            if prefix:
                title = prefix
    return _normalize(title)


def work_key(track: Track) -> str:
    """Stable artist/title key, preserving remix/tempo/release annotations.

    Case, punctuation, Topic suffix and official-audio/censorship declarations
    do not change the key. Distinct processing versions do change it.
    """
    title = _without_declarations(_strip_artist_prefix(track.title, track.artist))
    return _artist(track.artist) + "::" + _normalize(title)


def _same_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    # Very small names must match exactly. Do not conflate songs with extra
    # words, a shared generic token, or an entirely different title order.
    return (len(left) >= 6 and len(right) >= 6 and len(left.split()) == len(right.split())
            and SequenceMatcher(None, left, right).ratio() >= 0.94)


def _declared(title: str, pattern: re.Pattern) -> bool:
    # Do not call a song named 'Original Sin' an original-master claim.
    for match in _BRACKETS.finditer(title):
        annotation = match.group(1) if match.group(1) is not None else match.group(2)
        declaration = re.sub(r"\b(?:19|20)\d{2}\b", "", annotation)
        for _, version_pattern in _PROFILE:
            declaration = version_pattern.sub(" ", declaration)
        declaration = declaration.strip(" ,–—-|:+")
        if _CLAIM_ANNOTATION.fullmatch(declaration) and pattern.search(declaration):
            return True
    suffix = _SUFFIX.search(title)
    return bool(suffix and pattern.search(suffix.group(1)))


def _artist_matches(expected: str, actual: str) -> bool:
    expected_words, actual_words = expected.split(), actual.split()
    return any(actual_words[i:i + len(expected_words)] == expected_words
               for i in range(len(actual_words) - len(expected_words) + 1)) if expected_words else False


def _duration_match(reference: Track, candidate: Track, changed: bool) -> bool:
    if not (0 < reference.duration <= 1200 and 0 < candidate.duration <= 1200):
        return False
    if not changed:
        return abs(candidate.duration - reference.duration) <= max(6, min(20, reference.duration * 0.08))
    labels = set(_profile(reference.title) + _profile(candidate.title))
    ratio = candidate.duration / reference.duration
    if labels & {"SLOWED", "SUPER SLOWED", "ULTRA SLOWED", "SPED UP"}:
        return 0.5 <= ratio <= 2.0
    if labels & {"REMIX", "MASHUP", "EXTENDED"}:
        return 0.65 <= ratio <= 1.75
    return 0.85 <= ratio <= 1.15


def _matching_title(reference: Track, candidate: Track) -> tuple[str, bool] | None:
    """Check recording identity, including either explicit credit orientation."""
    expected = _artist(reference.artist)
    if (expected in _UNKNOWN_ARTISTS or not 0 < reference.duration <= 1200
            or _NON_STUDIO.search(reference.title) or _NON_STUDIO.search(candidate.title)):
        return None
    composition = _composition_title(_strip_artist_prefix(reference.title, reference.artist))
    title, credit_in_title = candidate.title, False
    if _artist_matches(expected, _artist(candidate.artist)):
        title = _strip_artist_prefix(title, candidate.artist)
    if not _artist_matches(expected, _artist(candidate.artist)) or not _same_name(composition, _composition_title(title)):
        parts = re.split(r"\s+[-–—]\s+", candidate.title, maxsplit=1)
        if len(parts) != 2:
            return None
        for credit, song_title in (parts, parts[::-1]):
            # A delimited performer credit must match exactly; mentioning the
            # performer somewhere in a sentence cannot establish identity.
            if _artist(_without_declarations(credit)) != expected:
                continue
            title, credit_in_title = song_title, True
            for pattern, claim in ((_UNCENSORED, "без цензуры"), (_ORIGINAL, "original"), (_CLEAN, "clean")):
                if _declared(credit, pattern):
                    title += f" ({claim})"
            break
        else:
            return None
    if not _same_name(composition, _composition_title(title)):
        return None
    changed = _profile(title) != _profile(reference.title)
    return (title, credit_in_title) if _duration_match(reference, candidate, changed) else None


class VersionFinder:
    """Use up to four filtered searches and an optional bounded reference lookup."""

    def __init__(self, source: _SearchSource):
        self.source = source

    def find(self, track: Track, limit: int = 12) -> list[RecordingVersion]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            return []
        artist = _artist(track.artist)
        if artist in _UNKNOWN_ARTISTS or not 0 < track.duration <= 1200 or _NON_STUDIO.search(track.title):
            return []
        cleaned = _without_declarations(_strip_artist_prefix(track.title, track.artist))
        composition = _composition_title(cleaned)
        if not composition:
            return []
        base = f"{_display_artist(track.artist)} {cleaned}"
        queries = list(dict.fromkeys([base, base + " uncensored", base + " без цензуры", base + " original"]))
        candidate_limit = max(24, min(60, limit * 3))
        matches: dict[str, tuple[tuple, RecordingVersion]] = {}
        failures: list[SourceError] = []
        successful_searches = 0
        reference_profile = _profile(cleaned)
        candidates: list[tuple[Track, str]] = []
        lookup = getattr(self.source, "recording_candidates", None)
        for query in queries:
            try:
                rows = self.source.search(query, limit=candidate_limit, order="relevance")
                successful_searches += 1
            except SourceError as exc:
                failures.append(exc)
                log.info("Recording version search unavailable (%s)", type(exc).__name__)
                if callable(lookup):
                    # All queries share the same catalog endpoint. On an outage,
                    # proceed to the independent reference lookup immediately.
                    break
                continue
            candidates.extend((candidate, "") for candidate in islice(rows, candidate_limit))
        if callable(lookup):
            try:
                uploads = lookup(track, limit=min(limit, 4))
                candidates.extend((upload.track, upload.evidence) for upload in islice(uploads, 4))
                successful_searches += 1
            except SourceError as exc:
                failures.append(exc)
                log.info("Reference recording search unavailable (%s)", type(exc).__name__)
        for candidate, source_evidence in candidates:
            if not isinstance(candidate, Track) or candidate.video_id == track.video_id:
                continue
            identity = _matching_title(track, candidate)
            if identity is None:
                continue
            title, credit_in_title = identity
            profile = _profile(title)
            same_processing = profile == reference_profile
            uncensored = _declared(title, _UNCENSORED)
            original = _declared(title, _ORIGINAL)
            clean = _declared(title, _CLEAN)
            claims = []
            if uncensored:
                claims.append("«без цензуры»: заявлено в названии")
            if original:
                claims.append("«оригинал»: заявлено в названии")
            if clean:
                claims.append("цензурированная версия: заявлено в названии")
            labels = list(profile)
            if uncensored:
                labels.append("«Без цензуры» — заявлено")
            elif clean:
                labels.append("Clean — заявлено")
            elif original:
                labels.append("«Оригинал» — заявлено")
            label = " · ".join(labels) if labels else "Другая загрузка"
            delta = abs(candidate.duration - track.duration)
            evidence = ("Совпадают название и исполнитель; "
                        + ("исполнитель указан в заголовке; " if credit_in_title else "")
                        + f"длительность {candidate.duration} с (разница {delta} с). "
                        + ("; ".join(claims) + ". " if claims else "")
                        + (source_evidence + " " if source_evidence else "")
                        + "Содержание и отсутствие цензуры не проверены.")
            version = RecordingVersion(candidate, label, evidence)
            # Same-processing, directly credited matches come first. Title
            # marketing claims never increase identity/reliability ranking.
            score = (same_processing, not credit_in_title, -delta)
            existing = matches.get(candidate.video_id)
            if existing is None or score > existing[0] or (
                    score == existing[0] and claims and "заявлено в названии" not in existing[1].evidence):
                matches[candidate.video_id] = (score, version)
        if not successful_searches and failures:
            raise SourceError("Не удалось найти другие записи: музыкальный источник недоступен.") from failures[-1]
        return [version for _, version in sorted(matches.values(), key=lambda item: item[0], reverse=True)][:limit]
