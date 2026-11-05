"""
Low-power mode (Settings → Heatmap): for slow computers, no blur and no motion.

Blur (the frosted glass) has to be worked out again every time anything under or
on it changes, which weak graphics chips, and computers where Anki draws its pages
without the graphics chip, struggle with. Everything else looks the same: blur over
a plain background barely shows, over a background photo the photo is just sharper.
"""

from __future__ import annotations

_get_config = None

# The pages' own blur, wherever it's set: no frosted glass, same colors.
CSS = "*,*::before,*::after{-webkit-backdrop-filter:none!important;backdrop-filter:none!important}"


def setup(get_config) -> None:
    global _get_config
    _get_config = get_config


def on(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            cfg = _get_config() or {}
        except Exception:
            return False
    return bool(cfg.get("low_power", False))


def motion(cfg: dict) -> str:
    """The Animations setting ("system" / "on" / "off"), "off" in low-power mode."""
    return "off" if on(cfg) else cfg.get("animations", "system")


def style(cfg: dict | None = None) -> str:
    """A <style> that takes the blur away, or "" when low-power mode is off."""
    return f"<style>{CSS}</style>" if on(cfg) else ""


def into(html: str) -> str:
    """A whole page with the blur taken away (in low-power mode)."""
    s = style()
    if not s:
        return html
    i = html.find("</head>")
    return html[:i] + s + html[i:] if i >= 0 else s + html
