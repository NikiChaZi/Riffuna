from __future__ import annotations

import uuid

from PySide6.QtCore import QSize, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton, QScrollArea, QInputDialog, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget, QFileDialog,
)

from .version_dialog import RecordingVersionsDialog
from .expanded_player import ExpandedPlayer, ExpandableCover
from .player_view_binding import ExpandedPlayerBinding
from .motion import MotionPolicy, PageFade
from .lyrics_controller import LyricsController
from .recommendations import RecommendationClient, resolve_suggestion
from .recommendation_page import RecommendationPage
from . import __version__
from .appearance import app_icon
from .branding import APP_NAME
from .icons import icon
from .models import Track, time_label
from .library_views import HomePage, PlaylistPage
from .playback import Playback
from .storage import Library
from .widgets import Artwork, Cover, ElidedLabel, PointerSlider, QueryCard, QueueRow, RecordArt, SortComboBox, TrackRow, icon_button, label, tile_pixmap
from .workers import Task
from .youtube import YouTubeSource


class MainWindow(QMainWindow):
    def __init__(self, library: Library, source: YouTubeSource | None = None):
        super().__init__()
        self.library = library
        self.source = source or YouTubeSource()
        self.artwork = Artwork(self)
        self.playback = Playback(library, self.source, self)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._search_token = ""
        self._search_tasks: dict[str, Task] = {}
        self._search_loading = False
        self._search_limit = 0
        self._requested_limit = 40
        self._search_order = "relevance"
        self._search_has_more = False
        self._search_error = ""
        self.search_results: list[Track] = []
        self.visible_tracks: list[Track] = []
        self.rows: list[TrackRow] = []
        self.liked = library.liked_ids()
        self._playlist_id = None
        self.view = "home"
        self.last_query = ""
        self._shutting_down = False
        self._recommendation_token = ""
        self._recommendation_tasks = {}
        self._recommendation_result = None
        self._recommendation_client = RecommendationClient()
        self._recommendation_play_token = ""
        self._recommendation_resolving = False
        self._version_dialogs = []
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1000, 650)
        self.resize(1280, 800)
        self._build()
        self._connect()
        self._build_expanded_player()
        self._refresh_queue()
        self._refresh_likes()
        self._shuffle_changed(self.playback.shuffle)
        self._on_track(self.playback.current)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._focus_search)

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        body.addWidget(self._content(), 1)
        body.addWidget(self._queue_panel())
        outer.addLayout(body, 1)
        outer.addWidget(self._player_bar())

    def _sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        self.sidebar_panel = panel
        panel.setFixedWidth(192)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 24, 12, 20)
        layout.setSpacing(7)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(36, 36))
        brand.addWidget(mark)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(24)
        layout.addWidget(label("ОБЗОР", "eyebrow"))
        self.nav: dict[str, QPushButton] = {}
        for key, title, glyph in [("home", "Главная", "home"), ("resonance", "Резонанс", "shuffle"), ("search", "Поиск", "search"),
                                   ("likes", "Мне нравится", "heart"), ("playlists", "Плейлисты", "playlist"), ("history", "История", "history")]:
            if key == "likes":
                layout.addSpacing(18)
                layout.addWidget(label("БИБЛИОТЕКА", "eyebrow"))
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setChecked(key == "home")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, section=key: self.show_view(section))
            self.nav[key] = button
            layout.addWidget(button)
        layout.addStretch()
        layout.addWidget(label("ЛОКАЛЬНО", "eyebrow"))
        self.likes_count = label("Пока без лайков", "muted")
        layout.addWidget(self.likes_count)
        layout.addSpacing(18)
        layout.addWidget(label("Лайки и история\nхранятся на этом ПК", "tiny"))
        layout.addSpacing(14)
        layout.addWidget(label("RIFFUNA / " + __version__, "tiny"))
        return panel

    def _content(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("content")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 12)
        layout.setSpacing(16)
        search_row = QHBoxLayout()
        search_row.setSpacing(9)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Трек, исполнитель или ссылка YouTube")
        self.search_input.setAccessibleName("Поиск музыки")
        self.search_input.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setToolTip("Поиск музыки · Ctrl+F")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedHeight(44)
        self.search_input.setMaxLength(500)
        self.search_input.returnPressed.connect(self.search)
        search_row.addWidget(self.search_input, 1)
        search_button = QPushButton("Найти")
        search_button.setObjectName("primary")
        search_button.setFixedHeight(44)
        search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        search_button.clicked.connect(self.search)
        search_row.addWidget(search_button)
        self.queue_toggle = icon_button("queue", "Показать или скрыть очередь", 44)
        self.queue_toggle.setCheckable(True)
        self.queue_toggle.setChecked(True)
        self.queue_toggle.clicked.connect(lambda checked: self.queue_panel.setVisible(checked))
        search_row.addWidget(self.queue_toggle)
        layout.addLayout(search_row)
        self.notice = label("", "notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        self.stack = QStackedWidget()
        self.home = self._home()
        self.stack.addWidget(self.home)
        self.playlist_page = PlaylistPage(self.artwork)
        self.playlist_page.playlist_requested.connect(self._show_playlist)
        self.playlist_page.create_requested.connect(self._create_playlist)
        self.playlist_page.context_requested.connect(self._playlist_menu)
        self.stack.addWidget(self.playlist_page)
        self.results_page = QWidget()
        results_layout = QVBoxLayout(self.results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(12)
        self.section_header = QFrame()
        self.section_header.setObjectName("sectionHeader")
        heading_row = QHBoxLayout(self.section_header)
        heading_row.setContentsMargins(16, 14, 16, 14)
        heading_row.setSpacing(16)
        self.section_cover = label("")
        self.section_cover.setFixedSize(64, 64)
        heading_row.addWidget(self.section_cover)
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_kind = label("ПОИСК", "eyebrow")
        titles.addWidget(self.page_kind)
        self.page_title = ElidedLabel("Результаты", "pageTitle")
        self.page_subtitle = label("", "muted")
        self.page_subtitle.setWordWrap(True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        heading_row.addLayout(titles, 1)
        self.play_all = QPushButton("Слушать всё")
        self.play_all.setIcon(icon("play", "#151716"))
        self.play_all.setObjectName("listenAll")
        self.play_all.clicked.connect(lambda: self.playback.play_all(self.visible_tracks))
        heading_row.addWidget(self.play_all)
        self.playlist_actions = icon_button("more", "Действия с плейлистом", 36)
        self.playlist_actions.clicked.connect(lambda: self._playlist_menu(self._playlist_id, self.playlist_actions.mapToGlobal(self.playlist_actions.rect().bottomLeft())))
        self.playlist_actions.hide()
        heading_row.addWidget(self.playlist_actions)
        results_layout.addWidget(self.section_header)
        self.search_controls = QWidget()
        search_controls_layout = QHBoxLayout(self.search_controls)
        search_controls_layout.setContentsMargins(0, 0, 0, 0)
        search_controls_layout.setSpacing(10)
        sort_label = label("Сортировка", "muted")
        search_controls_layout.addWidget(sort_label)
        self.search_order = SortComboBox()
        self.search_order.setObjectName("searchOrder")
        self.search_order.setAccessibleName("Сортировка результатов поиска")
        self.search_order.addItem("По релевантности", "relevance")
        self.search_order.addItem("По просмотрам", "views")
        self.search_order.setItemData(1, "Среди найденных музыкальных записей", Qt.ItemDataRole.ToolTipRole)
        self.search_order.setMinimumWidth(188)
        self.search_order.setMinimumHeight(38)
        sort_label.setBuddy(self.search_order)
        self.search_order.currentIndexChanged.connect(self._sort_changed)
        search_controls_layout.addWidget(self.search_order)
        search_controls_layout.addStretch()
        results_layout.addWidget(self.search_controls)
        self.results_stack = QStackedWidget()
        self.track_list = QListWidget()
        self.track_list.setSpacing(3)
        self.track_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.track_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.track_list.itemDoubleClicked.connect(self._double_click)
        self.track_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_list.customContextMenuRequested.connect(self._track_menu)
        self.results_stack.addWidget(self.track_list)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setContentsMargins(24, 40, 24, 40)
        empty_layout.addStretch()
        self.empty_icon = label("")
        self.empty_icon.setPixmap(tile_pixmap("search", 64, "sage"))
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_icon)
        empty_layout.addSpacing(12)
        self.empty_title = label("Что послушаем?", "emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_text = label("Найди любимый трек или исполнителя", "muted")
        self.empty_text.setFixedWidth(360)
        self.empty_text.setMinimumHeight(40)
        self.empty_text.setWordWrap(True)
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.retry = QPushButton("Повторить поиск")
        self.retry.setMinimumHeight(40)
        self.retry.clicked.connect(self.search)
        self.retry.hide()
        empty_layout.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        self.results_stack.addWidget(self.empty)
        results_layout.addWidget(self.results_stack, 1)
        self.search_footer = QWidget()
        footer_layout = QHBoxLayout(self.search_footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)
        self.search_status = label("", "muted")
        self.search_status.setWordWrap(True)
        footer_layout.addWidget(self.search_status, 1)
        self.show_more = QPushButton("Показать ещё")
        self.show_more.setMinimumHeight(40)
        self.show_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_more.clicked.connect(self._load_more)
        footer_layout.addWidget(self.show_more)
        results_layout.addWidget(self.search_footer)
        self.stack.addWidget(self.results_page)
        layout.addWidget(self.stack, 1)
        return panel

    def _home(self):
        page = HomePage(self.artwork)
        page.track_requested.connect(self.playback.play)
        page.track_context_requested.connect(self._track_popup)
        page.view_requested.connect(self.show_view)
        page.playlist_requested.connect(self._show_playlist)
        page.create_requested.connect(self._create_playlist)
        return page

    def _refresh_home(self):
        self.home.refresh(self.library.history(6), self.library.liked_tracks()[:6],
                          self.library.playlists(), self.playback.current, len(self.playback.queue.tracks))

    def _queue_panel(self) -> QFrame:
        self.queue_panel = QFrame()
        self.queue_panel.setObjectName("queuePanel")
        self.queue_panel.setFixedWidth(272)
        layout = QVBoxLayout(self.queue_panel)
        layout.setContentsMargins(16, 24, 14, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label("Очередь", "sectionTitle"), 1)
        self.queue_caption = label("0", "countBadge")
        header.addWidget(self.queue_caption)
        close = icon_button("close", "Скрыть очередь", 32)
        close.clicked.connect(self._hide_queue)
        header.addWidget(close)
        layout.addLayout(header)
        self.queue_now = QFrame()
        self.queue_now.setObjectName("queueNow")
        now_layout = QVBoxLayout(self.queue_now)
        now_layout.setContentsMargins(12, 12, 12, 12)
        now_layout.setSpacing(10)
        now_layout.addWidget(label("СЕЙЧАС В ПЛЕЕРЕ", "eyebrow"))
        now_row = QHBoxLayout()
        now_row.setSpacing(10)
        self.queue_current_cover = Cover(self.artwork, 44)
        now_row.addWidget(self.queue_current_cover)
        now_text = QVBoxLayout()
        now_text.setSpacing(4)
        self.queue_current_title = ElidedLabel("", "trackTitle")
        self.queue_current_artist = ElidedLabel("", "muted")
        now_text.addWidget(self.queue_current_title)
        now_text.addWidget(self.queue_current_artist)
        now_row.addLayout(now_text, 1)
        now_layout.addLayout(now_row)
        layout.addWidget(self.queue_now)
        self.queue_play = QPushButton("Слушать очередь")
        self.queue_play.setObjectName("listenAll")
        self.queue_play.setIcon(icon("play", "#151716"))
        self.queue_play.setToolTip("Запустить добавленные треки с начала")
        self.queue_play.clicked.connect(self.playback.play_queue)
        layout.addWidget(self.queue_play)
        queue_tools = QHBoxLayout()
        queue_tools.setSpacing(8)
        self.queue_shuffle = QPushButton("Вперемешку")
        self.queue_shuffle.setCheckable(True)
        self.queue_shuffle.setIcon(icon("shuffle"))
        self.queue_shuffle.setToolTip("Случайный порядок воспроизведения")
        self.queue_shuffle.clicked.connect(self.playback.toggle_shuffle)
        queue_tools.addWidget(self.queue_shuffle, 1)
        self.queue_save = icon_button("plus", "Сохранить очередь как плейлист", 36)
        self.queue_save.clicked.connect(lambda: self._create_playlist(from_queue=True))
        queue_tools.addWidget(self.queue_save)
        layout.addLayout(queue_tools)
        layout.addWidget(label("СПИСОК ВОСПРОИЗВЕДЕНИЯ", "eyebrow"))
        self.queue_list = QListWidget()
        self.queue_list.setSpacing(3)
        self.queue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.queue_list.itemDoubleClicked.connect(lambda item: self.playback.play(item.data(Qt.ItemDataRole.UserRole)))
        self.queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self._queue_track_menu)
        layout.addWidget(self.queue_list, 1)
        self.queue_empty = label("Добавь треки кнопкой +\nрядом с результатом поиска", "muted")
        self.queue_empty.setWordWrap(True)
        self.queue_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.queue_empty)
        layout.addWidget(label("Порядок сохранится после перезапуска", "tiny"))
        return self.queue_panel

    def _player_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("player")
        bar.setFixedHeight(100)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(20)
        current = QWidget()
        self.current_info = current
        current.setFixedWidth(280)
        current_layout = QHBoxLayout(current)
        current_layout.setContentsMargins(0, 0, 0, 0)
        current_layout.setSpacing(12)
        self.current_cover = ExpandableCover(self.artwork, 56)
        current_layout.addWidget(self.current_cover)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.current_title = ElidedLabel("Выбери первый трек", "trackTitle")
        self.current_artist = ElidedLabel("Музыка начинается с поиска", "muted")
        texts.addWidget(self.current_title)
        texts.addWidget(self.current_artist)
        current_layout.addLayout(texts, 1)
        self.current_like = icon_button("heart", "Нравится текущий трек", 32)
        self.current_like.setEnabled(False)
        self.current_like.clicked.connect(self._like_current)
        current_layout.addWidget(self.current_like)
        layout.addWidget(current)
        controls = QVBoxLayout()
        controls.setSpacing(7)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        self.shuffle_button = icon_button("shuffle", "Воспроизведение по порядку", 36)
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.clicked.connect(self.playback.toggle_shuffle)
        self.playback.shuffle_changed.connect(self._shuffle_changed)
        buttons.addWidget(self.shuffle_button)
        self.previous_button = icon_button("previous", "Предыдущий трек")
        self.previous_button.clicked.connect(self.playback.previous)
        buttons.addWidget(self.previous_button)
        self.play_button = icon_button("play", "Воспроизвести или приостановить", 44)
        self.play_button.setObjectName("playButton")
        self.play_button.setIcon(icon("play", "#151716", 25))
        self.play_button.setIconSize(QSize(25, 25))
        self.play_button.clicked.connect(self.playback.toggle)
        buttons.addWidget(self.play_button)
        self.next_button = icon_button("next", "Следующий трек")
        self.next_button.clicked.connect(self.playback.next)
        buttons.addWidget(self.next_button)
        self.repeat_button = icon_button("repeat", "Повтор выключен", 36)
        self.repeat_button.setCheckable(True)
        self.repeat_button.clicked.connect(self.playback.cycle_repeat)
        self.playback.repeat_changed.connect(self._repeat_changed)
        self._repeat_changed(self.playback.repeat_mode)
        buttons.addWidget(self.repeat_button)
        buttons.addStretch()
        controls.addLayout(buttons)
        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.elapsed = label("0:00", "tiny")
        self.elapsed.setMinimumWidth(33)
        progress.addWidget(self.elapsed)
        self.seek = PointerSlider(Qt.Orientation.Horizontal, formatter=lambda value: time_label(value // 1000))
        self.seek.setAccessibleName("Позиция воспроизведения")
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.committed.connect(self.playback.seek)
        self.seek.sliderMoved.connect(lambda value: self.elapsed.setText(time_label(value // 1000)))
        progress.addWidget(self.seek, 1)
        self.total = label("0:00", "tiny")
        self.total.setMinimumWidth(33)
        progress.addWidget(self.total)
        controls.addLayout(progress)
        layout.addLayout(controls, 1)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.setContentsMargins(0, 0, 0, 0)
        volume = QHBoxLayout()
        self.mute_button = icon_button("volume", "Выключить или включить звук", 28)
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self.playback.output.setMuted)
        volume.addWidget(self.mute_button)
        self.volume = PointerSlider(Qt.Orientation.Horizontal, formatter=lambda value: f"{value}%")
        self.volume.setAccessibleName("Громкость")
        self.volume.setRange(0, 100)
        self.volume.setValue(round(self.playback.output.volume() * 100))
        self.volume.setFixedWidth(92)
        self.volume.valueChanged.connect(self.playback.set_volume)
        volume.addWidget(self.volume)
        self.output_button = QPushButton("Вывод")
        self.output_button.setObjectName("outputButton")
        self.output_button.setIcon(icon("chevron_down", "#B2B8AF", 14))
        self.output_button.setAccessibleName("Выбрать устройство вывода звука")
        self.output_button.clicked.connect(self._choose_audio_output)
        volume.addWidget(self.output_button)
        self.playback.routing.changed.connect(self._audio_output_changed)
        self._audio_output_changed()
        right.addLayout(volume)
        self.player_status = label("Готово к музыке", "playerStatus")
        self.player_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.player_status)
        layout.addLayout(right)
        return bar

    def _build_expanded_player(self):
        self.recommendation_page = RecommendationPage()
        self.stack.addWidget(self.recommendation_page)
        self.recommendation_page.refresh_requested.connect(self._load_recommendations)
        self.recommendation_page.play_requested.connect(self._play_recommendation)
        self.recommendation_page.search_requested.connect(self.search_query)
        self.motion_policy = MotionPolicy(self.library.get_setting("reduced_motion", "0") == "1", self)
        self.page_fade = PageFade(self.stack, self.motion_policy)
        self.motion_policy.changed.connect(lambda reduced: self.library.set_setting("reduced_motion", "1" if reduced else "0"))
        self.lyrics_controller = LyricsController(self.library.path.parent / "lyrics", self)
        self.expanded_player = ExpandedPlayer(self.centralWidget(), policy=self.motion_policy)
        self.expanded_player.lyrics_requested.connect(self._request_lyrics)
        self.expanded_player.import_requested.connect(self._import_lyrics)
        self.lyrics_controller.changed.connect(self.expanded_player.apply_lyrics_payload)
        self.expanded_player.like_requested.connect(self._expanded_like)
        self.expanded_player.output_requested.connect(self._choose_audio_output)
        self.expanded_player.queue_requested.connect(self._expanded_queue)
        self.expanded_player.version_requested.connect(self._current_versions)
        self.expanded_player.set_version_selection_available(True)
        self.expanded_binding = ExpandedPlayerBinding(self.expanded_player, self.playback, artwork=self.artwork)
        self.current_cover.activated.connect(self._open_expanded_player)
        self._refresh_likes()

    def _open_expanded_player(self):
        if not self.playback.current:
            return
        self.expanded_player.open_from(self.current_cover)
        # Loading is lazy: background playback and UI tests do not request lyrics.
        self._lyrics_requested_id = self.playback.current.video_id
        self.lyrics_controller.load(self.playback.current)

    def _request_lyrics(self, recording_id, request_token):
        track = self.playback.current
        if track and track.video_id == recording_id and self.expanded_player.isVisible():
            force = getattr(self, "_lyrics_requested_id", None) == recording_id
            self._lyrics_requested_id = recording_id
            self.lyrics_controller.load(track, force=force)

    def _import_lyrics(self, recording_id):
        track = self.playback.current
        if not track or track.video_id != recording_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть синхронный текст", "", "Синхронный текст (*.lrc)")
        if path and self.playback.current and self.playback.current.video_id == recording_id:
            self.lyrics_controller.import_lrc(track, path)

    def _expanded_like(self, recording_id):
        track = self.playback.current
        if track and track.video_id == recording_id:
            self.toggle_like(track)

    def _expanded_queue(self):
        self.expanded_player.collapse()
        self.queue_panel.show()
        self.queue_toggle.setChecked(True)
        self.queue_list.setFocus()

    def _current_versions(self, recording_id):
        track = self.playback.current
        if track and track.video_id == recording_id:
            self._show_versions(track)

    def _show_versions(self, track):
        for dialog in self._version_dialogs:
            if dialog.track.video_id == track.video_id and not dialog._closed:
                dialog.raise_()
                return
        dialog = RecordingVersionsDialog(track, self.source, self)
        self._version_dialogs.append(dialog)
        dialog.selected.connect(self._choose_recording)
        dialog.finished.connect(lambda result: self._forget_version_dialog(dialog))
        dialog.open()

    def _forget_version_dialog(self, dialog):
        if dialog in self._version_dialogs:
            self._version_dialogs.remove(dialog)
        dialog.deleteLater()

    def _choose_recording(self, original, replacement):
        self.library.prefer_recording(original, replacement)
        self.playback.play(replacement)
        self._notice("Выбрана другая запись: " + replacement.title)

    def _load_recommendations(self):
        if self._recommendation_tasks or self._shutting_down:
            return
        seeds = self.library.liked_tracks()
        if not seeds:
            self.recommendation_page.message("Поставь лайки любимым песням: модель использует их как профиль вкуса")
            return
        self._recommendation_token = uuid.uuid4().hex
        token = self._recommendation_token
        excluded = self.library.history()
        task = Task(token, lambda: self._recommendation_client.recommend(seeds, excluded))
        task.signals.finished.connect(self._recommendations_ready)
        task.signals.failed.connect(self._recommendations_failed)
        self._recommendation_tasks[token] = task
        self.recommendation_page.loading()
        self.pool.start(task)

    def _recommendations_ready(self, token, result):
        self._recommendation_tasks.pop(token, None)
        if self._shutting_down or token != self._recommendation_token:
            return
        self._recommendation_result = result
        self.recommendation_page.set_result(result)

    def _recommendations_failed(self, token, message):
        self._recommendation_tasks.pop(token, None)
        if not self._shutting_down and token == self._recommendation_token:
            self.recommendation_page.message(message)

    def _play_recommendation(self, suggestion):
        if self._recommendation_resolving or self._shutting_down:
            return
        self._recommendation_play_token = uuid.uuid4().hex
        token = self._recommendation_play_token
        self._recommendation_resolving = True
        self.recommendation_page.message("Ищем подходящую запись в YouTube…")
        task = Task(token, lambda: resolve_suggestion(self.source, suggestion))
        task.signals.finished.connect(self._recommendation_recording_ready)
        task.signals.failed.connect(self._recommendation_recording_failed)
        self._recommendation_tasks[token] = task
        self.pool.start(task)

    def _recommendation_recording_ready(self, token, track):
        self._recommendation_tasks.pop(token, None)
        if self._shutting_down or token != self._recommendation_play_token:
            return
        self._recommendation_resolving = False
        self.recommendation_page.message("Запись найдена")
        self.playback.play(track)

    def _recommendation_recording_failed(self, token, message):
        self._recommendation_tasks.pop(token, None)
        if self._shutting_down or token != self._recommendation_play_token:
            return
        self._recommendation_resolving = False
        self.recommendation_page.message(message)

    def _audio_output_changed(self):
        selected = self.playback.routing.selected_id
        name = next((name for key, name in self.playback.routing.choices() if key == selected), "Системный выход")
        self.output_button.setToolTip("Устройство вывода: " + name)

    def _choose_audio_output(self):
        menu = QMenu(self)
        routing = self.playback.routing
        for device_id, name in routing.choices():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(device_id == routing.selected_id)
            action.triggered.connect(lambda checked=False, key=device_id: routing.select(key))
        menu.exec(self.output_button.mapToGlobal(self.output_button.rect().bottomLeft()))

    def _connect(self):
        self.playback.queue_changed.connect(self._refresh_queue)
        self.playback.track_changed.connect(self._on_track)
        self.playback.state_changed.connect(self._on_state)
        self.playback.position_changed.connect(self._position)
        self.playback.duration_changed.connect(self._duration)
        self.playback.player.seekableChanged.connect(lambda value: self.seek.setEnabled(value and self.seek.maximum() > 0))
        self.playback.error.connect(lambda message: self._notice(message, error=True))
        self.playback.history_changed.connect(self._history_changed)

    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _hide_queue(self):
        self.queue_panel.hide()
        self.queue_toggle.setChecked(False)

    def search_query(self, query: str):
        self.search_input.setText(query)
        self.search()

    def search(self):
        query = self.search_input.text().strip()
        if not query:
            self._focus_search()
            return
        order = self.search_order.currentData()
        if self._search_loading and query == self.last_query and order == self._search_order:
            self.show_view("search")
            return
        self._start_search(query, order)

    def _sort_changed(self, index: int):
        self.search_order.setToolTip(self.search_order.itemData(index, Qt.ItemDataRole.ToolTipRole) or "")
        if self.view == "search" and self.last_query:
            self._start_search(self.last_query, self.search_order.currentData())

    def _start_search(self, query: str, order: str, limit: int = 40):
        # Read all widget values before starting the worker. A new token also
        # invalidates older requests when the query or sort changes.
        if limit == 40:
            self.search_results = []
            self._search_limit = 0
            self._search_has_more = False
        self.last_query = query
        self._search_order = order
        self._requested_limit = limit
        self._search_token = uuid.uuid4().hex
        token = self._search_token
        self._search_loading = True
        self._search_error = ""
        self.notice.hide()
        self.view = "search"
        self._select_nav()
        self._render_search(rebuild=not self.search_results)
        task = Task(token, lambda: self.source.search(query, limit=limit, order=order))
        task.signals.finished.connect(self._searched)
        task.signals.failed.connect(self._search_failed)
        self._search_tasks[token] = task
        self.pool.start(task)

    def _load_more(self):
        if self._search_loading or not self._search_has_more or self._search_limit >= 120:
            return
        self._start_search(self.last_query, self._search_order, min(self._search_limit + 40, 120))

    def _searched(self, token: str, tracks: list[Track]):
        self._search_tasks.pop(token, None)
        if token != self._search_token or self._shutting_down:
            return
        self._search_loading = False
        self._search_error = ""
        self._search_limit = self._requested_limit
        # The source returns the first `limit` results, not a new page. Keep its
        # order and suppress duplicates rather than appending the prefix again.
        self.search_results = list({track.video_id: track for track in tracks}.values())
        self._search_has_more = len(self.search_results) >= self._search_limit and self._search_limit < 120
        if self.view == "search":
            self._render_search(preserve_position=self._search_limit > 40)
        if self._search_limit == 40:
            for track in self.search_results[:2]:
                self.playback.prefetch(track)

    def _search_failed(self, token: str, message: str):
        self._search_tasks.pop(token, None)
        if token != self._search_token or self._shutting_down:
            return
        self._search_loading = False
        self._search_error = message
        if self.view == "search":
            self._render_search(rebuild=not self.search_results)

    def _render_search(self, rebuild: bool = True, preserve_position: bool = False):
        subtitle = self.last_query or "Найди трек, исполнителя или нужную версию"
        if self.search_results:
            subtitle += f" · показано: {len(self.search_results)}"
        if rebuild:
            self._show_tracks(self.search_results, "Музыкальные записи" if self.search_results else "Поиск",
                              subtitle, preserve_position=preserve_position)
        else:
            self.stack.setCurrentWidget(self.results_page)
            self.page_subtitle.setText(subtitle)
        if not self.search_results:
            if self._search_loading:
                self._empty_state("Ищем в YouTube…", "Можно изменить запрос или сортировку, не дожидаясь ответа", "search")
            elif self._search_error:
                self._empty_state("Не удалось выполнить поиск", self._search_error, "search", retry=True)
        self._sync_search_controls()

    def _sync_search_controls(self):
        searching = self.view == "search"
        self.playlist_actions.setVisible(self.view == "playlist")
        self.search_controls.setVisible(searching)
        self.search_footer.setVisible(searching and bool(self.search_results))
        self.show_more.setEnabled(not self._search_loading)
        self.show_more.setVisible(self._search_has_more)
        self.show_more.setText("Загружаем…" if self._search_loading else
                               "Повторить загрузку" if self._search_error else "Показать ещё")
        if self._search_loading:
            status = "Ищем ещё записи. Найденные треки можно слушать."
        elif self._search_error:
            status = "Не удалось загрузить ещё. " + self._search_error
        elif len(self.search_results) >= 120:
            status = "Достигнут лимит поиска: 120 записей. Уточни запрос, чтобы найти другие."
        elif not self._search_has_more:
            status = "Больше записей по этому запросу не найдено."
        else:
            status = ""
        self.search_status.setText(status)

    def show_view(self, view: str):
        self.view = view
        self.notice.hide()
        self._select_nav()
        self._sync_search_controls()
        if view == "home":
            self._refresh_home()
            self.stack.setCurrentWidget(self.home)
        elif view == "resonance":
            self.stack.setCurrentWidget(self.recommendation_page)
            if self._recommendation_result is None and not self._recommendation_tasks:
                self._load_recommendations()
        elif view == "playlists":
            self.playlist_page.refresh(self.library.playlists())
            self.stack.setCurrentWidget(self.playlist_page)
        elif view == "likes":
            self._show_tracks(self.library.liked_tracks(), "Мне нравится", "Треки, которые хочется услышать снова")
        elif view == "history":
            self._show_tracks(self.library.history(), "История", "Последние прослушанные записи")
        elif view == "search":
            self._render_search()
            self._focus_search()

    def _select_nav(self):
        for key, button in self.nav.items():
            button.setChecked(key == ("playlists" if self.view == "playlist" else self.view))

    def _show_tracks(self, tracks: list[Track], title: str, subtitle: str, preserve_position: bool = False):
        scroll_position = self.track_list.verticalScrollBar().value() if preserve_position else 0
        selected = self.track_list.currentItem() if preserve_position else None
        selected_id = selected.data(Qt.ItemDataRole.UserRole).video_id if selected else None
        self.stack.setCurrentWidget(self.results_page)
        self.page_title.set_full_text(title)
        self.page_subtitle.setText(subtitle)
        section_glyph, section_tone = {"likes": ("heart_fill", "coral"), "history": ("history", "sage"), "playlist": ("playlist", "sand")}.get(self.view, ("search", "sand"))
        self.section_cover.setPixmap(tile_pixmap(section_glyph, 64, section_tone))
        self.page_kind.setText("ТВОЯ БИБЛИОТЕКА" if self.view in {"likes", "history", "playlist"} else "ПОИСК В YOUTUBE")
        self.visible_tracks = list(tracks)
        self.rows.clear()
        self.track_list.clear()
        self.play_all.setEnabled(bool(tracks))
        if not tracks:
            states = {
                "likes": ("Здесь будут твои любимые треки", "Нажми сердечко рядом с записью — она появится здесь", "heart"),
                "history": ("Пока тихо", "История появится после первого воспроизведения", "history"),
                "playlist": ("Собери свой плейлист", "В поиске нажми правой кнопкой на трек и выбери «В плейлист»", "playlist"),
            }
            self._empty_state(*states.get(self.view, ("Ничего не найдено" if self.last_query else "Что послушаем?",
                                                       "Попробуй другое название или вставь ссылку на YouTube", "search")))
            return
        self.results_stack.setCurrentWidget(self.track_list)
        for track in tracks:
            item = QListWidgetItem(self.track_list)
            item.setData(Qt.ItemDataRole.UserRole, track)
            item.setSizeHint(QSize(0, 72))
            row = TrackRow(track, self.artwork, track.video_id in self.liked)
            row.hovered.connect(self.playback.prefetch)
            row.play_requested.connect(self._play_visible_track)
            row.like_requested.connect(self.toggle_like)
            row.add_requested.connect(self._enqueue)
            row.set_current(bool(self.playback.current and self.playback.current.video_id == track.video_id))
            self.rows.append(row)
            self.track_list.setItemWidget(item, row)
            if track.video_id == selected_id:
                self.track_list.setCurrentItem(item)
        self.track_list.verticalScrollBar().setValue(scroll_position)

    def _empty_state(self, title: str, message: str, glyph: str, retry: bool = False):
        self.empty_title.setText(title)
        self.empty_text.setText(message)
        self.empty_text.setMinimumHeight(max(40, self.empty_text.heightForWidth(360)))
        self.empty_icon.setPixmap(tile_pixmap(glyph, 64, "sage"))
        self.retry.setVisible(retry)
        self.results_stack.setCurrentWidget(self.empty)

    def _enqueue(self, track: Track):
        self.playback.add(track)
        self._notice("Добавлено в очередь: " + track.title)

    def _play_visible_track(self, track):
        if self.view == "playlist":
            self.playback.play_from(self.visible_tracks, track)
        else:
            self.playback.play(track)

    def _double_click(self, item):
        self._play_visible_track(item.data(Qt.ItemDataRole.UserRole))

    def _track_menu(self, position):
        item = self.track_list.itemAt(position)
        if item is not None:
            menu = self._make_track_menu(item.data(Qt.ItemDataRole.UserRole),
                                         self._playlist_id if self.view == "playlist" else None)
            menu.exec(self.track_list.viewport().mapToGlobal(position))
            menu.deleteLater()

    def _queue_track_menu(self, position):
        item = self.queue_list.itemAt(position)
        if item is not None:
            self._track_popup(item.data(Qt.ItemDataRole.UserRole), self.queue_list.viewport().mapToGlobal(position))

    def _track_popup(self, track, position):
        menu = self._make_track_menu(track)
        menu.exec(position)
        menu.deleteLater()

    def _make_track_menu(self, track, playlist_context=None):
        menu = QMenu(self)
        menu.addAction("Слушать", lambda: self.playback.play_from(self.library.playlist_tracks(playlist_context), track)
                       if playlist_context is not None else self.playback.play(track))
        menu.addAction("В очередь", lambda: self._enqueue(track))
        menu.addAction("Убрать лайк" if track.video_id in self.liked else "Мне нравится", lambda: self.toggle_like(track))
        playlists = menu.addMenu("В плейлист")
        menu._playlists_menu = playlists
        for collection in self.library.playlists():
            playlists.addAction(collection["name"], lambda checked=False, key=collection["id"]: self._add_to_playlist(key, track))
        playlists.addSeparator()
        playlists.addAction("Новый плейлист…", lambda: self._create_playlist(track=track))
        if playlist_context is not None:
            menu.addSeparator()
            records = self.library.playlist_tracks(playlist_context)
            index = next((i for i, record in enumerate(records) if record.video_id == track.video_id), -1)
            up = menu.addAction("Выше в плейлисте", lambda: self._move_playlist_track(playlist_context, track, -1))
            up.setEnabled(index > 0)
            down = menu.addAction("Ниже в плейлисте", lambda: self._move_playlist_track(playlist_context, track, 1))
            down.setEnabled(0 <= index < len(records) - 1)
            menu.addAction("Убрать из плейлиста", lambda: self._remove_from_playlist(playlist_context, track))
        menu.addSeparator()
        menu.addAction("Другие записи…", lambda: self._show_versions(track))
        menu.addAction("Открыть на YouTube", lambda: QDesktopServices.openUrl(QUrl(track.url)))
        return menu

    def _show_playlist(self, playlist_id, preserve_position=False):
        collection = next((item for item in self.library.playlists() if item["id"] == playlist_id), None)
        if collection is None:
            return
        self._playlist_id = playlist_id
        self.view = "playlist"
        self.notice.hide()
        self._select_nav()
        self._sync_search_controls()
        self._show_tracks(self.library.playlist_tracks(playlist_id), collection["name"],
                          f"Треков: {collection['track_count']}", preserve_position=preserve_position)

    def _create_playlist(self, track=None, from_queue=False):
        name, accepted = QInputDialog.getText(self, "Новый плейлист", "Название")
        if not accepted:
            return
        try:
            playlist_id = self.library.create_playlist(name)
        except ValueError:
            self._notice("Введи название от 1 до 100 символов.", error=True)
            return
        records = list(self.playback.queue.tracks) if from_queue else [track] if track is not None else []
        for record in records:
            self.library.add_to_playlist(playlist_id, record)
        self._refresh_home()
        self._show_playlist(playlist_id)

    def _add_to_playlist(self, playlist_id, track):
        self.library.add_to_playlist(playlist_id, track)
        self._refresh_home()
        if self.view == "playlist" and self._playlist_id == playlist_id:
            self._show_playlist(playlist_id, preserve_position=True)
        self._notice("Сохранено в плейлист: " + track.title)

    def _remove_from_playlist(self, playlist_id, track):
        self.library.remove_from_playlist(playlist_id, track.video_id)
        self._refresh_home()
        self._show_playlist(playlist_id, preserve_position=True)

    def _move_playlist_track(self, playlist_id, track, offset):
        self.library.move_playlist_track(playlist_id, track.video_id, offset)
        self._show_playlist(playlist_id, preserve_position=True)

    def _playlist_menu(self, playlist_id, position):
        if playlist_id is None:
            return
        menu = QMenu(self)
        menu.addAction("Слушать всё", lambda: self.playback.play_all(self.library.playlist_tracks(playlist_id)))
        menu.addAction("Переименовать…", lambda: self._rename_playlist(playlist_id))
        menu.addSeparator()
        menu.addAction("Удалить плейлист…", lambda: self._delete_playlist(playlist_id))
        menu.exec(position)

    def _rename_playlist(self, playlist_id):
        collection = next((item for item in self.library.playlists() if item["id"] == playlist_id), None)
        if collection is None:
            return
        name, accepted = QInputDialog.getText(self, "Переименовать плейлист", "Название", text=collection["name"])
        if not accepted:
            return
        try:
            self.library.rename_playlist(playlist_id, name)
        except ValueError:
            self._notice("Введи название от 1 до 100 символов.", error=True)
            return
        self._refresh_home()
        if self.view == "playlist":
            self._show_playlist(playlist_id, preserve_position=True)
        elif self.view == "playlists":
            self.playlist_page.refresh(self.library.playlists())

    def _delete_playlist(self, playlist_id):
        collection = next((item for item in self.library.playlists() if item["id"] == playlist_id), None)
        if collection is None:
            return
        if QMessageBox.question(self, "Удалить плейлист?", "Удалить «" + collection["name"] + "»? Треки и лайки сохранятся.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.library.delete_playlist(playlist_id)
        self._playlist_id = None
        self._refresh_home()
        self.show_view("playlists")

    def toggle_like(self, track: Track):
        self.library.like(track, track.video_id not in self.liked)
        self._refresh_likes()
        if self.view == "likes":
            self.show_view("likes")

    def _like_current(self):
        if self.playback.current:
            self.toggle_like(self.playback.current)

    def _refresh_likes(self):
        self.liked = self.library.liked_ids()
        self.likes_count.setText(f"Сохранено треков: {len(self.liked)}" if self.liked else "Пока без лайков")
        self._refresh_home()
        for row in self.rows:
            row.set_liked(row.track.video_id in self.liked)
        liked = self.playback.current is not None and self.playback.current.video_id in self.liked
        self.current_like.setIcon(icon("heart_fill" if liked else "heart", "#FF875F" if liked else "#B2B8AF"))
        if hasattr(self, "expanded_player"):
            self.expanded_player.set_liked(liked)

    def _repeat_changed(self, mode):
        titles = {"off": "Повтор выключен", "one": "Повтор одного трека", "all": "Повтор всей очереди"}
        self.repeat_button.setChecked(mode != "off")
        self.repeat_button.setIcon(icon("repeat_one" if mode == "one" else "repeat",
                                        "#FF875F" if mode != "off" else "#B2B8AF"))
        self.repeat_button.setToolTip(titles[mode] + ". Нажми, чтобы переключить режим")
        self.repeat_button.setAccessibleName(titles[mode])
        self.next_button.setEnabled(self.playback.can_next)

    def _shuffle_changed(self, enabled):
        for button in (self.shuffle_button, self.queue_shuffle):
            button.setChecked(enabled)
            button.setIcon(icon("shuffle", "#FF875F" if enabled else "#B2B8AF"))
            button.setToolTip("Перемешивание включено" if enabled else "Слушать в случайном порядке")
        self._refresh_queue()

    def _refresh_queue(self):
        scroll_position = self.queue_list.verticalScrollBar().value()
        selected = self.queue_list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole).video_id if selected else None
        self.queue_list.clear()
        queue = self.playback.queue
        self.queue_caption.setText(str(len(queue.tracks)))
        self.queue_play.setEnabled(bool(queue.tracks))
        self.queue_save.setEnabled(bool(queue.tracks))
        self.queue_shuffle.setEnabled(bool(queue.tracks))
        self.queue_empty.setVisible(not queue.tracks)
        self.queue_list.setVisible(bool(queue.tracks))
        for index, track in enumerate(queue.tracks):
            item = QListWidgetItem(self.queue_list)
            item.setData(Qt.ItemDataRole.UserRole, track)
            item.setSizeHint(QSize(0, 62))
            row = QueueRow(track, index, index == queue.index, artwork=self.artwork)
            row.play_requested.connect(self.playback.play)
            row.remove_requested.connect(self.playback.remove)
            self.queue_list.setItemWidget(item, row)
            if track.video_id == selected_id:
                self.queue_list.setCurrentItem(item)
        self.queue_list.doItemsLayout()
        self.queue_list.verticalScrollBar().setValue(scroll_position)
        self.play_button.setEnabled(bool(queue.tracks) or self.playback.current is not None)
        self.previous_button.setEnabled(queue.index > 0 or self.playback.current is not None)
        self.next_button.setEnabled(self.playback.can_next)
        self._refresh_home()

    def _on_track(self, track: Track | None):
        self.notice.hide()
        self.current_title.set_full_text(track.title if track else "Выбери первый трек")
        self.current_artist.set_full_text(track.artist if track else "Музыка начинается с поиска")
        self.current_cover.seed = track.video_id if track else ""
        self.current_cover.set_url(track.thumbnail if track else "")
        self.queue_now.setVisible(track is not None)
        self.queue_current_cover.seed = track.video_id if track else ""
        self.queue_current_cover.set_url(track.thumbnail if track else "")
        self.queue_current_title.set_full_text(track.title if track else "")
        self.queue_current_artist.set_full_text(track.artist if track else "")
        self.current_like.setEnabled(track is not None)
        self.setWindowTitle(f"{track.title} — {APP_NAME}" if track else APP_NAME)
        self.seek.setValue(0)
        self.elapsed.setText("0:00")
        self.total.setText(time_label(track.duration) if track else "0:00")
        self._refresh_likes()
        for row in self.rows:
            row.set_current(bool(track and row.track.video_id == track.video_id))

    def _on_state(self, state: str):
        playing = state in {"playing", "loading"} and self.playback._want_play
        self.play_button.setIcon(icon("pause" if playing else "play", "#151716", 25))
        titles = {"loading": "Подключаем поток…", "playing": "Сейчас играет", "paused": "Пауза",
                  "stopped": "Готово к музыке", "error": "Запись недоступна"}
        self.player_status.setText(titles.get(state, ""))
        if state == "error":
            self.seek.setEnabled(False)

    def _position(self, value: int):
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
            self.elapsed.setText(time_label(value // 1000))

    def _duration(self, value: int):
        self.seek.setRange(0, min(value, 2147483647))
        self.seek.setEnabled(value > 0 and self.playback.player.isSeekable())
        self.total.setText(time_label(value // 1000))

    def _history_changed(self):
        self._refresh_home()
        if self.view == "history":
            self._show_tracks(self.library.history(), "История", "Последние прослушанные записи",
                              preserve_position=True)

    def _notice(self, text: str, error: bool = False):
        self.notice.setText(text)
        self.notice.setProperty("error", error)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sidebar_panel"):
            compact = self.width() < 1120
            self.sidebar_panel.setFixedWidth(168 if compact else 192)
            self.queue_panel.setFixedWidth(244 if compact else 272)
            self.current_info.setFixedWidth(240 if compact else 280)
        if hasattr(self, "expanded_player"):
            self.expanded_player.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event):
        self._shutting_down = True
        self._search_token = uuid.uuid4().hex
        self.pool.clear()
        for dialog in list(self._version_dialogs):
            dialog.close()
        self.page_fade.detach()
        self.lyrics_controller.shutdown()
        self.expanded_binding.disconnect()
        self.playback.shutdown()
        self.pool.waitForDone(100)
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not isinstance(self.focusWidget(), (QLineEdit, QComboBox, QPushButton)):
            self.playback.toggle()
            event.accept()
        else:
            super().keyPressEvent(event)

