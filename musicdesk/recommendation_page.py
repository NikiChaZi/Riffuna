from __future__ import annotations
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QFrame,QHBoxLayout,QVBoxLayout,QPushButton,QScrollArea,QWidget
from .widgets import label
from .icons import icon

class RecommendationPage(QWidget):
    refresh_requested=Signal()
    play_requested=Signal(object)
    search_requested=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        root.addWidget(label("ПОДБОР ПО ТВОИМ ЛАЙКАМ","eyebrow"))
        head=QHBoxLayout();head.addWidget(label("Резонанс","pageTitle"),1)
        self.refresh=QPushButton("Обновить");self.refresh.clicked.connect(self.refresh_requested);head.addWidget(self.refresh);root.addLayout(head)
        self.caption=label("Двухэтапная музыкальная модель: поиск кандидатов и ранжирование","muted");self.caption.setWordWrap(True);root.addWidget(self.caption)
        self.status=label("Поставь лайки любимым песням, чтобы получить подборку","muted");self.status.setWordWrap(True);root.addWidget(self.status)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body=QWidget();self.items=QVBoxLayout(self.body);self.items.setContentsMargins(0,10,0,0);self.items.addStretch();scroll.setWidget(self.body);root.addWidget(scroll,1)
        self.rows=[]
    def loading(self):
        self.refresh.setEnabled(False);self.status.setText("Подбираем треки по музыкальной модели…")
    def message(self,text):
        self.refresh.setEnabled(True);self.status.setText(text)
    def set_result(self,result):
        for row in self.rows:self.items.removeWidget(row);row.deleteLater()
        self.rows=[];self.refresh.setEnabled(True)
        coverage=result.get("coverage",{});matched=coverage.get("track",0);artists=coverage.get("artist",0);missing=coverage.get("missing",0);genres=coverage.get("genre",0)
        if not result["items"]:
            self.status.setText("В обучающем каталоге пока нет подходящих исполнителей из твоих лайков. Каталог нужно расширить.");return
        self.status.setText(f"По трекам: {matched} · по исполнителю: {artists} · по жанрам: {genres} · без данных: {missing}")
        for candidate in result["items"]:
            row=QFrame();layout=QHBoxLayout(row);layout.setContentsMargins(0,8,0,8)
            play=QPushButton();play.setIcon(icon("play"));play.setAccessibleName("Слушать "+candidate.title);play.setToolTip("Найти подходящую запись и слушать")
            play.clicked.connect(lambda checked=False,s=candidate:self.play_requested.emit(s));layout.addWidget(play)
            info=QVBoxLayout();title=label(candidate.title,"trackTitle");title.setWordWrap(True);info.addWidget(title)
            artist=label(candidate.artist,"muted");artist.setWordWrap(True);info.addWidget(artist)
            if candidate.genres:genres=label(" · ".join(candidate.genres[:4]),"tiny");genres.setWordWrap(True);info.addWidget(genres)
            layout.addLayout(info,1);search=QPushButton("Поиск");search.clicked.connect(lambda checked=False,s=candidate:self.search_requested.emit(s.artist+" "+s.title));layout.addWidget(search)
            self.items.insertWidget(self.items.count()-1,row);self.rows.append(row)
