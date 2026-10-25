"""Small ctypes binding to libmpv's stable C client API (no playback threads)."""
from __future__ import annotations

import ctypes as C
import itertools
import os
from pathlib import Path
import threading


NONE, STRING, OSD_STRING, FLAG, INT64, DOUBLE, NODE, NODE_ARRAY, NODE_MAP, BYTE_ARRAY = range(10)


class MpvNode(C.Structure):
    pass


class MpvNodeList(C.Structure):
    _fields_ = [("num", C.c_int), ("values", C.POINTER(MpvNode)), ("keys", C.POINTER(C.c_char_p))]


class MpvByteArray(C.Structure):
    _fields_ = [("data", C.c_void_p), ("size", C.c_size_t)]


class MpvNodeUnion(C.Union):
    _fields_ = [("string", C.c_char_p), ("flag", C.c_int), ("int64", C.c_int64),
                ("double_", C.c_double), ("list", C.POINTER(MpvNodeList)),
                ("ba", C.POINTER(MpvByteArray))]


MpvNode._fields_ = [("u", MpvNodeUnion), ("format", C.c_int)]


class MpvEvent(C.Structure):
    _fields_ = [("event_id", C.c_int), ("error", C.c_int),
                ("reply_userdata", C.c_uint64), ("data", C.c_void_p)]


def _decode(value):
    return value.decode("utf-8", errors="replace") if value else ""


def _node_value(node):
    kind = node.format
    if kind in (STRING, OSD_STRING):
        return _decode(node.u.string)
    if kind == FLAG:
        return bool(node.u.flag)
    if kind == INT64:
        return int(node.u.int64)
    if kind == DOUBLE:
        return float(node.u.double_)
    if kind in (NODE_ARRAY, NODE_MAP):
        if not node.u.list:
            return {} if kind == NODE_MAP else []
        entries = node.u.list.contents
        if entries.num < 0 or entries.num > 1000000:
            raise RuntimeError("libmpv returned an invalid node list")
        if kind == NODE_ARRAY:
            return [_node_value(entries.values[index]) for index in range(entries.num)]
        return {_decode(entries.keys[index]): _node_value(entries.values[index]) for index in range(entries.num)}
    if kind == BYTE_ARRAY and node.u.ba:
        data = node.u.ba.contents
        return C.string_at(data.data, data.size) if data.data else b""
    return None


def _text(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


class MpvCore:
    """Initialize once; caller owns event polling and joins it before close()."""

    def __init__(self, dll_path, options=None, *, _library=None):
        self._handle = None
        self._directory = None
        self._requests = itertools.count(1)
        self._request_lock = threading.Lock()
        if _library is None:
            path = Path(dll_path).resolve()
            try:
                if hasattr(os, "add_dll_directory"):
                    self._directory = os.add_dll_directory(str(path.parent))
                self._dll = C.CDLL(str(path))
            except OSError:
                if self._directory is not None:
                    self._directory.close()
                raise RuntimeError("Не удалось загрузить аудиодвижок libmpv.") from None
        else:
            self._dll = _library
        self._bind()
        self._handle = self._dll.mpv_create()
        if not self._handle:
            raise RuntimeError("Не удалось создать аудиодвижок libmpv.")
        try:
            for name, value in (options or {}).items():
                self._check(self._dll.mpv_set_option_string(self._handle, name.encode(), _text(value).encode()),
                            "set option")
            self._check(self._dll.mpv_initialize(self._handle), "initialize")
        except Exception:
            self.close()
            raise

    def _bind(self):
        specifications = {
            "mpv_create": (C.c_void_p, []),
            "mpv_initialize": (C.c_int, [C.c_void_p]),
            "mpv_set_option_string": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            "mpv_command_async": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_char_p)]),
            "mpv_get_property": (C.c_int, [C.c_void_p, C.c_char_p, C.c_int, C.c_void_p]),
            "mpv_observe_property": (C.c_int, [C.c_void_p, C.c_uint64, C.c_char_p, C.c_int]),
            "mpv_wait_event": (C.POINTER(MpvEvent), [C.c_void_p, C.c_double]),
            "mpv_event_to_node": (C.c_int, [C.POINTER(MpvNode), C.POINTER(MpvEvent)]),
            "mpv_free_node_contents": (None, [C.POINTER(MpvNode)]),
            "mpv_error_string": (C.c_char_p, [C.c_int]),
            "mpv_terminate_destroy": (None, [C.c_void_p]),
        }
        for name, (result, arguments) in specifications.items():
            function = getattr(self._dll, name)
            function.restype = result
            function.argtypes = arguments

    def _require_handle(self):
        if self._handle is None:
            raise RuntimeError("Аудиодвижок libmpv уже закрыт.")
        return self._handle

    def _check(self, code, operation):
        if code < 0:
            # Error descriptions contain engine status only, never command URLs.
            detail = _decode(self._dll.mpv_error_string(code))
            raise RuntimeError(f"libmpv {operation}: {detail}")
        return code

    def _request_id(self):
        with self._request_lock:
            return next(self._requests)

    def command(self, arguments):
        if not arguments:
            raise ValueError("A command requires at least one argument")
        encoded = [_text(value).encode("utf-8") for value in arguments]
        if any(b"\0" in value for value in encoded):
            raise ValueError("Command arguments must not contain NUL")
        values = (C.c_char_p * (len(encoded) + 1))(*encoded, None)
        request = self._request_id()
        self._check(self._dll.mpv_command_async(self._require_handle(), request, values), "command")
        return request

    def set_property(self, name, value):
        return self.command(["set", name, _text(value)])

    def get_property(self, name):
        node = MpvNode()
        try:
            self._check(self._dll.mpv_get_property(self._require_handle(), name.encode(), NODE, C.byref(node)),
                        "get property")
            return _node_value(node)
        finally:
            self._dll.mpv_free_node_contents(C.byref(node))

    def observe(self, name, format="double"):
        kind = {"none": NONE, "string": STRING, "flag": FLAG, "int64": INT64, "double": DOUBLE, "node": NODE}.get(format)
        if kind is None:
            raise ValueError("Unsupported libmpv observation format")
        request = self._request_id()
        self._check(self._dll.mpv_observe_property(self._require_handle(), request, name.encode(), kind),
                    "observe property")
        return request

    def wait_event(self, timeout=.2):
        event = self._dll.mpv_wait_event(self._require_handle(), max(0., float(timeout)))
        if not event or event.contents.event_id == 0:
            return {"event": "none"}
        node = MpvNode()
        try:
            self._check(self._dll.mpv_event_to_node(C.byref(node), event), "read event")
            value = _node_value(node)
            return value if isinstance(value, dict) else {"event": "unknown"}
        finally:
            self._dll.mpv_free_node_contents(C.byref(node))

    def close(self):
        handle, self._handle = self._handle, None
        if handle is not None:
            self._dll.mpv_terminate_destroy(handle)
        if self._directory is not None:
            self._directory.close()
            self._directory = None
