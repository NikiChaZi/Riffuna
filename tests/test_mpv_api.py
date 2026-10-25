import ctypes as C

import pytest

from musicdesk.mpv_api import (BYTE_ARRAY, DOUBLE, FLAG, INT64, NODE_ARRAY, NODE_MAP,
                               NONE, STRING, MpvCore, MpvEvent, MpvNode, MpvNodeList)


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Library:
    def __init__(self):
        self.options = []
        self.commands = []
        self.observations = []
        self.destroyed = []
        self.frees = 0
        self.references = []
        self.property_value = None
        self.get_error = 0
        self.initialize_error = 0
        self.command_error = 0
        self.event_value = {"event": "none"}
        self.event = MpvEvent(0, 0, 0, None)
        self.mpv_create = Function(lambda: 1234)
        self.mpv_initialize = Function(lambda _: self.initialize_error)
        self.mpv_set_option_string = Function(self.set_option)
        self.mpv_command_async = Function(self.command)
        self.mpv_get_property = Function(self.get_property)
        self.mpv_observe_property = Function(self.observe)
        self.mpv_wait_event = Function(lambda *_: C.pointer(self.event))
        self.mpv_event_to_node = Function(self.event_to_node)
        self.mpv_free_node_contents = Function(self.free)
        self.mpv_error_string = Function(lambda _: b"fixture engine error")
        self.mpv_terminate_destroy = Function(self.destroyed.append)

    def set_option(self, handle, name, value):
        self.options.append((name, value))
        return 0

    def command(self, handle, request, values):
        self.commands.append((request, [values[index] for index in range(len(values) - 1)]))
        assert values[len(values) - 1] is None
        return self.command_error

    def observe(self, handle, request, name, format):
        self.observations.append((request, name, format))
        return 0

    def node(self, value):
        node = MpvNode()
        if value is None:
            node.format = NONE
        elif isinstance(value, bool):
            node.format, node.u.flag = FLAG, value
        elif isinstance(value, int):
            node.format, node.u.int64 = INT64, value
        elif isinstance(value, float):
            node.format, node.u.double_ = DOUBLE, value
        elif isinstance(value, str):
            node.format, node.u.string = STRING, value.encode()
        elif isinstance(value, (list, dict)):
            children = list(value.values()) if isinstance(value, dict) else value
            nodes = (MpvNode * len(children))(*(self.node(child) for child in children))
            keys = (C.c_char_p * len(value))(*(key.encode() for key in value)) if isinstance(value, dict) else None
            entries = MpvNodeList(len(children), nodes, keys)
            node.format = NODE_MAP if isinstance(value, dict) else NODE_ARRAY
            node.u.list = C.pointer(entries)
            self.references.extend([nodes, keys, entries])
        else:
            raise AssertionError("Unexpected fixture value")
        self.references.append(node)
        return node

    def get_property(self, handle, name, format, destination):
        C.cast(destination, C.POINTER(MpvNode))[0] = self.node(self.property_value)
        return self.get_error

    def event_to_node(self, destination, event):
        C.cast(destination, C.POINTER(MpvNode))[0] = self.node(self.event_value)
        return 0

    def free(self, pointer):
        self.frees += 1
        # Invalidate the native result: returned Python data must remain owned.
        C.cast(pointer, C.POINTER(MpvNode)).contents.format = NONE


def test_initialization_async_commands_observation_and_idempotent_shutdown():
    library = Library()
    core = MpvCore("unused.dll", {"terminal": False, "idle": True}, _library=library)
    assert library.options == [(b"terminal", b"no"), (b"idle", b"yes")]
    first = core.command(["loadfile", "C:/Music/дора.m4a", "replace"])
    second = core.set_property("pause", False)
    observation = core.observe("time-pos", "double")
    assert 0 < first < second < observation
    assert library.commands[0][1] == [b"loadfile", "C:/Music/дора.m4a".encode(), b"replace"]
    assert library.commands[1][1] == [b"set", b"pause", b"no"]
    assert library.observations == [(observation, b"time-pos", DOUBLE)]
    with pytest.raises(ValueError):
        core.command(["loadfile", "bad\0argument"])
    core.close()
    core.close()
    assert library.destroyed == [1234]
    with pytest.raises(RuntimeError):
        core.command(["stop"])


def test_nested_native_properties_are_copied_and_freed_even_on_failure():
    library = Library()
    core = MpvCore("unused.dll", _library=library)
    library.property_value = {"devices": [{"name": "wasapi/one", "description": "Buds3 FE"}],
                              "duration": 123.5, "enabled": True, "id": 2 ** 40, "missing": None}
    expected = library.property_value
    assert core.get_property("audio-device-list") == expected
    assert library.frees == 1
    library.get_error = -10
    with pytest.raises(RuntimeError, match="fixture engine error"):
        core.get_property("unavailable")
    assert library.frees == 2
    core.close()


def test_event_maps_copy_property_changes_and_end_file_without_exposing_borrowed_pointers():
    library = Library()
    core = MpvCore("unused.dll", _library=library)
    assert core.wait_event(0) == {"event": "none"}
    library.event.event_id = 22
    library.event_value = {"event": "property-change", "id": 1, "name": "pause", "data": False}
    property_event = core.wait_event(0)
    assert property_event["data"] is False
    library.event.event_id = 7
    library.event_value = {"event": "end-file", "reason": "error", "error": "loading failed", "playlist_entry_id": 3}
    assert core.wait_event(0) == library.event_value
    assert property_event == {"event": "property-change", "id": 1, "name": "pause", "data": False}
    assert library.frees == 2
    core.close()


def test_initialization_failure_destroys_handle_and_command_errors_redact_arguments():
    library = Library()
    library.initialize_error = -3
    with pytest.raises(RuntimeError, match="initialize"):
        MpvCore("unused.dll", _library=library)
    assert library.destroyed == [1234]
    library.initialize_error = 0
    core = MpvCore("unused.dll", _library=library)
    library.command_error = -4
    with pytest.raises(RuntimeError) as error:
        core.command(["loadfile", "https://signed.example/audio?secret=never-print"])
    assert "secret" not in str(error.value)
    assert "fixture engine error" in str(error.value)
    core.close()
