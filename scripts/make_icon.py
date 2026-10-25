"""Generate the app's vector-derived Windows icon without external assets."""
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

root = Path(__file__).resolve().parent.parent
assets = root / "assets"
assets.mkdir(exist_ok=True)
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#1D201F"))
painter.drawRoundedRect(QRectF(0, 0, 256, 256), 52, 52)
painter.setBrush(QColor("#FF875F"))
for index, height in enumerate([52, 102, 160, 102, 52]):
    painter.drawRoundedRect(QRectF(43 + index * 36, (256 - height) / 2, 22, height), 11, 11)
painter.end()
if not image.save(str(assets / "riffuna.ico"), "ICO"):
    raise RuntimeError("Qt could not write the Windows icon")
image.save(str(assets / "riffuna.png"))
print("Generated assets/riffuna.ico")

