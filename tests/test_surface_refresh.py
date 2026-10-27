"""Offline visual-interaction regressions; no user data, network or audio."""
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton, QWidget
import pytest

from test_ui_search import app
from musicdesk.library_views import HomePage, PlaylistPage
from musicdesk.models import Track
from musicdesk.motion import MotionPolicy
from musicdesk.surface_motion import attach_surface_motion, install_surface_motion
from musicdesk.track_list import TrackList
from musicdesk.widgets import Artwork, Cover, TrackRow


@pytest.fixture
def records():
    return [Track(f'{i:011d}', f'Offline fixture {i}', 'Fixture artist', 180,
                  f'https://i.ytimg.com/vi/{i:011d}/hqdefault.jpg') for i in range(6)]


def cached(artwork, records):
    for track in records:
        image = QPixmap(240, 240)
        image.fill(QColor('#CC7959'))
        artwork.cache[track.thumbnail] = image


def test_surface_interruption_reduced_motion_and_hide_leave_no_running_animation(app):
    button = QPushButton('Action')
    policy = MotionPolicy()
    motion = attach_surface_motion(button, policy)
    button.show()
    app.processEvents()
    button.clearFocus()
    app.sendEvent(button, QEvent(QEvent.Type.Enter))
    motion.hover.animation.setCurrentTime(40)
    current = motion.hover.value
    assert 0 < current < 1
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert motion.hover.animation.startValue() == current
    policy.set_reduced(True)
    assert motion.hover.value == 0 and not motion.hover.running
    app.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert motion.hover.value == 1 and not motion.hover.running
    policy.set_reduced(False)
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    button.hide()
    assert not motion.hover.running and not motion.press.running
    assert motion.hover.value == motion.press.value == 0
    button.deleteLater()
    app.processEvents()


def test_surface_installation_is_idempotent_and_feedback_does_not_steal_clicks(app):
    host = QWidget()
    host.motion_policy = MotionPolicy(True, host)
    button = QPushButton('Action', host)
    button.setGeometry(20, 20, 120, 44)
    first = install_surface_motion(host, host.motion_policy)
    second = install_surface_motion(host, host.motion_policy)
    assert first == second and len(first) == 1
    host.show()
    app.processEvents()
    clicked = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicked.count() == 1
    assert first[0].overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert button.graphicsEffect() is None
    host.close()
    host.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('width', [430, 560, 920])
def test_responsive_cards_keep_original_artwork_and_do_not_run_idle_motion(app, records, width):
    artwork = Artwork()
    cached(artwork, records)
    page = HomePage(artwork)
    page.refresh(records, records[:2], [], records[0], 3)
    page.resize(width, 650)
    page.show()
    app.processEvents()
    QTest.qWait(180)
    assert page.horizontalScrollBar().maximum() == 0
    tiles = [tile for tile in page.findChildren(QPushButton, 'trackTile') if tile.isVisible()]
    assert len(tiles) == 8
    for tile in tiles:
        cover = tile.findChild(Cover)
        assert not cover.pixmap.isNull()
        assert cover.width() == min(208, tile.width() - 24)
        assert not tile.motion.hover.running and not tile.motion.press.running
    page.close()
    page.deleteLater()
    app.processEvents()


def test_home_feature_is_an_actual_recording_and_click_emits_its_exact_identity(app, records):
    artwork = Artwork()
    cached(artwork, records)
    page = HomePage(artwork)
    page.refresh(records, [], [], records[2], 0)
    feature = page.findChild(QPushButton, 'listeningHero')
    assert feature is not None
    assert records[2].title in feature.accessibleName()
    play = QSignalSpy(page.track_requested)
    feature.click()
    assert play.count() == 1 and play.at(0) == [records[2]]
    page.refresh([], [], [], None, 0)
    assert not [button for button in page.findChildren(QPushButton, 'listeningHero') if not button.isHidden()]
    page.deleteLater()
    app.processEvents()


def test_selection_feedback_is_cleared_without_altering_record_order(app, records):
    from PySide6.QtWidgets import QListWidgetItem
    artwork = Artwork()
    cached(artwork, records)
    listing = TrackList()
    row = TrackRow(records[0], artwork, False)
    item = QListWidgetItem(listing)
    item.setData(Qt.ItemDataRole.UserRole, records[0])
    listing.setItemWidget(item, row)
    item.setSelected(True)
    assert row.property('selected') is True
    listing.clearSelection()
    assert row.property('selected') is False
    assert listing.ids() == [records[0].video_id]
    listing.deleteLater()
    app.processEvents()


def test_cover_play_control_keeps_single_existing_intent_and_like_semantics(app, records):
    artwork = Artwork()
    cached(artwork, records)
    row = TrackRow(records[0], artwork, False)
    row.resize(500, 72)
    row.show()
    app.processEvents()
    play = QSignalSpy(row.play_requested)
    QTest.mouseClick(row.play_button, Qt.MouseButton.LeftButton)
    assert play.count() == 1 and play.at(0) == [records[0]]
    assert isinstance(row.play_button.parentWidget(), Cover)
    row.set_liked(True)
    assert row.like_button.accessibleName().startswith('Убрать лайк:')
    row.close()
    row.deleteLater()
    app.processEvents()


def test_surface_event_filter_ignores_qt_teardown_after_python_fields_are_cleared(app):
    # Reproduce the final Hide callback that PySide can issue during wrapper GC.
    button = QPushButton('Teardown')
    motion = attach_surface_motion(button)
    hover = motion.hover
    del motion.hover
    assert motion.eventFilter(button, QEvent(QEvent.Type.Hide)) is False
    motion.hover = hover
    button.deleteLater()
    app.processEvents()


def test_repeated_surface_widget_destruction_does_not_interrupt_result_population(app, records):
    import gc
    from PySide6.QtWidgets import QListWidgetItem
    artwork = Artwork()
    cached(artwork, records)
    listing = TrackList()
    listing.show()
    for _ in range(3):
        listing.clear()
        for index in range(120):
            row = TrackRow(records[index % len(records)], artwork, False)
            item = QListWidgetItem(listing)
            item.setData(Qt.ItemDataRole.UserRole, row.track)
            listing.setItemWidget(item, row)
        app.processEvents()
        gc.collect()
        assert listing.count() == 120
    listing.close()
    listing.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('width', [212, 240, 272])
def test_long_queue_metadata_keeps_play_and_remove_inside_narrow_panel(app, width):
    from musicdesk.widgets import QueueRow
    artwork = Artwork()
    record = Track('00000000000', 'Very long recording title (Extended Mix) ' * 4,
                   'A very long artist name ' * 4, 312)
    row = QueueRow(record, 0, False, artwork=artwork)
    row.resize(width, 62)
    row.show()
    app.processEvents()
    assert row.width() == width
    assert row.minimumSizeHint().width() <= width
    buttons = row.findChildren(QPushButton)
    assert len(buttons) == 2
    for button in buttons:
        assert row.rect().contains(button.geometry())
    removed = QSignalSpy(row.remove_requested)
    buttons[-1].click()
    assert removed.at(0) == [0]
    row.close()
    row.deleteLater()
    app.processEvents()
