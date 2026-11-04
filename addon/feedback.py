"""
Feedback — Settings → Feedback sends a message to the add-on's feedback Worker
(heatmap-feedback/ next to the add-on's source; a free Cloudflare Worker + D1).

What's sent: the message, its kind (bug / idea / other), an email only if one is typed,
a random id made once per install (so the Worker can rate-limit; no name or account),
and, if the box is ticked, version info: the add-on, Anki, OS and Qt versions, which of
the add-on's features are on, and the other add-ons installed (name, on or off), since
conflicts with them cause many bugs. Never cards, decks or review history.
"""

from __future__ import annotations

import json
import os
import platform
import urllib.error
import urllib.request
import uuid

from aqt import mw

URL = "https://heatmap-feedback.crowdstats-worker.workers.dev/feedback"
TIMEOUT = 15

_id_path = os.path.join(os.path.dirname(__file__), "user_files", "feedback_id")


def install_id() -> str:
    try:
        with open(_id_path, encoding="utf-8") as f:
            v = f.read().strip()
        uuid.UUID(v)
        return v
    except Exception:
        v = str(uuid.uuid4())
        try:
            os.makedirs(os.path.dirname(_id_path), exist_ok=True)
            with open(_id_path, "w", encoding="utf-8") as f:
                f.write(v)
        except OSError:
            pass
        return v


def other_addons() -> list[str]:
    """Installed add-ons other than this one: "Name", or "Name (off)" when disabled."""
    out = []
    try:
        mine = mw.addonManager.addonFromModule(__name__)
        for meta in mw.addonManager.all_addon_meta():
            if meta.dir_name == mine:
                continue
            name = (meta.human_name() or meta.dir_name).strip()[:60]
            out.append(name if meta.enabled else f"{name} (off)")
    except Exception:
        pass
    return sorted(out, key=str.lower)[:80]


def diagnostics(cfg: dict, version: str) -> dict:
    try:
        from anki.buildinfo import version as anki_version
    except Exception:
        anki_version = "?"
    try:
        from aqt.qt import QT_VERSION_STR
    except Exception:
        QT_VERSION_STR = "?"
    try:
        from aqt.theme import theme_manager
        night = bool(theme_manager.night_mode)
    except Exception:
        night = None
    system = platform.system()
    release = platform.mac_ver()[0] if system == "Darwin" else platform.release()
    system = {"Darwin": "macOS"}.get(system, system)
    return {
        "addon": version,
        "anki": anki_version,
        "os": f"{system} {release}".strip(),
        "qt": QT_VERSION_STR,
        "python": platform.python_version(),
        "dark_mode": night,
        "theme": cfg.get("heatmap_theme", "custom"),
        "features": {
            "time_left": bool(cfg.get("time_estimate_enabled")),
            "review_pill": bool(cfg.get("review_pill_enabled")),
            "background": bool(cfg.get("background_enabled")),
            "browser_theme": bool(cfg.get("enable_browser_theme", True)),
            "fsrs_forecast": bool(cfg.get("fsrs_simulation_enabled")),
            "modern_deck_list": bool(cfg.get("modern_deck_theme", True)),
        },
        "other_addons": other_addons(),
    }


def _post(payload: dict) -> tuple[bool, str]:
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"InteractiveHeatmap/{payload.get('version', '')}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status == 200, ""
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            msg = ""
        return False, msg or f"The server said {e.code}."
    except Exception:
        return False, "Couldn't reach the server. Check your connection and try again."


def send(kind: str, message: str, contact: str, diag: dict | None, version: str, on_done) -> None:
    """Send in the background; on_done(ok, error_text) runs on the main thread."""
    payload = {"install": install_id(), "kind": kind, "message": message, "contact": contact,
               "version": version}
    if diag:
        payload["diag"] = diag

    def done(fut):
        try:
            ok, err = fut.result()
        except Exception:
            ok, err = False, "Couldn't send. Please try again."
        on_done(ok, err)

    mw.taskman.run_in_background(lambda: _post(payload), done)
