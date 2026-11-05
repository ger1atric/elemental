"""
Review pill — a small live marker on the review screen with your retention for
the deck you're studying and the margin to your target:

  • Above target → how many more cards you can get WRONG before dropping below.
  • Below target → how many more you need to get RIGHT to reach the target.

Hover it for the details and, with Time Left on, when you'll finish and a cue when
you seem to be drifting. Settings → Review Pill. Off by default.

Retention is read straight from the review log for the studied deck and all its
subdecks (today's reviews by default), with the heatmap's retention rule: new cards
don't count on the day they're introduced, and "wrong" means Again.

Everything reads the collection through its own read-only sqlite connection —
never mw.col.db, which clears Anki's Undo during review.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import time

from pathlib import Path

from aqt import mw, gui_hooks
from aqt.qt import QTimer

from . import estimator, time_left, pomodoro
from .icons import icon

REVIEW_PILL_API = 1
_get_config = _write_config = None
_addon_name = ""

_MARKER_JS = open(os.path.join(os.path.dirname(__file__), "marker.js"), encoding="utf-8").read()


# The heatmap's config keys -> the names used below (and their defaults).
_KEYS = {
    "target_retention": ("review_pill_target", 90),
    "pill_shows": ("review_pill_shows", "graph"),
    "window": ("review_pill_window", "today"),
    "show_time_left": ("review_pill_show_time", True),
    "focus_cue": ("review_pill_focus_cue", True),
    "focus_ring": ("review_pill_focus_ring", True),
    "ring_style": ("review_pill_ring_style", "draw"),
    "position": ("review_pill_position", "top-right"),
    "draggable": ("review_pill_draggable", True),
    "rolling_window": ("review_pill_span", 100),
    "smoothing": ("review_pill_smoothing", 2),
    "min_reviews_to_show": ("review_pill_min_reviews", 1),
}
DEFAULTS = {"review_pill_enabled": False, **{hk: d for hk, d in _KEYS.values()}}


def setup(get_config, write_config, addon_name: str) -> None:
    """Called once by the heatmap with its config helpers."""
    global _get_config, _write_config, _addon_name
    _get_config, _write_config, _addon_name = get_config, write_config, addon_name
    gui_hooks.reviewer_did_answer_card.append(_on_answer)
    gui_hooks.reviewer_did_show_question.append(_on_show_question)
    gui_hooks.reviewer_will_end.append(_remove_marker)
    gui_hooks.profile_did_open.append(_migrate)
    time_left.listeners.append(_update_marker)
    from . import focus_log
    focus_log.listeners.append(_update_marker)     # the card on screen was left out of focus, or counted again
    pomodoro.setup(get_config)
    pomodoro.listeners.append(_update_marker)      # a break offered, started, ended


def _raw() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(_get_config() or {})
    except Exception:
        pass
    return cfg


def enabled() -> bool:
    return bool(_raw().get("review_pill_enabled"))


def _cfg() -> dict:
    hm = _raw()
    cfg = {k: hm.get(hk, d) for k, (hk, d) in _KEYS.items()}
    # The pill has two parts you can switch on separately — your retention and when
    # you'll finish — and retention is drawn as a graph or as numbers. Older settings
    # had one "the pill shows" choice; read them the same way until saved anew.
    shows = hm.get("review_pill_shows", "graph")
    if "review_pill_show_retention" in hm:
        cfg["show_retention"] = bool(hm["review_pill_show_retention"])
        cfg["retention_style"] = hm.get("review_pill_retention_style", "graph")
    else:
        cfg["show_retention"] = shows != "time"
        cfg["retention_style"] = "numbers" if shows == "numbers" else "graph"
        cfg["show_time_left"] = bool(hm.get("review_pill_show_time", True)) or shows in ("time", "both")
    # The pill's colors follow the heatmap's own retention scale.
    cfg["gradient_min"] = hm.get("retention_min", 75)
    cfg["gradient_max"] = hm.get("retention_max", 95)
    return cfg


def _migrate() -> None:
    """First run: bring over the separate Retention Tracker add-on's settings and
    switch the pill on, so moving to the heatmap's copy changes nothing you see."""
    try:
        stored = mw.addonManager.getConfig(_addon_name) or {}
    except Exception:
        return
    # A marker of its own: the heatmap writes all its defaults (review_pill_enabled
    # included) when you save Settings or update, so that key can't tell us.
    if stored.get("review_pill_migrated"):
        return
    try:
        rt = mw.addonManager.getConfig("retention_tracker")
    except Exception:
        rt = None
    cfg = _get_config()
    cfg["review_pill_migrated"] = True
    if rt:
        cfg["review_pill_enabled"] = True
        for k, (hk, _d) in _KEYS.items():
            if k in rt:
                cfg[hk] = rt[k]
        if "pill_shows" not in rt and "compact" in rt:
            cfg["review_pill_shows"] = "graph" if rt["compact"] else "numbers"
    _write_config(cfg)


# ──────────────────────────────────────────────────────────────
# Retention color gradient — the exact red→yellow→green stops used by
# Interactive Heatmap's get_retention_color(), so a given retention shows
# the same color in both places.
# ──────────────────────────────────────────────────────────────
_GRAD_BAD = (255, 85, 85)   # red    #ff5555
_GRAD_MID = (255, 204, 0)   # yellow #ffcc00
_GRAD_GOOD = (0, 204, 51)   # green  #00cc33


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _gradient_rgb(fraction: float, lo: float, hi: float):
    """Map a retention fraction to a red→yellow→green rgb (heatmap logic)."""
    if hi <= lo:
        ratio = 1.0 if fraction >= hi else 0.0
    elif fraction <= lo:
        ratio = 0.0
    elif fraction >= hi:
        ratio = 1.0
    else:
        ratio = (fraction - lo) / (hi - lo)
    if ratio < 0.5:
        return _lerp(_GRAD_BAD, _GRAD_MID, ratio * 2)
    return _lerp(_GRAD_MID, _GRAD_GOOD, (ratio - 0.5) * 2)


def _retention_text_color(fraction: float, cfg: dict, night: bool) -> str:
    lo = float(cfg.get("gradient_min", 75)) / 100.0
    hi = float(cfg.get("gradient_max", 95)) / 100.0
    rgb = _gradient_rgb(fraction, lo, hi)
    if not night:
        # Darken toward ink for legibility on the light marker background,
        # keeping the same hue.
        rgb = _lerp(rgb, (26, 26, 26), 0.28)
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _below_target_color(fraction: float, cfg: dict, night: bool) -> str:
    """Yellow just under the target, red at the gradient's low end (or 15 points
    under the target when the gradient starts above it)."""
    hi = _target_fraction(cfg)
    lo = float(cfg.get("gradient_min", 75)) / 100.0
    if lo > hi - 0.02:
        lo = hi - 0.15
    rgb = _lerp(_GRAD_BAD, _GRAD_MID, (fraction - lo) / (hi - lo))
    if not night:
        rgb = _lerp(rgb, (26, 26, 26), 0.28)
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _target_fraction(cfg: dict) -> float:
    # Clamp to a sane, division-safe range [1, 99].
    t = float(cfg.get("target_retention", 90))
    return max(1.0, min(99.0, t)) / 100.0


def _current_deck_id() -> int:
    try:
        return int(mw.col.decks.get_current_id())
    except Exception:
        return 0


# ──────────────────────────────────────────────────────────────
# Retention from the review log
# ──────────────────────────────────────────────────────────────
# For a time window, read the window's revlog rows once (an id range) and look
# each card up, instead of SQLite's default of walking every card in the deck
# and probing its revlog — tens of thousands of probes for a big deck. NOT
# INDEXED + CROSS JOIN pin that plan (left alone, SQLite scans the whole revlog
# through its cid index) and MATERIALIZED stops `win` being re-run inside
# `firsts`. Same rows either way; ~9 ms instead of ~22 ms on AnKing.
import sqlite3 as _sqlite3

if _sqlite3.sqlite_version_info >= (3, 35):
    _WINDOW_JOIN, _WIN_AS = "NOT INDEXED CROSS JOIN", "AS MATERIALIZED"
else:
    _WINDOW_JOIN, _WIN_AS = "JOIN", "AS"


def _deck_stats(did: int) -> tuple[int, int]:
    """(correct, wrong) retention reviews for this deck + subdecks in the window.

    Replicates the Interactive Heatmap's retention rule (with its
    exclude_new_cards_from_retention behaviour): count every revlog row of
    type < 4 (learn/review/relearn/filtered; manual excluded) EXCEPT reviews of
    a card on the day it was first introduced — i.e. new cards don't count on
    their first day, but their later reviews (and relearns) do. "Correct" is
    ease > 1 (Hard/Good/Easy); "wrong" is Again.
    """
    try:
        dids = [did] + [child_id for _, child_id in mw.col.decks.children(did)]
    except Exception:
        dids = [did]
    if not dids:
        return 0, 0

    cfg = _cfg()
    did_list = ",".join(str(int(d)) for d in dids)
    try:
        roll = int(mw.col.conf.get("rollover", 4)) * 3600 * 1000
    except Exception:
        roll = 4 * 3600 * 1000

    try:
        # Start of the current Anki day (respects the rollover hour).
        cutoff_ms = int((mw.col.sched.day_cutoff - 86400) * 1000)
    except Exception:
        cutoff_ms = 0
    today = _stats_query(did_list, roll, _WINDOW_JOIN, _WIN_AS, f"AND r.id >= {cutoff_ms}")
    if cfg.get("window", "today") != "all" or today is None:
        return today or (0, 0)
    # All time = everything before today, counted once per day (about a second on a
    # big deck), plus today's answers. Earlier answers' counting never changes later.
    key = (mw.col.path, did_list, cutoff_ms)
    before = _before_today.get(key)
    if before is None:
        before = _stats_query(did_list, roll, "JOIN", "AS", f"AND r.id < {cutoff_ms}")
        if before is None:
            return 0, 0
        _before_today.clear()
        _before_today[key] = before
    return before[0] + today[0], before[1] + today[1]


_before_today = {}      # (collection, decks, day start) -> (correct, wrong) before today


def _stats_query(did_list: str, roll: int, join: str, win_as: str, time_clause: str):
    """(correct, wrong) for the heatmap's retention rule over the rows time_clause
    picks; None when the query fails."""

    # `win`   = candidate reviews in the deck+subdecks (and window).
    # `firsts` = each of those cards' first-ever review (day + type), so we can
    #   drop a review that falls on its card's introduction day when that
    #   introduction was a new/learning card (ftype = 0). Mirrors the heatmap's
    #   ret_cond: NOT (ftype=0 AND rday=fday) AND (rtype>0 OR rid!=fid).
    sql = f"""
        WITH win {win_as} (
            SELECT r.id AS rid, r.ease AS ease, r.type AS rtype, r.cid AS cid,
                   strftime('%Y-%m-%d', (r.id - {roll}) / 1000, 'unixepoch', 'localtime') AS rday
            FROM revlog r {join} cards c ON r.cid = c.id
            WHERE r.type < 4 AND c.did IN ({did_list}) {time_clause}
        ),
        firsts AS (
            SELECT fr.cid AS cid, fr.id AS fid, fr.type AS ftype,
                   strftime('%Y-%m-%d', (fr.id - {roll}) / 1000, 'unixepoch', 'localtime') AS fday
            FROM revlog fr
            JOIN (
                SELECT cid, MIN(id) AS fid FROM revlog
                WHERE type < 4 AND cid IN (SELECT DISTINCT cid FROM win)
                GROUP BY cid
            ) m ON fr.id = m.fid
        )
        SELECT COUNT(*),
               COALESCE(SUM(CASE WHEN win.ease > 1 THEN 1 ELSE 0 END), 0)
        FROM win JOIN firsts ON win.cid = firsts.cid
        WHERE NOT (firsts.ftype = 0 AND win.rday = firsts.fday)
          AND (win.rtype > 0 OR win.rid != firsts.fid)
    """
    row = _readonly_query(sql)
    if not row:
        return None
    total = int(row[0] or 0)
    correct = int(row[1] or 0)
    return correct, total - correct


def _readonly_query(sql: str, many: bool = False):
    """Run a read-only SELECT against the collection WITHOUT touching mw.col.db.

    Direct mw.col.db access — even a plain read — clears Anki's backend undo
    queue, which silently breaks Undo (Cmd/Ctrl+Z) during review. Opening our
    own read-only SQLite connection to the collection file keeps the query
    completely outside the backend, so Undo is never affected. The connection
    sees committed data (including the review just answered).
    """
    try:
        import sqlite3

        uri = Path(mw.col.path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            conn.execute("PRAGMA query_only=1;")
            cur = conn.execute(sql)
            return cur.fetchall() if many else cur.fetchone()
        finally:
            conn.close()
    except Exception:
        return [] if many else None


def _session_eases(did: int) -> list:
    """Today's qualifying reviews for this deck + subdecks, as an ordered list of
    ease values (1 = Again, >1 = correct). Same exclude-new retention rule as
    _deck_stats, always scoped to the current day (the 'session'), read-only."""
    try:
        dids = [did] + [child_id for _, child_id in mw.col.decks.children(did)]
    except Exception:
        dids = [did]
    if not dids:
        return []
    did_list = ",".join(str(int(d)) for d in dids)
    try:
        roll = int(mw.col.conf.get("rollover", 4)) * 3600 * 1000
    except Exception:
        roll = 4 * 3600 * 1000
    try:
        cutoff = int((mw.col.sched.day_cutoff - 86400) * 1000)
    except Exception:
        cutoff = 0
    sql = f"""
        WITH win {_WIN_AS} (
            SELECT r.id AS rid, r.ease AS ease, r.type AS rtype, r.cid AS cid,
                   strftime('%Y-%m-%d', (r.id - {roll}) / 1000, 'unixepoch', 'localtime') AS rday
            FROM revlog r {_WINDOW_JOIN} cards c ON r.cid = c.id
            WHERE r.type < 4 AND c.did IN ({did_list}) AND r.id >= {cutoff}
        ),
        firsts AS (
            SELECT fr.cid AS cid, fr.id AS fid, fr.type AS ftype,
                   strftime('%Y-%m-%d', (fr.id - {roll}) / 1000, 'unixepoch', 'localtime') AS fday
            FROM revlog fr
            JOIN (
                SELECT cid, MIN(id) AS fid FROM revlog
                WHERE type < 4 AND cid IN (SELECT DISTINCT cid FROM win)
                GROUP BY cid
            ) m ON fr.id = m.fid
        )
        SELECT win.ease FROM win JOIN firsts ON win.cid = firsts.cid
        WHERE NOT (firsts.ftype = 0 AND win.rday = firsts.fday)
          AND (win.rtype > 0 OR win.rid != firsts.fid)
        ORDER BY win.rid
    """
    return [int(r[0]) for r in (_readonly_query(sql, many=True) or [])]


# ──────────────────────────────────────────────────────────────
# Margin math
# ──────────────────────────────────────────────────────────────
def _compute(correct: int, wrong: int, target: float):
    """Return (retention_pct, above_target, margin_count) or (None, None, None)."""
    n = correct + wrong
    if n == 0:
        return None, None, None
    r = correct / n
    above = r >= target
    # Epsilon absorbs floating-point noise (e.g. 1/0.1 == 10.000000000000002)
    # so exact boundaries don't spuriously gain/lose a card.
    eps = 1e-9
    if above:
        # Max additional wrong k such that correct / (n + k) >= target.
        margin = max(int(math.floor(correct / target - n + eps)), 0)
    else:
        # Min additional correct k such that (correct + k) / (n + k) >= target.
        margin = max(int(math.ceil((target * n - correct) / (1.0 - target) - eps)), 1)
    return r * 100.0, above, margin


# ──────────────────────────────────────────────────────────────
# Marker rendering
# ──────────────────────────────────────────────────────────────
_POSITIONS = {
    "top-right": "top:12px;right:14px;",
    "top-left": "top:12px;left:14px;",
    "bottom-right": "bottom:12px;right:14px;",
    "bottom-left": "bottom:12px;left:14px;",
}


def _is_night() -> bool:
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return False


def _build_payload() -> dict | None:
    """The marker's pill and hover panel: retention and/or when you'll finish."""
    cfg = _cfg()
    show_ret, show_time_part = cfg["show_retention"], cfg.get("show_time_left", True)
    graph = cfg["retention_style"] == "graph"
    # "hover": retention stays in the hover panel but out of the pill itself.
    ret_in_pill = cfg["retention_style"] != "hover"
    did = _current_deck_id()
    night = _is_night()

    retention, eases = None, []
    if show_ret:
        eases = _session_eases(did)
        if cfg.get("window", "today") != "all":
            # Same reviews as _deck_stats selects for "today" — count them here
            # rather than running the query twice.
            correct = sum(1 for e in eases if e > 1)
            wrong = len(eases) - correct
        else:
            correct, wrong = _deck_stats(did)
        if correct + wrong >= max(0, int(cfg["min_reviews_to_show"])):
            r_pct, above, margin = _compute(correct, wrong, _target_fraction(cfg))
            if r_pct is not None:
                retention = (r_pct, above, margin)
    est = _reviewer_estimate(did) if show_time_part else None
    pomo = _pomo_state()
    if retention is None and est is None and pomo is None:
        return None

    focus = _focus() if cfg.get("focus_cue", True) else None
    drift = bool(focus) and time_left.drifting(focus)
    lock = _lock_in() if show_time_part else None

    panel = []
    ret_text = []
    spark = time_bit = ""
    if retention is not None:
        r_pct, above, margin = retention
        accent = _retention_text_color(r_pct / 100.0, cfg, night)
        # Session trajectory: the cumulative retention % over today's recent
        # reviews (new cards excluded), ending on the headline number.
        if graph:
            spark = _sparkline(eases, cfg, night, accent, drift)
        # Below target the arrow and the "need" count slide from yellow just under the
        # target to red at the bottom of the gradient. Above target they follow it.
        hero = accent if above else _below_target_color(r_pct / 100.0, cfg, night)
        arrow = "&#9650;" if above else "&#9660;"  # ▲ / ▼
        target = round(_target_fraction(cfg) * 100)
        need = f"{margin} more can miss" if above else f"{margin} to reach {target}%"
        panel.append(
            '<div class="sec"><div class="row">'
            f'<span class="big" style="color:{hero};"><span style="font-size:10px;vertical-align:1px;">'
            f'{arrow}</span>&nbsp;{margin}</span>'
            f'<span class="big" style="color:{accent};">{r_pct:.1f}%</span></div>'
            f'<div class="row"><span class="sub">{need}</span><span class="sub">retention</span></div></div>'
        )
        ret_text.append(
            f'<span class="num" style="font-weight:700;font-size:15px;color:{hero};">'
            f'<span style="font-size:10px;vertical-align:1px;">{arrow}</span>&nbsp;{margin}</span>'
            f'<span class="sep">&middot;</span>'
            f'<span class="num" style="color:{accent};font-weight:600;">{r_pct:.1f}%</span>'
        )
    # Green reviews done: only new cards (if any) keep a finish time.
    reviews_done = est is not None and _reviews_finished(est)
    show_time = bool(est is not None and est["all"]["n"] and (not reviews_done or est["new"]["n"]))
    if show_time:
        a, rv, nw = est["all"], est["reviews"], est["new"]
        now = datetime.datetime.now()
        # Reviews get their own finish time when they come before the new cards;
        # mixed in (or after), they finish with everything else.
        split = bool(rv["n"] and nw["n"] and est.get("reviews_first")) and not reviews_done
        head = rv if split else a
        title = "Reviews finish" if rv["n"] and (split or not nw["n"]) else "All cards finish"
        if reviews_done:
            head, title = nw, "New cards finish"
        # With no graph to ring, a drifting cue tints the finish time itself; once only
        # new cards are left, the time takes the "new" blue the count pills use.
        if drift and not spark:
            tint = f"color:{_amber(night)};"
        elif reviews_done:
            tint = f"color:{_new_color()};"
        else:
            tint = ""
        clock = lambda sec: _fmt_clock(now + datetime.timedelta(seconds=sec))
        if _show_left():
            time_bit = (f'<span class="num" style="font-weight:600;{tint}">~{_fmt_dur(head["mean"])}</span>'
                        '<span class="sep">left</span>')
        else:
            time_bit = ('<span class="sep">Finish</span>'
                        f'<span class="num" style="font-weight:600;{tint}">~{clock(head["mean"])}</span>')
        # The hover leads with what the pill shows (time left or the finish time), with
        # the other one on the line under it. Nothing else: one figure, one reminder.
        if _show_left():
            title = title.replace("finish", "left")
            big, under = f"~{_fmt_dur(head['mean'])}", f"Finish ~{clock(head['mean'])}"
        else:
            big, under = f"~{clock(head['mean'])}", f"~{_fmt_dur(head['mean'])} left"
        rows = [
            '<div class="sec"><div class="row">'
            f'<span class="label">{title}</span>'
            f'<span class="big">{big}</span></div>'
            f'<div class="row"><span class="sub">{under}</span></div>'
        ]
        if lock:
            rows.append(_lock_block(lock, night))
        if drift:
            rows.append(_drift_row(focus, night))
        panel.append("".join(rows) + "</div>")
    elif lock:
        panel.append(f'<div class="sec">{_lock_block(lock, night)}</div>')

    # The pill: retention (graph or numbers), then the finish time.
    sep = '<span class="sep">&middot;</span>'
    if spark:
        pill = spark + time_bit
    else:
        pill = sep.join((ret_text if ret_in_pill else []) + ([time_bit] if time_bit else []))
    if not pill and ret_text:
        pill = sep.join(ret_text)       # nothing else to show: the numbers, so there's a pill to hover
    if drift and not show_time:
        panel.append(f'<div class="sec">{_drift_row(focus, night)}</div>')
    pomo_bits = _pomo_bits(pomo, night, drift) if pomo else None
    if pomo_bits and pomo_bits.get("row") and panel:
        # stopped: Start goes in the panel's last section, not a section of its own
        panel[-1] = panel[-1][:-len("</div>")] + pomo_bits["row"] + "</div>"
        pomo_bits = dict(pomo_bits, sec="")
    if pomo_bits:
        if pomo_bits["replace"]:        # on a break: the pill is the break (the panel keeps its order)
            pill = pomo_bits["pill"]
            panel.append(pomo_bits["sec"])
        else:
            if pomo_bits["pill"]:
                pill = pill + sep + pomo_bits["pill"] if pill else pomo_bits["pill"]
            if pomo_bits["sec"]:
                panel.append(pomo_bits["sec"])
    if not pill:
        return None
    from . import focus_log
    return {"pill": pill, "panel": "".join(panel), "night": night, "focus": "drift" if drift else "",
            "ring": _ring(cfg), "paused": focus_log.marked(),
            "pomo": pomo_bits["cls"] if pomo_bits else "", "pomo_title": pomo_bits["title"] if pomo_bits else ""}


# ──────────────────────────────────────────────────────────────
# Pomodoro (pomodoro.py): a countdown at the end of the pill, a section in the panel.
# A break offered or under way takes the pill over. The page counts the time down
# itself (data-end), so nothing is redrawn every second.
# ──────────────────────────────────────────────────────────────
_ARC = 50.27        # the ring's circumference (r = 8)


def _pomo_state() -> dict | None:
    return pomodoro.state() if pomodoro.enabled() else None


def _teal(night: bool) -> str:
    return "#3fc1a9" if night else "#0e7d6e"


def _pomo_ring(frac: float, night: bool) -> str:
    track = "rgba(255,255,255,.18)" if night else "rgba(0,0,0,.14)"
    return ('<svg width="13" height="13" viewBox="0 0 20 20" style="display:block;flex:none" aria-hidden="true">'
            f'<circle cx="10" cy="10" r="8" fill="none" stroke="{track}" stroke-width="2.6"/>'
            f'<circle class="pomo-arc" cx="10" cy="10" r="8" fill="none" stroke="{_teal(night)}" stroke-width="2.6" '
            f'stroke-linecap="round" transform="rotate(-90 10 10)" stroke-dasharray="{_ARC * frac:.2f} {_ARC}"/></svg>')


def _pomo_time(sec: float, end_ms, total: int = 0, cls: str = "num", style: str = "") -> str:
    live = (f' data-end="{end_ms}"' + (f' data-total="{total}"' if total else "")) if end_ms else ""
    return f'<span class="{cls} pomo-t"{live} style="{style}">{pomodoro.mmss(sec)}</span>'


def _pomo_dots(done: int, of: int, night: bool) -> str:
    on = min(max(done, 0), of)
    return (f'<span class="sub" style="letter-spacing:2px"><span style="color:{_teal(night)}">{"●" * on}</span>'
            f'{"○" * (of - on)}</span>')


def _pomo_act(act: str, text: str, night: bool) -> str:
    """A link in the panel (the panel takes clicks while it holds one)."""
    return f'<span class="pomo-act" data-act="{act}" style="color:{_teal(night)};">{text}</span>'


def _pomo_stop(night: bool) -> str:
    return f'<div class="row" style="margin-top:6px;"><span></span>{_pomo_act("stop", "Stop timer", night)}</div>'


_block_cache = {}


def _pomo_block(start_ms: int, end_ms: int) -> dict:
    """Cards answered in a finished block, % right of its review cards, its focus score."""
    key = (start_ms, end_ms)
    if key not in _block_cache:
        row = _readonly_query(
            "SELECT count(), sum(CASE WHEN type = 1 THEN 1 ELSE 0 END), "
            "sum(CASE WHEN type = 1 AND ease > 1 THEN 1 ELSE 0 END) "
            f"FROM revlog WHERE id BETWEEN {int(start_ms)} AND {int(end_ms)}") or (0, 0, 0)
        n, rv, ok = (int(v or 0) for v in row)
        api = _time_api()
        fn = getattr(api, "block_focus", None) if api else None
        _block_cache.clear()
        _block_cache[key] = {"n": n, "right": round(100 * ok / rv) if rv >= 5 else None,
                             "focus": fn(start_ms, end_ms) if fn else None}
    return _block_cache[key]


def _pomo_bits(st: dict, night: bool, drift: bool) -> dict | None:
    """The pill's piece, the panel's section, whether the break takes the pill over, the
    pill's extra class (click: clicking it does something) and its tooltip."""
    ph, teal = st.get("phase"), _teal(night)
    if ph == "idle":
        return None
    block, of = st.get("block", 1), st.get("of", 4)
    cup = f'<span style="display:flex;color:{teal}">{icon("coffee", "14px", 2.2)}</span>'
    brk_word = '<span class="num" style="font-weight:600;">Break</span>'
    if ph == "focus":
        left, total, held = st["left"], st["total"], bool(st.get("held"))
        offer = bool(drift and not held and pomodoro.cfg().get("pomo_drift_break"))
        pomodoro.offering(offer)
        ring = _pomo_ring(left / total if total else 0, night)
        if held:                        # paused from the pill: bars, the time dimmed
            pill = ('<span class="pz"><i></i><i></i></span><span style="display:flex;align-items:center;gap:7px;'
                    f'opacity:.5">{ring}{_pomo_time(left, None)}</span>')
        else:
            pill = ring + _pomo_time(left, st.get("end_ms"), total)
        if offer:
            pill += f'<span style="display:flex;color:{_amber(night)}">{icon("coffee", "14px", 2.2)}</span>'
        if held:
            line = f'<span class="sub">{block} of {of} · paused</span><span class="sub">click to resume</span>'
        else:
            brk_at = f" · break at {pomodoro.clock(time.time() + left)}" if st.get("running") else ""
            line = f'<span class="sub">{block} of {of}{brk_at}</span>{_pomo_dots(block - 1, of, night)}'
        sec = ('<div class="sec"><div class="row"><span class="label">Focus block</span>'
               + _pomo_time(left, None if held else st.get("end_ms"), 0, "big",
                            "color:#93a4bd;" if held and night else "color:#607089;" if held else f"color:{teal};")
               + f'</div><div class="row">{line}</div>'
               + (f'<div class="row" style="margin-top:6px;"><span class="sub" style="color:{_amber(night)};">'
                  'Drifting</span><span class="sub">click for a break</span></div>' if offer else "")
               + _pomo_stop(night) + '</div>')
        title = "Take a break now" if offer else "Resume" if held else "Pause"
        return {"pill": pill, "sec": sec, "replace": False, "cls": "click", "title": title}
    if ph == "brk":
        end = st["brk_end_ms"]
        left = max(0, end / 1000 - time.time())
        pill = cup + brk_word + _pomo_time(left, end, 0, "sep")
        rows = ['<div class="sec"><div class="row"><span class="label">'
                f'{"Long break" if st.get("long") else "Break"}</span>'
                + _pomo_time(left, end, 0, "big", f"color:{teal};") + '</div>'
                f'<div class="row"><span class="sub">back at {pomodoro.clock(end / 1000)}</span>'
                '<span class="sub">click to end it</span></div>']
        if st.get("start_ms"):          # how the block that just ended went
            bl = _pomo_block(st["start_ms"], st["end_ms"])
            bits = [f"{bl['n']} card{'s' if bl['n'] != 1 else ''}"]
            if bl["focus"] is not None:
                bits.append(f"focus {round(100 * bl['focus'])}%")
            if bl["right"] is not None:
                bits.append(f"{bl['right']}% right")
            rows.append(f'<div class="row" style="margin-top:7px;"><span class="label">Block {block} done</span>'
                        f'{_pomo_dots(block, of, night)}</div>'
                        f'<div class="row"><span class="sub">{" · ".join(bits)}</span></div>')
        return {"pill": pill, "sec": "".join(rows) + _pomo_stop(night) + "</div>", "replace": True, "cls": "brk click",
                "title": "End the break"}
    if ph == "off":                     # stopped: one row at the end of the panel, with Start
        row = (f'<div class="row" style="margin-top:6px;"><span class="sub">Pomodoro timer</span>'
               f'{_pomo_act("start", "Start", night)}</div>')
        return {"pill": "", "sec": "", "row": row, "replace": False, "cls": "", "title": ""}
    if ph == "over":
        nxt = st.get("next", 1)
        pill = _pomo_ring(1, night) + _pomo_time(st["total"], None)
        sec = ('<div class="sec"><div class="row"><span class="label">Break over</span>'
               f'<span class="big" style="color:{teal};">{pomodoro.mmss(st["total"])}</span></div>'
               f'<div class="row"><span class="sub">Block {nxt} starts with your next card</span></div>'
               + _pomo_stop(night) + '</div>')
        return {"pill": pill, "sec": sec, "replace": False, "cls": "", "title": ""}
    return None


RING_FRESH_MS = 5000        # ring only for an answer this recent (not after undo or a pause)


def _ring(cfg: dict) -> dict | None:
    """A brief ring around the pill for the answer just given: green when it was focused
    (within one SD of that card's usual time), amber when it wasn't, none for a lookup.
    The id lets the page play it once, though the pill redraws more than once per card."""
    if not cfg.get("focus_ring", True):
        return None
    api = _time_api()
    fn = getattr(api, "last_answer", None) if api else None
    last = fn() if fn else None
    if not last:
        ring_log("no ring: no answer or model yet")
        return None
    age = time.time() * 1000 - last[0]
    if last[1] == "lookup" or age > RING_FRESH_MS:
        if last[0] != _ring_log_seen[0]:        # once per answer, not every redraw
            _ring_log_seen[0] = last[0]
            ring_log(f"no ring: {'lookup' if last[1] == 'lookup' else f'latest answer {age / 1000:.1f} s old'}")
        return None
    return {"id": last[0], "kind": last[1], "style": cfg.get("ring_style", "draw")}


# A short log of how the after-answer rings went (the page reports each one), to
# diagnose rings that stop partway. user_files/ring_debug.log, last RING_LOG_KEEP lines.
RING_LOG_KEEP = 300
_ring_log_seen = [0]


def ring_log(line: str) -> None:
    path = os.path.join(os.path.dirname(__file__), "user_files", "ring_debug.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
        if os.path.getsize(path) > RING_LOG_KEEP * 200:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-RING_LOG_KEEP:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except OSError:
        pass


def on_ring_report(data: str) -> None:
    """From the page: how one ring went (frames drawn, how many by the fallback timer,
    the longest pause between frames, how it ended, any error)."""
    try:
        r = json.loads(data)
    except ValueError:
        return
    flag = "  <-- stalled" if r.get("timer") or r.get("gap", 0) > 100 or r.get("how") != "done" or r.get("err") else ""
    ring_log(f"ring {r.get('kind')}: {r.get('how')}, {r.get('frames')} frames ({r.get('timer')} by timer), "
             f"longest pause {r.get('gap')} ms, {r.get('ms')} ms{', error: ' + r['err'] if r.get('err') else ''}{flag}")


def _reviews_finished(est: dict) -> bool:
    """Reviews count as finished once the green (review) count is 0: red learning
    cards still to come don't keep their time showing — on most days they're under
    two minutes. New cards left still get their own finish time."""
    return est["counts"][2] == 0


def _amber(night: bool) -> str:
    """The retention gradient's yellow, deepened in light mode so it reads on white."""
    rgb = _GRAD_MID if night else _lerp(_GRAD_MID, (29, 39, 51), 0.28)
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def _drift_row(focus: tuple, night: bool) -> str:
    return (f'<div class="row" style="margin-top:6px;"><span class="sub" style="color:{_amber(night)};">'
            f'&#9679; Drifting</span><span class="sub">{focus[0]} of last {focus[1]} cards stalled</span></div>')


def _focus() -> tuple | None:
    """(stalled cards, answers) in the current session's recent window, from the heatmap."""
    api = _time_api()
    return api.focus() if api else None


def _new_color() -> str:
    """The heatmap's "new" pill color, so the bar matches the Time pills."""
    c = _raw().get("pill_new_color")
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#4a90e2"


def _lock_in() -> dict | None:
    """Today's focus-score numbers from the heatmap's Time Left (see time_left.lock_in)."""
    api = _time_api()
    fn = getattr(api, "lock_in", None) if api else None
    return fn() if fn else None


def _lock_block(lock: dict, night: bool) -> str:
    """Today's focus score (colored within your own usual range) over a box plot
    of today's answer times against each card's usual time, a typical day faint behind."""
    lo, hi = lock["range"]
    color = "#%02x%02x%02x" % tuple(int(v) for v in _gradient_rgb(lock["score"], lo, hi))
    typical = lock["typical"]
    k, away = lock.get("lookups") or 0, lock.get("away") or 0
    extra = ""
    if k or away:
        left = f"{k} lookup{'s' if k != 1 else ''} left out" if k else ""
        right = f"{away} time{'s' if away != 1 else ''} away" if away else ""
        extra = f'<div class="row"><span class="sub">{left}</span><span class="sub">{right}</span></div>'
    return (
        '<div class="row" style="margin-top:7px;"><span class="label">Focus</span>'
        f'<span class="big" style="color:{color};">{round(100 * lock["score"])}%</span></div>'
        f'{_lock_box(lock["box"], typical["box"] if typical else None, night, lock.get("points"))}'
        f'<div class="row"><span class="sub">typical {round(100 * typical["score"])}%</span>'
        f'<span class="sub">{lock["n"]} cards</span></div>'
        f'{extra}'
    )


# Viridis, for the density of the answer dots.
_VIRIDIS = ((68, 1, 84), (71, 45, 123), (59, 82, 139), (44, 114, 142), (33, 145, 140),
            (40, 174, 128), (94, 201, 98), (173, 220, 48), (253, 231, 37))


def _density_rgb(t: float, night: bool) -> tuple:
    """Density 0..1 to a viridis color, the densest dots always the most contrasting:
    toward yellow on the dark panel, toward deep purple on the light one."""
    u = 0.15 + 0.85 * t if night else 0.85 * (1.0 - t)
    f = max(0.0, min(1.0, u)) * (len(_VIRIDIS) - 1)
    i = min(int(f), len(_VIRIDIS) - 2)
    return _lerp(_VIRIDIS[i], _VIRIDIS[i + 1], f - i)


def _densities(xs: list, width: float) -> list:
    """Each point's local density, 0..1 (1 = the densest spot): a 2-px histogram of
    the dots' x positions, smoothed with a small Gaussian, read back at each dot."""
    nb = int(width // 2) + 1
    counts = [0] * nb
    for v in xs:
        counts[min(nb - 1, max(0, int(v // 2)))] += 1
    kernel = [math.exp(-0.5 * (k / 1.5) ** 2) for k in range(-4, 5)]
    smooth = [sum(counts[i + k - 4] * kernel[k] for k in range(9) if 0 <= i + k - 4 < nb) for i in range(nb)]
    top = max(smooth) or 1.0
    return [smooth[min(nb - 1, max(0, int(v // 2)))] / top for v in xs]


def _lock_box(today: tuple, typical, night: bool, points=None) -> str:
    """Two horizontal box plots of answer times in each card's own SDs from its usual
    time (−3 to +5): a typical day (faint, top) and today. Whiskers 5th–95th percentile,
    box the middle half, a tick at the median; the dashed line at +1 is where an answer
    stops counting as focused, the same for every card.
    Today's answers show as dots behind its box, spread up and down more where they crowd
    and colored by how crowded their spot is (viridis), densest on top."""
    w, h = 200.0, 47.0
    lo, hi = -3.0, 5.0              # axis ends, in SDs from the card's usual time

    def x(v):
        return 1 + (max(min(v, hi), lo) - lo) / (hi - lo) * (w - 2)

    ink = "#ffffff" if night else "#1d2733"
    faint = "rgba(255,255,255,.35)" if night else "rgba(29,39,51,.3)"
    grid = "rgba(255,255,255,.10)" if night else "rgba(29,39,51,.10)"

    def box(b, y, bh, stroke, fill, med):
        p5, q1, q2, q3, p95 = (x(v) for v in b)
        mid = y + bh / 2
        return (
            f'<line x1="{p5:.1f}" y1="{mid}" x2="{q1:.1f}" y2="{mid}" stroke="{stroke}" stroke-width="1"/>'
            f'<line x1="{q3:.1f}" y1="{mid}" x2="{p95:.1f}" y2="{mid}" stroke="{stroke}" stroke-width="1"/>'
            f'<line x1="{p5:.1f}" y1="{y + 2}" x2="{p5:.1f}" y2="{y + bh - 2}" stroke="{stroke}" stroke-width="1"/>'
            f'<line x1="{p95:.1f}" y1="{y + 2}" x2="{p95:.1f}" y2="{y + bh - 2}" stroke="{stroke}" stroke-width="1"/>'
            f'<rect x="{q1:.1f}" y="{y}" width="{max(q3 - q1, 2):.1f}" height="{bh}" rx="2" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            f'<line x1="{q2:.1f}" y1="{y - 1}" x2="{q2:.1f}" y2="{y + bh + 1}" stroke="{med}" '
            'stroke-width="2" stroke-linecap="round"/>'
        )

    svg = (f'<svg width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}" '
           'style="display:block;margin:6px 0 3px;overflow:visible;">')
    ticks = ((-2, "−2"), (-1, "−1"), (0, "usual"), (1, "+1"), (2, "+2"), (3, "+3"), (4, "+4 SD"))
    for v, label in ticks:
        svg += (f'<line x1="{x(v):.1f}" y1="0" x2="{x(v):.1f}" y2="33" stroke="{grid}" stroke-width="1"/>'
                f'<text x="{x(v):.1f}" y="44" font-size="8.5" text-anchor="middle" fill="{ink}" '
                f'fill-opacity=".5">{label}</text>')
    svg += (f'<line x1="{x(estimator.LOCK_SD):.1f}" y1="0" x2="{x(estimator.LOCK_SD):.1f}" y2="33" stroke="{ink}" '
            'stroke-opacity=".35" stroke-width="1" stroke-dasharray="2 2"/>')
    if typical:
        svg += box(typical, 3, 8, faint, "none", faint)
    top, bh = 16, 15
    xs = [x(v) for v in points or ()]
    dots = []
    mid = top + bh / 2
    for i, (cx, d) in enumerate(zip(xs, _densities(xs, w))):
        jitter = (i * 0.6180339887) % 1.0 - 0.5    # evenly spread, the same every redraw
        # Crowded stretches spread to the box's full height, sparse ones stay near the
        # middle line, so the cloud's outline traces the density (like a violin).
        dots.append((d, cx, mid + jitter * (bh - 3) * (0.15 + 0.85 * d)))
    for d, cx, cy in sorted(dots):
        fill = "#%02x%02x%02x" % tuple(int(c) for c in _density_rgb(d, night))
        svg += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.2" fill="{fill}" fill-opacity=".85"/>'
    outline = "rgba(255,255,255,.8)" if night else "rgba(29,39,51,.75)"
    svg += box(today, top, bh, outline, "none", ink)
    return svg + "</svg>"


def _show_left() -> bool:
    """Time Left's "Show as" choice: hours and minutes left rather than a finish clock."""
    return _raw().get("time_show_as") == "left"


def _sparkline(eases: list, cfg: dict, night: bool, accent: str, drift: bool = False) -> str:
    """Sparkline of the overall (cumulative) retention % over the last N cards,
    auto-zoomed tight to that range.

    This plots the same number shown in the headline — your whole-session
    retention % — and how it has drifted over the recent `rolling_window` cards,
    so the line's endpoint equals the displayed %. The y-axis fits just the
    min–max of those recent values (plus a little pad), so the small movements
    are visible. The percentage only moves on the current card (a correct nudges
    it up a hair, a wrong drops it more), so there are no sliding-window
    artefacts — no flat-on-correct, no jumps from old mistakes aging out.
    """
    span = max(5, int(cfg.get("rolling_window", 20)))
    cum_c = cum_n = 0
    cum = []
    for e in eases:
        cum_n += 1
        if e > 1:
            cum_c += 1
        cum.append(cum_c / cum_n * 100.0)
    series = cum[-span:]
    if len(series) < 2:
        return ""

    k = 120  # keep per-card detail for the default 100-card span
    if len(series) > k:
        series = [series[round(i * (len(series) - 1) / (k - 1))] for i in range(k)]
    series = _soften(series, max(0, int(cfg.get("smoothing", 2))))

    target_pct = round(_target_fraction(cfg) * 100)
    line = _retention_text_color(series[-1] / 100.0, cfg, night)
    w, h = 60.0, 16.0

    # Tight autoscale: fit just the recent range so the drift is visible. Pad is
    # proportional to the range, so as the session converges (range shrinking to
    # a few tenths of a percent) the view keeps zooming in and the line still
    # fills the height. The tiny floor only matters for a perfectly flat run.
    lo, hi = min(series), max(series)
    pad = max(0.02, (hi - lo) * 0.12)
    ylo, yhi = lo - pad, hi + pad
    rng = (yhi - ylo) or 1.0

    def _x(i):
        return i / (len(series) - 1) * w

    def _y(v):
        return h - (v - ylo) / rng * h

    path = _smooth_path([(_x(i), _y(v)) for i, v in enumerate(series)])
    svg = (
        f'<svg width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}" '
        f'style="display:block;flex:0 0 auto;overflow:visible;">'
    )
    if ylo <= target_pct <= yhi:  # only show the target line if it's in view
        ty = _y(target_pct)
        svg += (
            f'<line x1="0" y1="{ty:.1f}" x2="{w:.0f}" y2="{ty:.1f}" stroke="#6f819b" '
            f'stroke-width="0.8" stroke-dasharray="2 2" opacity="0.6"></line>'
        )
    svg += (
        f'<path d="{path}" fill="none" stroke="{line}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round"></path>'
        f'<circle cx="{_x(len(series) - 1):.1f}" cy="{_y(series[-1]):.1f}" r="1.9" fill="{line}"></circle>'
    )
    if drift:
        # Drifting: a soft amber ring around the endpoint (the hover panel says why).
        cx, cy = _x(len(series) - 1), _y(series[-1])
        svg += (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.6" fill="none" stroke="{_amber(night)}" '
                f'stroke-width="1.2" opacity="0.9"></circle>'
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7.2" fill="none" stroke="{_amber(night)}" '
                f'stroke-width="1" opacity="0.28"></circle>')
    svg += '</svg>'
    return svg


def _soften(series: list, k: int) -> list:
    """Light centered moving average (±k points). The window shrinks toward the
    ends, so the first and last points are left exactly as they are — the line
    still ends on the true current percentage."""
    if k <= 0:
        return series
    n = len(series)
    out = []
    for i in range(n):
        r = min(k, i, n - 1 - i)
        window = series[i - r:i + r + 1]
        out.append(sum(window) / len(window))
    return out


def _smooth_path(pts: list) -> str:
    """SVG path through the points using monotone cubic interpolation
    (Fritsch–Carlson): rounded corners, but no overshoot past the real values."""
    n = len(pts)
    if n < 3:
        return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    d = [(ys[i + 1] - ys[i]) / ((xs[i + 1] - xs[i]) or 1e-9) for i in range(n - 1)]
    m = [d[0]] + [
        0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, n - 1)
    ] + [d[-1]]
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / math.sqrt(s)
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    out = f"M{xs[0]:.2f},{ys[0]:.2f}"
    for i in range(n - 1):
        dx = (xs[i + 1] - xs[i]) / 3
        out += (
            f" C{xs[i] + dx:.2f},{ys[i] + m[i] * dx:.2f}"
            f" {xs[i + 1] - dx:.2f},{ys[i + 1] - m[i + 1] * dx:.2f}"
            f" {xs[i + 1]:.2f},{ys[i + 1]:.2f}"
        )
    return out


def _remove_marker() -> None:
    """Remove the marker from whatever page the reviewer web is showing."""
    try:
        if mw.reviewer is not None and mw.reviewer.web is not None:
            mw.reviewer.web.eval(
                "(function(){var e=document.getElementById('ret-marker');"
                "if(e)e.remove();})();"
            )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# Time left comes from the Interactive Heatmap (Settings → Time Left), which
# fits the model, runs the daily accuracy check and corrects the estimate.
# ──────────────────────────────────────────────────────────────
def _time_api():
    """Time Left, when it's switched on (Settings → Time Left), else None."""
    return time_left if time_left.enabled() else None


def _reviewer_estimate(did: int) -> dict | None:
    api = _time_api()
    if api is None:
        return None
    try:
        # The reviewer's own queue counts (what the top bar shows) — no extra
        # scheduler work, and the card on screen still counts as left.
        counts = mw.reviewer._v3.counts()[1]
    except Exception:
        try:
            counts = mw.col.sched.counts()
        except Exception:
            return None
    return api.estimate(did, counts)


def _fmt_dur(sec: float) -> str:
    m = int(round(sec / 60))
    if m < 1:
        return "&lt;1m"
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}m"


def _fmt_clock(dt: datetime.datetime) -> str:
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


# ──────────────────────────────────────────────────────────────
# Reviewer marker
# ──────────────────────────────────────────────────────────────
def _update_marker() -> None:
    if not enabled() or mw.state != "review" or mw.reviewer is None or mw.reviewer.web is None:
        return
    # No current card means reviews are finished (Anki is about to move to the
    # deck overview) — the number can't change, so take the marker away rather
    # than letting an async re-inject land on the overview page.
    if getattr(mw.reviewer, "card", None) is None:
        _remove_marker()
        return
    payload = _build_payload()
    if payload is None:
        _remove_marker()
        return
    cfg = _cfg()
    # `corner` is the DEFAULT spot; a dragged position (saved in the webview's
    # localStorage) overrides it and persists across cards/restarts.
    payload["corner"] = _POSITIONS.get(cfg["position"], _POSITIONS["top-right"])
    payload["draggable"] = bool(cfg.get("draggable", True))
    mw.reviewer.web.eval(_MARKER_JS + "\nwindow.RTMarker.update(" + json.dumps(payload) + ");")


# ──────────────────────────────────────────────────────────────
# Hooks
# ──────────────────────────────────────────────────────────────
def _on_answer(reviewer, card, ease: int) -> None:
    # Defer until after Anki has advanced to the next card (or moved to the
    # overview when finished). _update_marker then either refreshes the number
    # for the next card or removes the marker if there's no card left.
    QTimer.singleShot(0, _update_marker)


def _on_show_question(card) -> None:
    # Webview reloads each card, wiping the marker div — re-inject.
    _update_marker()


# ──────────────────────────────────────────────────────────────
# Settings preview
# ──────────────────────────────────────────────────────────────
def _sample_eases() -> list:
    """A session at about 91% that dips mid-way and recovers."""
    out = []
    for i in range(90):
        miss = (i % 17 == 8) or (40 <= i <= 48 and i % 3 == 0)
        out.append(1 if miss else 3)
    return out


def _sample_pomo() -> dict:
    """Block 2 of 4 with 18:42 left, counting down."""
    left = 18 * 60 + 42
    return {"phase": "focus", "block": 2, "of": 4, "total": 25 * 60, "left": left, "running": True,
            "end_ms": int((time.time() + left) * 1000)}


def _sample_lock() -> dict:
    """A focus score of 86% over 96 answers, with a typical day of 81%."""
    import math
    xs = sorted(1.15 * math.sin(2.39996 * i) * (0.4 + i / 96) for i in range(96))
    xs = [x + (1.6 if i > 88 else 0) for i, x in enumerate(xs)]
    return {"score": 0.86, "n": 96, "box": (-1.25, -0.5, 0.05, 0.62, 2.1), "points": xs,
            "lookups": 2, "away": 1, "typical": {"score": 0.81, "box": (-1.3, -0.55, 0.0, 0.72, 2.6)},
            "range": (0.72, 0.89)}


def preview_payload(overrides: dict, night: bool, show_left: bool) -> dict | None:
    """The pill and its hover panel drawn from sample numbers, with the Settings window's
    current choices (overrides: _cfg keys) — for the preview on the Review Pill page."""
    g = globals()
    est = {"all": {"n": 140, "mean": 3720, "lo": 3100, "hi": 4400},
           "reviews": {"n": 120, "mean": 2900, "lo": 2400, "hi": 3500},
           "new": {"n": 20, "mean": 820, "lo": 600, "hi": 1100},
           "done": 1500, "reviews_first": True, "counts": (20, 4, 120)}
    cfg = dict(_cfg(), **overrides)     # read before the swap below replaces _cfg
    swap = {
        "_cfg": lambda: dict(cfg),
        "_is_night": lambda: night,
        "_current_deck_id": lambda: 0,
        "_session_eases": lambda did: _sample_eases(),
        "_deck_stats": lambda did: (1180, 132),
        "_reviewer_estimate": lambda did: est,
        "_focus": lambda: None,
        "_lock_in": _sample_lock,
        "_ring": lambda cfg: None,
        "_show_left": lambda: show_left,
        "_pomo_state": lambda: _sample_pomo() if cfg.get("pomo") else None,
    }
    saved = {k: g[k] for k in swap}
    g.update(swap)
    try:
        return _build_payload()
    finally:
        g.update(saved)


def preview_page(payload: dict | None, corner: str, night: bool) -> str:
    """A small review screen with the pill on it, its panel held open."""
    bg, fg = ("#2f2f31", "#d8d8d8") if night else ("#ffffff", "#333333")
    if payload is None:
        body = f'<div class="empty">Switch on Retention or When you\'ll finish to see the pill.</div>'
        script = ""
    else:
        payload = dict(payload, corner=_POSITIONS.get(corner, _POSITIONS["top-right"]), draggable=False)
        script = (f"<script>{_MARKER_JS}\nwindow.RTMarker.update(window.__hmLastPayload = {json.dumps(payload)});\n"
                  # hold the hover panel open for the preview
                  "(function(){var h=document.querySelector('ret-marker');if(!h||!h.shadowRoot)return;"
                  "var s=document.createElement('style');s.textContent='.panel{opacity:1!important;"
                  "visibility:visible!important;transform:none!important}';h.shadowRoot.appendChild(s);})();"
                  "</script>")
        # the card's text on the side away from the pill's panel
        side = "right:24px;text-align:right" if "left" in corner else "left:24px;text-align:left"
        body = f'<div class="card" style="{side}">Which heart valve<br>closes at S1?</div>'
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"html,body{{margin:0;height:100%;background:{bg};color:{fg};overflow:hidden;"
            f"font-family:-apple-system,'Segoe UI',Roboto,sans-serif}}"
            f".card{{position:absolute;top:50%;transform:translateY(-50%);max-width:45%;"
            f"font-size:20px;line-height:1.35;opacity:.85}}"
            f".empty{{padding:40px;text-align:center;opacity:.6;font-size:13px}}"
            f"</style></head><body class='{'nightMode' if night else ''}'>{body}{script}</body></html>")


def preview_ring_js(kind: str, style: str, n: int) -> str:
    """Replays the after-answer ring on the preview page."""
    return (f"window.RTMarker && window.RTMarker.update(Object.assign({{}}, window.__hmLastPayload || {{}}, "
            f"{{ring: {json.dumps({'id': n, 'kind': kind, 'style': style})}}}));")
