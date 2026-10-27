from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .icons import icon
from .models import Track
from .surface_motion import attach_surface_motion
from .widgets import Artwork, Cover, ElidedLabel, label


class _TileAction(QWidget):
    def __init__(self, parent, playlist=False):
        super().__init__(parent)
        self.playlist = playlist
        self.progress = 0.0
        self.setFixedSize(40, 40)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        if self.progress <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.progress)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#FF875F'))
        painter.drawEllipse(QRectF(1, 1, 38, 38))
        icon('arrow_up_right' if self.playlist else 'play', '#151A19', 20).paint(painter, 10, 10, 20, 20)


class _CoverTile(QPushButton):
    def __init__(self, artwork: Artwork, title: str, subtitle: str,
                 thumbnail: str, seed: str, *, playlist=False, parent=None):
        super().__init__(parent)
        self.setObjectName('playlistTile' if playlist else 'trackTile')
        self.setAccessibleName(('Открыть плейлист: ' if playlist else 'Слушать: ') + title)
        self.setToolTip(title + '\n' + subtitle)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(218)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(5)
        self.cover = Cover(artwork, 136, seed=seed)
        self.cover.set_url(thumbnail)
        layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)
        layout.addWidget(ElidedLabel(title, 'tileTitle'))
        layout.addWidget(ElidedLabel(subtitle, 'tileSubtitle'))
        self.action = _TileAction(self, playlist)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.motion = attach_surface_motion(self)
        self.action.raise_()

    def _surface_progress(self, hover, press):
        self.action.progress = hover
        self._place_action()
        self.action.update()

    def _place_action(self):
        top = self.cover.mapTo(self, self.cover.rect().topLeft())
        self.action.move(top.x() + self.cover.width() - 46,
                         top.y() + self.cover.height() - 46 + round(5 * (1 - self.action.progress)))
        self.action.raise_()

    def resizeEvent(self, event):
        side = min(208, max(64, self.width() - 24))
        self.cover.setFixedSize(side, side)
        if self.height() != side + 82:
            self.setFixedHeight(side + 82)
        self.layout().activate()
        self._place_action()
        super().resizeEvent(event)


class _ListeningHero(QPushButton):
    def __init__(self, artwork, track, *, current=False):
        super().__init__()
        self.setObjectName('listeningHero')
        self.setAccessibleName('Слушать: ' + track.title + ' — ' + track.artist)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(200)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 18, 18, 18)
        row.setSpacing(20)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        texts.addWidget(label('В ТВОЁМ ПЛЕЕРЕ' if current else 'ВЕРНУТЬСЯ К МУЗЫКЕ', 'libraryKicker'))
        texts.addStretch(1)
        texts.addWidget(ElidedLabel(track.title, 'heroRecording'))
        texts.addWidget(ElidedLabel(track.artist, 'heroArtist'))
        texts.addStretch(1)
        texts.addWidget(label('Слушать запись  →', 'heroAction'))
        row.addLayout(texts, 1)
        self.cover = Cover(artwork, 164, seed=track.video_id)
        self.cover.set_url(track.thumbnail)
        row.insertWidget(0, self.cover)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        attach_surface_motion(self)

    def resizeEvent(self, event):
        side = 128 if self.width() < 560 else 164
        self.cover.setFixedSize(side, side)
        super().resizeEvent(event)


class _LibraryPage(QScrollArea):
    def __init__(self, artwork: Artwork, parent=None):
        super().__init__(parent)
        self.artwork = artwork
        self._signature = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body.setObjectName('libraryPage')
        self.layout = QVBoxLayout(self.body)
        self.layout.setContentsMargins(0, 4, 8, 24)
        self.layout.setSpacing(22)
        self.setWidget(self.body)
        self._grids = []
        self._columns = 3

    def _clear(self):
        self._grids.clear()
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def _restore(self, position):
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(position))

    def _heading(self, title, subtitle='', action=None):
        first = not self.layout.count()
        section = QWidget()
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(5)
        if first:
            texts.addWidget(label('ТВОЯ КОЛЛЕКЦИЯ', 'libraryKicker'))
        texts.addWidget(label(title, 'libraryTitle' if first else 'sectionTitle'))
        if subtitle:
            text = label(subtitle, 'libraryIntro')
            text.setWordWrap(True)
            texts.addWidget(text)
        row.addLayout(texts, 1)
        if action:
            button = QPushButton(action[0])
            button.setObjectName('primary' if first else 'sectionAction')
            button.setAccessibleName(action[0])
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action[1])
            attach_surface_motion(button)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignBottom)
        self.layout.addWidget(section)

    def _grid(self, tiles):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        for column in range(5):
            grid.setColumnStretch(column, 1 if column < self._columns else 0)
        for index, tile in enumerate(tiles):
            grid.addWidget(tile, index // self._columns, index % self._columns)
        self._grids.append((grid, tiles))
        self.layout.addWidget(container)

    def _empty(self, title, description, action_text, callback):
        panel = QWidget()
        panel.setObjectName('libraryEmpty')
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 26, 24, 26)
        layout.setSpacing(12)
        mark = label('', 'emptyMark')
        mark.setPixmap(icon('collection', '#FF875F', 32).pixmap(32, 32))
        layout.addWidget(mark)
        title_label = label(title, 'sectionTitle')
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        description_label = label(description, 'muted')
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        button = QPushButton(action_text)
        button.setObjectName('primary')
        button.setAccessibleName(action_text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        attach_surface_motion(button)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(panel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = max(1, min(5, (self.viewport().width() + 12) // 164))
        if columns == self._columns:
            return
        self._columns = columns
        for grid, tiles in self._grids:
            for tile in tiles:
                grid.removeWidget(tile)
            for column in range(5):
                grid.setColumnStretch(column, 1 if column < columns else 0)
            for index, tile in enumerate(tiles):
                grid.addWidget(tile, index // columns, index % columns)


class HomePage(_LibraryPage):
    track_requested = Signal(object)
    track_context_requested = Signal(object, object)
    view_requested = Signal(str)
    playlist_requested = Signal(int)
    create_requested = Signal()

    def _tracks(self, tracks):
        tiles = []
        for track in tracks:
            tile = _CoverTile(self.artwork, track.title, track.artist, track.thumbnail, track.video_id)
            tile.clicked.connect(lambda checked=False, track=track: self.track_requested.emit(track))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda point, track=track, tile=tile:
                self.track_context_requested.emit(track, tile.mapToGlobal(point)))
            tiles.append(tile)
        self._grid(tiles)

    def refresh(self, history: list[Track], likes: list[Track], playlists: list[dict],
                current: Track | None, queue_count: int):
        signature = (tuple(history[:9]), tuple(likes[:6]),
                     tuple((p['id'], p['name'], p['track_count'], p.get('thumbnail', '')) for p in playlists[:6]),
                     current, queue_count)
        if signature == self._signature:
            return
        self._signature = signature
        position = self.verticalScrollBar().value()
        self._clear()
        self._heading('Твоя музыка', 'То, к чему хочется возвращаться.')
        recent, seen = [], set()
        for track in ([current] if current else []) + list(history):
            if track.video_id not in seen:
                recent.append(track)
                seen.add(track.video_id)
            if len(recent) == 6:
                break
        if recent:
            feature = _ListeningHero(self.artwork, recent[0], current=current is not None)
            feature.clicked.connect(lambda checked=False, track=recent[0]: self.track_requested.emit(track))
            self.layout.addWidget(feature)
            self._heading('Недавно слушал', action=('Вся история', lambda: self.view_requested.emit('history')))
            self._tracks(recent)
        if likes:
            self._heading('Мне нравится', action=('Все треки', lambda: self.view_requested.emit('likes')))
            self._tracks(likes[:6])
        if not recent and not likes:
            self._empty('Здесь появится твоя музыка', 'Найди первый трек, послушай его или поставь лайк — он появится на главной.',
                        'Найти музыку', lambda: self.view_requested.emit('search'))
        self._heading('Твои плейлисты', action=('Создать', self.create_requested.emit))
        if playlists:
            tiles = []
            for playlist in playlists[:6]:
                playlist_id = int(playlist['id'])
                tile = _CoverTile(self.artwork, playlist['name'], f"Треков: {playlist['track_count']}",
                                  playlist.get('thumbnail', ''), str(playlist_id), playlist=True)
                tile.clicked.connect(lambda checked=False, value=playlist_id: self.playlist_requested.emit(value))
                tiles.append(tile)
            self._grid(tiles)
        else:
            self._empty('Собери свой первый плейлист', 'Добавляй треки через меню композиции и слушай свою подборку в любом порядке.',
                        'Создать плейлист', self.create_requested.emit)
        self.layout.addStretch(1)
        self._restore(position)


class PlaylistPage(_LibraryPage):
    playlist_requested = Signal(int)
    create_requested = Signal()
    context_requested = Signal(int, object)

    def refresh(self, playlists: list[dict]):
        signature = tuple((p['id'], p['name'], p['track_count'], p.get('thumbnail', '')) for p in playlists)
        if signature == self._signature:
            return
        self._signature = signature
        position = self.verticalScrollBar().value()
        self._clear()
        self._heading('Плейлисты', 'Собрано тобой. Звучит по-твоему.', action=('Создать плейлист', self.create_requested.emit))
        if playlists:
            tiles = []
            for playlist in playlists:
                playlist_id = int(playlist['id'])
                tile = _CoverTile(self.artwork, playlist['name'], f"Треков: {playlist['track_count']}",
                                  playlist.get('thumbnail', ''), str(playlist_id), playlist=True)
                tile.clicked.connect(lambda checked=False, value=playlist_id: self.playlist_requested.emit(value))
                tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                tile.customContextMenuRequested.connect(lambda point, value=playlist_id, tile=tile:
                    self.context_requested.emit(value, tile.mapToGlobal(point)))
                tiles.append(tile)
            self._grid(tiles)
        else:
            self._empty('Пока нет плейлистов', 'Создай подборку и добавь любимые композиции через меню трека.',
                        'Создать плейлист', self.create_requested.emit)
        self.layout.addStretch(1)
        self._restore(position)
