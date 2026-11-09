"""
Work saved between restarts, in user_files/ (startup_<profile>_*), so starting Anki again
doesn't redo seconds of background work:

  history   the heatmap's per-day totals before today; on a new day only the days since
            are added to it
  forecast  the FSRS forecast: shown at startup, then refreshed in the background
  model     Time Left's model, fitted once per Anki day

Each entry is keyed by what it was worked out from (the collection, the settings it
depends on, a fingerprint of the review log) and the add-on's version; anything that
doesn't match is ignored and worked out again. Files are written whole and closed at
once: Windows can't move user_files (Anki does on every update) while a file in it is
open.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import threading
import time
import zlib

_dir = os.path.join(os.path.dirname(__file__), "user_files")
_lock = threading.Lock()
_version = ""
_mem = {}           # kind -> the loaded JSON store, for the open profile

HISTORY_KEEP = 8    # deck scopes × settings kept (main heatmap, overview decks, retention scope…)
FORECAST_KEEP = 6


def setup(version: str) -> None:
    global _version
    _version = str(version)


def reset() -> None:
    """The profile closed: forget what was loaded."""
    with _lock:
        _mem.clear()


def _file(kind: str, ext: str) -> str | None:
    try:
        from aqt import mw
        name = re.sub(r"[^\w-]", "_", mw.pm.name or "profile")
    except Exception:
        return None
    return os.path.join(_dir, f"startup_{name}_{kind}.{ext}")


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _store(kind: str, col_path: str) -> dict:
    """The JSON store for this kind (loaded once), emptied if it's for another
    collection or add-on version. Call with _lock held."""
    st = _mem.get(kind)
    if st is None:
        st = {}
        path = _file(kind, "json")
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    st = json.load(f)
            except Exception:
                st = {}
        _mem[kind] = st
    if st.get("version") != _version or st.get("col") != col_path:
        st.clear()
        st.update(version=_version, col=col_path, entries=[])
    return st


def _save(kind: str) -> None:
    path = _file(kind, "json")
    st = _mem.get(kind)
    if not path or st is None:
        return
    try:
        _write(path, json.dumps(st, separators=(",", ":")).encode("utf-8"))
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# History: per-day totals before a boundary (the start of "today" when saved)
# ──────────────────────────────────────────────────────────────
def history_exact(col_path: str, base: list, bound: int, fp) -> list | None:
    """Rows saved for exactly this boundary and fingerprint, else None."""
    with _lock:
        for e in _store("history", col_path)["entries"]:
            if e["key"] == base and e["bound"] == bound and e["fp"] == list(fp):
                return [tuple(r) for r in e["rows"]]
    return None


def history_older(col_path: str, base: list, bound: int) -> list:
    """Saved entries for these settings with an earlier boundary, newest first (to top
    up with the days since, if the review log before that boundary hasn't changed)."""
    with _lock:
        out = [dict(e) for e in _store("history", col_path)["entries"] if e["key"] == base and e["bound"] < bound]
    return sorted(out, key=lambda e: -e["bound"])


def history_put(col_path: str, base: list, bound: int, fp, rows: list) -> None:
    with _lock:
        st = _store("history", col_path)
        es = [e for e in st["entries"] if e["key"] != base]
        es.append({"key": base, "bound": int(bound), "fp": list(fp), "rows": [list(r) for r in rows],
                   "used": time.time()})
        st["entries"] = sorted(es, key=lambda e: -e.get("used", 0))[:HISTORY_KEEP]
        _save("history")


# ──────────────────────────────────────────────────────────────
# FSRS forecast: (when, forecast, band) by the forecast's cache key
# ──────────────────────────────────────────────────────────────
def forecast_get(col_path: str, key) -> tuple | None:
    k = repr(key)
    with _lock:
        for e in _store("forecast", col_path)["entries"]:
            if e["key"] == k:
                band = {d: tuple(v) for d, v in (e["band"] or {}).items()}
                return e["when"], e["forecast"], band
    return None


def forecast_put(col_path: str, key, when: float, forecast, band) -> None:
    k = repr(key)
    with _lock:
        st = _store("forecast", col_path)
        es = [e for e in st["entries"] if e["key"] != k]
        es.append({"key": k, "when": when, "forecast": forecast,
                   "band": {d: list(v) for d, v in (band or {}).items()}})
        st["entries"] = es[-FORECAST_KEEP:]
        _save("forecast")


# ──────────────────────────────────────────────────────────────
# Time Left's model (a pickle: it's the add-on's own object, read back by this version)
# ──────────────────────────────────────────────────────────────
def model_get(key: tuple):
    path = _file("model", "bin")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            saved_key, blob = pickle.loads(f.read())
        if saved_key != (_version,) + tuple(key):
            return None
        return pickle.loads(zlib.decompress(blob))
    except Exception:
        return None


def model_put(key: tuple, model) -> None:
    path = _file("model", "bin")
    if not path:
        return
    try:
        blob = zlib.compress(pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL), 1)
        _write(path, pickle.dumps(((_version,) + tuple(key), blob), protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        pass
