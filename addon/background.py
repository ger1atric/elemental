"""
Background photo — a photo behind Anki's main screens that changes once a day.

The photos are either one of the built-in ones (builtin_backgrounds/, shipped with the
add-on; credits in CREDITS.txt there) or your own: whatever is in user_files/backgrounds
(that folder survives updates). For your own photos, in "daily" mode the photo changes when Anki's day rolls over (your "next day starts at"
hour), stays the same however often Anki is restarted, and changes even if Anki is left
open overnight: the next screen drawn after the rollover gets the new one. Every photo
is shown once before any is shown again. "launch" changes it each time the profile
opens instead; "fixed" keeps one chosen photo.

The photo is a fixed layer under each page (body::before), faint enough that the text
stays readable: one strength for the deck list, overview and bars, a separate, usually
much lower one for the review screen (and its bars: the top bar switches while you review). One photo a day at one address, so the web view
loads it once and reuses it.

Off by default (background_enabled).
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
import time
from urllib.parse import quote

from aqt import gui_hooks, mw
from aqt.qt import QTimer

PICS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
BUILTIN = {             # file stem: name shown in Settings (the first six go with photo themes)
    "highland_mist": "Highland Mist",
    "forest_trail": "Forest Trail",
    "rolling_hills": "Rolling Hills",
    "starlight": "Starlight",
    "na_pali": "N\u0101 Pali",
    "wanaka_dusk": "W\u0101naka Dusk",
    "dusk": "Dusk",
    "glacier_lagoon": "Glacier Lagoon",
    "black_sand": "Black Sand",
    "coast": "Coast",
    "waterfall": "Waterfall",
    "canyon": "Canyon",
}
DEFAULTS = {
    "background_enabled": False,
    "background_source": "builtin:dusk",   # mine (your folder) | builtin:<stem>
    "background_rotation": "daily",        # daily | launch | fixed
    "background_image": "",                # the photo for "fixed"
    "background_opacity_main": 0.6,        # deck list, overview, top and bottom bars
    "background_opacity_review": 0.1,      # review screen
    "background_in_review": True,
    "background_on_bars": True,            # top toolbar and bottom bar
}

_addon_dir = os.path.dirname(__file__)
_dir = os.path.join(_addon_dir, "user_files")
FOLDER = os.path.join(_dir, "backgrounds")
BUILTIN_DIR = os.path.join(_addon_dir, "builtin_backgrounds")
_STATE = os.path.join(_dir, "background_state.json")

_get_config = None
_pkg = ""
_state = None           # {"current", "seen": [...], "until": day cutoff (s)}
_launch_pending = True  # "launch" mode: pick a new photo at the next profile open


def setup(get_config, module_name: str) -> None:
    global _get_config, _pkg
    _get_config = get_config
    _pkg = mw.addonManager.addonFromModule(module_name)
    os.makedirs(FOLDER, exist_ok=True)
    mw.addonManager.setWebExports(module_name, r"(user_files/backgrounds|builtin_backgrounds)/[^/]+")
    gui_hooks.webview_will_set_content.append(_on_set_content)
    gui_hooks.webview_did_inject_style_into_page.append(_on_ts_page)
    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.state_did_change.append(_on_state_change)


def _cfg() -> dict:
    conf = dict(DEFAULTS)
    try:
        conf.update({k: v for k, v in _get_config().items() if k in DEFAULTS})
    except Exception:
        pass
    return conf


# ──────────────────────────────────────────────────────────────
# Which photo
# ──────────────────────────────────────────────────────────────
def photos() -> list[str]:
    try:
        return sorted(f for f in os.listdir(FOLDER)
                      if f.lower().endswith(PICS) and not f.startswith("."))
    except OSError:
        return []


def _load() -> dict:
    global _state
    if _state is None:
        try:
            with open(_STATE, encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            _state = {}
    return _state


def _save() -> None:
    try:
        tmp = _STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f)
        os.replace(tmp, _STATE)
    except Exception:
        pass


def _next_cutoff() -> float:
    try:
        return float(mw.col.sched.day_cutoff)
    except Exception:
        return time.time() + 3600       # no collection yet: look again in an hour


def _advance(st: dict, files: list[str]) -> None:
    """Move to a photo not yet shown this round; start a new round once all have been."""
    cur = st.get("current")
    seen = [f for f in st.get("seen", []) if f in files]
    left = [f for f in files if f not in seen and f != cur]
    if not left:
        seen = []
        left = [f for f in files if f != cur] or files
    st["current"] = random.choice(left)
    st["seen"] = seen + [st["current"]]


def builtin_file(stem: str) -> str | None:
    path = os.path.join(BUILTIN_DIR, stem + ".webp")
    return path if stem in BUILTIN and os.path.exists(path) else None


def current_path() -> str | None:
    """Path of the photo to show now, relative to the add-on folder (with "/"), or None."""
    conf = _cfg()
    if not conf["background_enabled"]:
        return None
    src = str(conf["background_source"])
    if src.startswith("builtin:"):
        stem = src[len("builtin:"):]
        return f"builtin_backgrounds/{stem}.webp" if builtin_file(stem) else None
    name = current(conf)
    return f"user_files/backgrounds/{name}" if name else None


def current(conf: dict | None = None) -> str | None:
    """Today's photo from your folder (file name), or None when off or the folder is
    empty. Moving on to the next photo happens here, the first time it's asked for after
    it's due."""
    global _launch_pending
    conf = conf or _cfg()
    if not conf["background_enabled"]:
        return None
    files = photos()
    if not files:
        return None
    mode = conf["background_rotation"]
    if mode == "fixed" and conf["background_image"] in files:
        return conf["background_image"]
    st = _load()
    had = st.get("current")
    if mode == "launch":
        due = _launch_pending
    else:
        due = time.time() >= st.get("until", 0)
    if due or had not in files:
        _advance(st, files)
        st["until"] = _next_cutoff()
        _launch_pending = False
        _save()
        if had and had != st["current"]:
            # Changed while Anki is open (the day rolled over): the top bar isn't redrawn
            # with each screen, so redraw it to match.
            QTimer.singleShot(0, _redraw_toolbar)
    return st["current"]


def next_photo() -> str | None:
    """Skip to the next photo now; it stays for the rest of the day."""
    files = photos()
    if not files:
        return None
    st = _load()
    _advance(st, files)
    st["until"] = _next_cutoff()
    _save()
    redraw()
    return st["current"]


def _on_profile_open() -> None:
    global _launch_pending
    _launch_pending = True


# ──────────────────────────────────────────────────────────────
# Drawing it
# ──────────────────────────────────────────────────────────────
def url(rel: str) -> str:
    return f"/_addons/{quote(_pkg)}/{quote(rel)}"


def _css(rel: str, opacity: float, position: str = "center", live: bool = False) -> str:
    # live: the strength can change without a redraw (the top bar, on entering and leaving review)
    op = f"var(--hm-bg-opacity,{float(opacity):.3f});transition:opacity .25s" if live else f"{float(opacity):.3f}"
    return ('body::before{content:"";position:fixed;top:0;left:0;right:0;bottom:0;z-index:-99;'
            f'pointer-events:none;background:url("{url(rel)}") {position}/cover no-repeat;'
            f'opacity:{op}}}')


def _bar_key() -> str:
    """The top bar matches the screen under it: the review strength while you review."""
    conf = _cfg()
    return "background_opacity_review" if conf["background_in_review"] and mw.state == "review" else "background_opacity_main"


def _layer_for(context) -> tuple[str, str] | None:
    """(strength key, position) for the screens that get the photo, else None."""
    from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar
    from aqt.overview import Overview, OverviewBottomBar
    from aqt.reviewer import Reviewer, ReviewerBottomBar
    from aqt.toolbar import TopToolbar
    conf = _cfg()
    if isinstance(context, (DeckBrowser, Overview)):
        return "background_opacity_main", "center"
    if isinstance(context, Reviewer):
        return ("background_opacity_review", "center") if conf["background_in_review"] else None
    if not conf["background_on_bars"]:
        return None
    if isinstance(context, TopToolbar):
        return _bar_key(), "top"
    if isinstance(context, (DeckBrowserBottomBar, OverviewBottomBar)):
        return "background_opacity_main", "bottom"
    if isinstance(context, ReviewerBottomBar):
        key = "background_opacity_review" if conf["background_in_review"] else "background_opacity_main"
        return key, "bottom"
    return None


def _on_set_content(web_content, context) -> None:
    try:
        layer = _layer_for(context)
        if layer is None:
            return
        rel = current_path()
        if rel:
            from aqt.toolbar import TopToolbar
            live = isinstance(context, TopToolbar)
            web_content.head += f"<style id='hm-background'>{_css(rel, _cfg()[layer[0]], layer[1], live)}</style>"
    except Exception:
        pass


def _on_ts_page(web) -> None:
    # The "Congratulations, you've finished" screen is a separate page Anki loads itself.
    try:
        if os.path.basename(web.page().url().path()) not in ("congrats", "congrats.html"):
            return
        rel = current_path()
        if not rel:
            return
        css = _css(rel, _cfg()["background_opacity_main"])
        web.eval("(() => { const s = document.createElement('style'); s.textContent = %s;"
                 " document.head.appendChild(s); })();" % json.dumps(css))
    except Exception:
        pass


def _on_state_change(new_state: str, old_state: str) -> None:
    if "review" not in (new_state, old_state):
        return
    try:
        conf = _cfg()
        if conf["background_enabled"] and conf["background_on_bars"]:
            mw.toolbar.web.eval("document.documentElement.style.setProperty('--hm-bg-opacity', %s)"
                                % json.dumps(f"{float(conf[_bar_key()]):.3f}"))
    except Exception:
        pass


def _redraw_toolbar() -> None:
    try:
        mw.toolbar.draw()
    except Exception:
        pass


def redraw() -> None:
    """Show a changed photo or setting on the screens that are up now."""
    _redraw_toolbar()
    try:
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()
        elif mw.state == "overview":
            mw.overview.refresh()
        else:
            mw.reset()
    except Exception:
        pass


def backdrop() -> dict | None:
    """Today's photo for windows that draw their own page (Time Estimate Accuracy)."""
    rel = current_path()
    if not rel:
        return None
    return {"url": url(rel), "path": os.path.join(_addon_dir, *rel.split("/")),
            "opacity": _cfg()["background_opacity_main"], "size": "cover", "position": "center"}


# ──────────────────────────────────────────────────────────────
# Photos from the Custom Background add-on
# ──────────────────────────────────────────────────────────────
def other_addon() -> dict | None:
    """The Custom Background Image add-on, if installed: {"folder", "photos", "enabled",
    "name"} with the photos this folder doesn't have yet."""
    for name, mod in list(sys.modules.items()):
        if not (name.endswith(".adjust_css") and hasattr(mod, "add_bg_img")):
            continue
        pkg = name.split(".")[0]
        try:
            folder = os.path.join(mw.addonManager.addonsFolder(pkg), "user_files", "background")
            theirs = [f for f in os.listdir(folder) if f.lower().endswith(PICS) and not f.startswith(".")]
            meta = mw.addonManager.addonMeta(pkg) or {}
        except Exception:
            continue
        mine = set(photos())
        return {"folder": folder, "photos": sorted(f for f in theirs if f not in mine),
                "enabled": not meta.get("disabled", False),
                "name": meta.get("name") or "Custom Background Image"}
    return None


def copy_from_other() -> int:
    other = other_addon()
    if not other:
        return 0
    n = 0
    for f in other["photos"]:
        try:
            shutil.copy2(os.path.join(other["folder"], f), os.path.join(FOLDER, f))
            n += 1
        except OSError:
            pass
    return n
