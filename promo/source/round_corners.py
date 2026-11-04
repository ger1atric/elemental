"""Rounded copies of every poster in ../ with white corners, into ../Rounded/.
Run with Anki's venv python (needs PyQt6)."""
import os
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath, QColor
from PyQt6.QtCore import QRectF
app = QGuiApplication([])
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(SRC, "Rounded"); os.makedirs(OUT, exist_ok=True)
for f in sorted(os.listdir(SRC)):
    if not f.endswith(".png"):
        continue
    im = QImage(os.path.join(SRC, f)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    w, h = im.width(), im.height()
    r = 72 if f.startswith(("15-banner", "16-banner")) else max(32, round(0.045 * min(w, h)))
    out = QImage(w, h, QImage.Format.Format_RGB32); out.fill(QColor("#ffffff"))
    p = QPainter(out); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, w, h), r, r); p.setClipPath(path)
    p.drawImage(0, 0, im); p.end()
    out.save(os.path.join(OUT, f))

# AnkiWeb strips alignment, so the description's screenshots are centered by padding:
# each Rounded poster on a white canvas 1/0.8 as wide, shown at width 100% (looks 80%, centered).
AW = os.path.join(SRC, "AnkiWeb"); os.makedirs(AW, exist_ok=True)
for n in ["01-at-a-glance", "04-review-pill", "09-day-details", "03-time-left", "02-six-views", "05-themes", "06-card-browser", "07-settings"]:
    im = QImage(os.path.join(OUT, n + ".png")); W = round(im.width() / 0.8)
    pad = QImage(W, im.height(), QImage.Format.Format_RGB32); pad.fill(QColor("#ffffff"))
    p = QPainter(pad); p.drawImage((W - im.width()) // 2, 0, im); p.end(); pad.save(os.path.join(AW, n + ".png"))
