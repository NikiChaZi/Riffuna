from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtNetwork import QNetworkProxyFactory
from PySide6.QtWidgets import QApplication, QMessageBox

from .branding import APP_NAME
from .storage import Library, data_directory
from .style import STYLE
from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#151716"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#F1F0E8"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1D201F"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#F1F0E8"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#252925"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#F1F0E8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#6B4534"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#F1F0E8"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    QNetworkProxyFactory.setUseSystemConfiguration(True)
    data = data_directory()
    data.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "application.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if "--diagnose" in sys.argv:
        from .diagnostics import run
        return run(app, data)
    lock = QLockFile(str(data / "instance.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, APP_NAME, APP_NAME + " уже запущен. Найди окно на панели задач.")
        return 0
    try:
        library = Library()
        window = MainWindow(library)
        window.show()
        screen = app.primaryScreen().availableGeometry()
        window.resize(min(1280, screen.width() - 40), min(800, screen.height() - 50))
        window.move(screen.center() - window.rect().center())
        autoclose = os.environ.get("MUSICDESK_AUTOCLOSE_MS")
        if autoclose:
            QTimer.singleShot(int(autoclose), window.close)
        result = app.exec()
        library.close()
        return result
    except Exception:
        logging.exception("Application failed")
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.critical(None, APP_NAME, "Не удалось запустить приложение. Подробности сохранены в " + str(data / "application.log"))
        return 1
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())

