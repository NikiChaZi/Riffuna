"""Thread-safe Float32LE PCM queue with smooth, device-independent boundaries."""
from __future__ import annotations

from array import array
from collections import deque
import math
import sys
import threading


class PcmBuffer:
    """A bounded interleaved PCM FIFO; reads never signal end-of-stream.

    Audio already returned to the device is never rewritten. A transition starts
    its tail at the last delivered frame, discards old queued PCM, then fades the
    next source in from zero. Volume is applied while reading, not while feeding.
    """

    def __init__(self, sample_rate=48000, channels=2):
        if sample_rate <= 0 or channels <= 0:
            raise ValueError("Positive sample rate and channel count required")
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_bytes = self.channels * 4
        self.max_bytes = self.sample_rate * 2 * self.frame_bytes
        self._fade_frames = max(2, round(self.sample_rate * .008))
        self._ramp_frames = max(1, round(self.sample_rate * .010))
        self._lock = threading.RLock()
        self._queue = deque()
        self._offset = 0
        self._queued_samples = 0
        self._input_partial = b""
        self._pending = b""
        self._pending_frame = None
        self._last_frame = [0.] * self.channels
        self._rendered_last = self._last_frame[:]
        self._tail_origin = None
        self._tail_position = 0
        self._fade_position = 0
        self._volume = 1.
        self._muted = False
        self._gain = 1.
        self._gain_start = 1.
        self._gain_target = 1.
        self._gain_position = self._ramp_frames

    @property
    def queued_bytes(self):
        with self._lock:
            tail_frames = self._fade_frames - self._tail_position if self._tail_origin is not None else 0
            return self._queued_samples * 4 + tail_frames * self.frame_bytes + len(self._pending)

    def feed(self, data):
        if not data:
            return
        with self._lock:
            payload = self._input_partial + bytes(data)
            complete = len(payload) - len(payload) % self.frame_bytes
            self._input_partial = payload[complete:]
            if not complete:
                return
            samples = array("f")
            samples.frombytes(payload[:complete])
            if sys.byteorder != "little":
                samples.byteswap()
            if self.queued_bytes + len(samples) * 4 > self.max_bytes:
                partial = self._input_partial
                self._transition()
                self._input_partial = partial
            available_bytes = max(0, self.max_bytes - self.queued_bytes)
            capacity = available_bytes // self.frame_bytes * self.channels
            if len(samples) > capacity:
                samples = samples[-capacity:] if capacity else array("f")
            if samples:
                self._queue.append(samples)
                self._queued_samples += len(samples)

    def transition(self):
        with self._lock:
            self._transition()

    def _transition(self):
        self._queue.clear()
        self._offset = 0
        self._queued_samples = 0
        self._input_partial = b""
        # If the device requested part of a frame, finish that same frame first.
        origin = self._pending_frame if self._pending else self._last_frame
        self._tail_origin = list(origin) if any(origin) else None
        self._tail_position = 0
        self._fade_position = 0
        self._rendered_last = list(origin)

    def clear(self):
        """Hard reset for a device being closed, rather than an audible boundary."""
        with self._lock:
            self._queue.clear()
            self._offset = 0
            self._queued_samples = 0
            self._input_partial = b""
            self._pending = b""
            self._pending_frame = None
            self._last_frame = [0.] * self.channels
            self._rendered_last = self._last_frame[:]
            self._tail_origin = None
            self._tail_position = 0
            self._fade_position = 0

    def set_volume(self, value):
        value = float(value)
        if not math.isfinite(value):
            value = 0.
        with self._lock:
            self._volume = min(1., max(0., value))
            self._set_target_gain()

    def set_muted(self, value):
        with self._lock:
            self._muted = bool(value)
            self._set_target_gain()

    def _set_target_gain(self):
        target = 0. if self._muted else self._volume
        if target != self._gain_target:
            self._gain_start = self._gain
            self._gain_target = target
            self._gain_position = 0

    def _next_gain(self):
        if self._gain_position < self._ramp_frames:
            self._gain_position += 1
            fraction = (1 - math.cos(math.pi * self._gain_position / self._ramp_frames)) / 2
            self._gain = self._gain_start + (self._gain_target - self._gain_start) * fraction
        return self._gain

    def _frame(self):
        gain = self._next_gain()
        if self._tail_origin is not None:
            factor = (1 + math.cos(math.pi * self._tail_position / (self._fade_frames - 1))) / 2
            frame = [sample * factor for sample in self._tail_origin]
            self._tail_position += 1
            if self._tail_position >= self._fade_frames:
                self._tail_origin = None
        elif self._queue:
            chunk = self._queue[0]
            start = self._offset
            frame = chunk[start:start + self.channels]
            self._offset += self.channels
            self._queued_samples -= self.channels
            if self._offset >= len(chunk):
                self._queue.popleft()
                self._offset = 0
            if self._fade_position < self._fade_frames:
                self._fade_position += 1
                gain *= (1 - math.cos(math.pi * self._fade_position / self._fade_frames)) / 2
            frame = [max(-1., min(1., sample)) * gain if math.isfinite(sample) else 0. for sample in frame]
        elif any(self._rendered_last):
            # A network underrun is also a discontinuity. Return a short tail
            # before padding with silence, then fade in when PCM arrives again.
            self._tail_origin = self._rendered_last[:]
            self._tail_position = 0
            self._fade_position = 0
            return self._frame()
        else:
            frame = [0.] * self.channels
        self._rendered_last = list(frame)
        return frame

    def read(self, size):
        size = max(0, int(size))
        if not size:
            return b""
        with self._lock:
            result = bytearray()
            if self._pending:
                take = min(size, len(self._pending))
                result.extend(self._pending[:take])
                self._pending = self._pending[take:]
                if not self._pending:
                    self._last_frame = self._pending_frame
                    self._pending_frame = None
            remaining = size - len(result)
            complete_frames, remainder = divmod(remaining, self.frame_bytes)
            if complete_frames:
                samples = array("f")
                for _ in range(complete_frames):
                    frame = self._frame()
                    samples.extend(frame)
                self._last_frame = list(frame)
                if sys.byteorder != "little":
                    samples.byteswap()
                result.extend(samples.tobytes())
            if remainder:
                frame = self._frame()
                samples = array("f", frame)
                if sys.byteorder != "little":
                    samples.byteswap()
                payload = samples.tobytes()
                result.extend(payload[:remainder])
                self._pending = payload[remainder:]
                self._pending_frame = list(frame)
            return bytes(result)
