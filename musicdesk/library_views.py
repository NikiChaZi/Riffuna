from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .models import Track
from .widgets import Artwork, Cover, ElidedLabel, label


class _CoverTile(QPushButton):
    def __init__(self, artwork: Artwork, title: str, subtitle: str,
                 thumbnail: str, seed: str, *, playlist=False, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistTile" if playlist else "trackTile")
        self.setAccessibleName(("Открыть плейлист: " if playlist else "Слушать: ") + title)
        self.setToolTip(title + "\n" + subtitle)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(5)
        self.cover = Cover(artwork, 128, seed=seed)
        self.cover.set_url(thumbnail)
        layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(5)
        layout.addWidget(ElidedLabel(title, "trackTitle"))
        layout.addWidget(ElidedLabel(subtitle, "cardSubtitle"))
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class _LibraryPage(QScrollArea):
    def __init__(self, artwork: Artwork, parent=None):
        super().__init__(parent)
        self.artwork = artwork
        self._signature = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("libraryPage")
        self.layout = QVBoxLayout(self.body)
        self.layout.setContentsMargins(0, 0, 8, 16)
        self.layout.setSpacing(18)
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

    def _heading(self, title, subtitle="", action=None):
        section = QWidget()
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addWidget(label(title, "pageTitle" if not self.layout.count() else "sectionTitle"))
        if subtitle:
            text = label(subtitle, "muted")
            text.setWordWrap(True)
            texts.addWidget(text)
        row.addLayout(texts, 1)
        if action:
            button = QPushButton(action[0])
            button.setAccessibleName(action[0])
            button.clicked.connect(action[1])
            row.addWidget(button)
        self.layout.addWidget(section)

    def _grid(self, tiles):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for column in range(3):
            grid.setColumnStretch(column, 1 if column < self._columns else 0)
        for index, tile in enumerate(tiles):
            grid.addWidget(tile, index // self._columns, index % self._columns)
        self._grids.append((grid, tiles))
        self.layout.addWidget(container)

    def _empty(self, title, description, action_text, callback):
        panel = QWidget()
        panel.setObjectName("libraryEmpty")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(10)
        layout.addWidget(label(title, "sectionTitle"))
        description_label = label(description, "muted")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        button = QPushButton(action_text)
        button.setObjectName("primary")
        button.setAccessibleName(action_text)
        button.clicked.connect(callback)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(panel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 3 if self.viewport().width() >= 480 else 2
        if columns == self._columns:
            return
        self._columns = columns
        for grid, tiles in self._grids:
            for tile in tiles:
                grid.removeWidget(tile)
            for column in range(3):
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
            tile = _CoverTile(self.artwork, track.title, track.artist, track.thumbnail,
                              track.video_id)
            tile.clicked.connect(lambda checked=False, track=track: self.track_requested.emit(track))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(
                lambda point, track=track, tile=tile:
                self.track_context_requested.emit(track, tile.mapToGlobal(point)))
            tiles.append(tile)
        self._grid(tiles)

    def refresh(self, history: list[Track], likes: list[Track], playlists: list[dict],
                current: Track | None, queue_count: int):
        signature = (tuple(history[:9]), tuple(likes[:6]),
                     tuple((p["id"], p["name"], p["track_count"], p.get("thumbnail", ""))
                           for p in playlists[:6]), current, queue_count)
        if signature == self._signature:
            return
        self._signature = signature
        position = self.verticalScrollBar().value()
        self._clear()
        self._heading("Твоя музыка", "Любимые треки, недавние прослушивания и твои плейлисты.")
        recent, seen = [], set()
        for track in ([current] if current else []) + list(history):
            if track.video_id not in seen:
                recent.append(track)
                seen.add(track.video_id)
            if len(recent) == 6:
                break
        if recent:
            self._heading("Недавно слушал", action=("Вся история", lambda: self.view_requested.emit("history")))
            self._tracks(recent)
        if likes:
            self._heading("Мне нравится", action=("Все треки", lambda: self.view_requested.emit("likes")))
            self._tracks(likes[:6])
        if not recent and not likes:
            self._empty("Здесь появится твоя музыка", "Найди первый трек, послушай его или поставь лайк — он появится на главной.",
                        "Найти музыку", lambda: self.view_requested.emit("search"))
        self._heading("Твои плейлисты", action=("Создать", self.create_requested.emit))
        if playlists:
            tiles = []
            for playlist in playlists[:6]:
                playlist_id = int(playlist["id"])
                tile = _CoverTile(self.artwork, playlist["name"],
                                  f"Треков: {playlist['track_count']}", playlist.get("thumbnail", ""),
                                  str(playlist_id), playlist=True)
                tile.clicked.connect(lambda checked=False, value=playlist_id: self.playlist_requested.emit(value))
                tiles.append(tile)
            self._grid(tiles)
        else:
            self._empty("Собери свой первый плейлист", "Добавляй треки через меню композиции и слушай свою подборку в любом порядке.",
                        "Создать плейлист", self.create_requested.emit)
        self.layout.addStretch(1)
        self._restore(position)


class PlaylistPage(_LibraryPage):
    playlist_requested = Signal(int)
    create_requested = Signal()
    context_requested = Signal(int, object)

    def refresh(self, playlists: list[dict]):
        signature = tuple((p["id"], p["name"], p["track_count"], p.get("thumbnail", ""))
                          for p in playlists)
        if signature == self._signature:
            return
        self._signature = signature
        position = self.verticalScrollBar().value()
        self._clear()
        self._heading("Плейлисты", "Твои подборки для любого настроения.",
                      action=("Создать плейлист", self.create_requested.emit))
        if playlists:
            tiles = []
            for playlist in playlists:
                playlist_id = int(playlist["id"])
                tile = _CoverTile(self.artwork, playlist["name"], f"Треков: {playlist['track_count']}",
                                  playlist.get("thumbnail", ""), str(playlist_id), playlist=True)
                tile.clicked.connect(lambda checked=False, value=playlist_id: self.playlist_requested.emit(value))
                tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                tile.customContextMenuRequested.connect(lambda point, value=playlist_id, tile=tile:
                    self.context_requested.emit(value, tile.mapToGlobal(point)))
                tiles.append(tile)
            self._grid(tiles)
        else:
            self._empty("Пока нет плейлистов", "Создай подборку и добавь любимые композиции через меню трека.",
                        "Создать плейлист", self.create_requested.emit)
        self.layout.addStretch(1)
        self._restore(position)
