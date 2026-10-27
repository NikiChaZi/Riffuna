from musicdesk.collection_tools import collection_tracks, collection_summary
from musicdesk.models import Track
import pytest


def t(index, title, artist="Artist", duration=180):
    return Track(f"{index:011d}", title, artist, duration)


def test_filter_matches_all_words_across_title_artist_and_normalizes_cyrillic():
    original = [t(1, "ЁК", "Дора"), t(2, "Верю", "Дора"), t(3, "ЁК", "Другой")]
    assert collection_tracks(original, "  ДОРА ек ") == original[:1]
    assert len(original) == 3
    assert collection_tracks(original, "missing") == []


def test_stable_sort_and_original_chronology_are_explicit():
    first, second, third = t(1, "Zulu", "A", 60), t(2, "alpha", "B", 30), t(3, "Alpha", "B", 30)
    values = [first, second, third]
    assert collection_tracks(values, order="recent") == values
    assert collection_tracks(values, order="custom", reverse=True) == values[::-1]
    assert collection_tracks(values, order="title") == [second, third, first]
    assert collection_tracks(values, order="artist") == values
    assert collection_tracks(values, order="duration") == [second, third, first]
    assert collection_tracks(values, order="duration", reverse=True) == [first, third, second]
    assert values == [first, second, third]
    with pytest.raises(ValueError):
        collection_tracks(values, order="popularity")


def test_summary_counts_real_rows_and_known_duration_with_iterables():
    assert collection_summary(iter([t(1, "A", duration=0), t(2, "B", duration=123)])) == {"count": 2, "duration": 123}
    assert collection_summary([]) == {"count": 0, "duration": 0}
