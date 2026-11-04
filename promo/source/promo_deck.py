"""Render Anki's real deck screen (its template + CSS + the add-on's render hook) to PNG at 2x."""
import sys, os, types, json
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = os.environ.get("SCALE", "2")
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication as _QA; _app = _QA(sys.argv)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load, S
mod, mw, col = load(os.path.join(S, os.environ.get("COL", "col") + "/collection.anki2"))
NIGHT = os.environ.get("NIGHT", "1") == "1"
mod._is_dark_mode = lambda: NIGHT
cfg = mw.addonManager.cfg
cfg.update(json.loads(os.environ.get("CFG", "{}")))
from aqt.qt import QUrl, QTimer, QEventLoop, QColor
# Poster-only demo numbers for today (FAKE_TODAY='{"revs":..,"rate":..,"speed":..,"mins":..}')
_fake = json.loads(os.environ.get("FAKE_TODAY", "{}"))
if _fake:
    _orig_get = mod.FastEngine.get_data
    def _get(self, *a, **k):
        out = list(_orig_get(self, *a, **k))
        out[6], out[7], out[8], out[9] = _fake["revs"], _fake["rate"], _fake["speed"], _fake["mins"]
        if isinstance(out[0], dict) and out[15] in out[0]:
            out[0][out[15]] = _fake["revs"]
        return tuple(out)
    mod.FastEngine.get_data = _get
if os.environ.get("FIT", "1") == "1":
    TL = sys.modules["heatmap_mod.time_left"]; EST = sys.modules["heatmap_mod.estimator"]
    TL._model = EST.fit(col.path, int(col.sched.day_cutoff), os.path.join(S, os.environ.get("COL", "col"), "focus_log.sqlite"), False, False)
    TL.focus_log.today_index = lambda: {}
from aqt.deckbrowser import DeckBrowser, DeckBrowserContent, RenderData
tree = col.sched.deck_due_tree()
data = RenderData(tree=tree, current_deck_id=col.decks.get_current_id(), studied_today="", sched_upgrade_required=False)
db = types.SimpleNamespace(_render_data=data, mw=mw)
db._topLevelDragRow = lambda: DeckBrowser._topLevelDragRow(db)
db._render_deck_node = lambda n, ctx: DeckBrowser._render_deck_node(db, n, ctx)
content = DeckBrowserContent(tree=DeckBrowser._renderDeckTree(db, tree), stats="")
mod.render(db, content)
W = "/Users/jerryshen/Library/Application Support/AnkiProgramFiles/.venv/lib/python3.13/site-packages/_aqt/data/web/"
css = open(W + "css/webview.css").read() + open(W + "css/deckbrowser.css").read()
js = open(W + "js/vendor/jquery.min.js").read() + "\n" + open(W + "js/vendor/jquery-ui.min.js").read()
bgcss = ""
photo = os.environ.get("PHOTO")
if photo:
    BG = sys.modules["heatmap_mod.background"]
    BG.url = lambda rel: QUrl.fromLocalFile(photo).toString()
    bgcss = "<style>" + BG._css("x", float(os.environ.get("PHOTO_OPACITY", "0.6"))) + "</style>"
body = DeckBrowser._body % dict(tree=content.tree, stats=content.stats)
html = f"""<!doctype html><html class="{'night-mode' if NIGHT else ''}" data-bs-theme="{'dark' if NIGHT else 'light'}"><head>
<style>{css}</style>{bgcss}<style>::-webkit-scrollbar{{display:none}}</style><script>function pycmd(){{return false}}; var bridgeCommand = pycmd;</script></head>
<body class="isMac {'nightMode night_mode' if NIGHT else ''}"><script>{js}</script>{body}</body></html>"""
open(os.path.join(S, "promo", "deck_page.html"), "w").write(html)
v = QWebEngineView(); v.resize(int(os.environ.get("W", "1100")), int(os.environ.get("H", "760")))
v.page().setBackgroundColor(QColor("#2c2c2c" if NIGHT else "#f5f5f5"))
v.load(QUrl.fromLocalFile(os.path.join(S, "promo", "deck_page.html"))); v.show()
def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
wait(3500)
for mode in (os.environ.get("MODES") or "").split(",") or [""]:
    if mode:
        v.page().runJavaScript(f"window.hmSetMode && window.hmSetMode('{mode}')"); wait(700)
    name = os.environ.get("OUT", "deck") + (f"_{mode}" if mode else "") + ".png"
    img = v.grab(); img.save(os.path.join(S, "promo", name)); print("saved", name, img.width(), img.height())
