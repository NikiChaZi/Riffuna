"""Shared application identity and appearance for source and frozen startups."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys

from PySide6.QtGui import QColor, QFont, QIcon, QPalette

from .branding import APP_NAME
from .style import STYLE

APP_ID = "Riffuna.Desktop"


def asset_path(name: str) -> Path:
    # PyInstaller keeps this module and bundled assets under the same base.
    return Path(__file__).resolve().parents[1] / "assets" / name


def app_icon() -> QIcon:
    return QIcon(str(asset_path("riffuna.ico")))


def prepare_windows_identity():
    if sys.platform == "win32":
        function = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        if function(APP_ID) != 0:
            raise OSError("Could not set Riffuna's Windows application identity")


def configure_app(app):
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#111615", QPalette.ColorRole.WindowText: "#F4F1E8",
        QPalette.ColorRole.Base: "#1B211F", QPalette.ColorRole.Text: "#F4F1E8",
        QPalette.ColorRole.Button: "#272F2B", QPalette.ColorRole.ButtonText: "#F4F1E8",
        QPalette.ColorRole.Highlight: "#624638", QPalette.ColorRole.HighlightedText: "#F4F1E8",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


def write_startup_report(app, window, path: Path):
    """Opt-in local UI smoke evidence; never includes library or track data."""
    report = {
        "frozen": bool(getattr(sys, "frozen", False)), "platform": app.platformName(),
        "icon_asset_exists": asset_path("riffuna.ico").is_file(),
        "application_icon": not app.windowIcon().isNull(), "window_icon": not window.windowIcon().isNull(),
        "icon_sizes": sorted(size.width() for size in window.windowIcon().availableSizes()),
        "audio_output": "continuous-pcm" if hasattr(window.playback.seek_guard, "pcm") else "qt-native",
    }
    if sys.platform == "win32":
        app_id = ctypes.c_void_p()
        get_id = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
        get_id.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        get_id.restype = ctypes.c_long
        if get_id(ctypes.byref(app_id)) == 0:
            report["windows_app_id"] = ctypes.wstring_at(app_id)
            free = ctypes.windll.ole32.CoTaskMemFree
            free.argtypes = [ctypes.c_void_p]
            free(app_id)
        if app.platformName() == "windows":
            send = ctypes.windll.user32.SendMessageW
            send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
            send.restype = ctypes.c_ssize_t
            handle = int(window.winId())
            report["native_small_icon"] = bool(send(handle, 0x007F, 0, 0))
            report["native_big_icon"] = bool(send(handle, 0x007F, 1, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
