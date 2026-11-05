"""
Pomodoro timer, shown in the review pill (Settings → Review Pill → Pomodoro).

The usual cycle: a block of focus time, a short break, and after every 4th block (by
default) a long break, then the next set starts at block 1 again.

A block starts with your first card. When it runs out the break starts by itself, right
then: the pill turns into the break's countdown, with a short summary of the block in its
panel, and the card on screen is yours to finish. When the break ends, the next block
starts by itself if you're on the review screen, or with your next card if you're not.
The deck list shows a break counting down, and an optional system notification says when
it ends if Anki isn't in front.

Clicking the pill pauses and resumes a block, ends a break early, or takes the early
break offered when focus drifts. Stop in the pill's hover panel clears the timer when
you're not doing pomodoros (nothing shows in the pill), and Start there brings it back,
from block 1. A stop lasts until you start again, or the next day.
With "pause when you leave reviews" a block only counts time on the review screen, so a
trip to the deck list or the browser doesn't use it up. Breaks run on the clock.

Phases:
  idle   nothing yet (or after a long gap): the first card starts block 1
  focus  a block is running, or paused (from the pill, or off the review screen)
  brk    on a break
  over   a break ended off the review screen: the next card starts the next block
  off    stopped from the panel: nothing runs until Start (or the next day)

State lives in memory only: restarting Anki starts afresh.
"""

from __future__ import annotations

import subprocess
import sys
import time

from aqt import mw, gui_hooks
from aqt.qt import QApplication, QTimer, Qt

_get_config = None
listeners = []          # called with no arguments when the phase changes (the pill redraws)

DEFAULTS = {
    "pomo_enabled": False,
    "pomo_focus_min": 25,
    "pomo_break_min": 5,
    "pomo_long_min": 15,
    "pomo_long_every": 4,
    "pomo_pause_away": True,
    "pomo_drift_break": False,
    "pomo_notify": True,
}

STALE_PAUSE = 30 * 60   # a block paused this long (not from the pill) starts again in full
STALE_CYCLE = 2 * 3600  # no blocks or breaks for this long: back to block 1

_s = {"phase": "idle", "block": 0, "left": 0.0, "since": None, "start_ms": 0, "end_ms": 0,
      "brk_end": 0.0, "brk_len": 0, "touched": 0.0,
      "held": False,        # paused from the pill: stays paused until clicked again
      "offer": False,       # the pill on screen offers an early break (a click takes it)
      "focused": 0.0,       # seconds of focus in this set's finished blocks
      "day": None}          # the Anki day it was stopped (off)
_brk_timer = _blk_timer = None


def setup(get_config) -> None:
    global _get_config, _brk_timer, _blk_timer
    _get_config = get_config
    _brk_timer = QTimer()
    _brk_timer.setSingleShot(True)
    _brk_timer.timeout.connect(_break_over)
    _blk_timer = QTimer()
    _blk_timer.setSingleShot(True)
    _blk_timer.timeout.connect(_block_up)
    gui_hooks.reviewer_did_show_question.append(_on_question)
    gui_hooks.state_will_change.append(_on_state)     # before the next screen draws, so it shows the break


def cfg() -> dict:
    out = dict(DEFAULTS)
    try:
        out.update({k: v for k, v in (_get_config() or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def enabled() -> bool:
    try:
        c = _get_config() or {}
    except Exception:
        return False
    return bool(c.get("pomo_enabled")) and bool(c.get("review_pill_enabled"))


def _focus_len() -> int:
    return max(1, int(cfg()["pomo_focus_min"])) * 60


def _cycle() -> int:
    return max(1, int(cfg()["pomo_long_every"]))


def _today():
    try:
        return mw.col.sched.today
    except Exception:
        return time.strftime("%Y-%m-%d")


def _running() -> bool:
    return _s["since"] is not None


def focus_left() -> float:
    """Seconds left in the block (focus phase)."""
    if _running():
        return max(0.0, _s["left"] - (time.monotonic() - _s["since"]))
    return max(0.0, _s["left"])


def _pause() -> None:
    if _running():
        _s["left"] = focus_left()
        _s["since"] = None
    if _blk_timer is not None:
        _blk_timer.stop()
    _s["touched"] = time.time()


def _resume() -> None:
    if not _running():
        _s["since"] = time.monotonic()
    if _blk_timer is not None:
        _blk_timer.start(int(focus_left() * 1000) + 50)


def _set(phase: str) -> None:
    _s["phase"] = phase
    _s["touched"] = time.time()
    for fn in listeners:
        try:
            fn()
        except Exception:
            pass


def _start_block() -> None:
    if _s["phase"] == "idle" or time.time() - _s["touched"] > STALE_CYCLE:
        _s["block"], _s["focused"] = 1, 0.0
    else:
        _s["block"] += 1
    _s["left"] = float(_focus_len())
    _s["since"] = None
    _s["start_ms"] = int(time.time() * 1000)
    _s["held"] = False
    _s["phase"] = "focus"
    _resume()
    _s["touched"] = time.time()


def _block_up() -> None:
    """The block's time ran out (its timer, while it was running)."""
    if _s["phase"] == "focus" and _running() and focus_left() <= 0.5:
        start_break()


def start_break() -> None:
    """End the block and start its break: when its time runs out, or early (the pill's
    drift offer)."""
    if _s["phase"] != "focus":
        return
    _pause()
    _s["focused"] += _focus_len() - _s["left"]
    _s["left"] = 0.0
    _s["end_ms"] = int(time.time() * 1000)
    long_ = _s["block"] % _cycle() == 0
    c = cfg()
    mins = max(1, int(c["pomo_long_min"] if long_ else c["pomo_break_min"]))
    _s["brk_len"] = mins * 60
    _s["brk_end"] = time.time() + mins * 60
    if _brk_timer is not None:
        _brk_timer.start(mins * 60 * 1000)
    _set("brk")


def _last_block() -> bool:
    return _s["block"] % _cycle() == 0


def end_break() -> None:
    """Cut the break short (clicking the pill during one)."""
    if _s["phase"] == "brk":
        if _brk_timer is not None:
            _brk_timer.stop()
        _s["brk_end"] = time.time()
        _after_break(notify=False)


def _break_over() -> None:
    if _s["phase"] == "brk":
        _after_break(notify=bool(cfg()["pomo_notify"]) and enabled())


def _after_break(notify: bool) -> None:
    """The next block starts now if you're on the review screen, or with your next card.
    After the long break, that's block 1 of a new set."""
    if _last_block():
        _s["block"], _s["focused"] = 0, 0.0
    if getattr(mw, "state", None) == "review" and not _away():     # there, and Anki in front
        _start_block()
        _set("focus")
        if notify:
            _notify("Break's over", f"Block {_s['block']} of {_cycle()} has started")
    else:
        _set("over")
        if notify:
            _notify("Break's over", f"Block {_s['block'] % _cycle() + 1} of {_cycle()} starts with your next card")


def _away() -> bool:
    try:
        return QApplication.applicationState() != Qt.ApplicationState.ApplicationActive
    except Exception:
        return False


def stop() -> None:
    """Clear the timer (the panel's Stop): nothing runs or shows until start()."""
    for t in (_brk_timer, _blk_timer):
        if t is not None:
            t.stop()
    _s.update(since=None, held=False, offer=False, block=0, focused=0.0, day=_today())
    _set("off")


def start() -> None:
    """Start again from block 1 (the panel's Start): now if you're reviewing, else with
    your next card."""
    if _s["phase"] != "off":
        return
    _s["block"], _s["focused"] = 0, 0.0
    _s["phase"] = "idle"
    if getattr(mw, "state", None) == "review":
        _start_block()
    _set(_s["phase"])


def offering(on: bool) -> None:
    """The pill says whether it's offering an early break, so a click takes the break."""
    _s["offer"] = bool(on)


def click() -> None:
    """The pill was clicked: take the early break it offers, end a break, or pause and
    resume a block."""
    if not enabled():
        return
    ph = _s["phase"]
    if ph == "focus" and _s["offer"] and not _s["held"]:
        start_break()
    elif ph == "brk":
        end_break()
    elif ph == "focus":
        if _s["held"]:
            _s["held"] = False
            _resume()
        else:
            _s["held"] = True
            _pause()
        _set("focus")


def _on_question(card) -> None:
    if not enabled():
        return
    ph = _s["phase"]
    if ph == "off":
        if _s["day"] == _today():
            return                       # stopped: only Start brings it back
        ph = _s["phase"] = "idle"        # a new day: on again
    if ph not in ("brk", "idle") and time.time() - _s["touched"] > STALE_CYCLE:
        ph = _s["phase"] = "idle"        # a long gap: start the set over
    if ph in ("idle", "over"):
        _start_block()
    elif ph == "brk":
        return                           # reviewing on a break: the break keeps running
    elif ph == "focus":
        if _s["held"]:
            return                       # paused from the pill: only a click resumes it
        if not _running() and time.time() - _s["touched"] > STALE_PAUSE:
            _s["left"] = float(_focus_len())
        if focus_left() <= 0:
            _resume()
            start_break()
            return
        _resume()
    _s["touched"] = time.time()


def _on_state(new_state, old_state) -> None:
    if not enabled() or new_state == "review" or old_state != "review":
        return
    if _s["phase"] == "focus" and cfg()["pomo_pause_away"]:
        _pause()


def state() -> dict:
    """The timer's state for the pill and the deck list: phase, block, of (blocks per
    set), total (a block's seconds), and per phase: left / running / held / end_ms (focus;
    end_ms when it's counting down live), brk_end_ms / brk_len / start_ms / end_ms / long
    (break), next (over)."""
    ph = _s["phase"]
    if ph == "off":
        return {"phase": "off" if _s["day"] == _today() else "idle"}
    if ph not in ("idle", "brk") and time.time() - _s["touched"] > STALE_CYCLE:
        return {"phase": "idle"}
    out = {"phase": ph, "block": _s["block"], "of": _cycle(), "total": _focus_len()}
    if ph == "focus":
        left = focus_left()
        out.update(left=left, running=_running(), held=_s["held"])
        if _running():
            out["end_ms"] = int((time.time() + left) * 1000)
    elif ph == "brk":
        out.update(brk_end_ms=int(_s["brk_end"] * 1000), brk_len=_s["brk_len"], start_ms=_s["start_ms"],
                   end_ms=_s["end_ms"], long=_last_block())
    elif ph == "over":
        out["next"] = _s["block"] % _cycle() + 1
    return out


# ──────────────────────────────────────────────────────────────
# System notification (only when Anki isn't the app in front; otherwise a tooltip)
# ──────────────────────────────────────────────────────────────
_tray = None


def _notify(title: str, body: str) -> None:
    if not _away():
        try:
            from aqt.utils import tooltip
            tooltip(f"{title} · {body}", period=4000)
        except Exception:
            pass
        return
    try:
        if sys.platform == "darwin":
            q = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'display notification "{q(body)}" with title "Elemental" '
                                                 f'subtitle "{q(title)}"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        global _tray
        from aqt.qt import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        from . import brand
        if _tray is None:
            _tray = QSystemTrayIcon(brand.icon("", False), mw)
        _tray.show()
        _tray.showMessage(title, body, brand.icon("", False), 6000)
        QTimer.singleShot(12000, _tray.hide)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# Formatting
# ──────────────────────────────────────────────────────────────
def mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_focused(sec: float) -> str:
    m = int(round(sec / 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def clock(epoch: float) -> str:
    import datetime
    t = datetime.datetime.fromtimestamp(epoch)
    return f"{t.hour % 12 or 12}:{t.minute:02d}"
