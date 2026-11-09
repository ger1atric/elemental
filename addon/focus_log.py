"""
Focus log — what Anki's review log can't tell. Anki stores one number per answer: the
time on the card, question and answer side together, capped by the deck. This records,
for each answer, the time on the question side and on the answer side, how long Anki
wasn't the active app (you switched to a browser, a PDF, UWorld…), and whether the
editor or the browser was opened during that card, or you pressed the lookup key
(focus_lookup_key, "x") to leave it out yourself.

The focus score uses it (estimator._focus_x): a card during which you opened the editor
or browser was a lookup and is left out. Leaving Anki is shown ("away") but still counts,
since it may have been a video rather than a lookup — unless the Time Left setting
focus_away_is_lookup says your app switches are lookups. With focus_reading_counts (off
by default), a slow card whose question side took your usual time, with Anki in front
throughout, counts as focused: the extra went into reading the answer.

Stored in user_files/focus_log_<profile>.sqlite, never the collection, so Undo is
untouched: one small row per answer, rows older than KEEP_DAYS dropped at profile open.
Only records while Time Left is on.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time

from aqt import gui_hooks, mw
from aqt.qt import QApplication, Qt

KEEP_DAYS = 400

_dir = os.path.join(os.path.dirname(__file__), "user_files")
_enabled = lambda: False
_lookup_key = lambda: ""
listeners = []          # called when the card on screen is left out of focus or counted again
_path = None            # the open profile's log file; None when not recording
_cur = None             # the card on screen: {"cid", "q0", "a0", "away", "since", "edit"}
                        # edit: 1 = editor or browser opened, 2 = lookup key pressed
_today = []             # rows answered since the last day cutoff: (cid, t_ms, q, a, away, edit)


def setup(enabled, lookup_key=lambda: "") -> None:
    """Called once by Time Left; enabled() says whether to record, lookup_key() is the
    review-screen key that leaves the card on screen out of the focus score."""
    global _enabled, _lookup_key
    _enabled, _lookup_key = enabled, lookup_key
    gui_hooks.profile_did_open.append(_open)
    gui_hooks.profile_will_close.append(_close)
    gui_hooks.reviewer_did_show_question.append(_on_question)
    gui_hooks.reviewer_did_show_answer.append(_on_answer_shown)
    gui_hooks.reviewer_did_answer_card.append(_on_answered)
    gui_hooks.reviewer_will_end.append(_drop_current)
    gui_hooks.editor_did_init.append(_on_lookup_window)
    gui_hooks.browser_will_show.append(_on_lookup_window)
    gui_hooks.state_shortcuts_will_change.append(_on_shortcuts)
    try:
        QApplication.instance().applicationStateChanged.connect(_on_app_state)
    except Exception:
        pass


def path() -> str | None:
    return _path


# ──────────────────────────────────────────────────────────────
# Recording
# ──────────────────────────────────────────────────────────────
def _connect(path: str | None = None) -> sqlite3.Connection:
    """A connection for one write. Nothing stays open between answers: Windows can't move
    user_files (Anki does that on every update) while a file in it is open."""
    db = sqlite3.connect(path or _path, timeout=1.0)
    no_ckpt = getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
    if no_ckpt is not None:
        try:
            db.setconfig(no_ckpt, True)     # closing doesn't fold the WAL back (no fsync per answer)
        except Exception:
            pass
    db.execute("PRAGMA synchronous=NORMAL")     # no fsync per answer; safe with WAL
    # Each commit appends a 4 KB page to the WAL; fold it back often and keep the
    # file small instead of letting it grow to SQLite's 4 MB default.
    db.execute("PRAGMA wal_autocheckpoint=64")
    db.execute("PRAGMA journal_size_limit=262144")
    return db


def _open() -> None:
    global _path, _today
    _close()
    try:
        name = re.sub(r"[^\w-]", "_", mw.pm.name or "profile")
        os.makedirs(_dir, exist_ok=True)
        _path = os.path.join(_dir, f"focus_log_{name}.sqlite")
        db = _connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS log (cid INTEGER, t INTEGER, q REAL, a REAL, "
                       "away REAL, edit INTEGER)")
            db.execute("CREATE INDEX IF NOT EXISTS log_t ON log (t)")
            db.execute("CREATE INDEX IF NOT EXISTS log_cid ON log (cid, t)")     # the model fit's join
            db.execute("DELETE FROM log WHERE t < ?", (int((time.time() - KEEP_DAYS * 86400) * 1000),))
            db.commit()
            since = int((mw.col.sched.day_cutoff - 86400) * 1000)
            _today = list(db.execute("SELECT cid, t, q, a, away, edit FROM log WHERE t >= ?", (since,)))
        finally:
            db.close()
    except Exception:
        _path = None


def _close() -> None:
    global _path, _cur, _today
    _flush()
    _cur, _today, _path = None, [], None


_writer = None      # one background thread for the writes, so they stay in order


def _write(path: str, row) -> None:
    db = _connect(path)
    try:
        db.execute("INSERT INTO log VALUES (?, ?, ?, ?, ?, ?)", row)
        db.commit()
    finally:
        db.close()


def _flush() -> None:
    """Wait for the writes still queued (the profile is closing: nothing may stay open)."""
    if _writer is not None:
        try:
            _writer.submit(lambda: None).result(timeout=3)
        except Exception:
            pass


def _on_question(card) -> None:
    global _cur
    if _path is None or not _enabled():
        _cur = None
        return
    now = time.monotonic()
    away_now = QApplication.applicationState() != Qt.ApplicationState.ApplicationActive
    _cur = {"cid": card.id, "q0": now, "a0": None, "away": 0.0,
            "since": now if away_now else None, "edit": 0}


def _on_answer_shown(card) -> None:
    if _cur is not None and _cur["cid"] == card.id and _cur["a0"] is None:
        _cur["a0"] = time.monotonic()


def _on_answered(reviewer, card, ease) -> None:
    global _cur
    c, _cur = _cur, None
    if c is None or c["cid"] != card.id or _path is None:
        return
    now = time.monotonic()
    away = c["away"] + (now - c["since"] if c["since"] is not None else 0.0)
    a0 = c["a0"] if c["a0"] is not None else now
    row = (card.id, int(time.time() * 1000), round(a0 - c["q0"], 2), round(now - a0, 2),
           round(away, 1), c["edit"])
    # The day's rows are read from memory (today_index), so the file write can happen off
    # the main thread: opening a file can take a while on Windows, with antivirus scanning it.
    _today.append(row)
    global _writer
    try:
        if _writer is None:
            from concurrent.futures import ThreadPoolExecutor
            _writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="elemental-focus-log")
        _writer.submit(_write, _path, row)
    except Exception:
        try:
            _write(_path, row)
        except Exception:
            pass


def _drop_current(*_args) -> None:
    global _cur
    _cur = None


def _on_app_state(state) -> None:
    if _cur is None:
        return
    now = time.monotonic()
    if state == Qt.ApplicationState.ApplicationActive:
        if _cur["since"] is not None:
            _cur["away"] += now - _cur["since"]
            _cur["since"] = None
    elif _cur["since"] is None:
        _cur["since"] = now


def _on_lookup_window(*_args) -> None:
    # The editor (Edit during review, Add) or the browser opened while a card is up.
    if _cur is not None and mw.state == "review":
        was = _cur["edit"]
        _cur["edit"] = 1
        if not was:
            _notify()


def marked() -> bool:
    """Whether the card on screen is left out of the focus score."""
    return _cur is not None and bool(_cur["edit"])


def _notify() -> None:
    for fn in listeners:
        try:
            fn()
        except Exception:
            pass


def toggle_lookup() -> bool | None:
    """Leave the card on screen out of the focus score, or count it again. The new
    state; None when nothing is being recorded."""
    if _cur is None:
        return None
    if _cur["edit"] == 1:           # the editor or browser already left it out
        return True
    _cur["edit"] = 0 if _cur["edit"] == 2 else 2
    return _cur["edit"] == 2


def _on_shortcuts(state, shortcuts) -> None:
    key = _lookup_key() if state == "review" and _enabled() else ""
    if key:
        shortcuts.append((key, _on_lookup_key))


def _on_lookup_key() -> None:
    now = toggle_lookup()
    if now is not None:
        from aqt.utils import tooltip
        tooltip("Not counted toward focus" if now else "Counted toward focus again", period=1200)
        _notify()


# ──────────────────────────────────────────────────────────────
# Reading it back
# ──────────────────────────────────────────────────────────────
def today_index() -> dict:
    """{cid: [(t_ms, q, a, away, edit)]} for today's answers so far (main thread)."""
    out = {}
    for cid, t, q, a, away, edit in _today:
        out.setdefault(cid, []).append((t, q, a, away, edit))
    return out
