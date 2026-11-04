"""Headless harness: load the heatmap add-on against a collection copy with a fake mw."""
import os, sys, json, types, importlib.util
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aqt.qt import QApplication
app = QApplication.instance() or QApplication([])
import aqt
from anki.collection import Collection
import anki.lang
anki.lang.set_lang("en_US")      # Anki's own modules translate strings at import time

ADDON = os.path.expanduser("~/Library/Application Support/Anki2/addons21/Interactive Heatmap")
S = os.path.dirname(os.path.abspath(__file__))
META = json.load(open(os.path.join(ADDON, "meta.json")))

class AM:
    def __init__(self): self.cfg = json.loads(json.dumps(META.get("config", {})))
    def getConfig(self, name): return json.loads(json.dumps(self.cfg))
    def writeConfig(self, name, c): self.cfg = json.loads(json.dumps(c))
    def setConfigAction(self, *a): pass
    def setWebExports(self, *a): pass
    def addonFromModule(self, m): return "Interactive Heatmap"

class Dummy:
    def __getattr__(self, k): return Dummy()
    def __call__(self, *a, **k): return Dummy()

class FakeMW:
    def __init__(self, col):
        self.col = col; self.addonManager = AM(); self.state = "deckBrowser"
        self.form = Dummy(); self.progress = Dummy(); self.taskman = Dummy()
        self.pm = Dummy()
    def reset(self): pass

def load(colpath):
    col = Collection(colpath)
    mw = FakeMW(col)
    aqt.mw = mw
    sys.path.insert(0, os.path.dirname(ADDON))
    spec = importlib.util.spec_from_file_location("heatmap_mod", os.path.join(ADDON, "__init__.py"),
                                                  submodule_search_locations=[ADDON])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["heatmap_mod"] = mod
    spec.loader.exec_module(mod)
    mod.mw = mw
    return mod, mw, col
