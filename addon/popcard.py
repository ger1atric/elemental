"""
A small card with Elemental's logo in the corner of the screen: the pomodoro's "Break's
over" when Anki isn't the app in front. Used on macOS, where Qt's system notifications
no longer show (they go through an Apple API recent macOS drops), and wherever the system
has no tray messages. No permission needed. It shows over other apps (and full-screen
ones on macOS) without taking focus, fades out after a few seconds (not while the
pointer is on it), and clicking it brings Anki forward.
"""

from __future__ import annotations

import sys

SHOW_MS = 8000
MARGIN = 14
WIDTH = 330

_card = None


def show(title: str, body: str, on_click=None) -> bool:
    """Show the card (replacing one that's up). False if it couldn't be shown."""
    global _card
    try:
        if _card is not None:
            _card.close()
    except Exception:
        pass
    _card = None
    try:
        _card = _cls()(title, body, on_click)
        _card.pop()
        return True
    except Exception:
        _card = None
        return False


def _night() -> bool:
    """The system's appearance (the card sits over other apps, not Anki)."""
    try:
        from aqt.qt import QGuiApplication, Qt
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        try:
            from aqt.theme import theme_manager
            return bool(theme_manager.night_mode)
        except Exception:
            return False


def _mac_all_spaces(widget) -> None:
    """macOS: show on every Space, including over full-screen apps (NSWindow collection
    behavior, set through the Objective-C runtime)."""
    if sys.platform != "darwin":
        return
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    view = ctypes.c_void_p(int(widget.winId()))
    send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
    window = send(view, objc.sel_registerName(b"window"))
    if not window:
        return
    # canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary
    behavior = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)
    send.restype, send.argtypes = None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    send(window, objc.sel_registerName(b"setCollectionBehavior:"), behavior)


def _cls():
    global _Card
    try:
        return _Card
    except NameError:
        pass
    from aqt.qt import (QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPainter, QColor, QPen,
                        QPropertyAnimation, QEasingCurve, QTimer, QGuiApplication, QCursor, Qt)
    from . import brand

    class Card(QWidget):
        def __init__(self, title, body, on_click):
            flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            super().__init__(None, flags)
            for attr in ("WA_TranslucentBackground", "WA_ShowWithoutActivating",
                         "WA_MacAlwaysShowToolWindow", "WA_DeleteOnClose"):
                a = getattr(Qt.WidgetAttribute, attr, None)
                if a is not None:
                    self.setAttribute(a, True)
            self._on_click = on_click
            self._night = night = _night()
            fg, sub = ("#f2f2f2", "#b4b4b8") if night else ("#1d1d1f", "#5f5f66")

            logo = brand.LogoWidget(38, "", night, animate=True)
            t = QLabel(title)
            t.setStyleSheet(f"color:{fg}; font-weight:600; font-size:14px; background:transparent;")
            b = QLabel(body)
            b.setWordWrap(True)
            b.setStyleSheet(f"color:{sub}; font-size:13px; background:transparent;")
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(t)
            text.addWidget(b)
            row = QHBoxLayout(self)
            row.setContentsMargins(14, 13, 16, 13)
            row.setSpacing(12)
            row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(text, 1)
            self.setFixedWidth(WIDTH)
            self.adjustSize()
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            self._fade = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._fade_out)

        def pop(self):
            scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            y = g.top() + MARGIN if sys.platform == "darwin" else g.bottom() - self.height() - MARGIN
            self.move(g.right() - self.width() - MARGIN, y)
            self.setWindowOpacity(0.0)
            self.show()
            try:
                _mac_all_spaces(self)
            except Exception:
                pass
            self.raise_()
            self._fade.stop()
            self._fade.setDuration(220)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            self._timer.start(SHOW_MS)

        def _fade_out(self):
            self._fade.stop()
            self._fade.setDuration(400)
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(0.0)
            try:
                self._fade.finished.disconnect()
            except Exception:
                pass
            self._fade.finished.connect(self.close)
            self._fade.start()

        def enterEvent(self, ev):
            # hold it while the pointer is on it
            self._timer.stop()
            try:
                self._fade.finished.disconnect()
            except Exception:
                pass
            self._fade.stop()
            self.setWindowOpacity(1.0)
            super().enterEvent(ev)

        def leaveEvent(self, ev):
            self._timer.start(2500)
            super().leaveEvent(ev)

        def mouseReleaseEvent(self, ev):
            cb = self._on_click
            self.close()
            if cb:
                try:
                    cb()
                except Exception:
                    pass

        def paintEvent(self, ev):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.rect().adjusted(1, 1, -1, -1)
            bg = QColor(44, 44, 46, 246) if self._night else QColor(255, 255, 255, 248)
            edge = QColor(255, 255, 255, 34) if self._night else QColor(0, 0, 0, 30)
            p.setPen(QPen(edge, 1))
            p.setBrush(bg)
            p.drawRoundedRect(r, 14, 14)
            p.end()

    _Card = Card
    return Card
