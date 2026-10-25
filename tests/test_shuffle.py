import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from musicdesk.models import ShuffleOrder, Track
from musicdesk.playback import Playback
from musicdesk.storage import Library


def order(ids, current=None):
    result = ShuffleOrder(random.Random(19))
    result.reset(ids, current)
    return result


def test_full_shuffle_cycle_has_no_repeats_and_peek_does_not_consume():
    navigator = order(list("abcdef"))
    played = []
    for _ in range(6):
        candidate = navigator.peek()
        assert navigator.peek() == candidate
        assert navigator.next() == candidate
        played.append(candidate)
    assert set(played) == set("abcdef")
    assert navigator.next() is None
    assert navigator.ids == list("abcdef")


def test_previous_and_next_follow_known_history_without_new_random_choice():
    navigator = order(list("abcdef"))
    played = [navigator.next() for _ in range(4)]
    assert navigator.previous() == played[2]
    assert navigator.previous() == played[1]
    assert navigator.peek() == played[2]
    assert navigator.next() == played[2]
    assert navigator.next() == played[3]
    remaining = [navigator.next(), navigator.next()]
    assert len(set(played + remaining)) == 6


def test_repeat_all_starts_new_full_cycle_without_adjacent_duplicate():
    navigator = order(list("abcdef"))
    cycle = [navigator.next(True) for _ in range(6)]
    for _ in range(12):
        candidate = navigator.peek(True)
        assert candidate != cycle[-1]
        following = [navigator.next(True) for _ in range(6)]
        assert following[0] == candidate
        assert len(set(following)) == 6
        cycle = following


def test_add_and_remove_mid_cycle_never_resurrect_removed_items():
    navigator = order(list("abcd"))
    first = navigator.next()
    removed = navigator.peek()
    retained = [item for item in "abcd" if item != removed]
    navigator.sync(retained + ["new"])
    tail = [navigator.next() for _ in range(3)]
    assert set([first] + tail) == set(retained + ["new"])
    assert navigator.next() is None
    navigator.sync([item for item in navigator.ids if item != first])
    assert navigator.previous() in navigator.ids


def test_empty_singleton_and_removed_current_are_safe():
    navigator = order([])
    assert navigator.peek(True) is None
    assert navigator.next(True) is None
    assert navigator.previous() is None
    navigator.reset(["only"])
    assert navigator.next() == "only"
    assert navigator.next() is None
    assert navigator.previous() is None
    assert navigator.next(True) == "only"
    navigator.sync([])
    assert navigator.next(True) is None
    assert navigator.previous() is None


@pytest.fixture
def playback(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    db = Library(tmp_path / "library.sqlite3")

    class OfflineSource:
        def resolve(self, track):
            raise AssertionError("Navigation must not resolve audio in these tests")

    player = Playback(db, OfflineSource())
    monkeypatch.setattr(player, "_open_current", lambda: None)
    monkeypatch.setattr(player, "prefetch", lambda track: None)
    yield player
    player.shutdown()
    db.close()
    assert app is not None


def tracks(count=5):
    return [Track(f"{index:011d}", f"Track {index}") for index in range(count)]


def test_play_queue_restarts_existing_list_and_persists_it_without_reordering(playback):
    queued = tracks()
    playback.play_all(queued)
    playback.next()
    assert playback.current == queued[1]
    playback.play_queue()
    assert playback.current == queued[0]
    playback.toggle_shuffle()
    playback.play_queue()
    played = [playback.current]
    for _ in range(4):
        playback.next()
        played.append(playback.current)
    assert set(played) == set(queued)
    assert playback.queue.tracks == queued
    assert playback.library.load_queue().tracks == queued
    assert playback.library.get_setting("shuffle", "") == "on"


def test_shuffle_previous_forward_and_prefetch_agree(playback, monkeypatch):
    playback.play_all(tracks())
    playback.toggle_shuffle()
    playback.play_queue()
    first = playback.current
    prepared = []
    monkeypatch.setattr(playback, "prefetch", prepared.append)
    playback._prepare_next()
    playback._prepare_next()
    assert prepared[0] == prepared[1]
    playback.next()
    second = playback.current
    assert second == prepared[0] and second != first
    playback.previous()
    assert playback.current == first
    playback.next()
    assert playback.current == second


def test_shuffle_end_of_media_advances_but_repeat_one_does_not(playback, monkeypatch):
    queued = tracks(3)
    playback.play_all(queued)
    playback.toggle_shuffle()
    playback.play_queue()
    first = playback.current
    playback._expected_url = "file:///fake.wav"
    playback._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    assert playback.current != first
    second = playback.current
    seeks = []
    monkeypatch.setattr(playback, "seek", seeks.append)
    playback.repeat_mode = "one"
    playback._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    assert playback.current == second and seeks == [0]
    playback.next()
    assert playback.current not in [first, second]


def test_direct_selection_does_not_enqueue_and_queue_edit_preserves_audio(playback):
    queued = tracks(3)
    playback.play_all(queued)
    playback.toggle_shuffle()
    playback.play_queue()
    current = playback.current
    playback.remove(playback.queue.index)
    assert playback.current == current
    external = tracks(4)[-1]
    playback.play(external)
    assert external not in playback.queue.tracks
    playback.next()
    assert playback.current in playback.queue.tracks
    playback.previous()
    assert playback.current in playback.queue.tracks


def test_shuffle_setting_restored_and_empty_start_is_noop(playback, monkeypatch):
    playback.toggle_shuffle()
    assert playback.shuffle
    assert playback.library.get_setting("shuffle", "") == "on"
    opened = []
    monkeypatch.setattr(playback, "_open_current", lambda: opened.append(True))
    playback.play_queue()
    assert opened == []
    playback.toggle_shuffle()
    assert not playback.shuffle
    assert playback.library.get_setting("shuffle", "") == "off"


def test_can_next_handles_exhaustion_repeat_and_empty_queue(playback):
    assert not playback.can_next
    playback.play_all(tracks(2))
    playback.toggle_shuffle()
    playback.play_queue()
    assert playback.can_next
    playback.next()
    assert not playback.can_next
    playback.repeat_mode = "all"
    assert playback.can_next
    before = playback.current
    playback.next()
    assert playback.current != before


def test_existing_shuffle_setting_is_loaded_without_reordering(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    db = Library(tmp_path / "restored.sqlite3")
    queued = tracks(3)
    from musicdesk.models import PlayQueue
    db.save_queue(PlayQueue(queued, 1))
    db.set_setting("shuffle", "on")

    class OfflineSource:
        def resolve(self, track):
            raise AssertionError("offline")

    player = Playback(db, OfflineSource())
    monkeypatch.setattr(player, "prefetch", lambda track: None)
    monkeypatch.setattr(player, "_open_current", lambda: None)
    try:
        assert player.shuffle
        assert player.current == queued[1]
        player.next()
        assert player.current != queued[1]
        assert player.queue.tracks == queued
    finally:
        player.shutdown()
        db.close()
    assert app is not None


def test_play_from_selected_middle_continues_playlist_and_opens_once(playback, monkeypatch):
    queued = tracks(5)
    playback.play_all([tracks(8)[-1]])
    opened = []
    monkeypatch.setattr(playback, "_open_current", lambda: opened.append(playback.current))
    playback.play_from(queued, queued[2])
    assert opened == [queued[2]]
    assert playback.current == queued[2]
    assert playback.queue.tracks == queued
    playback.next()
    assert playback.current == queued[3]
    assert playback.library.load_queue().tracks == queued


def test_play_from_shuffle_keeps_selected_seen_and_visits_rest_once(playback):
    queued = tracks(5)
    playback.toggle_shuffle()
    playback.play_from(queued, queued[2])
    played = [playback.current]
    for _ in range(4):
        playback.next()
        played.append(playback.current)
    assert played[0] == queued[2]
    assert len(set(played)) == len(queued)
    assert set(played) == set(queued)
    assert not playback.can_next
    assert playback.queue.tracks == queued
    assert playback.library.load_queue().tracks == queued


def test_play_from_missing_or_empty_preserves_current_queue(playback, monkeypatch):
    queued = tracks(3)
    playback.play_all(queued)
    opened = []
    monkeypatch.setattr(playback, "_open_current", lambda: opened.append(True))
    playback.play_from(queued, tracks(4)[-1])
    playback.play_from([], queued[0])
    assert opened == []
    assert playback.current == queued[0]
    assert playback.queue.tracks == queued
