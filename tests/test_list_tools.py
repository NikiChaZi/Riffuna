"""Local list controls: context, selection intent and non-destructive reset."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from musicdesk.list_tools import ListTools


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tools(app):
    widget = ListTools()
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def test_typing_and_sorting_emit_values_and_clear_is_available(tools):
    queries = QSignalSpy(tools.query_changed)
    orders = QSignalSpy(tools.sort_changed)
    tools.search_input.setText('Дора')
    assert queries.at(0) == ['Дора']
    assert tools.search_input.isClearButtonEnabled()
    tools.sort_order.setCurrentIndex(tools.sort_order.findData('artist'))
    assert orders.at(0) == ['artist']
    tools.search_input.clear()
    assert queries.at(1) == ['']


def test_reset_is_atomic_and_rejects_invalid_order_before_changing_query(tools):
    queries = QSignalSpy(tools.query_changed)
    orders = QSignalSpy(tools.sort_changed)
    tools.reset('saved', 'duration')
    assert tools.query == 'saved' and tools.order == 'duration'
    assert queries.count() == orders.count() == 0
    with pytest.raises(ValueError):
        tools.reset('destroyed', 'unknown')
    assert tools.query == 'saved' and tools.order == 'duration'


def test_selection_actions_are_hidden_until_selected_and_emit_intent(tools):
    assert tools.actions_row.isHidden()
    assert not tools.selection_hint.isHidden()
    assert not tools.queue_button.isEnabled()
    signals = [QSignalSpy(tools.queue_requested), QSignalSpy(tools.playlist_requested),
               QSignalSpy(tools.remove_requested)]
    tools.set_context('playlist')
    tools.set_selection_count(3)
    assert not tools.actions_row.isHidden()
    assert tools.selection_label.text() == 'Выбрано: 3'
    assert tools.selection_hint.isHidden()
    for button in (tools.queue_button, tools.playlist_button, tools.remove_button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert [signal.count() for signal in signals] == [1, 1, 1]
    tools.set_selection_count(0)
    assert tools.actions_row.isHidden()
    assert not any(button.isEnabled() for button in (
        tools.queue_button, tools.playlist_button, tools.remove_button))


@pytest.mark.parametrize('context, removable, queueable', [
    ('search', False, True), ('history', False, True), ('likes', True, True),
    ('playlist', True, True), ('queue', True, False),
])
def test_context_limits_actions_and_server_search_preserves_batch_controls(
        tools, context, removable, queueable):
    tools.set_context(context)
    tools.set_selection_count(2)
    assert tools.filter_row.isHidden() == (context == 'search')
    assert tools.remove_button.isHidden() != removable
    assert tools.queue_button.isHidden() != queueable
    assert not tools.actions_row.isHidden()
    assert tools.playlist_button.isEnabled()


def test_context_change_clears_old_selection_and_updates_sort_labels(tools):
    tools.set_context('likes')
    tools.set_selection_count(2)
    tools.set_context('playlist')
    assert tools.actions_row.isHidden()
    assert tools.sort_order.itemText(tools.sort_order.findData('custom')) == 'Порядок плейлиста'
    assert tools.sort_order.findData('recent') == -1
    tools.set_context('history')
    assert tools.sort_order.itemText(tools.sort_order.findData('recent')) == 'Сначала новые'
    assert tools.sort_order.itemText(tools.sort_order.findData('custom')) == 'Порядок библиотеки'
    with pytest.raises(ValueError):
        tools.set_context('unknown')


def test_focus_search_selects_existing_filter_without_changing_it(tools, app):
    tools.reset('Дора')
    tools.activateWindow()
    tools.focus_search()
    app.processEvents()
    assert tools.search_input.hasFocus()
    assert tools.search_input.selectedText() == 'Дора'
