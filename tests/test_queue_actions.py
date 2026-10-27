import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from musicdesk.models import PlayQueue, ShuffleOrder, Track
from musicdesk.playback import Playback
from musicdesk.storage import Library


def tracks(count=5):
    return [Track(f'{number:011d}', f'Track {number}', 'Artist', 180)
            for number in range(count)]


@pytest.fixture
def playback(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = Library(tmp_path / 'library.sqlite3')

    class OfflineSource:
        def resolve(self, track):
            raise AssertionError('Queue editing must never resolve audio')

    result = Playback(library, OfflineSource())
    monkeypatch.setattr(result, '_open_current', lambda: None)
    monkeypatch.setattr(result, 'prefetch', lambda track: None)
    yield result
    result.shutdown()
    library.close()
    assert app is not None


@pytest.mark.parametrize('source,destination', [(0, 4), (4, 0), (1, 3), (3, 1)])
def test_move_retains_current_identity(source, destination):
    entries = tracks()
    queue = PlayQueue(entries.copy(), 2)
    assert queue.move(entries[source].video_id, destination)
    assert queue.current == entries[2]
    assert queue.tracks[destination] == entries[source]
    assert set(queue.tracks) == set(entries)


def test_invalid_or_unchanged_move_is_noop():
    queue = PlayQueue(tracks(2), 0)
    before = queue.tracks.copy()
    for source, destination in [(-1, 0), (0, 2), ('missing', 0), (0, -1), (0, 0)]:
        assert not queue.move(source, destination)
        assert queue.tracks == before and queue.index == 0


@pytest.mark.parametrize('existing', [True, False])
def test_play_next_is_noninterrupting_and_deduplicates(playback, monkeypatch, existing):
    entries = tracks()
    playback.play_from(entries[:4], entries[2])
    inserted = entries[0] if existing else entries[4]
    def forbidden():
        pytest.fail('Queue edit reopened current audio')
    monkeypatch.setattr(playback, '_open_current', forbidden)
    playback.play_next(inserted)
    assert playback.current == entries[2]
    assert playback.queue.current == entries[2]
    assert playback.queue.tracks[playback.queue.index + 1] == inserted
    assert playback.queue.tracks.count(inserted) == 1
    assert playback.library.load_queue() == playback.queue
    monkeypatch.setattr(playback, '_open_current', lambda: None)
    playback.next()
    assert playback.current == inserted


def test_shuffle_next_priority_overrides_random_and_preserves_previous(playback):
    entries = tracks()
    playback.play_from(entries, entries[1])
    playback.toggle_shuffle()
    playback.play_next(entries[4])
    assert playback._shuffle_order.peek() == entries[4].video_id
    playback.next()
    assert playback.current == entries[4]
    playback.previous()
    assert playback.current == entries[1]
    playback.next()
    assert playback.current == entries[4]
    remaining = []
    while playback.can_next:
        playback.next()
        remaining.append(playback.current)
    assert set(remaining) == {entries[0], entries[2], entries[3]}
    assert len(remaining) == 3


def test_priority_survives_restart_and_toggle(playback, monkeypatch):
    entries = tracks()
    playback.play_from(entries, entries[1])
    playback.play_next(entries[4])
    playback.toggle_shuffle()
    assert playback._shuffle_order.peek() == entries[4].video_id
    restored = Playback(playback.library, playback.source)
    monkeypatch.setattr(restored, 'prefetch', lambda track: None)
    monkeypatch.setattr(restored, '_open_current', lambda: None)
    try:
        assert restored._shuffle_order.peek() == entries[4].video_id
        restored.next()
        assert restored.current == entries[4]
    finally:
        restored.shutdown()


def test_clear_queue_retains_current_audio_and_saved_current(playback, monkeypatch):
    entries = tracks()
    playback.play_from(entries, entries[2])
    playback.toggle_shuffle()
    playback.play_next(entries[4])
    playback._expected_url = 'file:///unchanged.wav'
    playback._want_play = True
    playback._token = 'unchanged-token'
    playback.clear_queue()
    assert playback.queue == PlayQueue()
    assert playback.current == entries[2]
    assert playback.library.load_current() == entries[2]
    assert playback.library.load_queue() == PlayQueue()
    assert playback._expected_url == 'file:///unchanged.wav'
    assert playback._want_play and playback._token == 'unchanged-token'
    assert not playback.can_next
    playback.next()
    assert playback.current == entries[2]
    playback.add(entries[4])
    playback.next()
    assert playback.current == entries[4]


def test_move_persists_without_changing_audio(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    assert playback.move_queue(entries[0].video_id, 4)
    assert playback.current == playback.queue.current == entries[2]
    assert playback.library.load_queue() == playback.queue
    playback.next()
    assert playback.current == entries[3]


def test_preferred_recording_is_seen_as_its_queue_entry(playback):
    entries = tracks()
    replacement = Track('zzzzzzzzzzz', 'Track 2 (Uncensored)', 'Artist', 180)
    playback.play_from(entries, entries[2])
    playback.library.prefer_recording(entries[2], replacement)
    playback._current = replacement
    playback.toggle_shuffle()
    assert entries[2].video_id in playback._shuffle_order.seen
    playback.play_next(entries[2])
    assert not playback._shuffle_order.priority
    visited = []
    while playback.can_next:
        playback.next()
        visited.append(playback.current)
    assert set(visited) == set(entries) - {entries[2]}
    assert len(visited) == 4


def test_removed_priority_does_not_resurrect(playback):
    entries = tracks()
    playback.play_from(entries, entries[0])
    playback.toggle_shuffle()
    playback.play_next(entries[3])
    playback.remove(playback.queue.tracks.index(entries[3]))
    assert entries[3].video_id not in playback._shuffle_order.priority
    visited = []
    while playback.can_next:
        playback.next()
        visited.append(playback.current)
    assert entries[3] not in visited


def test_direct_selection_consumes_pending_priority(playback):
    entries = tracks()
    playback.play_from(entries, entries[0])
    playback.play_next(entries[3])
    playback.play(entries[3])
    assert not playback._shuffle_order.priority


def test_add_many_and_remove_many_emit_once_and_deduplicate(playback, monkeypatch):
    entries = tracks()
    changes = []
    playback.queue_changed.connect(lambda: changes.append(True))
    saves = []
    original_save = playback._save_queue
    def save():
        saves.append(True)
        original_save()
    monkeypatch.setattr(playback, '_save_queue', save)
    assert playback.add_many([entries[0], entries[1], entries[0]]) == 2
    assert len(changes) == len(saves) == 1
    assert playback.add_many([entries[0]]) == 0
    assert len(changes) == len(saves) == 1
    assert playback.remove_many([entries[0].video_id, entries[0].video_id, 'missing']) == 1
    assert len(changes) == len(saves) == 2
    assert playback.remove_many(['missing']) == 0
    assert len(changes) == len(saves) == 2
    assert playback.queue.tracks == [entries[1]]


def test_add_many_rejects_invalid_entry_before_mutation(playback):
    with pytest.raises(TypeError):
        playback.add_many([tracks(1)[0], object()])
    assert playback.queue.tracks == []
    assert playback.library.load_queue().tracks == []


@pytest.mark.parametrize('invalid', [[], ['missing'], ['00000000000'] * 3,
                                      ['00000000000', '00000000001', 'missing'],
                                      [[], '00000000001', '00000000002']])
def test_invalid_reorder_never_partially_mutates(playback, invalid):
    entries = tracks(3)
    playback.play_from(entries, entries[1])
    changes = []
    playback.queue_changed.connect(lambda: changes.append(True))
    assert not playback.reorder_queue(invalid)
    assert playback.queue.tracks == entries
    assert playback.queue.current == entries[1]
    assert playback.library.load_queue() == playback.queue
    assert changes == []


def test_reorder_batch_retains_preferred_current_priority_and_shuffle(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    replacement = Track('zzzzzzzzzzz', 'Track 2 (Uncensored)', 'Artist', 180)
    playback.library.prefer_recording(entries[2], replacement)
    playback._current = replacement
    playback.toggle_shuffle()
    playback.play_next(entries[4])
    changes = []
    playback.queue_changed.connect(lambda: changes.append(True))
    reverse = [entry.video_id for entry in reversed(entries)]
    assert playback.reorder_queue(reverse)
    assert changes == [True]
    assert playback.queue.current == entries[2]
    assert playback.current == replacement
    assert playback._shuffle_order.peek() == entries[4].video_id
    playback.next()
    assert playback.current == entries[4]


def test_remove_current_continues_after_it_without_highlighting_another_row(playback, monkeypatch):
    entries = tracks()
    playback.play_from(entries, entries[2])
    prepared = []
    monkeypatch.setattr(playback, 'prefetch', prepared.append)
    playback._expected_url = 'file:///same.wav'
    playback._token = 'same-token'
    playback.remove(2)
    assert playback.current == entries[2]
    assert playback.queue.index == -1 and playback.queue.current is None
    assert playback._expected_url == 'file:///same.wav' and playback._token == 'same-token'
    assert prepared == [entries[3]]
    playback.next()
    assert playback.current == entries[3]


def test_remove_current_and_successors_together_and_then_append(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    assert playback.remove_many([entry.video_id for entry in entries[2:]]) == 3
    assert playback.current == entries[2]
    assert playback.queue.current is None
    assert not playback.can_next
    playback.next()
    assert playback.current == entries[2]
    assert playback.add_many([entries[4]]) == 1
    assert playback.can_next
    playback.next()
    assert playback.current == entries[4]


def test_remove_current_continuation_survives_restart_and_later_removal(playback, monkeypatch):
    entries = tracks()
    playback.play_from(entries, entries[2])
    playback.remove(2)
    playback.remove_many([entries[3].video_id])
    restored = Playback(playback.library, playback.source)
    monkeypatch.setattr(restored, 'prefetch', lambda track: None)
    monkeypatch.setattr(restored, '_open_current', lambda: None)
    try:
        assert restored.queue.current is None
        assert restored.current == entries[2]
        restored.next()
        assert restored.current == entries[4]
    finally:
        restored.shutdown()


def test_reorder_detached_continuation_changes_future_order_not_previous_tracks(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    playback.remove(2)
    assert playback.reorder_queue([entries[4].video_id, entries[0].video_id,
                                   entries[3].video_id, entries[1].video_id])
    playback.next()
    assert playback.current == entries[4]


def test_remove_preferred_current_uses_original_queue_continuation(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    replacement = Track('zzzzzzzzzzz', 'Track 2 (Uncensored)', 'Artist', 180)
    playback.library.prefer_recording(entries[2], replacement)
    playback._current = replacement
    playback.remove_many([entries[2].video_id, entries[3].video_id])
    assert playback.current == replacement and playback.queue.current is None
    playback.next()
    assert playback.current == entries[4]


def test_play_next_overrides_exhausted_continuation_without_replaying_current(playback):
    entries = tracks()
    playback.play_from(entries, entries[4])
    playback.remove(4)
    assert not playback.can_next
    playback.play_next(entries[0])
    playback.next()
    assert playback.current == entries[0]


def test_remove_current_shuffle_keeps_only_unseen_remaining_and_priority(playback):
    entries = tracks()
    playback.play_from(entries, entries[2])
    playback.toggle_shuffle()
    playback.play_next(entries[4])
    playback.remove_many([entries[2].video_id, entries[0].video_id])
    assert playback.current == entries[2] and playback.queue.current is None
    playback.next()
    assert playback.current == entries[4]
    visited = [playback.current]
    while playback.can_next:
        playback.next()
        visited.append(playback.current)
    assert set(visited) == {entries[1], entries[3], entries[4]}
    assert len(visited) == 3
