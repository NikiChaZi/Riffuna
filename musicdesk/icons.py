from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "arrow_up_right": '<path d="M6 18 18 6M6 6h12v12"/>',
    "arrow_right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "collection": '<rect x="4" y="7" width="16" height="14" rx="2"/><path d="M7 3h10m-6 9 5 3-5 3Z"/>',
    "filter": '<path d="M4 6h16M7 12h10m-7 6h4"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',

    "back": '<path d="m15 5-7 7 7 7"/>',
    "forward": '<path d="m9 5 7 7-7 7"/>',
    "shuffle": '<path d="M3 6h3l12 12h3M17 14l4 4-4 4M3 18h3l4-4m4-4 4-4h3m-4-4 4 4-4 4"/>',
    "playlist": '<path d="M4 5h16M4 10h16M4 15h8m5-1v7m-3-3h6"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "play": '<path d="m9 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="4"/>',
    "next": '<path d="m5 5 10 7-10 7Z" fill="currentColor" stroke="none"/><path d="M19 5v14"/>',
    "previous": '<path d="m19 5-10 7 10 7Z" fill="currentColor" stroke="none"/><path d="M5 5v14"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "heart": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    "heart_fill": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" fill="currentColor"/>',
    "queue": '<path d="M4 6h16M4 12h12M4 18h8m6-3 4 3-4 3Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "history": '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7m2-4v5l3 2"/>',
    "home": '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3Z"/>',
    "volume": '<path d="M4 9h4l5-4v14l-5-4H4Zm13-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
    "repeat": '<path d="m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3"/>',
    "repeat_one": '<path d="m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3m7-9 2-1v6m-2 0h4"/>',
    "external": '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    "note": '<path d="M9 18V5l12-2v13M9 8l12-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="18" cy="16" rx="3" ry="2"/>',
    "wave": '<path d="M3 10v4m4-8v12m5-16v20m5-16v12m4-8v4" stroke-width="2.5"/>',
}


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#B2B8AF", size: int = 24) -> QIcon:
    paths = PATHS[name].replace("currentColor", color)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)

