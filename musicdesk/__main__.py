from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtNetwork import QNetworkProxyFactory
from PySide6.QtWidgets import QApplication, QMessageBox

from .branding import APP_NAME
from .appearance import configure_app, prepare_windows_identity, write_startup_report
from .storage import Library, data_directory
from .window import MainWindow


def main():
    prepare_windows_identity()
    app = QApplication(sys.argv)
    configure_app(app)
    QNetworkProxyFactory.setUseSystemConfiguration(True)
    data = data_directory()
    data.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "application.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if "--diagnose" in sys.argv:
        from .diagnostics import run
        return run(app, data)
    logging.info("Starting local Riffuna build; continuous PCM output; source=%s", __file__)
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
        ui_report = os.environ.get("MUSICDESK_UI_REPORT")
        if ui_report:
            QTimer.singleShot(150, lambda: write_startup_report(app, window, Path(ui_report)))
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

