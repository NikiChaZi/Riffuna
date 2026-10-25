"""Render the original SVG mark into a multi-resolution Windows ICO and PNG."""
from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256)


def generate():
    assets = ROOT / "assets"
    renderer = QSvgRenderer(str(assets / "riffuna.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid Riffuna SVG")
    frames = []
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not encode icon")
        frames.append((size, bytes(buffer.data())))
        if size == 256:
            image.save(str(assets / "riffuna.png"))
    # PNG-compressed ICO frames preserve alpha and are supported on Windows 10+.
    offset = 6 + 16 * len(frames)
    entries = []
    for size, payload in frames:
        dimension = size if size < 256 else 0
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset))
        offset += len(payload)
    (assets / "riffuna.ico").write_bytes(struct.pack("<HHH", 0, 1, len(frames)) +
                                       b"".join(entries) + b"".join(payload for _, payload in frames))
    print("Generated Riffuna icon:", ", ".join(map(str, SIZES)))


if __name__ == "__main__":
    generate()
