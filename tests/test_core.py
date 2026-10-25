import sqlite3

import pytest

from musicdesk.models import PlayQueue, Track, parse_duration, version_label, video_id_from_url
from musicdesk.storage import Library


def track(number, title="Track"):
    return Track(f"test{number:07}", title, "Artist", 183)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=ewCPQeAtICk&list=abc",
    "https://youtu.be/ewCPQeAtICk?t=4",
    "https://music.youtube.com/watch?v=ewCPQeAtICk",
    "https://www.youtube.com/shorts/ewCPQeAtICk",
    "ewCPQeAtICk",
])
def test_youtube_links(url):
    assert video_id_from_url(url) == "ewCPQeAtICk"


@pytest.mark.parametrize("url", [
    "https://youtube.com.attacker.example/watch?v=ewCPQeAtICk",
    "https://notyoutube.com/watch?v=ewCPQeAtICk",
    "file:///ewCPQeAtICk", "https://youtube.com/watch?v=short",
    "https://youtube.com/playlist?list=123", "",
])
def test_reject_unrelated_or_malformed_urls(url):
    assert video_id_from_url(url) is None


def test_versions_stay_distinct_after_restart(tmp_path):
    path = tmp_path / "library.sqlite3"
    library = Library(path)
    original, slowed = track(1, "worry"), track(2, "worry (ultra slowed)")
    library.like(original, True)
    library.like(slowed, True)
    library.like(slowed, True)
    library.record_play(slowed)
    library.save_queue(PlayQueue([original, slowed], 1))
    library.close()
    library = Library(path)
    assert library.liked_ids() == {original.video_id, slowed.video_id}
    assert library.history() == [slowed]
    assert library.load_queue().current == slowed
    library.like(original, False)
    assert library.liked_tracks() == [slowed]
    assert library.load_queue().tracks == [original, slowed]
    library.close()


def test_failed_queue_save_is_atomic(tmp_path):
    library = Library(tmp_path / "library.sqlite3")
    original = track(1)
    library.save_queue(PlayQueue([original], 0))
    library.db.execute("CREATE TRIGGER reject_bad BEFORE INSERT ON tracks WHEN NEW.title='bad' BEGIN SELECT RAISE(ABORT,'bad'); END")
    with pytest.raises(sqlite3.IntegrityError):
        library.save_queue(PlayQueue([track(2, "bad")], 0))
    assert library.load_queue().tracks == [original]
    library.close()


def test_queue_boundaries_and_removing_current():
    a, b, c = track(1), track(2), track(3)
    queue = PlayQueue([a, b, c], 1)
    assert not queue.remove(0)
    assert queue.current == b
    assert queue.index == 0
    assert queue.remove(0)
    assert queue.current == c
    assert queue.advance() is None
    assert queue.current == c
    assert queue.advance(repeat=True) == c
    assert queue.remove(0)
    assert queue.current is None
    assert queue.advance() is None


def test_queue_deduplicates_ids_not_titles():
    a, b = track(1, "Song"), track(2, "Song")
    queue = PlayQueue()
    assert queue.add(a) == 0
    assert queue.add(a) == 0
    assert queue.add(b) == 1
    assert queue.tracks == [a, b]


def test_duration_and_version_boundaries():
    assert parse_duration("1:02:03") == 3723
    assert parse_duration(None) == 0
    assert parse_duration("LIVE") == 0
    assert version_label("worry (ultra slowed)") == "ULTRA SLOWED"
    assert version_label("worry (slowed)") == "SLOWED"



def test_live_tag_requires_a_word_boundary():
    assert version_label("Oliver Tree") == ""
    assert version_label("Delivered") == ""
    assert version_label("Song (LIVE)") == "LIVE"
