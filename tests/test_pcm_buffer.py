from array import array
from concurrent.futures import ThreadPoolExecutor
import math
import sys

import pytest

from musicdesk.pcm_buffer import PcmBuffer


RATE = 48000
CHANNELS = 2
FRAME_BYTES = CHANNELS * 4


def pcm(left, frames, right=None):
    samples = array("f", [left, left if right is None else right]) * frames
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def floats(data):
    samples = array("f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def mono(data, channel=0):
    return list(floats(data))[channel::CHANNELS]


def assert_smooth(values, limit=.01):
    assert max(abs(b - a) for a, b in zip(values, values[1:])) < limit


def test_transition_uses_delivered_tail_clears_old_queue_and_smooths_new_source():
    queue = PcmBuffer()
    queue.feed(pcm(.7, 4800, .3))
    delivered = queue.read(960 * FRAME_BYTES)
    assert mono(delivered)[-1] == pytest.approx(.7)
    queue.feed(pcm(.9, 4800, .8))  # Never delivered: must not become the tail.
    queue.transition()
    assert queue.queued_bytes == 384 * FRAME_BYTES
    queue.feed(pcm(-.5, 2400, -.2))
    rendered = queue.read(1500 * FRAME_BYTES)
    left, right = mono(rendered), mono(rendered, 1)
    assert left[0] == pytest.approx(.7)
    assert right[0] == pytest.approx(.3)
    assert left[383] == pytest.approx(0, abs=1e-8)
    assert all(value <= 0 for value in left[384:])
    assert left[-1] == pytest.approx(-.5)
    assert right[-1] == pytest.approx(-.2)
    assert_smooth([mono(delivered)[-1]] + left)
    assert_smooth([mono(delivered, 1)[-1]] + right)


def test_read_always_returns_requested_size_and_pads_empty_queue_with_silence():
    queue = PcmBuffer()
    for size in (0, 1, 3, 8, 8191, 65536):
        data = queue.read(size)
        assert len(data) == size
        assert not any(data)
    queue.feed(pcm(.5, 3))
    data = queue.read(10000)
    assert len(data) == 10000
    assert not any(data[-100:])
    assert queue.queued_bytes < FRAME_BYTES
    queue.clear()
    assert queue.queued_bytes == 0
    assert queue.read(32) == bytes(32)


def test_volume_and_mute_ramp_at_read_time_and_unmute_restores_requested_volume():
    queue = PcmBuffer()
    queue.feed(pcm(1., 10000))
    queue.read(960 * FRAME_BYTES)
    queue.set_volume(.2)
    down = mono(queue.read(480 * FRAME_BYTES))
    assert down[0] > .99
    assert down[-1] == pytest.approx(.2)
    assert_smooth([1.] + down)
    queue.set_muted(True)
    muted = mono(queue.read(480 * FRAME_BYTES))
    assert muted[0] > .19
    assert muted[-1] == 0
    assert_smooth([.2] + muted)
    assert mono(queue.read(100 * FRAME_BYTES)) == [0.] * 100
    queue.set_volume(.4)  # Updating while muted must preserve silence.
    assert mono(queue.read(100 * FRAME_BYTES)) == [0.] * 100
    queue.set_muted(False)
    restored = mono(queue.read(480 * FRAME_BYTES))
    assert restored[0] < .001
    assert restored[-1] == pytest.approx(.4)
    assert_smooth([0.] + restored)


def test_overflow_is_bounded_and_uses_smooth_transition_instead_of_hard_cut():
    queue = PcmBuffer()
    queue.feed(pcm(.7, 4800))
    previous = mono(queue.read(960 * FRAME_BYTES))[-1]
    queue.feed(pcm(-.5, RATE * 3))
    assert 0 < queue.queued_bytes <= queue.max_bytes
    rendered = mono(queue.read(1500 * FRAME_BYTES))
    assert_smooth([previous] + rendered)
    assert rendered[-1] == pytest.approx(-.5)
    assert queue.queued_bytes <= queue.max_bytes


def test_new_audio_samples_keep_order_and_phase_after_boundary_fade():
    queue = PcmBuffer()
    queue.feed(pcm(.5, 1000))
    queue.read(500 * FRAME_BYTES)
    queue.transition()
    values = [math.sin(index * .01) * .2 for index in range(2000)]
    samples = array("f", [channel for value in values for channel in (value, -value)])
    queue.feed(samples.tobytes())
    rendered = queue.read((384 + 1200) * FRAME_BYTES)
    left, right = mono(rendered), mono(rendered, 1)
    assert left[384 + 384:] == pytest.approx(values[384:1200])
    assert right[384 + 384:] == pytest.approx([-value for value in values[384:1200]])


def test_partial_feeds_reads_and_rapid_transition_keep_frames_well_formed():
    queue = PcmBuffer()
    payload = pcm(.6, 1000, -.6)
    for index in range(0, len(payload), 3):
        queue.feed(payload[index:index + 3])
    pieces = [queue.read(3), queue.read(1), queue.read(17), queue.read(11)]
    assert all(math.isfinite(value) for value in floats(b"".join(pieces)))
    queue.transition()
    queue.read(13)
    queue.transition()
    queue.feed(pcm(-.2, 1000, .2))
    assert len(queue.read(801)) == 801
    assert 0 <= queue.queued_bytes <= queue.max_bytes


def test_concurrent_read_feed_and_transitions_are_safe_and_bounded():
    queue = PcmBuffer()
    def producer():
        for _ in range(100):
            queue.feed(pcm(.3, 1024))
            assert queue.queued_bytes <= queue.max_bytes
    def reader():
        for _ in range(100):
            assert len(queue.read(1024)) == 1024
    def transitions():
        for index in range(100):
            queue.set_volume((index % 10) / 10)
            queue.set_muted(index % 7 == 0)
            queue.transition()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(function) for function in (producer, reader, transitions)]
        for future in futures:
            future.result(timeout=5)
    assert queue.queued_bytes <= queue.max_bytes


def test_nonfinite_and_clipping_input_cannot_send_invalid_samples_to_device():
    queue = PcmBuffer()
    queue.set_volume(float("nan"))
    queue.feed(pcm(float("nan"), 1000, float("inf")))
    assert not any(queue.read(1000 * FRAME_BYTES))
    queue.clear()
    queue.set_volume(1.)
    queue.feed(pcm(100., 1000, -100.))
    values = floats(queue.read(1000 * FRAME_BYTES))
    assert all(math.isfinite(value) and -1 <= value <= 1 for value in values)
