"""The Card Browser preview from Settings, with the user's own browser settings."""
import sys, os
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"; os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); os.environ["QT_SCALE_FACTOR"] = "4"
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication as _QA; _app = _QA(sys.argv)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load, S
mod, mw, col = load(os.path.join(S, "promo_col/collection.anki2"))
mod._is_dark_mode = lambda: True
from aqt.qt import QPalette, QColor, QEventLoop, QTimer
_app.setStyle("Fusion"); pal = QPalette()
for role, c in ((QPalette.ColorRole.Window, "#2c2c2c"), (QPalette.ColorRole.WindowText, "#e8e8e8"), (QPalette.ColorRole.Base, "#1e1e1e"),
                (QPalette.ColorRole.Text, "#e8e8e8"), (QPalette.ColorRole.Button, "#3a3a3a"), (QPalette.ColorRole.ButtonText, "#e8e8e8"),
                (QPalette.ColorRole.Highlight, "#0a84ff")):
    pal.setColor(role, QColor(c))
_app.setPalette(pal)
def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
d = mod.HeatmapSettingsDialog(None); d.resize(940, 680); d.show()
d.nav.setCurrentItem([it for it, *_ in d._pages if it.text() == "Card Browser"][0]); wait(600)
print("theme", d.browser_theme_combo.currentData(), "| custom", d.chk_custom_colors.isChecked(), "| icons", d.chk_state_icons.isChecked(),
      "| spacing", d.browser_spacing_combo.currentData(), flush=True)
img = d.browser_preview.grab(); img.save(os.path.join(S, "promo", "browser_mine.png")); print("saved", img.width(), img.height(), flush=True)
os._exit(0)
