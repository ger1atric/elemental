"""
Time left — how long today's remaining cards will take, learned from your own
review history (estimator.py), with a daily accuracy check that also corrects it
(accuracy.py).

Shown, when switched on in Settings → Time Left & Focus:
  • a Time column in the deck list,
  • today's total as a pill under the decks (above the heatmap without the modern deck theme),
  • a line on the deck overview,
  • Tools → Time Estimate Accuracy.

Other add-ons (the Retention Tracker's review-screen pill) read it through the
small API at the bottom: enabled(), estimate(), focus(), drifting(), lock_in(),
lock_days(), last_answer(), listeners.

Everything reads the collection through its own read-only sqlite connection
(through col.db on Windows, SELECTs only, which keep Undo; see estimator.connect),
and the model fit and the accuracy check run off the main thread. Off by default.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import time

from urllib.parse import quote

from aqt import gui_hooks, mw
from aqt.qt import QAction, QDialog, QTimer, QUrl, QVBoxLayout, qconnect

try:
    # Anki's own web view: the page is served by Anki's local media server, so it
    # has no size limit and isn't blocked like a bare QWebEngineView.setHtml page.
    from aqt.webview import AnkiWebView
except ImportError:     # very old Anki
    AnkiWebView = None
    from aqt.qt import QWebEngineView

from . import accuracy, estimator, focus_log

TIME_LEFT_API = 1

_get_config = _write_config = None
_addon_name = ""
_dir = os.path.dirname(__file__)

DEFAULTS = {
    "time_estimate_enabled": False,
    "time_deck_column": True,
    "time_today_pill": True,
    "time_overview": True,
    "time_desk_time": True,
    "time_show_as": "finish",      # finish (clock time) | left (hours and minutes)
    "focus_away_is_lookup": False,  # focus score: leaving Anki during a card = a lookup
    "focus_reading_counts": False,  # focus score: judge a card by its question side if you stayed
}


def setup(get_config, write_config, addon_name: str) -> None:
    """Called once by the heatmap with its config helpers."""
    global _get_config, _write_config, _addon_name
    _get_config, _write_config, _addon_name = get_config, write_config, addon_name
    focus_log.setup(enabled, lookup_key)    # first, so its file is open before the model fit reads it
    estimator.use_anki_when_locked(lambda: mw.col.db if mw.col is not None else None)
    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.profile_will_close.append(_on_profile_close)
    _add_menu()


def _conf() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(_get_config() or {})
    except Exception:
        pass
    return cfg


def lookup_key() -> str:
    """The review-screen key that leaves a card out of the focus score. "F", the first
    default, is Anki's own Create Filtered Deck key, so it never fired: use X instead."""
    key = str(_conf().get("focus_lookup_key", "x") or "")
    return "x" if key.lower() == "f" else key


def enabled() -> bool:
    return bool(_conf().get("time_estimate_enabled"))


def _desk() -> bool:
    return bool(_conf().get("time_desk_time", True))


def _migrate() -> None:
    """First run: if the Retention Tracker was already showing time left, carry its
    choices over so nothing disappears; everyone else starts with it off."""
    try:
        stored = mw.addonManager.getConfig(_addon_name) or {}
    except Exception:
        return
    # Done before, or already on. (A stored False proves nothing: the heatmap writes all
    # its defaults when Settings are saved or it updates.)
    if stored.get("time_left_migrated") or stored.get("time_estimate_enabled"):
        return
    rt = None
    for name in ("retention_tracker",):
        try:
            rt = mw.addonManager.getConfig(name)
        except Exception:
            rt = None
    cfg = _get_config()
    cfg["time_left_migrated"] = True
    if rt and (rt.get("deck_list_time", True) or rt.get("show_time_left", True)):
        cfg.update({"time_estimate_enabled": True,
                    "time_deck_column": bool(rt.get("deck_list_time", True)),
                    "time_today_pill": bool(rt.get("deck_list_time", True)),
                    "time_overview": bool(rt.get("overview_time", True)),
                    "time_desk_time": bool(rt.get("desk_time", True))})
    else:
        cfg["time_estimate_enabled"] = False
    _write_config(cfg)


def _is_night() -> bool:
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return False


def _new_color() -> str:
    """The heatmap's "new" pill color, so the time pills match the count pills."""
    c = _conf().get("pill_new_color")
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#4a90e2"


def _glass_opacity() -> float:
    try:
        return float(_conf().get("glass_opacity", 0.45))
    except (TypeError, ValueError):
        return 0.45


def _current_deck_id() -> int:
    try:
        return int(mw.col.decks.get_current_id())
    except Exception:
        return 0


# ──────────────────────────────────────────────────────────────
# The model (fit once per Anki day, off the main thread)
# ──────────────────────────────────────────────────────────────
_model = None       # estimator.Model for the open profile
_fitting = False
_after_fit = None   # a redraw that waited for this fit (the heatmap's, at startup)
deck_refresh = None  # set by the heatmap: redraws the deck list, joining its own pending redraw
listeners = []      # called with no arguments whenever a new day's model lands


def _background(task, done) -> None:
    """Run off the main thread WITHOUT queuing behind (or blocking) Anki's own
    collection work. Our tasks read the collection through their own read-only
    connection, so they don't need — and mustn't hold — Anki's collection queue:
    anything holding it makes answering a card wait, which looks like a freeze.
    (On Windows they read through col.db instead, statement by statement; see
    estimator.connect.)"""
    try:
        mw.taskman.run_in_background(task, done, uses_collection=False)
    except TypeError:       # Anki before 2.1.45 has one queue
        mw.taskman.run_in_background(task, done)


def _get_model():
    """The current day's model; kicks off a background fit when it's missing or stale
    (returns the stale one meanwhile, or None before the first fit lands)."""
    global _fitting
    if mw.col is None or not enabled():
        return None
    try:
        cutoff = int(mw.col.sched.day_cutoff)
    except Exception:
        return _model
    if (_model is None or _model.cutoff != cutoff) and not _fitting:
        _fitting = True
        path = mw.col.path

        def done(fut) -> None:
            global _model, _fitting, _after_fit
            _fitting = False
            after, _after_fit = _after_fit, None
            try:
                m = fut.result()
            except Exception:
                if after:
                    after()
                return
            if mw.col is None or mw.col.path != path:
                return
            _model = m
            _refresh_views()
            # A new Anki day: redo the accuracy check once things have settled.
            QTimer.singleShot(90_000, _run_accuracy)

        log_path, away, reading = focus_log.path(), _away_is_lookup(), _reading_counts()
        _background(lambda: estimator.fit(path, cutoff, log_path, away, reading), done)
    return _model


def fitting() -> bool:
    return _fitting


def after_fit(fn) -> None:
    """Run fn after the fit in progress (it redraws the screen anyway when it works)."""
    global _after_fit
    _after_fit = fn


def _refresh_views() -> None:
    try:
        if mw.state == "deckBrowser":
            (deck_refresh or mw.deckBrowser.refresh)()
        elif mw.state == "overview":
            mw.overview.refresh()
    except Exception:
        pass
    for fn in list(listeners):
        try:
            fn()
        except Exception:
            pass


def _top_name(did: int) -> str:
    try:
        return str(mw.col.decks.name(did)).split("::")[0]
    except Exception:
        return ""


def _tree_totals(m, tree, costs, ds, visit=None) -> tuple:
    """(reviews+learning, new) Costs for a deck tree, by the scheduler's counts;
    visit(node, work, new) sees every deck's subtree."""
    total_work, total_new = estimator.Cost(), estimator.Cost()

    def walk(node, top):
        rev, lrn = estimator.Cost(), estimator.Cost()
        own = costs.get(node.deck_id)
        if own:
            rev.add(own[0])
            lrn.add(own[1])
        for child in node.children:
            r, l = walk(child, top)
            rev.add(r)
            lrn.add(l)
        work = estimator.Cost().add(lrn)
        if rev.n:
            # Daily limits can hold back some due reviews; cost the ones you'll see.
            work.add(rev, min(1.0, node.review_count / rev.n))
            work.n += node.review_count - rev.n
        new = estimator.new_cost(m, top, node.new_count, ds)
        if visit:
            visit(node, work, new)
        if node.level == 1:
            total_work.add(work)
            total_new.add(new)
        return rev, lrn

    for child in tree.children:
        walk(child, child.name.split("::")[0])
    return total_work, total_new


_left = None    # (cutoff, when, predicted seconds left in the whole collection)


def _progress(m, conn, cutoff: int, today: int, ds, factor: float, totals=None) -> tuple:
    """(share of today's time already done, predicted seconds left in every deck) —
    what the accuracy correction is keyed on. The collection-wide time left is
    refreshed at most once a minute."""
    global _left
    if totals is not None:
        _left = (cutoff, time.time(), (totals[0].total() + totals[1].total()) * factor)
    own = conn is None
    if own:
        conn = estimator.connect(mw.col.path)
    try:
        if _left is None or _left[0] != cutoff or time.time() - _left[1] > 60:
            costs = estimator.card_costs(m, conn, today, cutoff, time.time(), ds)
            w, n = _tree_totals(m, mw.col.sched.deck_due_tree(), costs, ds)
            _left = (cutoff, time.time(), (w.total() + n.total()) * factor)
        done = estimator.done_today(conn, cutoff) * factor
    finally:
        if own:
            conn.close()
    share = done / (done + _left[2]) if done + _left[2] > 0 else 0.0
    return share, _left[2]


def _calibration() -> list:
    """The latest accuracy check's correction table, if it was made by this model
    code for this collection and desk-time setting (yesterday's is fine); [] otherwise."""
    acc = _acc_load()
    try:
        path, _cutoff, desk, version = str(acc.get("key", "")).rsplit("|", 3)
    except ValueError:
        return []
    if mw.col is None or path != mw.col.path or version != _ACC_VERSION or desk != str(int(_desk())):
        return []
    return (acc.get("result") or {}).get("calib") or []


def _reviews_first(did: int) -> bool:
    """Whether the deck's preset shows reviews before new cards (Display order →
    New/review order = "Show after reviews"); otherwise they finish together."""
    try:
        return int(mw.col.decks.config_dict_for_deck_id(did).get("newMix", 0)) == 1
    except Exception:
        return False


def estimate(did: int, counts, with_recent: bool = False) -> dict | None:
    """Time left in this deck + subdecks for the scheduler's (new, learn, review)
    counts: {"reviews", "new", "all"} each {mean, lo, hi, n} in seconds (lo–hi = 80%
    range), plus "counts", "reviews_first", "done" (seconds already spent in these
    decks today, counted like the estimate), and with_recent "recent" — the time
    left at your last ~50 cards' pace. None when switched off or not ready yet."""
    m = _get_model()
    if m is None or not m.table1:
        return None
    try:
        dids = [did] + [child_id for _, child_id in mw.col.decks.children(did)]
        cutoff, today = int(mw.col.sched.day_cutoff), int(mw.col.sched.today)
        factor = m.wall if _desk() else 1.0
        conn = estimator.connect(mw.col.path)
        try:
            ds, recent = estimator.paces(m, conn, cutoff)
            args = (m, conn, today, cutoff, time.time(), dids, tuple(counts), _top_name(did))
            est = estimator.deck_estimate(*args, ds, factor)
            est["recent"] = None
            if with_recent and recent is not None:
                r = estimator.deck_estimate(*args, [recent] * estimator.DAY_NODES, factor)
                est["recent"] = {"reviews": r["reviews"]["mean"], "all": r["all"]["mean"]}
            table = _calibration()
            if table:
                p, left = _progress(m, conn, cutoff, today, ds, factor)
                c = estimator.correction_at(table, p, left)[0]
                for k in ("reviews", "new", "all"):
                    est[k] = estimator.corrected(est[k], p, left, table)
                if est["recent"]:
                    est["recent"] = {k: v * c for k, v in est["recent"].items()}
            est["done"] = estimator.done_today(conn, cutoff, dids) * factor
            est["reviews_first"] = _reviews_first(did)
            est["counts"] = tuple(counts)
            return est
        finally:
            conn.close()
    except Exception:
        return None


def focus() -> tuple | None:
    """(stalled cards, answers) in the current session's recent window; see
    estimator.focus. None when switched off or not ready yet."""
    m = _get_model()
    if m is None or not m.mu or mw.col is None:
        return None
    try:
        conn = estimator.connect(mw.col.path)
        try:
            return estimator.focus(m, conn, int(mw.col.sched.day_cutoff))
        finally:
            conn.close()
    except Exception:
        return None


def drifting(f: tuple) -> bool:
    return estimator.drifting(f)


def _away_is_lookup() -> bool:
    return bool(_conf().get("focus_away_is_lookup", False))


def _reading_counts() -> bool:
    return bool(_conf().get("focus_reading_counts", False))


def refit() -> None:
    """Drop the day's model so the next use fits it again (a setting it uses changed)."""
    global _model
    if not _fitting:
        _model = None


def lock_in() -> dict | None:
    """Today's focus-score numbers (estimator.lock_stats) plus 'typical' (a recent day,
    same keys) and 'range' (your 10th/90th percentile day). None when off, not ready,
    or fewer than estimator.LOCK_MIN answers today."""
    m = _get_model()
    if m is None or not m.mu or m.lock_typical is None or mw.col is None:
        return None
    try:
        conn = estimator.connect(mw.col.path)
        try:
            today = estimator.lock_in(m, conn, int(mw.col.sched.day_cutoff), focus_log.today_index(),
                                      _away_is_lookup(), _reading_counts())
        finally:
            conn.close()
    except Exception:
        return None
    if today is None or today["n"] < estimator.LOCK_MIN:
        return None
    return dict(today, typical=m.lock_typical, range=m.lock_range)


def block_focus(since_ms: int, until_ms: int) -> float | None:
    """The focus score (0..1) of the answers given between since_ms and until_ms (a
    pomodoro block), or None when off, not ready, or too few answers to say."""
    m = _get_model()
    if m is None or not m.mu or mw.col is None:
        return None
    try:
        conn = estimator.connect(mw.col.path)
        try:
            rows = estimator.today_focus(m, conn, int(mw.col.sched.day_cutoff), focus_log.today_index(),
                                         _away_is_lookup(), _reading_counts())
        finally:
            conn.close()
    except Exception:
        return None
    xs = [x for rid, x, _row in rows if since_ms <= rid <= until_ms and x is not None]
    st = estimator.lock_stats(xs) if len(xs) >= 8 else None
    return st["score"] if st else None


def last_answer():
    """(revlog id, 'focus' | 'slow' | 'lookup') for today's latest answer; None when off
    or not ready. See estimator.last_answer."""
    m = _get_model()
    if m is None or not m.mu or mw.col is None:
        return None
    try:
        conn = estimator.connect(mw.col.path)
        try:
            return estimator.last_answer(m, conn, int(mw.col.sched.day_cutoff), focus_log.today_index(),
                                         _away_is_lookup(), _reading_counts())
        finally:
            conn.close()
    except Exception:
        return None


def lock_days() -> tuple | None:
    """({'YYYY-MM-DD': (score, answers)} for past days and today, (lo, hi) range) for
    the heatmap's FOCUS view; None when off or not ready."""
    m = _get_model()
    if m is None or not m.mu or not m.lock_days or mw.col is None:
        return None
    first = datetime.date.fromtimestamp(m.cutoff - 86400)      # day -1 = today
    days = {(first + datetime.timedelta(days=d + 1)).isoformat(): v for d, v in m.lock_days.items()}
    today = lock_in()
    if today is not None:
        days[first.isoformat()] = (today["score"], today["n"])
    return days, m.lock_range


def _fmt_dur(sec: float) -> str:
    m = int(round(sec / 60))
    if m < 1:
        return "&lt;1m"
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}m"


def _fmt_clock(sec_from_now: float) -> str:
    t = datetime.datetime.now() + datetime.timedelta(seconds=sec_from_now)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def show_left() -> bool:
    """Show today's time as hours and minutes left rather than a finish clock."""
    return _conf().get("time_show_as") == "left"


def _fmt_range(s: dict) -> str:
    lo, hi = _fmt_dur(s["lo"]), _fmt_dur(s["hi"])
    if lo.endswith("m") and hi.endswith("m") and "h" not in lo + hi:
        return f"{lo[:-1]}&ndash;{hi}"
    return f"{lo}&ndash;{hi}"


# ──────────────────────────────────────────────────────────────
# Deck list: a Time column, and today's total under the decks
# ──────────────────────────────────────────────────────────────
# A glass capsule in the same family as the count pills (12px/600, 12px radius,
# color at 20%/50% alpha): reviews in neutral glass, the new-card time as a
# segment tinted with the "new" color.
_PILL_CSS = """<style>
.rt-time { text-align: center; white-space: nowrap; }
.rt-pill { display: inline-flex; align-items: stretch; box-sizing: border-box; height: 22px;
  border-radius: 12px; overflow: hidden; vertical-align: middle; white-space: nowrap;
  font-size: 12px; font-weight: 600; line-height: 20px; font-variant-numeric: tabular-nums;
  background: linear-gradient(135deg, rgba(255,255,255,.62), rgba(255,255,255,.34));
  border: 1px solid rgba(0,0,0,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.7), 0 1px 3px rgba(0,0,0,.06);
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px); }
.night_mode .rt-pill, .nightMode .rt-pill, .night-mode .rt-pill {
  background: linear-gradient(135deg, rgba(255,255,255,.13), rgba(255,255,255,.05));
  border-color: rgba(255,255,255,.14);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.10), 0 1px 3px rgba(0,0,0,.25); }
.rt-pill > span { padding: 0 9px; }
.rt-pill .rt-new { color: NEW; background: NEW38; }
.rt-pill > span + .rt-new { border-left: 1px solid NEW80; }
.rt-pill.rt-only-new { background: NEW38; border-color: NEW80; box-shadow: none; }
.rt-pill .rt-new:only-child { background: none; }
.rt-pill i { font-style: normal; font-weight: 500; opacity: .55; margin-left: 4px; }
.rt-pill .rt-label { font-size: 9.5px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase;
  opacity: .5; margin: 0 5px 0 0; }
.rt-dim { opacity: .15; font-weight: 400; }
.rt-total { display: flex; justify-content: center; margin: 0 auto 14px; }
.glass-deck-container .rt-total { margin: 12px auto 2px; }
.rt-total .rt-pill, .rt-ov .rt-pill { height: 26px; line-height: 24px; border-radius: 13px; font-size: 12.5px; }
.rt-total .rt-pill > span, .rt-ov .rt-pill > span { padding: 0 11px; }
.rt-ov { display: flex; justify-content: center; margin: .5em 0 .9em; }
.rt-ov-cell .rt-ov { margin: 2px 0 0; }
.rt-ov-cell { padding-top: 0 !important; }
</style>"""


def _pill_css() -> str:
    return _PILL_CSS.replace("NEW", _new_color())


def _time_title(work: dict, new: dict) -> str:
    parts = []
    if work["n"]:
        parts.append(f"Reviews {_fmt_range(work)}")
    if new["n"]:
        parts.append(f"{new['n']} new cards {_fmt_range(new)}")
    return " · ".join(parts).replace("&ndash;", "–").replace("&lt;", "<")


def _time_pill(segments: list, only_new: bool = False) -> str:
    cls = "rt-pill rt-only-new" if only_new else "rt-pill"
    return f'<span class="{cls}">' + "".join(segments) + "</span>"


def _time_cell(work: dict, new: dict) -> str:
    if not work["n"] and not new["n"]:
        return '<td class="rt-time"><span class="rt-dim">&ndash;</span></td>'
    segs = []
    if work["n"]:
        segs.append(f"<span>{_fmt_dur(work['mean'])}</span>")
    if new["n"]:
        segs.append(f'<span class="rt-new">+{_fmt_dur(new["mean"])}</span>')
    pill = _time_pill(segs, only_new=not work["n"])
    return f'<td class="rt-time" title="{_time_title(work, new)}">{pill}</td>'


# The Today pill's time rolls from the old value to the new one when you come back and it
# moved by ROLL_MIN minutes or more since the last deck list you saw. deck_browser notes what
# it shows; finish_roll(), called only for the final deck list (not the dimmed one drawn
# first), commits it and returns the script, so a redraw never replays it.
ROLL_MIN = 5
_last_when = None       # (mode, minutes, text) at the last final deck list
_seen_when = None       # the same for the deck list being drawn
_FINISH_ROLL = """<script>(function(){
  var FROM = %s, TO = %s;
  function wrap() {
    var el = document.querySelector('#rt-today .rt-when');
    if (!el || el.dataset.roll || (window.hmStill && window.hmStill())) return;
    // the window is one line of the pill tall (its line height, not just the text's), so the
    // numbers sit where the text does; once rolled, the plain text goes back
    var h = parseFloat(getComputedStyle(el).lineHeight) || el.offsetHeight;
    if (!h) return;
    el.dataset.roll = '1';
    el.innerHTML = '<span style="display:inline-block;vertical-align:top;overflow:hidden;height:' + h +
      'px;line-height:' + h + 'px"><span style="display:block;text-align:center">' + FROM + '<br>' + TO + '</span></span>';
    var inner = el.firstChild.firstChild;
    function play() {
      var t0 = null;
      function step(now) {
        if (t0 === null) t0 = now;
        var p = Math.min(1, (now - t0) / 550), e = 1 - Math.pow(1 - p, 3);
        inner.style.transform = 'translateY(' + (-h * e) + 'px)';
        if (p < 1) requestAnimationFrame(step);
        else el.innerHTML = TO;
      }
      setTimeout(function () { requestAnimationFrame(step); }, 250);
    }
    // In the reminders carousel it rolls when its side first comes round
    function shown() { var s = el.closest('.hm-car-s'); return !s || s.className === 'hm-car-s'; }
    (window.hmWhenShown || function (f) { f(); })(function () {
      if (shown()) return play();
      var mo = new MutationObserver(function () { if (shown()) { mo.disconnect(); setTimeout(play, 300); } });
      mo.observe(el.closest('.hm-car-s'), { attributes: true, attributeFilter: ['class'] });
    });
  }
  (window.hmAfterGlass = window.hmAfterGlass || []).push(wrap);
})();</script>"""


def finish_roll() -> str:
    """For the final deck list: the script that rolls the Today pill's time, if it moved
    enough since the last one, and remember what this one shows."""
    global _last_when
    last, _last_when = _last_when, _seen_when
    if not (last and _seen_when and last[0] == _seen_when[0] and last[2] != _seen_when[2]
            and abs(last[1] - _seen_when[1]) >= ROLL_MIN):
        return ""
    import html as _h
    return _FINISH_ROLL % (json.dumps(_h.escape(last[2])), json.dumps(_h.escape(_seen_when[2])))


def deck_browser(browser, content, done: bool = False) -> str:
    """Adds the Time column to the deck list (if on) and returns today's total pill
    (with its CSS) for the heatmap to place above itself; "" when off or not ready.
    done: nothing left to study today, after studying some; the pill says so."""
    global _seen_when
    _seen_when = None
    _sync_menu()
    cfg = _conf()
    if not cfg.get("time_estimate_enabled") or not (cfg.get("time_deck_column") or cfg.get("time_today_pill")):
        return ""
    m = _get_model()
    tree = getattr(getattr(browser, "_render_data", None), "tree", None)
    if m is None or not m.table1 or tree is None:
        return ""
    try:
        cutoff, today = int(mw.col.sched.day_cutoff), int(mw.col.sched.today)
        factor = m.wall if _desk() else 1.0
        conn = estimator.connect(mw.col.path)
        try:
            ds = estimator.pace(m, conn, cutoff)
            costs = estimator.card_costs(m, conn, today, cutoff, time.time(), ds)
        finally:
            conn.close()

        raw, shown = {}, (estimator.Cost(), estimator.Cost())

        def visit(node, work, new):
            # A deck is done once its green reviews are; red learning cards alone don't count.
            if not node.review_count:
                work = estimator.Cost()
            raw[node.deck_id] = (work, new)
            if node.level == 1:
                shown[0].add(work)
                shown[1].add(new)

        total_work, total_new = _tree_totals(m, tree, costs, ds, visit)
        table = _calibration()
        p, left = _progress(m, None, cutoff, today, ds, factor, (total_work, total_new))
        fix = lambda c: estimator.corrected(estimator.summarize(c, factor), p, left, table)
        cells = {did: _time_cell(fix(w), fix(n)) for did, (w, n) in raw.items()}
        w, n = fix(shown[0]), fix(shown[1])
    except Exception:
        return ""

    if cfg.get("time_deck_column"):
        html = content.tree.replace(
            "<th class=optscol></th>", "<th class=count>Time</th><th class=optscol></th>", 1)

        def add_cell(mo):
            cell = cells.get(int(mo.group(2)))
            return mo.group(1) + (cell or "<td></td>") + mo.group(3)

        # Each deck row ends with its options cell; the Time cell goes just before it.
        content.tree = re.sub(r"(<tr class='deck[^']*' id='(\d+)'.*?)(<td align=center class=opts>)",
                              add_cell, html, flags=re.S)

    out = _pill_css()
    # Into the deck list's glass box (built by the heatmap's script) when there is one,
    # under the decks; otherwise it stays here, above the heatmap.
    # (run by the heatmap right after it builds that box, so the page first shows it in place;
    # the timer is for a page without the heatmap)
    move = ("<script>(function(){var n=0;function move(){"
            "var p=document.getElementById('rt-today'),b=document.querySelector('.glass-deck-container');"
            "if(!p)return;if(b){if(p.parentNode!==b)b.appendChild(p);return;}if(++n<60)setTimeout(move,50);}"
            "(window.hmAfterGlass=window.hmAfterGlass||[]).push(move);setTimeout(move,0);})();</script>")
    if cfg.get("time_today_pill") and done:
        out += ('<div class="rt-total" id="rt-today" title="Nothing left to study today">'
                f'{_time_pill(["<span><span class=rt-label>Today</span>Done</span>"])}</div>' + move)
    elif cfg.get("time_today_pill") and (w["n"] or n["n"]):
        segs = []
        left = show_left()
        if w["n"]:
            # When today's reviews would be done if you started now, or how long they'd take.
            text = _fmt_dur(w['mean']) if left else _fmt_clock(w['mean'])
            _seen_when = ("left" if left else "finish",
                          w['mean'] / 60 if left else (time.time() + w['mean']) / 60, text)
            text = f'<span class="rt-when">{text}</span>'
            when = f"~{text} left" if left else f"Finish ~{text}"
            segs.append(f'<span><span class="rt-label">Today</span>{when}</span>')
        if n["n"]:
            label = "" if w["n"] else '<span class="rt-label">Today</span>'
            segs.append(f'<span class="rt-new">{label}+{_fmt_dur(n["mean"])} new</span>')
        other = f"finish ~{_fmt_clock(w['mean'])}" if left else f"~{_fmt_dur(w['mean'])} of reviews"
        title = _time_title(w, n) + (f" · {other}" if w["n"] else "")
        out += (f'<div class="rt-total" id="rt-today" title="{title}">'
                f'{_time_pill(segs, only_new=not w["n"])}</div>' + move)
    return out


# ──────────────────────────────────────────────────────────────
# Deck overview: one line under the counts
# ──────────────────────────────────────────────────────────────
def overview(overview_, content) -> None:
    cfg = _conf()
    if not cfg.get("time_estimate_enabled") or not cfg.get("time_overview"):
        return
    try:
        est = estimate(_current_deck_id(), mw.col.sched.counts())
    except Exception:
        est = None
    if not est:
        return
    rv, nw = est["reviews"], est["new"]
    if not est["counts"][2]:
        rv = dict(rv, n=0)      # green reviews done: red learning cards alone don't count
    segs = []
    if rv["n"]:
        segs.append(f'<span>Reviews ~{_fmt_dur(rv["mean"])}</span>')
    if nw["n"]:
        segs.append(f'<span class="rt-new">{nw["n"]} new ~{_fmt_dur(nw["mean"])}</span>')
    if not segs:
        return
    # Spans only: the overview's numeric <b> tags get restyled into count pills.
    # The likely range is in the tooltip.
    pill = (f'<div class="rt-ov" title="{_time_title(rv, nw)}">'
            f'{_time_pill(segs, only_new=not rv["n"])}</div>')
    # Inside the counts + Study Now box, as a last row under both.
    end = "</td></tr></table>"
    table = content.table or ""
    i = table.find(end)
    if i >= 0:
        i += len("</td></tr>")
        content.table = (table[:i] + f'<tr><td colspan=2 align=center class="rt-ov-cell">{pill}</td></tr>'
                         + table[i:] + _pill_css())
    else:
        content.table = table + _pill_css() + pill


# ──────────────────────────────────────────────────────────────
# Accuracy window (Tools menu): a backtest of the estimate on your recent days,
# redone in the background once per Anki day and kept in user_files.
# ──────────────────────────────────────────────────────────────
_ACC_FILE = os.path.join(_dir, "user_files", "time_accuracy.json")
# Results are only reused while the model code is unchanged.
_ACC_VERSION = hashlib.sha1(b"".join(
    open(m.__file__, "rb").read() for m in (estimator, accuracy))).hexdigest()[:10]
_acc = None             # {"key": ..., "result": ...} from the last run
_acc_running = False
_acc_dialog = None
_menu_action = None


def _acc_key() -> str | None:
    try:
        return f"{mw.col.path}|{int(mw.col.sched.day_cutoff)}|{int(_desk())}|{_ACC_VERSION}"
    except Exception:
        return None


def _acc_load() -> dict:
    global _acc
    if _acc is None:
        try:
            with open(_ACC_FILE, encoding="utf-8") as f:
                _acc = json.load(f)
        except Exception:
            _acc = {}
    return _acc


def _run_accuracy() -> None:
    """Start today's check in the background, unless it's done, running, or off.
    It holds while you review, so it never competes with the reviewer."""
    global _acc_running
    if not enabled():
        return
    key = _acc_key()
    if key is None or _acc_running or _acc_load().get("key") == key:
        return
    _acc_running = True
    path, cutoff, desk = mw.col.path, int(mw.col.sched.day_cutoff), _desk()

    def done(fut) -> None:
        global _acc, _acc_running
        _acc_running = False
        try:
            _acc = {"key": key, "result": fut.result()}
        except Exception:
            _acc = {"key": key, "result": None, "error": True}
        else:
            try:
                os.makedirs(os.path.dirname(_ACC_FILE), exist_ok=True)
                with open(_ACC_FILE, "w", encoding="utf-8") as f:
                    json.dump(_acc, f)
            except Exception:
                pass
        _render_accuracy()

    # Days scored by the last run (same model code and desk setting) are reused.
    prev = _acc_load()
    same = str(prev.get("key", "")).rsplit("|", 3)
    mine = key.rsplit("|", 3)
    cache = None
    if len(same) == 4 and same[0] == mine[0] and same[2:] == mine[2:]:
        cache = (prev.get("result") or {}).get("day_cache")
    _background(lambda: accuracy.run(path, cutoff, desk, pause=lambda: mw.state == "review", cache=cache), done)


def _alive(d) -> bool:
    try:
        d.isVisible()
        return True
    except (RuntimeError, AttributeError):     # closed with the window it opened from
        return False


def _render_accuracy() -> None:
    d = _acc_dialog
    if d is None or mw.col is None or not _alive(d):
        return
    acc = _acc_load()
    mine = str(acc.get("key", "")).startswith(f"{mw.col.path}|")
    res = acc.get("result") if mine else None
    if _acc_running:
        status = "updating…" if res else "Working it out — about a minute."
    elif mine and acc.get("error"):
        status = "Couldn't run the check."
    else:
        status = ""
    try:
        html = accuracy.page(res, _is_night(), _new_color(), status, _backdrop(), _glass_opacity())
    except Exception as e:      # show what went wrong rather than a blank window
        import html as _h, traceback
        html = (f"<body style='font:13px -apple-system,sans-serif;padding:20px;color:#999;background:"
                f"{'#1f1f1f' if _is_night() else '#fff'}'>The accuracy page couldn't be drawn: "
                f"{_h.escape(str(e))}<pre style='font-size:11px'>{_h.escape(traceback.format_exc())}</pre></body>")
    from . import lowpower
    html = lowpower.into(html)
    if AnkiWebView is not None:
        d.web.setHtml(html)
    else:
        d.web.setHtml(html, QUrl.fromLocalFile(_dir + os.sep))


def _backdrop() -> dict | None:
    """The photo behind the main screen, so the window sits on the same background:
    the heatmap's own background photo, else the one the Custom Background add-on
    picked for this session. None when there's neither."""
    try:
        from . import background
        own = background.backdrop()
    except Exception:
        own = None
    if own:
        if AnkiWebView is None:
            own["url"] = QUrl.fromLocalFile(own["path"]).toString()
        return own
    for name, mod in list(sys.modules.items()):
        img = getattr(mod, "imgname", None)
        if not (name.endswith(".adjust_css") and img and hasattr(mod, "add_bg_img")):
            continue
        pkg = name.split(".")[0]
        try:
            path = os.path.join(mw.addonManager.addonsFolder(pkg), "user_files", "background", img)
            conf = mw.addonManager.getConfig(pkg) or {}
            opacity = float(conf.get("background opacity main", 1))
        except Exception:
            continue
        if os.path.exists(path):
            # Custom Background exports its user_files, so Anki's media server serves the photo.
            url = (f"/_addons/{quote(pkg)}/user_files/background/{quote(img)}" if AnkiWebView is not None
                   else QUrl.fromLocalFile(path).toString())
            return {"url": url, "opacity": opacity,
                    "size": conf.get("background-size", "cover"),
                    "position": conf.get("background-position", "center")}
    return None


def show_accuracy(parent=None) -> None:
    """Open the accuracy window: its own window over the main one, whoever asks.
    Never open it from inside a modal dialog's exec(): on macOS a web view created
    there ends that dialog's event loop but leaves it registered as modal, and then
    no window in Anki takes clicks. (`parent` is accepted for older callers.)"""
    global _acc_dialog
    if mw.col is None:
        return
    if _acc_dialog is None or not _alive(_acc_dialog):
        _acc_dialog = _new_accuracy_dialog(mw)
    _run_accuracy()
    _render_accuracy()
    _acc_dialog.show()
    _acc_dialog.raise_()
    _acc_dialog.activateWindow()


def _new_accuracy_dialog(parent) -> QDialog:
    d = QDialog(parent)
    d.setWindowTitle("Time Estimate Accuracy")
    # Match the page's base color so there's no white flash while it loads.
    d.setStyleSheet(f"QDialog {{ background: {'#1f1f1f' if _is_night() else '#ffffff'}; }}")
    d.resize(780, 520)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(0, 0, 0, 0)
    d.web = AnkiWebView(d, title="time estimate accuracy") if AnkiWebView else QWebEngineView(d)
    lay.addWidget(d.web)
    return d


def _add_menu() -> None:
    global _menu_action
    try:
        _menu_action = QAction("Time Estimate Accuracy", mw)
        qconnect(_menu_action.triggered, lambda: show_accuracy())
        mw.form.menuTools.addAction(_menu_action)
        _menu_action.setVisible(False)
    except Exception:
        _menu_action = None


def _sync_menu() -> None:
    if _menu_action is not None:
        _menu_action.setVisible(enabled())


def _on_profile_open() -> None:
    _migrate()
    _sync_menu()
    _get_model()


def _on_profile_close() -> None:
    global _model, _acc_dialog, _left, _acc
    _model = _left = _acc = None
    if _acc_dialog is not None and _alive(_acc_dialog):
        _acc_dialog.close()
    _acc_dialog = None


# ──────────────────────────────────────────────────────────────
# Settings preview
# ──────────────────────────────────────────────────────────────
def preview_page(column: bool, today_pill: bool, overview_line: bool, show_left_: bool, night: bool,
                 counts_colors: tuple) -> str:
    """Where Time Left shows up, drawn with sample numbers: the deck list's Time column,
    today's pill under the decks, and the line on a deck's overview."""
    w = {"n": 120, "mean": 2900, "lo": 2400, "hi": 3500}
    n = {"n": 20, "mean": 820, "lo": 600, "hi": 1100}
    bg, fg = ("#252527", "#e2e2e2") if night else ("#f6f6f8", "#222222")
    new_c, learn_c, due_c = counts_colors
    parts = []

    def label(text):
        return f'<div class="lbl">{text}</div>'

    if column:
        rows = [("AnKing Step Deck", 20, 4, 120, w, n), ("Cardio", 6, 1, 38, dict(w, mean=950), dict(n, mean=240)),
                ("Renal", 0, 0, 0, dict(w, n=0), dict(n, n=0))]
        trs = "".join(
            f'<tr><td class="dk">{name}</td><td class="c" style="color:{new_c if a else "inherit"}">'
            f'{a if a else "<span class=rt-dim>0</span>"}</td>'
            f'<td class="c" style="color:{learn_c if b else "inherit"}">{b if b else "<span class=rt-dim>0</span>"}</td>'
            f'<td class="c" style="color:{due_c if c else "inherit"}">{c if c else "<span class=rt-dim>0</span>"}</td>'
            f'{_time_cell(ww, nn)}</tr>'
            for name, a, b, c, ww, nn in rows)
        parts.append(label("Deck list") + '<table class="decks"><tr><th></th><th>New</th><th>Learn</th>'
                     f'<th>Due</th><th>Time</th></tr>{trs}</table>')
    if today_pill:
        when = f"~{_fmt_dur(w['mean'])} left" if show_left_ else f"Finish ~{_fmt_clock(w['mean'])}"
        segs = [f'<span><span class="rt-label">Today</span>{when}</span>',
                f'<span class="rt-new">+{_fmt_dur(n["mean"])} new</span>']
        parts.append(label("Under your decks") + f'<div class="rt-total">{_time_pill(segs)}</div>')
    if overview_line:
        segs = [f'<span>Reviews ~{_fmt_dur(w["mean"])}</span>',
                f'<span class="rt-new">{n["n"]} new ~{_fmt_dur(n["mean"])}</span>']
        parts.append(label("Deck overview") + f'<div class="rt-ov">{_time_pill(segs)}</div>')
    if not parts:
        parts.append('<div class="empty">Pick at least one place to show it.</div>')
    css = (f"html,body{{margin:0;background:{bg};color:{fg};font:13px -apple-system,'Segoe UI',Roboto,sans-serif;"
           "overflow:hidden}"
           ".wrap{padding:12px 18px}.lbl{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
           "opacity:.45;margin:10px 0 6px}.wrap>.lbl:first-child{margin-top:0}"
           ".rt-total,.rt-ov{justify-content:flex-start;margin:0}"
           ".decks{border-collapse:collapse}.decks th{font-size:11px;font-weight:600;opacity:.55;padding:0 10px 4px}"
           ".decks td{padding:4px 10px}.decks td.dk{padding-left:0;min-width:150px}.decks td.c{text-align:center;"
           "font-weight:600}.empty{padding:24px;text-align:center;opacity:.6}")
    return (f"<!doctype html><html><head><meta charset='utf-8'>{_pill_css()}<style>{css}</style></head>"
            f"<body class='{'nightMode' if night else ''}'><div class='wrap'>{''.join(parts)}</div></body></html>")
