"""
Elemental's logo ("Ring of three"): four heatmap squares inside one ring, with three dots
on the ring. Always in the brand teal, so it looks the same whatever the heatmap's theme.

  svg(...)          the logo as inline SVG, for the web pages (heatmap, stats window)
  SCRIPT            window.hmLogo(svg, loop): the dots spread out from one point (once),
                    or spread and gather again for as long as something is loading
  LogoWidget        the logo as a Qt widget; play() runs the same spread once
  icon(...)         a QIcon of it (menu item, window icons)
  motion_ok(mode)   the add-on's Animations setting (system | on | off) for Qt widgets
"""

from __future__ import annotations

import math
import sys

DOTS = (-90.0, 30.0, 150.0)     # where the three dots rest, in degrees (0 = right, clockwise)
SPREAD_MS = 1300


def _mix(a: str, b: str, t: float) -> str:
    try:
        pa = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        pb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    except (ValueError, AttributeError):
        pa, pb = [142, 68, 173], [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


TEAL = "#0e7d6e"    # the logo is always teal, whatever the heatmap's color


def parts(base: str, night: bool) -> dict:
    """The logo's colors: ring, the four squares, the dots. (base is ignored: always teal.)"""
    base = TEAL
    h1, h2, h3 = _mix(base, "#ffffff", 0.85), _mix(base, "#ffffff", 0.52), _mix(base, "#ffffff", 0.22)
    return {
        "ring": h3, "ring_alpha": 0.6 if night else 0.55,
        "cells": (h2, base, h3, h1 if night else h2),
        "dot": h2 if night else base,
    }


def _geom(size: float) -> tuple:
    """(ring width, dot radius) in the 120-unit box; heavier when the logo is tiny."""
    return (5.0, 10.0) if size < 24 else (3.5, 8.0)


def svg(base: str, night: bool, size: int, cls: str = "", style: str = "") -> str:
    c = parts(base, night)
    ring_w, dot_r = _geom(size)
    cells = "".join(
        f'<rect x="{x}" y="{y}" width="18" height="18" rx="4" fill="{f}"/>'
        for (x, y), f in zip(((40, 40), (62, 40), (40, 62), (62, 62)), c["cells"]))
    dots = "".join(
        f'<circle class="hm-logo-dot" cx="{60 + 44 * math.cos(math.radians(a)):.2f}" '
        f'cy="{60 + 44 * math.sin(math.radians(a)):.2f}" r="{dot_r}" fill="{c["dot"]}"/>' for a in DOTS)
    return (f'<svg class="hm-logo {cls}" viewBox="0 0 120 120" width="{size}" height="{size}" '
            f'style="display:block;flex:none;{style}" aria-hidden="true">'
            f'<circle cx="60" cy="60" r="44" fill="none" stroke="{c["ring"]}" stroke-width="{ring_w}" '
            f'stroke-opacity="{c["ring_alpha"]}"/>{cells}{dots}</svg>')


# The dots start together at the top and spread around the ring, all moving clockwise.
# loop: spread, a short rest, then gather back to the top the same way round, and again.
SCRIPT = """
window.hmLogo = window.hmLogo || function (svg, loop, still) {
    if (!svg) return;
    var dots = svg.querySelectorAll('.hm-logo-dot');
    if (dots.length !== 3 || still) return;
    function put(a) {
        for (var i = 0; i < 3; i++) {
            var r = a[i] * Math.PI / 180;
            dots[i].setAttribute('cx', (60 + 44 * Math.cos(r)).toFixed(2));
            dots[i].setAttribute('cy', (60 + 44 * Math.sin(r)).toFixed(2));
        }
    }
    function out(t) { return 1 - Math.pow(1 - t, 3); }
    function inout(t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
    function spread(e) { return [0, 1, 2].map(function (i) { return -90 - 360 * (1 - e) + 120 * i * e; }); }
    function gather(e) { return [0, 1, 2].map(function (i) { return -90 + 120 * i + (360 - 120 * i) * e; }); }
    var SPREAD = %SPREAD%, REST = 250, GATHER = 700, REST2 = 150, t0 = null;
    put(spread(0));
    function frame(ts) {
        if (!svg.isConnected) return;
        if (t0 === null) t0 = ts;
        var t = ts - t0;
        if (!loop) {
            put(spread(out(Math.min(1, t / SPREAD))));
            if (t < SPREAD) requestAnimationFrame(frame);
            return;
        }
        t = t % (SPREAD + REST + GATHER + REST2);
        if (t < SPREAD) put(spread(out(t / SPREAD)));
        else if (t < SPREAD + REST) put(spread(1));
        else if (t < SPREAD + REST + GATHER) put(gather(inout((t - SPREAD - REST) / GATHER)));
        else put(spread(0));
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
};
""".replace("%SPREAD%", str(SPREAD_MS))


# A third of a turn for the three dots (they end where they started), e.g. on hover.
TURN_SCRIPT = """
window.hmLogoTurn = window.hmLogoTurn || function (svg, still) {
    if (!svg || still || svg._hmTurning) return;
    var dots = svg.querySelectorAll('.hm-logo-dot');
    if (dots.length !== 3) return;
    svg._hmTurning = true;
    var MS = 300, t0 = null;
    function out(t) { return 1 - Math.pow(1 - t, 3); }
    function frame(ts) {
        if (t0 === null) t0 = ts;
        var t = Math.min(1, (ts - t0) / MS), turn = 120 * out(t);
        for (var i = 0; i < 3; i++) {
            var r = (-90 + 120 * i + turn) * Math.PI / 180;
            dots[i].setAttribute('cx', (60 + 44 * Math.cos(r)).toFixed(2));
            dots[i].setAttribute('cy', (60 + 44 * Math.sin(r)).toFixed(2));
        }
        if (t < 1) requestAnimationFrame(frame); else svg._hmTurning = false;
    }
    requestAnimationFrame(frame);
};
"""


def still_js(mode: str) -> str:
    """A JS expression: true when the Animations setting (or the system) says no motion."""
    import json
    return (f"({json.dumps(mode or 'system')} === 'off' || ({json.dumps(mode or 'system')} === 'system' && "
            "!!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches))")


# ---------------------------------------------------------------------------- Qt

_reduce = None


def _system_reduce_motion() -> bool:
    global _reduce
    if _reduce is not None:
        return _reduce
    _reduce = False
    try:
        if sys.platform == "darwin":
            import subprocess
            r = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                               capture_output=True, text=True, timeout=1)
            _reduce = r.stdout.strip() == "1"
        elif sys.platform.startswith("win"):
            import ctypes
            on = ctypes.c_int(1)
            # SPI_GETCLIENTAREAANIMATION: off when "Show animations in Windows" is off
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):
                _reduce = not on.value
    except Exception:
        _reduce = False
    return _reduce


def motion_ok(mode: str) -> bool:
    mode = mode or "system"
    return mode == "on" or (mode == "system" and not _system_reduce_motion())


def paint(p, x: float, y: float, size: float, base: str, night: bool, angles=DOTS) -> None:
    from aqt.qt import QColor, QPen, QRectF, QPointF, Qt
    c = parts(base, night)
    s = size / 120.0
    ring_w, dot_r = _geom(size)
    p.save()
    p.setRenderHint(p.RenderHint.Antialiasing, True)
    ring = QColor(c["ring"])
    ring.setAlphaF(c["ring_alpha"])
    p.setPen(QPen(ring, ring_w * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(x + 60 * s, y + 60 * s), 44 * s, 44 * s)
    p.setPen(Qt.PenStyle.NoPen)
    for (cx, cy), f in zip(((40, 40), (62, 40), (40, 62), (62, 62)), c["cells"]):
        p.setBrush(QColor(f))
        p.drawRoundedRect(QRectF(x + cx * s, y + cy * s, 18 * s, 18 * s), 4 * s, 4 * s)
    p.setBrush(QColor(c["dot"]))
    for a in angles:
        r = math.radians(a)
        p.drawEllipse(QPointF(x + (60 + 44 * math.cos(r)) * s, y + (60 + 44 * math.sin(r)) * s),
                      dot_r * s, dot_r * s)
    p.restore()


def pixmap(base: str, night: bool, size: int, dpr: float = 2.0):
    from aqt.qt import QPixmap, QPainter, Qt
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    paint(p, 0, 0, size, base, night)
    p.end()
    return pm


def icon(base: str, night: bool):
    from aqt.qt import QIcon
    ic = QIcon()
    for n in (16, 24, 32, 64, 128):
        ic.addPixmap(pixmap(base, night, n, 1.0))
    return ic


def _make_widget():
    from aqt.qt import QWidget, QPainter, QVariantAnimation, QSize

    class LogoWidget(QWidget):
        """The logo at a fixed size. With animate, its dots spread out the first time it
        is shown (when the Animations setting allows motion); play() runs it again."""

        def __init__(self, size: int, base: str, night: bool, animate: bool = False,
                     motion: str = "system", parent=None):
            super().__init__(parent)
            self._size, self._base, self._night = size, base, night
            self._angles = DOTS
            self._auto = animate and motion_ok(motion)
            self._played = False
            self.setFixedSize(QSize(size, size))
            self._anim = QVariantAnimation(self)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(SPREAD_MS)
            self._anim.valueChanged.connect(self._step)
            if self._auto:
                self._angles = tuple(-450.0 for _ in DOTS)

        def _step(self, v):
            e = 1 - (1 - float(v)) ** 3
            self._angles = tuple(-90 - 360 * (1 - e) + 120 * i * e for i in range(3))
            self.update()

        def play(self):
            self._anim.stop()
            self._anim.start()

        def showEvent(self, ev):
            super().showEvent(ev)
            if self._auto and not self._played:
                self._played = True
                # after the window's first paint, so its opening frames aren't dropped
                from aqt.qt import QTimer
                QTimer.singleShot(160, self.play)

        def paintEvent(self, ev):
            p = QPainter(self)
            paint(p, 0, 0, self._size, self._base, self._night, self._angles)
            p.end()

    return LogoWidget


def LogoWidget(*a, **kw):
    global _LogoWidget
    try:
        cls = _LogoWidget
    except NameError:
        cls = _LogoWidget = _make_widget()
    return cls(*a, **kw)
