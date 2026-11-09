# Elemental (formerly Interactive Heatmap)
# Copyright (c) 2026 Jerry Shen
# License: MIT

import datetime
import functools
import time
import json
import os
import math
import traceback
import html as _html
import re
import sys
import types
import aqt
from datetime import timedelta, date
from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showInfo, askUser, openFolder, tooltip
from . import themes, changelog, brand, startup_cache


def _log_exc():
    """The current traceback, to stdout: Anki shows anything on stderr as an error
    popup, so this is for errors the add-on already works around."""
    print(traceback.format_exc())


try:
    from PyQt6.QtGui import QPolygonF
except ImportError:
    try:
        from PyQt5.QtGui import QPolygonF
    except ImportError:
        QPolygonF = None

ADDON_NAME = "Elemental"
VERSION = "1.9.5"

_home_dark_now = False      # while the home page draws with "Always dark" on (_HomeDark)


def _is_dark_mode():
    """Check if Anki is in dark mode (or the home page is drawing with "Always dark" on)."""
    if _home_dark_now:
        return True
    try:
        from aqt.theme import theme_manager
        return theme_manager.night_mode
    except:
        return False


def _home_always_dark() -> bool:
    """The "Always dark" setting (read raw: get_config itself asks _is_dark_mode)."""
    try:
        return bool((mw.addonManager.getConfig(__name__) or {}).get("home_always_dark", False))
    except Exception:
        return False


class _HomeDark:
    """While the home page draws: dark if Anki is, or if "Always dark" is on."""
    def __enter__(self):
        global _home_dark_now
        self.prev = _home_dark_now
        _home_dark_now = _home_always_dark()

    def __exit__(self, *_exc):
        global _home_dark_now
        _home_dark_now = self.prev
        return False

def _release_notes_html(releases, text, subtext, accent, headings=True):
    """Release notes as rich text: each release's version and date, then its notes."""
    font = "font-family: -apple-system, sans-serif;"
    out = []
    for ri, r in enumerate(releases):
        if headings:
            out.append(f'<p style="{font} font-size: 12px; font-weight: 700; color: {accent}; '
                       f'letter-spacing: .5px; margin: 6px 0 12px 0;">VERSION {r["version"]}'
                       f'<span style="color: {subtext}; font-weight: 400;">&nbsp;&nbsp;·&nbsp;&nbsp;{r["date"]}</span></p>')
        for ni, (title, body) in enumerate(r["notes"]):
            # No gap after the very last note: the card's own padding ends it
            gap = 0 if (ri == len(releases) - 1 and ni == len(r["notes"]) - 1) else 14
            if not body:
                out.append(f'<p style="{font} font-size: 13px; font-weight: 600; color: {text}; margin: 0 0 {gap}px 0;">{title}</p>')
                continue
            out.append(f'<p style="{font} font-size: 13px; font-weight: 600; color: {text}; margin: 0 0 3px 0;">{title}</p>'
                       f'<p style="{font} font-size: 12px; line-height: 135%; color: {subtext}; margin: 0 0 {gap}px 0;">{body}</p>')
    return "".join(out)


def _release_card(r, night, installed=False):
    """A release as a settings-style card: its version and date, then its notes."""
    c = _settings_palette(night)
    card = QFrame()
    card.setObjectName("hmCard")
    v = QVBoxLayout(card)
    v.setContentsMargins(18, 14, 18, 16)
    v.setSpacing(8)
    head = QLabel(f'<span style="font-size: 16px; font-weight: 700; color: {c["text"]};">{r["version"]}</span>'
                  f'<span style="color: {c["sub"]};">&nbsp;&nbsp;{r["date"]}</span>'
                  + (f'&nbsp;&nbsp;<span style="color: {c["accent"]}; font-weight: 600;">· Installed</span>'
                     if installed else ""))
    head.setTextFormat(Qt.TextFormat.RichText)
    v.addWidget(head)
    body = QLabel(_release_notes_html([r], c["text"], c["sub"], c["accent"], headings=False))
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setWordWrap(True)
    body.setOpenExternalLinks(True)
    v.addWidget(body)
    return card


class WhatsNewDialog(QDialog):
    """Shown once after an update: every release since the one you last saw, styled
    like the settings window."""

    def __init__(self, parent=None, releases=None):
        super().__init__(parent)
        self.releases = releases or changelog.RELEASES[:1]
        self.setObjectName("hmSettings")
        self.setWindowTitle("What's New")
        night = _is_dark_mode()
        self.setWindowIcon(brand.icon(get_config().get("base_color", "#8e44ad"), night))
        self.setStyleSheet(_settings_css(night))
        self.resize(540, 640)
        self.setMinimumSize(440, 420)
        self.setup_ui(night)

    def setup_ui(self, night):
        body = QWidget()
        body.setObjectName("hmPageBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(26, 20, 26, 22)
        v.setSpacing(10)
        cfg = get_config()
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(brand.LogoWidget(46, cfg.get("base_color", "#8e44ad"), night, animate=True,
                                        motion=lowpower.motion(cfg)),
                       0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel("What's new")
        title.setObjectName("hmPageTitle")
        words.addWidget(title)
        n = len(self.releases)
        sub = QLabel(f"Here's what changed in Elemental {VERSION}." if n == 1
                     else f"Here's what changed in the last {n} updates.")
        sub.setObjectName("hmPageSub")
        sub.setWordWrap(True)
        words.addWidget(sub)
        head.addLayout(words, 1)
        v.addLayout(head)
        v.addSpacing(4)
        for r in self.releases:
            v.addWidget(_release_card(r, night))
        v.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("hmPage")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        footer = QWidget()
        footer.setObjectName("hmFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 10, 16, 10)
        hint = QLabel("Past updates are in Settings → Version History.")
        hint.setObjectName("hmPageSub")
        fl.addWidget(hint)
        fl.addStretch()
        ok = QPushButton("Got it")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        fl.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll, 1)
        layout.addWidget(footer)

# The look a brand-new install starts with: the Rolling Hills photo theme (its dark
# version follows Anki's dark mode). Only for new installs; nobody's chosen look changes.
FRESH_INSTALL_LOOK = {"heatmap_theme": "rolling_hills", "background_enabled": True,
                      "background_source": "builtin:rolling_hills"}


def check_whats_new():
    """Show What's New dialog if version has changed or on first install."""
    cfg = get_config()
    last_version = cfg.get("last_seen_version", "")

    if last_version != VERSION:
        if not last_version and "heatmap_theme" not in (mw.addonManager.getConfig(__name__) or {}):
            cfg.update(FRESH_INSTALL_LOOK)      # first run ever, no theme saved yet
        if last_version and changelog._key(last_version) < (1, 9, 5) and cfg.get("low_power") is False:
            # Before 1.9.5 Settings saved "off" whenever it was saved, so off doesn't mean
            # chosen: make it automatic (on only when Anki draws without the graphics chip)
            cfg["low_power"] = None
        cfg["last_seen_version"] = VERSION
        write_config(cfg)
        releases = changelog.since(last_version)
        mw.progress.timer(500, lambda: WhatsNewDialog(mw, releases).exec(), False)

gui_hooks.profile_did_open.append(check_whats_new)

_ONE_YEAR_AGO = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")

DEFAULT_CONFIG = {
    "base_color": "#8e44ad",
    "forecast_color": "#bdc3c7",
    "forecast_shade_color": "#20b2aa",     # future days, shaded by predicted cards
    "forecast_shading": False,             # off: every forecast day in forecast_color, flat
    "today_color": "#2ecc71",
    "empty_color": "#ebedf0",
    "empty_color_night": "#282c34",
    "graph_reviews_color": "#3498db",
    "graph_time_color": "#e67e22",
    "graph_time_studied_color": "#3498db",
    "graph_retention_color": "#f1c40f",
    "graph_forecast_color": "#95a5a6",
    "start_date": _ONE_YEAR_AGO,
    "weeks_back": 26,                      # (before 1.9.5; now weeks_ahead)
    "weeks_ahead": None,                   # empty weeks after this one; None: from weeks_back
    "separate_months": False,              # each month its own block, with a gap between
    "days_future": 21,
    "cell_size": 10,
    "cell_gap": 2,
    "border_radius": 2,
    "heatmap_width": 540,                   # the heatmap box, in px (540 to 900)
    "animations": "system",                 # deck list animations: system (off with reduce motion) | on | off
    "low_power": None,                      # Low-power mode: no blur, no animations (lowpower.py); None: only without the graphics chip
    "heatmap_theme": "custom",            # custom ("My colors": the colors below) | a key of themes.THEMES
    "display_mode": "volume",
    "show_mode_time": True,              # Show Time Studied toggle button
    "show_mode_newcards": True,          # Show New Cards toggle button
    "show_mode_focus": True,             # Show FOCUS (focus score) toggle button; needs Time Left
    "custom_time_color": "#e67e22",      # Cell color for time-studied mode
    "custom_newcards_color": "#27ae60",  # Cell color for new-cards mode
    "color_scale_max_time": 0,           # 0 = auto (peak day in minutes)
    "color_scale_max_newcards": 0,       # 0 = auto (peak day count)
    "show_graph": True,
    "monochrome_text": False,
    "enable_shadows": True,
    "enable_glass": True,
    "modern_deck_theme": True,
    "enable_deck_glass": True,
    "show_deck_ratio": True,
    "deck_count_pills": True,              # New / Learning / Due as pills (off: Anki's plain numbers)
    "home_always_dark": False,             # the home page stays dark when Anki is light
    "deck_list_width": 540,
    "replace_stats": True,
    "glass_opacity": 0.4,
    "active_graphs_v14": ["reviews", "time_card", "time_studied", "retention", "forecast"],
    "reviews_rolling_avg": False,
    "reviews_rolling_avg_period": 7,
    "time_rolling_avg": False,
    "time_rolling_avg_period": 7,
    "ret_rolling_avg": False,
    "ret_rolling_avg_period": 7,
    "time_studied_rolling_avg": False,
    "time_studied_rolling_avg_period": 7,
    "forecast_rolling_avg": False,
    "forecast_rolling_avg_period": 7,
    "show_exam_markers": True,
    "exam_countdown": True,                 # deck list: days to your next exam, under the Today pill
    "exam_countdown_days": 14,              # ... once it's this many days away or closer
    "refresh_interval": 60,
    "daily_notes": {},
    "exam_days": {},
    "tag_colors": {},
    "retention_min": 75,
    "retention_max": 95,
    "exclude_new_cards_from_retention": False,
    "speed_min": 3.0,
    "speed_max": 15.0,
    "avg_period": "year",  # Options: "week", "month", "year", "all"
    "pill_new_color": "#4a90e2",
    "pill_learn_color": "#e74c3c",
    "pill_due_color": "#f1c40f",
    "filtered_deck_color": "#20b2aa",      # Deck-list name color for filtered decks
    "browser_color_theme": "default",
    "enable_editor_theme": True,           # Style the note editor (browser / add cards windows)
    "browser_custom_colors": False,
    "browser_bg_primary": "#1e1e1e",
    "browser_bg_secondary": "#252525",
    "browser_bg_suspended": "#3a2f1a",
    "browser_bg_buried": "#1a2a3a",
    "browser_bg_marked": "#3a1a3a",
    "browser_text_normal": "#e0e0e0",
    "browser_text_suspended": "#d4af37",
    "browser_text_buried": "#6c91b0",
    "browser_text_marked": "#c792ea",
    "browser_selection": "#8e44ad",
    "browser_flag_1": "#e25555",
    "browser_flag_2": "#ff9632",
    "browser_flag_3": "#32cd32",
    "browser_flag_4": "#56b4e9",
    "browser_flag_5": "#ff82ab",
    "browser_flag_6": "#009688",
    "browser_flag_7": "#7c4dff",
    "browser_row_spacing": "comfortable",  # Options: "comfortable", "compact", "tight"
    "browser_state_icons": True,           # ‖ suspended, ● buried, ★ marked before the first column
    "browser_tag_display": "full",         # Tags column: "full", "leaf" (last part only), "arrows" (:: → ›)
    # Deck filtering options
    "heatmap_deck_filter_enabled": False,  # Enable deck filtering on main heatmap
    "heatmap_filtered_decks": [],          # List of deck IDs to show (empty = all)
    "retention_deck_scope_enabled": False, # Scope the retention % to specific deck(s)
    "retention_scope_decks": [],           # Deck IDs used ONLY for retention (empty = all)
    "show_overview_heatmap": True,         # Show heatmap on overview screen
    "overview_filter_current_deck": True,  # Auto-filter to current deck on overview
    # Intensity settings
    "cell_intensity_curve": 0.7,           # Exponent for opacity scaling (0.3-1.0, lower = more visible low activity)
    "cell_min_opacity": 0.05,              # Minimum opacity for cells with reviews (0.05-0.5)
    "color_gradient_mode": "glow",         # "glow" (by rank, dark→bright), "opacity", "shade" (dark→bright), or "shade_inverted" (bright→dark)
    "glow_contrast": 0.75,                 # Glow mode: how far the quietest and busiest days sit from the base color (0..1)
    "shade_dark_factor": 0.15,             # How dark the low end is in shade mode (0.0=black, 0.5=half brightness)
    # FSRS Simulation Settings (matches Anki's built-in FSRS Simulator)
    "fsrs_simulation_enabled": False,      # Enable FSRS-based smart prediction
    "fsrs_simulation_days": 90,            # Days to simulate
    "fsrs_simulation_new_cards": 0,        # New cards per day in the FSRS forecast
    "fsrs_new_card_days": [0, 1, 2, 3, 4, 5, 6],  # weekdays new cards are added on (0=Mon)
    "fsrs_band_enabled": False,            # confidence band around the FSRS forecast
    "fsrs_band_sd": 1,                     # band width in standard deviations (1 or 2)
    "fsrs_simulation_retention": 0.9,      # Desired retention for simulation (0.7-0.99)
    "new_cards_per_weekday": {"0":0,"1":0,"2":0,"3":0,"4":0,"5":0,"6":0},  # 0=Mon..6=Sun
    "fsrs_simulation_max_reviews": 9999,   # Maximum reviews/day
    "fsrs_simulation_max_interval": 36500, # Maximum interval (days)
    "fsrs_learning_steps": 2,              # Learning step count
    "fsrs_relearning_steps": 1,            # Relearning step count
    "fsrs_simulate_overhead": True,        # count every answer: learning + relearning steps (as the graph does)
    "fsrs_prediction_color": "#9b59b6",    # Color for FSRS forecast line
    "fsrs_use_custom_weights": False,      # Use manually entered weights instead of deck config
    "fsrs_custom_weights": "",             # Custom FSRS weights (comma-separated)
    "fsrs_advanced_expanded": False,       # Whether advanced settings is expanded
    "fsrs_forecast_deck": 0,               # Deck ID for forecast (0 = all decks)
    "backtest_stability_scale": 1.0,       # Calibration: scale FSRS initial stability (1.0 = off)
    "backtest_existing_baseline": 0.0,     # Calibration: add N existing-card reviews/day to forecast
    "color_scale_max": 0,                  # Heatmap color ceiling (0 = auto: use daily max)
    # Stats bar settings
    "streak_display": "streak",            # Options: "streak", "pct_week", "pct_month"
    "show_stats_bar": True,                # Show/hide the stats numerics row
    # Time calculation settings
    "exclude_idle_cards": True,            # Exclude cards where time > idle_threshold from avg time calc
    "idle_threshold_secs": 60,             # Threshold in seconds; cards above this are "idle" and excluded
    # Time left (time_left.py) — off by default
    "time_estimate_enabled": False,        # Estimate how long today's remaining cards will take
    "time_deck_column": True,              # Time column in the deck list
    "time_today_pill": True,               # Today's total as a pill under the decks
    "notice_backlog": True,                # ... which also rolls to: how many cards are overdue
    "notice_tomorrow": True,               # ... tomorrow's reviews, in the evening
    "notice_streak": True,                 # ... your streak, late in the day if you haven't studied
    "notice_learning": True,               # ... learning cards still to come back today, once the rest is done
    "notice_sync": True,                   # ... cards changed since your last sync, and when that was
    "notice_milestone": True,              # ... a streak milestone (every 5, 10, 25 … days), on the day
    "notice_last_week": True,              # ... last week's reviews and retention, on the first day of the week
    "notice_this_week": True,              # ... this week's reviews against last week's, when they differ a lot
    "time_overview": True,                 # Time left on the deck overview
    "time_desk_time": True,                # Include the time between cards
    "time_show_as": "finish",              # finish (clock time) | left (hours and minutes)
    "focus_away_is_lookup": False,         # Focus score: leaving Anki during a card counts as a lookup
    "focus_reading_counts": False,         # Focus score: a card is judged by its question side if you stayed in Anki
    "focus_lookup_key": "x",               # Review-screen key that leaves the current card out of the focus score
    # Day view (day_view.py): clicking a day
    "day_topic_tag": "",                   # Tag folder the day view groups topics by ("" = AnKing systems, else subdecks)
    "day_topic_level": 1,                  # How many levels below that folder a topic is
    "stats_topic_level": 0,                # Stats window topics: levels below that folder (0 = auto, at most 2)
    # Review pill (review_pill.py) — off by default
    "review_pill_enabled": False,          # Live retention pill on the review screen
    "review_pill_target": 90,              # Target retention (%)
    "review_pill_shows": "graph",          # graph | time | both | numbers
    "review_pill_window": "today",         # today | all
    "review_pill_show_time": True,         # Finish time in the hover panel
    "review_pill_focus_cue": True,         # Amber cue when you seem to be drifting
    "review_pill_focus_ring": True,        # Brief ring after each answer: focused (green) or not (amber)
    "review_pill_ring_style": "draw",      # draw (outline drawn around the pill) | fade
    "review_pill_position": "top-right",   # Default corner
    "review_pill_draggable": True,         # Drag handle
    "review_pill_span": 100,               # Cards the retention graph spans
    "review_pill_smoothing": 2,            # Graph smoothing
    "review_pill_min_reviews": 1,          # Hide until this many reviews
    "pomo_enabled": False,                 # Pomodoro timer in Live Stats
    "pomo_focus_min": 25,                  # ... focus block length
    "pomo_break_min": 5,                   # ... break length
    "pomo_long_min": 15,                   # ... long break length
    "pomo_long_every": 4,                  # ... a long break after this many blocks
    "pomo_pause_away": True,               # ... the block only counts time on the review screen
    "pomo_drift_break": False,             # ... offer a break when focus drifts
    "pomo_notify": True,                   # ... a notification when a break ends
    # Background photo (background.py) — off by default
    "background_enabled": False,           # A photo behind the main screens
    "background_source": "builtin:dusk",   # mine (your folder) | builtin:<name> (background.BUILTIN)
    "background_rotation": "daily",        # daily | launch | fixed
    "background_image": "",                # The photo for "fixed"
    "background_opacity_main": 0.6,        # Deck list, overview, top and bottom bars
    "background_opacity_review": 0.1,      # Review screen
    "background_in_review": True,          # Also behind the review screen
    "background_on_bars": True,            # Also on the top and bottom bars
}

# Browser color themes
BROWSER_THEMES = {
    "default": {
        "name": "Default (follows Anki theme)",
        "bg_primary": "#1e1e1e",
        "bg_secondary": "#252525",
        "bg_suspended": "#3a2f1a",
        "bg_buried": "#1a2a3a",
        "bg_marked": "#3a1a3a",
        "text_normal": "#e0e0e0",
        "text_suspended": "#d4af37",
        "text_buried": "#6c91b0",
        "text_marked": "#c792ea",
        "selection": "#8e44ad",
        "flag_1": "#e25555",
        "flag_2": "#ff9632",
        "flag_3": "#32cd32",
        "flag_4": "#56b4e9",
        "flag_5": "#ff82ab",
        "flag_6": "#009688",
        "flag_7": "#7c4dff",
    },
    "catppuccin_macchiato": {
        "name": "Catppuccin Macchiato",
        "bg_primary": "#24273a",
        "bg_secondary": "#1e2030",
        "bg_suspended": "#494d64",
        "bg_buried": "#363a4f",
        "bg_marked": "#363a4f",
        "text_normal": "#cad3f5",
        "text_suspended": "#eed49f",
        "text_buried": "#8aadf4",
        "text_marked": "#c6a0f6",
        "selection": "#8aadf4",
        "flag_1": "#ed8796",
        "flag_2": "#f5a97f",
        "flag_3": "#a6da95",
        "flag_4": "#8aadf4",
        "flag_5": "#f5bde6",
        "flag_6": "#8bd5ca",
        "flag_7": "#c6a0f6",
    },
    "catppuccin_mocha": {
        "name": "Catppuccin Mocha",
        "bg_primary": "#1e1e2e",
        "bg_secondary": "#181825",
        "bg_suspended": "#45475a",
        "bg_buried": "#313244",
        "bg_marked": "#313244",
        "text_normal": "#cdd6f4",
        "text_suspended": "#f9e2af",
        "text_buried": "#89b4fa",
        "text_marked": "#cba6f7",
        "selection": "#89b4fa",
        "flag_1": "#f38ba8",
        "flag_2": "#fab387",
        "flag_3": "#a6e3a1",
        "flag_4": "#89b4fa",
        "flag_5": "#f5c2e7",
        "flag_6": "#94e2d5",
        "flag_7": "#cba6f7",
    },
    "nord": {
        "name": "Nord",
        "bg_primary": "#2e3440",
        "bg_secondary": "#3b4252",
        "bg_suspended": "#4c566a",
        "bg_buried": "#434c5e",
        "bg_marked": "#434c5e",
        "text_normal": "#eceff4",
        "text_suspended": "#ebcb8b",
        "text_buried": "#81a1c1",
        "text_marked": "#b48ead",
        "selection": "#5e81ac",
        "flag_1": "#bf616a",
        "flag_2": "#d08770",
        "flag_3": "#a3be8c",
        "flag_4": "#81a1c1",
        "flag_5": "#b48ead",
        "flag_6": "#8fbcbb",
        "flag_7": "#b48ead",
    },
    "dracula": {
        "name": "Dracula",
        "bg_primary": "#282a36",
        "bg_secondary": "#21222c",
        "bg_suspended": "#44475a",
        "bg_buried": "#383a59",
        "bg_marked": "#383a59",
        "text_normal": "#f8f8f2",
        "text_suspended": "#f1fa8c",
        "text_buried": "#8be9fd",
        "text_marked": "#bd93f9",
        "selection": "#6272a4",
        "flag_1": "#ff5555",
        "flag_2": "#ffb86c",
        "flag_3": "#50fa7b",
        "flag_4": "#8be9fd",
        "flag_5": "#ff79c6",
        "flag_6": "#8be9fd",
        "flag_7": "#bd93f9",
    },
    "gruvbox": {
        "name": "Gruvbox Dark",
        "bg_primary": "#282828",
        "bg_secondary": "#1d2021",
        "bg_suspended": "#3c3836",
        "bg_buried": "#32302f",
        "bg_marked": "#32302f",
        "text_normal": "#ebdbb2",
        "text_suspended": "#fabd2f",
        "text_buried": "#83a598",
        "text_marked": "#d3869b",
        "selection": "#458588",
        "flag_1": "#fb4934",
        "flag_2": "#fe8019",
        "flag_3": "#b8bb26",
        "flag_4": "#83a598",
        "flag_5": "#d3869b",
        "flag_6": "#8ec07c",
        "flag_7": "#d3869b",
    },
    "one_dark": {
        "name": "One Dark",
        "bg_primary": "#282c34",
        "bg_secondary": "#21252b",
        "bg_suspended": "#3e4451",
        "bg_buried": "#2c313c",
        "bg_marked": "#2c313c",
        "text_normal": "#abb2bf",
        "text_suspended": "#e5c07b",
        "text_buried": "#61afef",
        "text_marked": "#c678dd",
        "selection": "#3e4451",
        "flag_1": "#e06c75",
        "flag_2": "#d19a66",
        "flag_3": "#98c379",
        "flag_4": "#61afef",
        "flag_5": "#c678dd",
        "flag_6": "#56b6c2",
        "flag_7": "#c678dd",
    },
    "tokyo_night": {
        "name": "Tokyo Night",
        "bg_primary": "#1a1b26",
        "bg_secondary": "#16161e",
        "bg_suspended": "#292e42",
        "bg_buried": "#24283b",
        "bg_marked": "#24283b",
        "text_normal": "#a9b1d6",
        "text_suspended": "#e0af68",
        "text_buried": "#7aa2f7",
        "text_marked": "#bb9af7",
        "selection": "#33467c",
        "flag_1": "#f7768e",
        "flag_2": "#ff9e64",
        "flag_3": "#9ece6a",
        "flag_4": "#7aa2f7",
        "flag_5": "#ff007c",
        "flag_6": "#73daca",
        "flag_7": "#bb9af7",
    },
    "solarized_dark": {
        "name": "Solarized Dark",
        "bg_primary": "#002b36",
        "bg_secondary": "#073642",
        "bg_suspended": "#586e75",
        "bg_buried": "#073642",
        "bg_marked": "#073642",
        "text_normal": "#839496",
        "text_suspended": "#b58900",
        "text_buried": "#268bd2",
        "text_marked": "#d33682",
        "selection": "#2aa198",
        "flag_1": "#dc322f",
        "flag_2": "#cb4b16",
        "flag_3": "#859900",
        "flag_4": "#268bd2",
        "flag_5": "#d33682",
        "flag_6": "#2aa198",
        "flag_7": "#6c71c4",
    },
    "monokai": {
        "name": "Monokai Pro",
        "bg_primary": "#2d2a2e",
        "bg_secondary": "#221f22",
        "bg_suspended": "#403e41",
        "bg_buried": "#353236",
        "bg_marked": "#353236",
        "text_normal": "#fcfcfa",
        "text_suspended": "#ffd866",
        "text_buried": "#78dce8",
        "text_marked": "#ab9df2",
        "selection": "#ff6188",
        "flag_1": "#ff6188",
        "flag_2": "#fc9867",
        "flag_3": "#a9dc76",
        "flag_4": "#78dce8",
        "flag_5": "#ff6188",
        "flag_6": "#78dce8",
        "flag_7": "#ab9df2",
    },
    "github_dark": {
        "name": "GitHub Dark",
        "bg_primary": "#0d1117",
        "bg_secondary": "#161b22",
        "bg_suspended": "#30363d",
        "bg_buried": "#21262d",
        "bg_marked": "#21262d",
        "text_normal": "#c9d1d9",
        "text_suspended": "#e3b341",
        "text_buried": "#58a6ff",
        "text_marked": "#bc8cff",
        "selection": "#1f6feb",
        "flag_1": "#f85149",
        "flag_2": "#d29922",
        "flag_3": "#3fb950",
        "flag_4": "#58a6ff",
        "flag_5": "#db61a2",
        "flag_6": "#39c5cf",
        "flag_7": "#bc8cff",
    },
    "ayu_dark": {
        "name": "Ayu Dark",
        "bg_primary": "#0a0e14",
        "bg_secondary": "#0d1016",
        "bg_suspended": "#1c2028",
        "bg_buried": "#151920",
        "bg_marked": "#151920",
        "text_normal": "#b3b1ad",
        "text_suspended": "#ffb454",
        "text_buried": "#59c2ff",
        "text_marked": "#d2a6ff",
        "selection": "#273747",
        "flag_1": "#f07178",
        "flag_2": "#ff8f40",
        "flag_3": "#aad94c",
        "flag_4": "#59c2ff",
        "flag_5": "#f07178",
        "flag_6": "#95e6cb",
        "flag_7": "#d2a6ff",
    },
    "material_darker": {
        "name": "Material Darker",
        "bg_primary": "#212121",
        "bg_secondary": "#1a1a1a",
        "bg_suspended": "#3a3a3a",
        "bg_buried": "#2c2c2c",
        "bg_marked": "#2c2c2c",
        "text_normal": "#eeffff",
        "text_suspended": "#ffcb6b",
        "text_buried": "#82aaff",
        "text_marked": "#c792ea",
        "selection": "#4a4a4a",
        "flag_1": "#f07178",
        "flag_2": "#f78c6c",
        "flag_3": "#c3e88d",
        "flag_4": "#82aaff",
        "flag_5": "#ff9cac",
        "flag_6": "#89ddff",
        "flag_7": "#c792ea",
    },
    "rose_pine": {
        "name": "Rosé Pine",
        "bg_primary": "#191724",
        "bg_secondary": "#1f1d2e",
        "bg_suspended": "#26233a",
        "bg_buried": "#21202e",
        "bg_marked": "#21202e",
        "text_normal": "#e0def4",
        "text_suspended": "#f6c177",
        "text_buried": "#9ccfd8",
        "text_marked": "#c4a7e7",
        "selection": "#524f67",
        "flag_1": "#eb6f92",
        "flag_2": "#f6c177",
        "flag_3": "#31748f",
        "flag_4": "#9ccfd8",
        "flag_5": "#ebbcba",
        "flag_6": "#31748f",
        "flag_7": "#c4a7e7",
    },
    "everforest_dark": {
        "name": "Everforest Dark",
        "bg_primary": "#2d353b",
        "bg_secondary": "#272e33",
        "bg_suspended": "#3d484d",
        "bg_buried": "#343f44",
        "bg_marked": "#343f44",
        "text_normal": "#d3c6aa",
        "text_suspended": "#dbbc7f",
        "text_buried": "#7fbbb3",
        "text_marked": "#d699b6",
        "selection": "#475258",
        "flag_1": "#e67e80",
        "flag_2": "#e69875",
        "flag_3": "#a7c080",
        "flag_4": "#7fbbb3",
        "flag_5": "#d699b6",
        "flag_6": "#83c092",
        "flag_7": "#d699b6",
    },
    "darkest": {
        "name": "Darkest",
        "bg_primary": "#000000",
        "bg_secondary": "#0a0a0a",
        "bg_suspended": "#1a1500",
        "bg_buried": "#001020",
        "bg_marked": "#180018",
        "text_normal": "#e0e0e0",
        "text_suspended": "#ffc107",
        "text_buried": "#64b5f6",
        "text_marked": "#ce93d8",
        "selection": "#7c4dff",
        "flag_1": "#ff5252",
        "flag_2": "#ffab40",
        "flag_3": "#69f0ae",
        "flag_4": "#40c4ff",
        "flag_5": "#ff80ab",
        "flag_6": "#64ffda",
        "flag_7": "#b388ff",
    },
    # ===== LIGHT THEMES =====
    "catppuccin_latte": {
        "name": "Catppuccin Latte (Light)",
        "bg_primary": "#eff1f5",
        "bg_secondary": "#e6e9ef",
        "bg_suspended": "#dce0e8",
        "bg_buried": "#ccd0da",
        "bg_marked": "#ccd0da",
        "text_normal": "#4c4f69",
        "text_suspended": "#df8e1d",
        "text_buried": "#1e66f5",
        "text_marked": "#8839ef",
        "selection": "#7287fd",
        "flag_1": "#d20f39",
        "flag_2": "#fe640b",
        "flag_3": "#40a02b",
        "flag_4": "#1e66f5",
        "flag_5": "#ea76cb",
        "flag_6": "#179299",
        "flag_7": "#8839ef",
    },
    "github_light": {
        "name": "GitHub Light",
        "bg_primary": "#ffffff",
        "bg_secondary": "#f6f8fa",
        "bg_suspended": "#fff8c5",
        "bg_buried": "#ddf4ff",
        "bg_marked": "#fbefff",
        "text_normal": "#24292f",
        "text_suspended": "#9a6700",
        "text_buried": "#0969da",
        "text_marked": "#8250df",
        "selection": "#0969da",
        "flag_1": "#cf222e",
        "flag_2": "#bf8700",
        "flag_3": "#1a7f37",
        "flag_4": "#0969da",
        "flag_5": "#bf3989",
        "flag_6": "#1b7c83",
        "flag_7": "#8250df",
    },
    "solarized_light": {
        "name": "Solarized Light",
        "bg_primary": "#fdf6e3",
        "bg_secondary": "#eee8d5",
        "bg_suspended": "#e8e1c8",
        "bg_buried": "#d5e8f0",
        "bg_marked": "#f0e5f0",
        "text_normal": "#657b83",
        "text_suspended": "#b58900",
        "text_buried": "#268bd2",
        "text_marked": "#d33682",
        "selection": "#268bd2",
        "flag_1": "#dc322f",
        "flag_2": "#cb4b16",
        "flag_3": "#859900",
        "flag_4": "#268bd2",
        "flag_5": "#d33682",
        "flag_6": "#2aa198",
        "flag_7": "#6c71c4",
    },
    "nord_light": {
        "name": "Nord Light",
        "bg_primary": "#eceff4",
        "bg_secondary": "#e5e9f0",
        "bg_suspended": "#d8dee9",
        "bg_buried": "#d8dee9",
        "bg_marked": "#d8dee9",
        "text_normal": "#2e3440",
        "text_suspended": "#d08770",
        "text_buried": "#5e81ac",
        "text_marked": "#b48ead",
        "selection": "#5e81ac",
        "flag_1": "#bf616a",
        "flag_2": "#d08770",
        "flag_3": "#a3be8c",
        "flag_4": "#5e81ac",
        "flag_5": "#b48ead",
        "flag_6": "#88c0d0",
        "flag_7": "#b48ead",
    },
    "everforest_light": {
        "name": "Everforest Light",
        "bg_primary": "#fdf6e3",
        "bg_secondary": "#f4f0d9",
        "bg_suspended": "#e9e5cf",
        "bg_buried": "#e1ddc9",
        "bg_marked": "#e1ddc9",
        "text_normal": "#5c6a72",
        "text_suspended": "#dfa000",
        "text_buried": "#3a94c5",
        "text_marked": "#df69ba",
        "selection": "#a7c080",
        "flag_1": "#f85552",
        "flag_2": "#f57d26",
        "flag_3": "#8da101",
        "flag_4": "#3a94c5",
        "flag_5": "#df69ba",
        "flag_6": "#35a77c",
        "flag_7": "#df69ba",
    },
    "one_light": {
        "name": "One Light",
        "bg_primary": "#fafafa",
        "bg_secondary": "#f0f0f0",
        "bg_suspended": "#e5e5e6",
        "bg_buried": "#d8eaf9",
        "bg_marked": "#f5e6f5",
        "text_normal": "#383a42",
        "text_suspended": "#c18401",
        "text_buried": "#4078f2",
        "text_marked": "#a626a4",
        "selection": "#4078f2",
        "flag_1": "#e45649",
        "flag_2": "#c18401",
        "flag_3": "#50a14f",
        "flag_4": "#4078f2",
        "flag_5": "#a626a4",
        "flag_6": "#0184bc",
        "flag_7": "#a626a4",
    },
    "ayu_light": {
        "name": "Ayu Light",
        "bg_primary": "#fafafa",
        "bg_secondary": "#f0f0f0",
        "bg_suspended": "#fff3d4",
        "bg_buried": "#d4edfa",
        "bg_marked": "#f5e6f5",
        "text_normal": "#575f66",
        "text_suspended": "#f2ae49",
        "text_buried": "#399ee6",
        "text_marked": "#a37acc",
        "selection": "#399ee6",
        "flag_1": "#f07178",
        "flag_2": "#fa8d3e",
        "flag_3": "#86b300",
        "flag_4": "#399ee6",
        "flag_5": "#f07178",
        "flag_6": "#4cbf99",
        "flag_7": "#a37acc",
    },
    # ── Light counterparts for the dark-only families (so every theme can swap) ──
    "default_light": {
        "name": "Default Light",
        "bg_primary": "#ffffff",
        "bg_secondary": "#f2f2f2",
        "bg_suspended": "#fff3d4",
        "bg_buried": "#e3f0fb",
        "bg_marked": "#f6e9f6",
        "text_normal": "#202124",
        "text_suspended": "#b8860b",
        "text_buried": "#2b6cb0",
        "text_marked": "#8e44ad",
        "selection": "#8e44ad",
        "flag_1": "#d64545",
        "flag_2": "#e07b00",
        "flag_3": "#2e9e2e",
        "flag_4": "#2b7cc9",
        "flag_5": "#d94f8a",
        "flag_6": "#009688",
        "flag_7": "#7c4dff",
    },
    "dracula_light": {
        "name": "Alucard (Dracula Light)",
        "bg_primary": "#fffbeb",
        "bg_secondary": "#f2eedd",
        "bg_suspended": "#f5ecc8",
        "bg_buried": "#dfe7f0",
        "bg_marked": "#efe4f0",
        "text_normal": "#1f1f1f",
        "text_suspended": "#846e15",
        "text_buried": "#036a96",
        "text_marked": "#644ac9",
        "selection": "#644ac9",
        "flag_1": "#cb3a2a",
        "flag_2": "#a34d14",
        "flag_3": "#14710a",
        "flag_4": "#036a96",
        "flag_5": "#a3144d",
        "flag_6": "#036a96",
        "flag_7": "#644ac9",
    },
    "gruvbox_light": {
        "name": "Gruvbox Light",
        "bg_primary": "#fbf1c7",
        "bg_secondary": "#ebdbb2",
        "bg_suspended": "#f2e5bc",
        "bg_buried": "#e3ddcc",
        "bg_marked": "#ecdfd0",
        "text_normal": "#3c3836",
        "text_suspended": "#b57614",
        "text_buried": "#076678",
        "text_marked": "#8f3f71",
        "selection": "#af3a03",
        "flag_1": "#9d0006",
        "flag_2": "#af3a03",
        "flag_3": "#79740e",
        "flag_4": "#076678",
        "flag_5": "#8f3f71",
        "flag_6": "#427b58",
        "flag_7": "#8f3f71",
    },
    "tokyo_night_light": {
        "name": "Tokyo Night Day",
        "bg_primary": "#e1e2e7",
        "bg_secondary": "#d6d8df",
        "bg_suspended": "#e6e0cf",
        "bg_buried": "#d3ddf2",
        "bg_marked": "#e7dcf2",
        "text_normal": "#343b58",
        "text_suspended": "#8c6c3e",
        "text_buried": "#2e7de9",
        "text_marked": "#9854f1",
        "selection": "#2e7de9",
        "flag_1": "#f52a65",
        "flag_2": "#b15c00",
        "flag_3": "#587539",
        "flag_4": "#2e7de9",
        "flag_5": "#9854f1",
        "flag_6": "#007197",
        "flag_7": "#9854f1",
    },
    "rose_pine_dawn": {
        "name": "Rosé Pine Dawn",
        "bg_primary": "#faf4ed",
        "bg_secondary": "#fffaf3",
        "bg_suspended": "#f2e9de",
        "bg_buried": "#dfe5ec",
        "bg_marked": "#f0e6ef",
        "text_normal": "#575279",
        "text_suspended": "#ea9d34",
        "text_buried": "#286983",
        "text_marked": "#907aa9",
        "selection": "#907aa9",
        "flag_1": "#b4637a",
        "flag_2": "#ea9d34",
        "flag_3": "#286983",
        "flag_4": "#56949f",
        "flag_5": "#907aa9",
        "flag_6": "#56949f",
        "flag_7": "#907aa9",
    },
    "monokai_light": {
        "name": "Monokai Light",
        "bg_primary": "#fafaf6",
        "bg_secondary": "#f0f0ea",
        "bg_suspended": "#fbf0cd",
        "bg_buried": "#dcefe8",
        "bg_marked": "#f6e6ef",
        "text_normal": "#2c292d",
        "text_suspended": "#a08a1e",
        "text_buried": "#1a97b0",
        "text_marked": "#7d4fd1",
        "selection": "#c41d5e",
        "flag_1": "#c41d5e",
        "flag_2": "#c9640a",
        "flag_3": "#5c8a00",
        "flag_4": "#1a97b0",
        "flag_5": "#c41d5e",
        "flag_6": "#1a97b0",
        "flag_7": "#7d4fd1",
    },
    "material_light": {
        "name": "Material Light",
        "bg_primary": "#fafafa",
        "bg_secondary": "#f2f2f2",
        "bg_suspended": "#fff3d4",
        "bg_buried": "#e3f2fd",
        "bg_marked": "#f3e5f5",
        "text_normal": "#272727",
        "text_suspended": "#f6a434",
        "text_buried": "#6182b8",
        "text_marked": "#7c4dff",
        "selection": "#6182b8",
        "flag_1": "#e53935",
        "flag_2": "#f76d47",
        "flag_3": "#91b859",
        "flag_4": "#6182b8",
        "flag_5": "#ff5370",
        "flag_6": "#39adb5",
        "flag_7": "#7c4dff",
    },
    "lightest": {
        "name": "Lightest",
        "bg_primary": "#ffffff",
        "bg_secondary": "#f4f4f4",
        "bg_suspended": "#fff3d4",
        "bg_buried": "#e3f0fb",
        "bg_marked": "#f6e9f6",
        "text_normal": "#111111",
        "text_suspended": "#b8860b",
        "text_buried": "#1a6fc0",
        "text_marked": "#8250df",
        "selection": "#1a6fc0",
        "flag_1": "#d64545",
        "flag_2": "#e07b00",
        "flag_3": "#2e9e2e",
        "flag_4": "#1a6fc0",
        "flag_5": "#d94f8a",
        "flag_6": "#009688",
        "flag_7": "#7c4dff",
    },
}

# Each user-facing theme is a family with a dark and a light variant (keys into
# BROWSER_THEMES). The addon picks the variant matching Anki's current mode, so
# the browser/editor never end up light-on-light or dark-on-dark — this is what
# keeps third-party toolbar icons, the sidebar, and the editor readable.
THEME_FAMILIES = {
    "default":     {"name": "Default (Anki)",   "dark": "default",              "light": "default_light"},
    "catppuccin":  {"name": "Catppuccin",       "dark": "catppuccin_mocha",     "light": "catppuccin_latte"},
    "github":      {"name": "GitHub",           "dark": "github_dark",          "light": "github_light"},
    "nord":        {"name": "Nord",             "dark": "nord",                 "light": "nord_light"},
    "solarized":   {"name": "Solarized",        "dark": "solarized_dark",       "light": "solarized_light"},
    "dracula":     {"name": "Dracula",          "dark": "dracula",              "light": "dracula_light"},
    "gruvbox":     {"name": "Gruvbox",          "dark": "gruvbox",              "light": "gruvbox_light"},
    "tokyo_night": {"name": "Tokyo Night",      "dark": "tokyo_night",          "light": "tokyo_night_light"},
    "one":         {"name": "One",              "dark": "one_dark",             "light": "one_light"},
    "ayu":         {"name": "Ayu",              "dark": "ayu_dark",             "light": "ayu_light"},
    "everforest":  {"name": "Everforest",       "dark": "everforest_dark",      "light": "everforest_light"},
    "rose_pine":   {"name": "Rosé Pine",        "dark": "rose_pine",            "light": "rose_pine_dawn"},
    "monokai":     {"name": "Monokai",          "dark": "monokai",              "light": "monokai_light"},
    "material":    {"name": "Material",         "dark": "material_darker",      "light": "material_light"},
    "darkest":     {"name": "Darkest / Lightest","dark": "darkest",             "light": "lightest"},
}

# Map every variant key (and legacy config value) back to its family, so old
# saved settings like "catppuccin_mocha" or "nord_light" resolve correctly.
_VARIANT_TO_FAMILY = {}
for _fam_key, _fam in THEME_FAMILIES.items():
    _VARIANT_TO_FAMILY[_fam_key] = _fam_key
    _VARIANT_TO_FAMILY[_fam["dark"]] = _fam_key
    _VARIANT_TO_FAMILY[_fam["light"]] = _fam_key
# Legacy keys that aren't a variant of any current family
_VARIANT_TO_FAMILY["catppuccin_macchiato"] = "catppuccin"

def _theme_family_for_key(key):
    """Resolve a stored config value (family key OR legacy variant key) to a family key."""
    if key in THEME_FAMILIES:
        return key
    return _VARIANT_TO_FAMILY.get(key, "default")

def _theme_variant_key(family_key, dark):
    """Return the BROWSER_THEMES key for a family's dark/light variant."""
    fam = THEME_FAMILIES.get(family_key, THEME_FAMILIES["default"])
    return fam["dark"] if dark else fam["light"]

def _resolve_browser_theme_key(config):
    """Resolve the stored theme choice to the BROWSER_THEMES variant that matches
    Anki's current light/dark mode.

    The user picks a theme *family* (e.g. "Dracula"); we return its dark variant
    when Anki is dark and its light variant when Anki is light. This keeps the
    theme's brightness aligned with Anki so the sidebar, menu bar, third-party
    toolbar icons, and the editor stay legible in both modes. Legacy configs that
    stored a specific variant key (e.g. "catppuccin_mocha") are mapped back to
    their family first.
    """
    family_key = _theme_family_for_key(config.get("browser_color_theme", "default"))
    return _theme_variant_key(family_key, _is_dark_mode())

refresh_timer = None

# Short-lived cache for the FSRS simulator result (see get_fsrs_forecast)
_FSRS_FORECAST_CACHE = {}
_STARTUP_HOLD_UNTIL = 0.0      # until then a saved forecast isn't refreshed (Anki just started)
STARTUP_HOLD_S = 20


def _startup_opened():
    global _STARTUP_HOLD_UNTIL
    startup_cache.reset()
    _STARTUP_HOLD_UNTIL = time.time() + STARTUP_HOLD_S


def _startup_closed():
    startup_cache.reset()


gui_hooks.profile_did_open.append(_startup_opened)
gui_hooks.profile_will_close.append(_startup_closed)
startup_cache.setup(VERSION)

# Cache for the per-day revlog aggregation (see FastEngine._aggregate_revlog);
# keyed by revlog fingerprint so any new/undone review invalidates it.
_REVLOG_AGG_CACHE = {}

_cfg_held = None     # while the review pill builds: the config, read once (see hold_config)


def get_config():
    if _cfg_held is not None:
        return dict(_cfg_held)
    conf = DEFAULT_CONFIG.copy()
    mgr_conf = mw.addonManager.getConfig(__name__)
    if mgr_conf: conf.update(mgr_conf)
    return themes.apply(conf, _is_dark_mode())


def hold_config(on: bool) -> None:
    """Anki reads the config from disk on every call, and one pill update asks for it
    about 20 times; between hold_config(True) and hold_config(False) it's read once.
    Only for code that reads the config, never writes it."""
    global _cfg_held
    _cfg_held = None
    if on:
        _cfg_held = get_config()


get_config.hold = hold_config


def get_saved_colors():
    """The colors saved in the config ("My colors"), whatever theme is chosen."""
    conf = DEFAULT_CONFIG.copy()
    conf.update(mw.addonManager.getConfig(__name__) or {})
    return {k: conf[k] for k in themes.THEME_KEYS if k in conf}

def write_config(conf, clear_caches=True):
    # Pass clear_caches=False for changes that can't affect the cached revlog
    # aggregates or FSRS forecast (view mode, daily notes): rebuilding those
    # takes seconds on a large collection.
    if clear_caches:
        _FSRS_FORECAST_CACHE.clear()
        _REVLOG_AGG_CACHE.clear()
    # conf came from get_config(), so it holds the theme's colors: store yours instead.
    themes.keep_saved_colors(conf, mw.addonManager.getConfig(__name__) or {})
    mw.addonManager.writeConfig(__name__, conf)


def _refresh_heatmap_screen():
    """Redraw just the screen showing the heatmap. mw.reset() would tell every
    open screen and add-on that the whole collection changed."""
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()
    elif mw.state == "overview":
        mw.overview.refresh()
    else:
        mw.reset()

from . import time_left
time_left.setup(get_config, write_config, __name__)
from . import lowpower
lowpower.setup(get_config)
from . import review_pill
from . import pomodoro
review_pill.setup(get_config, write_config, __name__)
from . import background
background.setup(get_config, __name__)
from . import feedback
from . import anking_style
from . import forecast_band
from . import day_view
from . import stats_view
from . import moments
from . import help_text
from .icons import icon, CHEVRON_MASK


# ──────────────────────────────────────────────────────────────
# Updates on Windows
# ──────────────────────────────────────────────────────────────
# To update an add-on, Anki moves its user_files folder aside, then deletes the rest.
# Windows refuses either while a file inside is open, and the update fails ("Access is
# denied") every time Anki starts. Nothing here keeps a file open, but a write or the
# daily model fit can have one open for a moment: before Anki moves or deletes this
# add-on's folder, finish the queued writes, and if Windows still refuses, wait and try
# again for a few seconds.
UPDATE_RETRY_S = 10


def _release_files():
    try:
        from . import focus_log
        focus_log._flush()
    except Exception:
        pass
    review_pill.flush_log()


def _patient(fn, module, *args, **kwargs):
    deadline = time.time() + UPDATE_RETRY_S
    _release_files()
    while True:
        try:
            return fn(module, *args, **kwargs)
        except OSError as e:
            busy = isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32)
            if not busy or time.time() >= deadline:
                raise
            time.sleep(0.5)


def _guard_updates():
    am = getattr(mw, "addonManager", None)
    if am is None:
        return
    me = am.addonFromModule(__name__)
    for name in ("backupUserFiles", "deleteAddon"):
        orig = getattr(am, name, None)
        if orig is None or getattr(orig, "_elemental", False):
            continue

        def guarded(module, *args, _orig=orig, **kwargs):
            if module != me:
                return _orig(module, *args, **kwargs)
            return _patient(_orig, module, *args, **kwargs)

        guarded._elemental = True
        setattr(am, name, guarded)


try:
    _guard_updates()
except Exception:
    print(traceback.format_exc())

# FSRS Helper Functions
# FSRS-5 default weights for reference
FSRS_DEFAULT_WEIGHTS = [
    0.4072,  # w0: initial stability for Again
    1.1829,  # w1: initial stability for Hard
    3.1262,  # w2: initial stability for Good
    15.4722, # w3: initial stability for Easy
    7.2102,  # w4: difficulty weight
    0.5316,  # w5: difficulty weight
    1.0651,  # w6: difficulty weight
    0.0234,  # w7: difficulty weight
    1.616,   # w8: stability increase base
    0.1544,  # w9: stability increase decay
    1.0061,  # w10: stability increase retrievability factor
    1.6358,  # w11: fail stability decay
    0.1154,  # w12: fail stability modifier
    0.0,     # w13: hard penalty
    0.0,     # w14: easy bonus
    0.0,     # w15: (reserved)
    2.7488,  # w16: short-term stability
    0.0,     # w17: (reserved)
    0.9325,  # w18: (reserved)
]

# Where Deck Options keeps the optimized parameters, newest FSRS first (Anki uses the
# first that isn't empty). The snake_case names are from older versions of this add-on.
_FSRS_PARAM_KEYS = ("fsrsParams6", "fsrsParams5", "fsrsWeights", "fsrs_params_6", "fsrs_params_5")


def _saved_fsrs_weights(deck_id=None):
    """The optimized FSRS parameters in this deck's preset (no deck: the current deck's),
    or None if it has none."""
    try:
        if not mw.col:
            return None
        if not deck_id:
            deck_id = mw.col.decks.current()["id"]
        conf = mw.col.decks.config_dict_for_deck_id(deck_id)
        for key in _FSRS_PARAM_KEYS:
            w = (conf or {}).get(key)
            if w and len(w) >= 17:
                return [float(x) for x in w]
    except Exception:
        pass
    return None


def _get_fsrs_weights(deck_id=None):
    """The deck preset's optimized FSRS parameters, else FSRS's defaults."""
    return _saved_fsrs_weights(deck_id) or FSRS_DEFAULT_WEIGHTS

def _get_fsrs_params(deck_id=None):
    """Check if FSRS enabled and return parameters from deck config."""
    try:
        if not mw.col or not mw.col.get_config("fsrs"):
            return None

        # Get FSRS weights
        weights = _get_fsrs_weights(deck_id)

        # Get deck-specific desired retention if available
        desired_retention = 0.9  # Default
        if deck_id:
            try:
                conf = mw.col.decks.config_dict_for_deck_id(deck_id)
                if conf and conf.get("desiredRetention"):
                    dr = float(conf.get("desiredRetention"))
                    # Anki stores as decimal (0.9); guard against legacy percentage (90)
                    desired_retention = dr / 100.0 if dr > 1.0 else dr
            except:
                pass

        decay = -0.5  # FSRS decay constant
        factor = 0.9 ** (1/decay) - 1  # ~0.234

        return {
            'decay': decay,
            'factor': factor,
            'desired_retention': desired_retention,
            'weights': weights
        }
    except:
        return None

def _calculate_retrievability(stability, elapsed_days, params):
    """Calculate retrievability using FSRS formula: R = (1 + factor * t / s) ^ decay"""
    if stability <= 0:
        return 0.0
    return (1 + params['factor'] * elapsed_days / stability) ** params['decay']

def _predict_next_review(stability, target_retention, params):
    """Predict days until retrievability drops below target retention."""
    if stability <= 0:
        return 1
    ivl = stability / params['factor'] * (target_retention ** (1/params['decay']) - 1)
    return max(1, int(round(ivl)))

def _fsrs_stability_after_success(stability, difficulty, retrievability, params):
    """
    Calculate new stability after a successful review using FSRS algorithm.

    FSRS formula: S' = S * SInc
    where SInc = 1 + e^w8 * (11-D) * S^(-w9) * (e^(w10*(1-R)) - 1)

    Args:
        stability: Current stability (days)
        difficulty: Card difficulty (1-10)
        retrievability: Retrievability at review time (0-1)
        params: FSRS parameters including weights
    """
    weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)
    w8 = weights[8] if len(weights) > 8 else 1.616
    w9 = weights[9] if len(weights) > 9 else 0.1544
    w10 = weights[10] if len(weights) > 10 else 1.0061

    # Clamp values to valid ranges
    difficulty = max(1, min(10, difficulty))
    retrievability = max(0.01, min(0.99, retrievability))
    stability = max(0.1, stability)

    # FSRS stability increase formula
    stability_increase = 1 + math.exp(w8) * (11 - difficulty) * (stability ** (-w9)) * (math.exp(w10 * (1 - retrievability)) - 1)

    # Allow natural growth; only guard against numerical pathologies
    stability_increase = max(1.0, min(100.0, stability_increase))

    return stability * stability_increase

def _fsrs_stability_after_fail(stability, difficulty, retrievability, params):
    """
    Calculate new stability after a failed review (lapse) using FSRS algorithm.

    FSRS formula: S' = w11 * D^(-w12) * ((S+1)^w13 - 1) * e^(w14*(1-R))
    Simplified: stability drops significantly on lapse
    """
    weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)
    w11 = weights[11] if len(weights) > 11 else 1.6358
    w12 = weights[12] if len(weights) > 12 else 0.1154

    difficulty = max(1, min(10, difficulty))

    # Simplified lapse formula - stability drops to a fraction
    new_stability = w11 * (difficulty ** (-w12)) * (stability ** 0.2)
    return max(0.5, min(stability * 0.5, new_stability))

def _simulate_new_card_reviews(per_day_schedule, simulation_days, params, today_date):
    """
    Simulate future review workload generated by introducing new cards on a per-weekday schedule.

    Uses a min-heap of (due_day, stability, difficulty) tuples.  Cards are always reviewed on
    their scheduled day (retrievability == target_retention at review time), which is how FSRS
    derives the next interval.

    per_day_schedule : {weekday_int: count}  (0=Mon … 6=Sun)
    simulation_days  : how many days forward to simulate
    params           : FSRS params dict from _get_fsrs_params()
    today_date       : date object for "today" (day 0)

    Returns {date_str: review_count} for future days only.
    """
    import heapq

    weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)
    s0 = (weights[2] if len(weights) > 2 else 3.126) * params.get('stability_scale', 1.0)
    d0 = 5.0
    target_retention = params['desired_retention']

    card_heap = []  # (due_day_offset, stability, difficulty)
    reviews_by_day = {}

    for day_offset in range(1, simulation_days + 1):
        day_date = today_date + timedelta(days=day_offset)
        weekday = day_date.weekday()  # 0=Mon … 6=Sun

        new_count = per_day_schedule.get(weekday, 0)
        for _ in range(new_count):
            first_ivl = max(1, int(round(s0)))
            heapq.heappush(card_heap, (day_offset + first_ivl, s0, d0))

        # Review every card that is due on or before today
        due_today = 0
        while card_heap and card_heap[0][0] <= day_offset:
            _, stability, difficulty = heapq.heappop(card_heap)
            due_today += 1
            new_stability = _fsrs_stability_after_success(
                stability, difficulty, target_retention, params)
            next_ivl = _predict_next_review(new_stability, target_retention, params)
            next_due = day_offset + next_ivl
            if next_due <= simulation_days:
                heapq.heappush(card_heap, (next_due, new_stability, difficulty))

        if due_today > 0:
            reviews_by_day[day_date.strftime("%Y-%m-%d")] = due_today

    return reviews_by_day

def _simulate_new_card_reviews_dated(per_date_counts, end_date, params, start_date):
    """
    Like _simulate_new_card_reviews but the new-card schedule is keyed by exact date
    (datetime.date objects) rather than weekday.  Used for backtesting.

    per_date_counts : {datetime.date: int}  new cards introduced on each date
    start_date      : datetime.date  first day of the simulation window
    end_date        : datetime.date  last day (exclusive) — typically today
    params          : FSRS params dict from _get_fsrs_params()

    Returns {datetime.date: int} predicted reviews per day.
    """
    import heapq

    weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)
    s0 = (weights[2] if len(weights) > 2 else 3.126) * params.get('stability_scale', 1.0)
    d0 = 5.0
    target_retention = params['desired_retention']
    total_days = (end_date - start_date).days

    card_heap = []
    reviews_by_date = {}

    for day_offset in range(total_days):
        current_date = start_date + timedelta(days=day_offset)

        new_count = per_date_counts.get(current_date, 0)
        for _ in range(new_count):
            first_ivl = max(1, int(round(s0)))
            heapq.heappush(card_heap, (day_offset + first_ivl, s0, d0))

        due_today = 0
        while card_heap and card_heap[0][0] <= day_offset:
            _, stability, difficulty = heapq.heappop(card_heap)
            due_today += 1
            new_stability = _fsrs_stability_after_success(
                stability, difficulty, target_retention, params)
            next_ivl = _predict_next_review(new_stability, target_retention, params)
            next_due = day_offset + next_ivl
            if next_due < total_days:
                heapq.heappush(card_heap, (next_due, new_stability, difficulty))

        if due_today > 0:
            reviews_by_date[current_date] = due_today

    return reviews_by_date

def _get_initial_stability(deck_id=None, rating="good"):
    """
    Get initial stability for new cards from FSRS weights.

    FSRS weights w[0]-w[3] are initial stabilities for Again, Hard, Good, Easy.
    """
    try:
        weights = _get_fsrs_weights(deck_id)
        rating_index = {"again": 0, "hard": 1, "good": 2, "easy": 3}.get(rating, 2)
        if weights and len(weights) > rating_index:
            return weights[rating_index]
        return 3.0  # Reasonable default
    except:
        return 3.0

def _settings_palette(night):
    if night:
        return dict(win="#1e1e20", side="#252528", card="#2b2b2e", border="#3a3a3e", inner="#333337",
                    text="#e8e8ea", sub="#9c9ca3", hover="rgba(255,255,255,0.06)", accent="#0a84ff",
                    match="rgba(10,132,255,0.28)")
    return dict(win="#f5f5f7", side="#ebebef", card="#ffffff", border="#dcdce1", inner="#e6e6ea",
                text="#1d1d1f", sub="#6e6e73", hover="rgba(0,0,0,0.05)", accent="#007aff",
                match="rgba(0,122,255,0.18)")


def _settings_css(night):
    """The settings window's look: a sidebar, pages of rounded cards, light or dark.
    The What's New dialog uses it too."""
    c = _settings_palette(night)
    return """
QDialog#hmSettings {{ background: {win}; }}
QWidget#hmSidebar {{ background: {side}; border-right: 1px solid {border}; }}
QLineEdit#hmSearch {{ padding: 4px 9px; min-height: 22px; border-radius: 7px; border: 1px solid {border}; background: {card}; color: {text}; }}
QListWidget#hmNav {{ background: transparent; border: none; outline: 0; font-size: 13px; }}
QListWidget#hmNav::item {{ padding: 6px 10px; margin: 1px 0px; border-radius: 6px; color: {text}; }}
QListWidget#hmNav::item:hover:!selected {{ background: {hover}; }}
QListWidget#hmNav::item:selected {{ background: {accent}; color: white; }}
QListWidget#hmNav::item:disabled {{ color: {sub}; font-size: 10px; font-weight: 600; padding: 12px 10px 2px 10px; background: transparent; }}
QScrollArea#hmPage, QWidget#hmPageBody {{ background: {win}; border: none; }}
QLabel#hmPageTitle {{ font-size: 21px; font-weight: 600; color: {text}; }}
QLabel#hmBrand {{ font-size: 16px; font-weight: 600; color: {text}; }}
QLabel#hmPageSub {{ color: {sub}; }}
QWidget#hmPageBody QGroupBox {{ background: {card}; border: 1px solid {border}; border-radius: 10px;
    margin-top: 24px; padding: 14px 12px 10px 12px; font-weight: 600; }}
QWidget#hmPageBody QGroupBox QWidget {{ font-weight: 400; }}
QWidget#hmPageBody QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 6px; top: 4px; color: {text}; }}
QWidget#hmPageBody QGroupBox QGroupBox {{ background: transparent; border: 1px solid {inner}; margin-top: 20px; }}
QFrame#hmCard {{ background: {card}; border: 1px solid {border}; border-radius: 10px; }}
QWidget#hmCardBody {{ background: transparent; }}
QWidget#hmPageBody QFrame#hmCard QGroupBox {{ background: transparent; border: 1px solid {inner}; margin-top: 20px; }}
QWidget#hmPageBody QPlainTextEdit {{ background: {win}; border: 1px solid {border}; border-radius: 8px;
    padding: 6px; color: {text}; }}
QFrame#hmPreview {{ border: 1px solid {border}; border-radius: 8px; background: {win}; }}
QToolButton#hmFold {{ border: none; color: {accent}; font-weight: 600; padding: 4px 2px; }}
QPushButton#hmDay {{ min-width: 26px; padding: 3px 4px; border-radius: 6px; border: 1px solid {border}; background: {card}; color: {text}; }}
QPushButton#hmDay:checked {{ background: {accent}; border-color: {accent}; color: white; }}
QLabel[hmMatch="true"], QCheckBox[hmMatch="true"], QRadioButton[hmMatch="true"], QPushButton[hmMatch="true"] {{ background: {match}; border-radius: 4px; }}
QWidget#hmFooter {{ background: {win}; border-top: 1px solid {border}; }}
QLabel#hmHelp {{ color: {sub}; border: 1px solid {sub}; border-radius: 7px; font-size: 10px; font-weight: 700; }}
QLabel#hmHelp:hover {{ color: {accent}; border-color: {accent}; }}
QToolTip {{ background: {card}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 2px 4px; }}
""".format(**c)


@functools.lru_cache(maxsize=32)
def _theme_thumb(path, w, h):
    """A theme card's photo, scaled to the card: decoding a full-size photo takes ~30 ms,
    so it's done when the card is first drawn, and once a session."""
    img = QImage(path)
    if img.isNull():
        return None
    return img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)


class _FirstShow(QObject):
    def __init__(self, widget, fn):
        super().__init__(widget)
        self.fn = fn
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and self.fn is not None:
            fn, self.fn = self.fn, None
            try:
                fn()
            except Exception:
                pass
            obj.removeEventFilter(self)
        return False


def _when_first_shown(widget, fn):
    """Run fn the first time widget is shown (e.g. its Settings page is opened)."""
    _FirstShow(widget, fn)


class _LazyCombo(QComboBox):
    """An editable combo box whose items (items() -> list of str) are added the first time
    it's opened or focused. Its text can be set before that."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = items

    def fill(self):
        if self._items is None:
            return
        items, self._items = self._items, None
        text = self.currentText()
        self.blockSignals(True)     # the text stays what it was; nothing to react to
        try:
            self.addItems(items())
            self.setCurrentText(text)
        finally:
            self.blockSignals(False)

    def showPopup(self):
        self.fill()
        super().showPopup()

    def focusInEvent(self, e):
        self.fill()
        super().focusInEvent(e)


class _ThemeCard(QWidget):
    """A theme in the gallery: a small heatmap, the deck pills, and the name, drawn in the
    theme's colors for Anki's current mode."""
    W, H = 136, 108
    # cell levels (0 = no reviews … 4 = busiest); the last columns are the forecast
    _LEVELS = ["0123432101", "1234321012", "2343210123", "1232101234", "0121012343"]
    _AHEAD = (0.9, 0.7, 0.8, 0.6, 0.75)    # forecast shading, first forecast column
    shade = False                         # Shade forecast by cards due (set by Settings)

    def __init__(self, key, name, colors, night, on_pick, photo_path=None, parent=None):
        super().__init__(parent)
        self.key, self.name, self.colors, self.night, self.on_pick = key, name, colors, night, on_pick
        self.selected = False
        self.photo = None
        self.photo_path = photo_path     # decoded when first drawn (_theme_thumb), not with the window
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def set_colors(self, colors):
        self.colors = colors
        self.update()

    def set_selected(self, on):
        self.selected = on
        self.update()

    def mousePressEvent(self, e):
        self.on_pick(self.key)

    def paintEvent(self, e):
        c = self.colors
        night = self.night
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#262629" if night else "#ffffff")
        edge = QColor("#0a84ff" if night else "#007aff") if self.selected else QColor("#3a3a3e" if night else "#dcdce1")
        p.setPen(QPen(edge, 2.2 if self.selected else 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(1.5, 1.5, self.W - 3, self.H - 3), 10, 10)
        if self.photo is None and self.photo_path:
            self.photo = _theme_thumb(self.photo_path, self.W, self.H)
            if self.photo is None:
                self.photo_path = None
        if self.photo is not None:
            # the photo behind a frosted panel, like the heatmap on that background
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(2, 2, self.W - 4, self.H - 4), 9, 9)
            p.save()
            p.setClipPath(clip)
            p.drawImage(QPointF((self.W - self.photo.width()) / 2, (self.H - self.photo.height()) / 2), self.photo)
            p.restore()
            panel = QColor(bg)
            panel.setAlphaF(0.80)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(panel)
            p.drawRoundedRect(QRectF(6, 6, self.W - 12, 78), 7, 7)
            if self.selected:
                p.setPen(QPen(edge, 2.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(1.5, 1.5, self.W - 3, self.H - 3), 10, 10)
        empty = QColor(c["empty_color_night"] if night else c["empty_color"])
        base = QColor(c["base_color"])
        cell, gap, x0, y0 = 8, 2.2, 12, 11
        p.setPen(Qt.PenStyle.NoPen)
        for r, row in enumerate(self._LEVELS):
            for col, ch in enumerate(row + "00"):
                x, y = x0 + col * (cell + gap), y0 + r * (cell + gap)
                if col >= 10 and self.shade:
                    p.setBrush(QColor(c.get("forecast_shade_color") or DEFAULT_CONFIG["forecast_shade_color"]))
                    p.setOpacity(self._AHEAD[r] * (1 if col == 10 else 0.7))
                elif col >= 10:
                    p.setBrush(QColor(c["forecast_color"]))
                    p.setOpacity(0.55 if r % 2 else 0.35)
                else:
                    lvl = int(ch)
                    if lvl == 0:
                        p.setBrush(empty)
                        p.setOpacity(1)
                    else:
                        p.setBrush(base)
                        p.setOpacity((0.28, 0.52, 0.76, 1.0)[lvl - 1])
                p.drawRoundedRect(QRectF(x, y, cell, cell), 2.5, 2.5)
        p.setOpacity(1)
        tx, ty = x0 + 9 * (cell + gap), y0 + 2 * (cell + gap)
        p.setPen(QPen(QColor(c["today_color"]), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(tx - 1, ty - 1, cell + 2, cell + 2), 3, 3)
        # the deck list's count pills
        f = p.font()
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        px = x0
        for key, n in (("pill_new_color", "24"), ("pill_learn_color", "3"), ("pill_due_color", "180")):
            w = 14 + 6 * len(n)
            col = QColor(c[key])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(px, 66, w, 14), 7, 7)
            p.setPen(QColor(themes.readable_text(c[key])))
            p.drawText(QRectF(px, 66, w, 14), Qt.AlignmentFlag.AlignCenter, n)
            px += w + 5
        f.setPixelSize(12)
        f.setBold(False)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        name_rect = QRectF(x0, 87, self.W - 2 * x0, 16)
        if self.photo is not None:
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(name_rect.translated(0, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
            p.setPen(QColor("#ffffff"))
        else:
            p.setPen(QColor("#e8e8ea" if night else "#1d1d1f"))
        p.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        p.end()


class _BrowserPreview(QFrame):
    """Sample rows painted by the browser's own row painter (ModernBrowserDelegate), so the
    preview is exactly what the card browser shows: cloze colors, state tints and symbols,
    flags, the selection, row spacing and the tags column."""
    ROWS = [  # sort field, card column, tags, card state
        ("The {{c1::mitral valve}} closes at {{c2::S1}}", "Due today", "#AK_Step1::Cardio::Valves", {}),
        ("{{c1::Staph aureus}} is the top cause of {{c2::acute endocarditis}}", "New", "#AK_Step1::Micro::Bacteria", {}),
        ("Loop diuretics act on the {{c1::thick ascending limb}}", "Suspended", "#AK_Step1::Renal::Diuretics", {"suspended": True}),
        ("{{c1::Ketamine}} is an {{c2::NMDA}} antagonist", "Buried", "#AK_Step1::Pharm::Anesthesia", {"buried": True}),
        ("Kawasaki disease risks {{c1::coronary aneurysms}}", "Marked", "#AK_Step1::Peds::Vasculitis", {"marked": True}),
        ("Most common site of a {{c1::berry aneurysm}}", "Red flag", "#AK_Step1::Neuro::Vascular", {"flag": 1}),
        ("{{c1::B12}} deficiency: {{c2::subacute combined degeneration}}", "Blue flag", "#AK_Step1::Heme::Anemia", {"flag": 4}),
        ("{{c1::Digoxin}} inhibits the {{c2::Na/K ATPase}}", "Selected", "#AK_Step1::Cardio::Pharm", {}),
    ]
    HEIGHTS = {"comfortable": 38, "compact": 30, "tight": 24}
    HEADER_PAD = {"comfortable": "10px 12px", "compact": "8px 10px", "tight": "6px 8px"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hmBrowserPreview")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(len(self.ROWS), 3)
        self.table.setHorizontalHeaderLabels(["Sort Field", "Card", "Tags"])
        for r, (field, card, tags, _state) in enumerate(self.ROWS):
            for c, text in enumerate((field, card, tags)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.selectRow(len(self.ROWS) - 1)
        # a picture, not a control: clicks don't change the selection
        self.table.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.table.horizontalHeader().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 108)
        self.table.setColumnWidth(2, 170)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.table)
        self.delegate = None

    def apply(self, colors, spacing, icons, tags):
        rows = self.ROWS

        class Delegate(ModernBrowserDelegate):
            def _get_card_id_from_index(self, index):
                return index.row()

            def _get_card_state(self, row):
                state = {"suspended": False, "buried": False, "marked": False, "flag": 0}
                state.update(rows[row][3] if row is not None and row < len(rows) else {})
                return state

            def _column_key(self, index):
                return "noteTags" if index.column() == 2 else None

        d = Delegate(self.table, colors.get("selection", "#8e44ad"))
        d.color_theme = colors
        d.show_state_icons = icons
        d.tag_display = tags
        self.delegate = d               # keep a reference: the table doesn't own it
        self.table.setItemDelegate(d)
        h = self.HEIGHTS.get(spacing, 38)
        self.table.verticalHeader().setDefaultSectionSize(h)
        self.table.setStyleSheet(f"""
            QTableWidget {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 13px;
                background-color: {colors['bg_primary']}; color: {colors['text_normal']};
                border: 1px solid {colors.get('bg_secondary', colors['bg_primary'])}; border-radius: 8px; }}
            QHeaderView {{ background-color: {colors['bg_primary']}; border: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
            QHeaderView::section {{ background-color: {colors['bg_primary']}; border: none;
                border-bottom: 2px solid {colors['selection']}; padding: {self.HEADER_PAD.get(spacing, '10px 12px')};
                font-weight: 600; font-size: 11px; color: {colors['text_normal']}; }}
        """)
        header_h = self.table.horizontalHeader().sizeHint().height()
        self.table.setFixedHeight(header_h + h * len(rows) + 4)
        self.setFixedHeight(self.table.height())      # so the page makes room when the spacing changes
        self.table.viewport().update()


class _HtmlPreview(QFrame):
    """A small web view showing make_html(). It's created the first time its page is
    shown (so opening Settings stays quick) and redrawn shortly after a setting changes."""

    def __init__(self, height, make_html, parent=None, base_dir=None, zoom=1.0):
        super().__init__(parent)
        self.setObjectName("hmPreview")
        self.make_html = make_html
        self.zoom = zoom
        self.base_dir = base_dir        # a folder the page's relative links (images) resolve against
        self.view = None
        self.setFixedHeight(height)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(1, 1, 1, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._draw)

    def showEvent(self, e):
        super().showEvent(e)
        if self.view is None:
            try:
                self.view = QWebEngineView(self)
                self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
                self.view.setZoomFactor(self.zoom)
                self._lay.addWidget(self.view)
            except Exception:
                self.view = None
                return
            self._draw()

    def refresh(self, *_args):
        if self.view is not None:
            self._timer.start()

    def _draw(self):
        if self.view is not None:
            try:
                base = self.base_dir() if callable(self.base_dir) else self.base_dir
                if base:
                    self.view.setHtml(self.make_html(), QUrl.fromLocalFile(os.path.join(base, "")))
                else:
                    self.view.setHtml(self.make_html())
            except Exception:
                traceback.print_exc()

    def run_js(self, js):
        if self.view is not None:
            self.view.page().runJavaScript(js)


class _WheelGuard(QObject):
    """Sends a wheel event over an unfocused control to the page's scroll area."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel or obj.hasFocus():
            return False
        area = obj.parent()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parent()
        if area is not None:
            QApplication.sendEvent(area.verticalScrollBar(), event)
        return True


class HeatmapSettingsDialog(QDialog):
    _last_page = 0          # reopen on the page you were last on (this session)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hmSettings")
        self.setWindowTitle("Elemental Settings")
        self.setMinimumSize(780, 520)
        self.resize(920, 660)
        self.cfg = get_config()
        self.setWindowIcon(brand.icon(self.cfg.get("base_color", "#8e44ad"), _is_dark_mode()))
        self.color_btns = {}
        self.color_inputs = {}
        self.deck_checkboxes = {}
        self.setup_ui()

    def setup_ui(self):
        night = _is_dark_mode()
        self.setStyleSheet(_settings_css(night))

        # The sections are built as before (same controls, same saving) and then
        # arranged into the sidebar's pages.
        general = self.create_general_tab()
        appearance = self.create_appearance_tab()
        graphs = self.create_graphs_tab()
        time_tab = self.create_time_tab()
        pill_tab = self.create_review_pill_tab()
        day_tab = self.create_day_tab()
        bg_tab = self.create_background_tab()
        reminders_tab = self.create_reminders_tab()
        browser_tab = self.create_browser_tab()

        def groups(tab):
            inner = tab.widget() if isinstance(tab, QScrollArea) else tab
            return {g.title(): g for g in inner.findChildren(QGroupBox, options=Qt.FindChildOption.FindDirectChildrenOnly)}

        def unwrap(tab):
            """A whole tab, as one card."""
            inner = tab.takeWidget() if isinstance(tab, QScrollArea) else tab
            inner.setAutoFillBackground(False)
            inner.setObjectName("hmCardBody")       # transparent on the card (only this panel, not its controls)
            card = QFrame()
            card.setObjectName("hmCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 6, 8, 6)
            cl.addWidget(inner)
            return card

        def titled(tab, title):
            """A whole tab as one titled group, like the others on a page."""
            inner = tab.takeWidget() if isinstance(tab, QScrollArea) else tab
            inner.setAutoFillBackground(False)
            inner.setObjectName("hmCardBody")
            box = QGroupBox(title)
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(inner)
            return box

        G, A, S = groups(general), groups(appearance), groups(graphs)
        # Anki's "Studied N cards" line is the deck list's, not the theme's
        A["Deck Browser"].layout().addWidget(self.chk_replace)
        for g, title in ((G["Heatmap Settings"], "Heatmap"), (A["Heatmap"], "Style"),
                         (A["Deck Browser"], "Deck List"), (A["Custom Heatmap Modes"], "Extra Views"),
                         (A["Colors"], "")):
            g.setTitle(title)

        pages = [
            (None, "General", "The default view and the extra views, how much history to show, and the stats bar.",
             [G["Heatmap Settings"], A["Custom Heatmap Modes"], G["Stats Bar"]]),
            ("APPEARANCE", "Theme", "Colors for the heatmap, its graphs and the deck list's pills, and a photo behind "
             "them. Each theme has a light and a dark version that follows Anki.",
             [self._theme_gallery(night), A["Heatmap"], A["Text"], titled(bg_tab, "Background"),
              self._colors_fold(A["Colors"])]),
            ("APPEARANCE", "Deck List", "The deck list next to the heatmap.", [A["Deck Browser"]]),
            ("APPEARANCE", "Reminders", "One pill under your decks that rolls through these, a few seconds each. "
             "Each shows only when it applies.", [unwrap(reminders_tab)]),
            ("APPEARANCE", "AnKing Cards", "Restyle your AnKing cards with a cleaner reading layout.",
             [self.create_anking_page(night)]) if self._anking_found() else None,
            ("HEATMAP", "Data", "What each view counts, and which decks the heatmap covers.",
             [G["Thresholds"], G["Deck Filter"], G["Retention Deck Scope"]]),
            ("HEATMAP", "Graphs", "The graph panel under the heatmap.", [S["Graph Panel"]]),
            ("HEATMAP", "Forecast", "The FSRS forecast of upcoming reviews.",
             [S["FSRS Forecast Simulation"], S["Forecast Deck"], self.validate_btn]),
            ("HEATMAP", "Day Details", "Click a day on the heatmap to see it up close. STATS by the heatmap's views shows longer stretches.",
             [unwrap(day_tab)]),
            ("REVIEWING", "Time Left & Focus", "How long today's cards will take, and your focus score.", [unwrap(time_tab)]),
            ("REVIEWING", "Live Stats", "Your retention, time and focus in a corner of the review screen.", [unwrap(pill_tab)]),
            ("BROWSER", "Card Browser", "The look of the card browser and note editor.", [unwrap(browser_tab)]),
            ("HELP", "Feedback", "Found a bug or have an idea? Send it straight to the developer.",
             [self.create_feedback_page()]),
            ("HELP", "Version History", "What each update added.", self.create_history_page(night)),
        ]

        pages = [p for p in pages if p]
        sidebar = QWidget()
        sidebar.setObjectName("hmSidebar")
        sidebar.setFixedWidth(200)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(10, 12, 10, 10)
        sv.setSpacing(6)
        _base, _night = self.cfg.get("base_color", "#8e44ad"), _is_dark_mode()
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 2, 6, 8)
        brand_row.setSpacing(9)
        brand_row.addWidget(brand.LogoWidget(28, _base, _night, animate=True,
                                             motion=self.cfg.get("animations", "system")))
        brand_name = QLabel("Elemental")
        brand_name.setObjectName("hmBrand")
        brand_row.addWidget(brand_name)
        brand_row.addStretch()
        sv.addLayout(brand_row)
        self.search = QLineEdit()
        self.search.setObjectName("hmSearch")
        self.search.setPlaceholderText("Search settings")
        self.search.setClearButtonEnabled(True)
        sv.addWidget(self.search)
        self.nav = QListWidget()
        self.nav.setObjectName("hmNav")
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sv.addWidget(self.nav, 1)

        self.stack = QStackedWidget()
        self._pages = []        # (nav item, scroll area, body, section header item)
        header_items = {}
        for section, title, sub, parts in pages:
            if section and section not in header_items:
                h = QListWidgetItem(section)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                self.nav.addItem(h)
                header_items[section] = h
            item = QListWidgetItem(title)
            self.nav.addItem(item)
            body = QWidget()
            body.setObjectName("hmPageBody")
            v = QVBoxLayout(body)
            v.setContentsMargins(26, 20, 26, 22)
            v.setSpacing(10)
            t = QLabel(title)
            t.setObjectName("hmPageTitle")
            v.addWidget(t)
            d = QLabel(sub)
            d.setObjectName("hmPageSub")
            d.setWordWrap(True)
            v.addWidget(d)
            for part in parts:
                v.addWidget(part)
            v.addStretch()
            scroll = QScrollArea()
            scroll.setObjectName("hmPage")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(body)
            self.stack.addWidget(scroll)
            self._pages.append((item, scroll, body, header_items.get(section)))

        self.nav.currentItemChanged.connect(self._on_nav)
        self.search.textChanged.connect(self._on_search)

        footer = QWidget()
        footer.setObjectName("hmFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.addWidget(brand.LogoWidget(14, _base, _night))
        fl.addSpacing(2)
        ver = QLabel(f"Elemental {VERSION}")
        ver.setObjectName("hmPageSub")
        fl.addWidget(ver)
        fl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        fl.addWidget(btns)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self.stack, 1)
        rv.addWidget(footer)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(right, 1)

        help_text.attach(self)

        # Scrolling the page with the pointer over a dropdown, number box or slider
        # scrolls the page instead of changing that setting, unless you clicked into it.
        self._wheel_guard = _WheelGuard(self)
        for kind in (QComboBox, QAbstractSpinBox, QSlider):
            for w in self.findChildren(kind):
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self._wheel_guard)

        # macOS sizes number boxes for the digits alone, cutting off units like "39 wks":
        # make each one wide enough for its widest value, unit included.
        for box in self.findChildren(QAbstractSpinBox):
            if isinstance(box, QDoubleSpinBox):
                widest = f"{box.prefix()}{box.maximum():.{box.decimals()}f}{box.suffix()}"
            elif isinstance(box, QSpinBox):
                widest = f"{box.prefix()}{box.maximum()}{box.suffix()}"
            else:
                continue
            if box.specialValueText() and len(box.specialValueText()) > len(widest):
                widest = box.specialValueText()
            box.setMinimumWidth(max(box.minimumWidth(), box.fontMetrics().horizontalAdvance(widest) + 46))

        last = min(max(0, HeatmapSettingsDialog._last_page), len(self._pages) - 1)
        self.nav.setCurrentItem(self._pages[last][0])

    # ── version history ─────────────────────────────────────────────
    def create_history_page(self, night):
        return [_release_card(r, night, installed=r["version"] == VERSION) for r in changelog.RELEASES]

    # ── AnKing cards ────────────────────────────────────────────────
    def _anking_found(self):
        """AnKingOverhaul note types with notes; the AnKing Cards page only shows up when there are some."""
        if not hasattr(self, "_ak_found"):
            try:
                ok = mw.col is not None and anking_style.available()
                self._ak_found = anking_style.targets(mw.col) if ok else []
            except Exception:
                self._ak_found = []
        return self._ak_found

    def create_anking_page(self, night):
        card = QFrame()
        card.setObjectName("hmCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)
        found = self._anking_found()

        self._ak_targets = found
        self._ak_note = None
        self._ak_after = True
        self._ak_back = True

        intro = QLabel("<b>Clean Reading Theme</b> puts the answer and Extra in one calm reading column, centers "
                       "short answers and stacked lists, turns clozes into soft pills, and keeps tags quiet until "
                       "you hover them. <b>Beautify Text Dashes</b> turns lines that start with a dash into "
                       "proper bullets.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.ak_parts = {}
        for key, tip in (("theme", "The card styling plus the small script in the card templates it needs."),
                         ("beautify", "A small script in the card templates.")):
            chk = QCheckBox(anking_style.PARTS[key]["name"])
            chk.setChecked(True)
            chk.setToolTip(tip)
            self.ak_parts[key] = chk
            v.addWidget(chk)

        self.ak_types = {}
        if len(found) > 1:
            v.addWidget(QLabel("Note types:"))
        for nt, n in found:
            chk = QCheckBox(f"{nt['name']}  ·  {n:,} notes")
            chk.setChecked(True)
            chk.setVisible(len(found) > 1)
            self.ak_types[nt["id"]] = chk
            v.addWidget(chk)
        if len(found) == 1:
            nt, n = found[0]
            one = QLabel(f"For <b>{nt['name']}</b> · {n:,} notes")
            one.setStyleSheet("color: gray;")
            v.addWidget(one)

        # preview: one of their own cards, now and with the changes
        def chosen_types():
            return [nt for nt, _n in self._ak_targets if self.ak_types[nt["id"]].isChecked()]

        def chosen_parts():
            return [k for k, c in self.ak_parts.items() if c.isChecked()]

        def preview_html():
            types = chosen_types() or [self._ak_targets[0][0]]
            nt = mw.col.models.get(types[0]["id"]) or types[0]
            if self._ak_note is None:
                self._ak_note = anking_style.sample_note(mw.col, nt)
            if self._ak_note is None:
                return "<body style='font:13px sans-serif;color:gray;padding:30px'>No cards of this type to show.</body>"
            use = anking_style.applied(nt, chosen_parts()) if self._ak_after else nt
            html, css = anking_style.render(mw.col, self._ak_note, use, self._ak_back)
            dark = _is_dark_mode()
            return (f"<!doctype html><html class='{'night-mode' if dark else ''}'><head><meta charset='utf-8'>"
                    f"<style>body{{margin:20px;overflow-x:hidden}}</style><style>{css}</style></head>"
                    f"<body class='card card1 isMac {'nightMode night_mode' if dark else ''}'><div id='qa'>{html}</div>"
                    f"<script>function pycmd(){{}}</script></body></html>")

        # zoomed out so a whole card, Extra and its bullets included, fits
        self.ak_preview = _HtmlPreview(460, preview_html, base_dir=lambda: mw.col.media.dir() if mw.col else None,
                                       zoom=0.68)

        def seg(labels, current, on_change):
            row = QHBoxLayout()
            row.setSpacing(0)
            group = QButtonGroup(card)
            for n, label in enumerate(labels):
                b = QPushButton(label)
                b.setCheckable(True)
                b.setChecked(n == current)
                b.setAutoDefault(False)
                group.addButton(b, n)
                row.addWidget(b)
            group.idClicked.connect(on_change)
            return row

        bar = QHBoxLayout()
        bar.addLayout(seg(["Now", "With these changes"], 1, lambda i: (setattr(self, "_ak_after", i == 1), self.ak_preview.refresh())))
        bar.addSpacing(12)
        bar.addLayout(seg(["Front", "Back"], 1, lambda i: (setattr(self, "_ak_back", i == 1), self.ak_preview.refresh())))
        bar.addStretch()
        v.addLayout(bar)
        v.addWidget(self.ak_preview)

        self.ak_status = QLabel()
        self.ak_status.setWordWrap(True)
        v.addWidget(self.ak_status)

        btns = QHBoxLayout()
        self.ak_apply = QPushButton("Apply to my AnKing cards")
        self.ak_remove = QPushButton("Remove")
        for b in (self.ak_apply, self.ak_remove):
            b.setAutoDefault(False)
        btns.addWidget(self.ak_apply)
        btns.addWidget(self.ak_remove)
        btns.addStretch()
        v.addLayout(btns)

        note = QLabel("Changes go below AnkiHub's protected line, so AnKing updates keep them. "
                      "Edit → Undo works right after, Remove takes them out any time, and a backup is saved first.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        v.addWidget(note)

        # for the author: the cards that hold the original can refresh the shared copy
        originals = [nt for nt, _n in found if any(anking_style.status(nt, k) == "original" for k in anking_style.PARTS)]
        if originals:
            refresh = QPushButton("Update the shared copy from my cards")
            refresh.setToolTip("Copies your current Clean Reading Theme and scripts into the add-on,\n"
                               "so the next version you package shares them.")
            refresh.setAutoDefault(False)

            def do_refresh():
                files = anking_style.refresh_bundle(mw.col.models.get(originals[0]["id"]))
                tooltip(f"Updated {len(files)} files in the add-on.", parent=self)
                self.ak_preview.refresh()
            refresh.clicked.connect(do_refresh)
            v.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)

        word = {"applied": "on your cards", "original": "your own original", "none": "not added"}

        def sync(*_):
            types = [mw.col.models.get(nt["id"]) or nt for nt in chosen_types()]
            parts = chosen_parts()
            lines = []
            for k in anking_style.ORDER:
                states = {anking_style.status(nt, k) for nt in types}
                lines.append(f"{anking_style.PARTS[k]['name']}: " + (", ".join(word[s] for s in sorted(states)) or "–"))
            self.ak_status.setText("\n".join(lines))
            self.ak_status.setStyleSheet("color: gray;")
            can_add = any(anking_style.status(nt, k) != "original" for nt in types for k in parts)
            self.ak_apply.setEnabled(bool(types and parts and can_add))
            self.ak_remove.setEnabled(any(anking_style.status(nt, k) == "applied" for nt in types for k in parts))

        def change(add):
            types = [mw.col.models.get(nt["id"]) for nt in chosen_types()]
            parts = chosen_parts()
            names = " and ".join(anking_style.PARTS[k]["name"] for k in parts)
            notes = sum(n for nt, n in self._ak_targets if self.ak_types[nt["id"]].isChecked())
            if add and not askUser(f"Add {names} to {len(types)} note type{'s' if len(types) != 1 else ''} "
                                   f"({notes:,} notes)?\n\nYou can undo it with Edit → Undo, or take it out "
                                   f"here with Remove.", parent=self):
                return
            new = []
            for nt in types:
                anking_style.backup(nt)
                new.append(anking_style.applied(nt, parts) if add else anking_style.removed(nt, parts))
            label = f"{'Apply' if add else 'Remove'} {names}"

            def done(*_):
                self._ak_note = None
                sync()
                self.ak_preview.refresh()
                tooltip(("Added " if add else "Removed ") + names + ".", parent=self)

            try:
                from aqt.operations import CollectionOp
                CollectionOp(parent=self, op=lambda c: anking_style.save(c, new, label)).success(done).run_in_background()
            except Exception:
                anking_style.save(mw.col, new, label)
                done()

        self.ak_apply.clicked.connect(lambda: change(True))
        self.ak_remove.clicked.connect(lambda: change(False))
        for c in list(self.ak_parts.values()) + list(self.ak_types.values()):
            c.toggled.connect(sync)
            c.toggled.connect(self.ak_preview.refresh)
        sync()
        return card

    # ── feedback ────────────────────────────────────────────────────
    def create_feedback_page(self):
        card = QFrame()
        card.setObjectName("hmCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        self.fb_kind = QComboBox()
        self.fb_kind.addItem("Bug", "bug")
        self.fb_kind.addItem("Idea", "idea")
        self.fb_kind.addItem("Something else", "other")
        form.addRow("About:", self.fb_kind)
        self.fb_contact = QLineEdit()
        self.fb_contact.setPlaceholderText("Only if you'd like a reply")
        form.addRow("Email:", self.fb_contact)
        v.addLayout(form)

        self.fb_message = QPlainTextEdit()
        self.fb_message.setPlaceholderText("What happened, or what would you like? For a bug, what you did "
                                           "just before helps a lot.")
        self.fb_message.setMinimumHeight(150)
        v.addWidget(self.fb_message)

        diag_row = QHBoxLayout()
        self.fb_diag = QCheckBox("Include version info and my add-on list")
        self.fb_diag.setChecked(True)
        self.fb_diag.setToolTip("The add-on, Anki, OS and Qt versions, which of the add-on's features are on,\n"
                                "and your other add-ons. Never your cards, decks or reviews.")
        diag_row.addWidget(self.fb_diag)
        show = QToolButton()
        show.setObjectName("hmFold")
        show.setText("What's sent")
        show.setCheckable(True)
        diag_row.addWidget(show)
        diag_row.addStretch()
        v.addLayout(diag_row)
        self.fb_diag_view = QLabel()
        self.fb_diag_view.setWordWrap(True)
        self.fb_diag_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fb_diag_view.setStyleSheet("color: gray; font-family: Menlo, Consolas, monospace; font-size: 11px;")
        self.fb_diag_view.setVisible(False)
        v.addWidget(self.fb_diag_view)

        send_row = QHBoxLayout()
        self.fb_status = QLabel()
        self.fb_status.setWordWrap(True)
        send_row.addWidget(self.fb_status, 1)
        self.fb_send = QPushButton("Send feedback")
        self.fb_send.setDefault(False)
        self.fb_send.setAutoDefault(False)
        send_row.addWidget(self.fb_send)
        v.addLayout(send_row)

        def diag_text():
            d = feedback.diagnostics(self.cfg, VERSION)
            on = [k.replace("_", " ") for k, val in d.pop("features").items() if val]
            others = d.pop("other_addons")
            lines = [f"{k.replace('_', ' ')}: {val}" for k, val in d.items()]
            lines.append("features on: " + (", ".join(on) or "none"))
            lines.append(f"other add-ons ({len(others)}): " + (", ".join(others) or "none"))
            return "\n".join(lines)

        def toggle_view(on):
            self.fb_diag_view.setText(diag_text())
            self.fb_diag_view.setVisible(on)

        def sync(*_):
            n = len(self.fb_message.toPlainText().strip())
            self.fb_send.setEnabled(n >= 3 and getattr(self, "_fb_sending", False) is False)

        def sent(ok, err):
            self._fb_sending = False
            if ok:
                self.fb_message.clear()
                self.fb_status.setStyleSheet("color: #30a46c;")
                self.fb_status.setText("Sent. Thank you!")
            else:
                self.fb_status.setStyleSheet("color: #e5484d;")
                self.fb_status.setText(err)
            sync()

        def send():
            msg = self.fb_message.toPlainText().strip()
            if len(msg) < 3:
                return
            self._fb_sending = True
            self.fb_send.setEnabled(False)
            self.fb_status.setStyleSheet("color: gray;")
            self.fb_status.setText("Sending…")
            diag = feedback.diagnostics(self.cfg, VERSION) if self.fb_diag.isChecked() else None
            feedback.send(self.fb_kind.currentData(), msg, self.fb_contact.text().strip(), diag, VERSION, sent)

        show.toggled.connect(toggle_view)
        self.fb_message.textChanged.connect(sync)
        self.fb_send.clicked.connect(send)
        sync()
        return card

    # ── sidebar and search ──────────────────────────────────────────
    def _on_nav(self, item, _prev=None):
        for n, (it, scroll, _body, _h) in enumerate(self._pages):
            if it is item:
                self.stack.setCurrentIndex(n)
                HeatmapSettingsDialog._last_page = n
                self._scroll_to_match(n)
                return

    @staticmethod
    def _search_texts(w):
        if w.objectName() == "hmHelp":
            return ""
        texts = []
        if isinstance(w, QGroupBox):
            texts.append(w.title())
        elif isinstance(w, (QLabel, QAbstractButton)):
            texts.append(w.text())
        elif isinstance(w, QComboBox):
            texts.extend(w.itemText(i) for i in range(w.count()))
        if w.toolTip():
            texts.append(w.toolTip())
        return " ".join(texts).lower()

    def _on_search(self, text):
        q = text.strip().lower()
        self._matches = {}
        strong = set()      # pages where the word is in a visible label, not just a tooltip or list item
        for n, (item, _scroll, body, _h) in enumerate(self._pages):
            hits = []
            for w in body.findChildren(QWidget):
                hit = bool(q) and q in self._search_texts(w)
                if w.property("hmMatch") != (hit and isinstance(w, (QLabel, QAbstractButton))):
                    w.setProperty("hmMatch", hit and isinstance(w, (QLabel, QAbstractButton)))
                    w.style().unpolish(w)
                    w.style().polish(w)
                if hit:
                    hits.append(w)
                    if w.isVisibleTo(body) and isinstance(w, (QLabel, QAbstractButton, QGroupBox)) and q in (
                            w.title() if isinstance(w, QGroupBox) else w.text()).lower():
                        strong.add(n)
            self._matches[n] = hits
            item.setHidden(bool(q) and not hits and q not in item.text().lower())
        for _item, _s, _b, header in self._pages:
            if header is not None:
                header.setHidden(all(it.isHidden() for it, _s2, _b2, h in self._pages if h is header))
        cur = self.stack.currentIndex()
        if self._pages[cur][0].isHidden() or (strong and cur not in strong):
            best = [n for n in range(len(self._pages)) if n in strong] or \
                   [n for n, (it, *_r) in enumerate(self._pages) if not it.isHidden()]
            if best:
                self.nav.setCurrentItem(self._pages[best[0]][0])
        else:
            self._scroll_to_match(cur)

    def _scroll_to_match(self, n):
        hits = getattr(self, "_matches", {}).get(n)
        if hits:
            visible = [w for w in hits if isinstance(w, (QLabel, QAbstractButton, QComboBox))] or hits
            self._pages[n][1].ensureWidgetVisible(visible[0], 40, 60)

    # ── theme gallery ───────────────────────────────────────────────
    def _theme_gallery(self, night):
        box = QFrame()
        box.setObjectName("hmCard")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(8)
        self._night = night
        self._saved_colors = get_saved_colors()
        self._theme_key = self.cfg.get("heatmap_theme", themes.CUSTOM)
        if self._theme_key != themes.CUSTOM and self._theme_key not in themes.THEMES:
            self._theme_key = themes.CUSTOM
        self._theme_cards = []
        photo_entries = [(k, t["name"], themes.colors(k, night), background.builtin_file(t["photo"]))
                         for k, t in themes.THEMES.items() if t.get("photo")]
        color_entries = [(themes.CUSTOM, "My colors", self._saved_colors, None)] + \
                        [(k, t["name"], themes.colors(k, night), None)
                         for k, t in themes.THEMES.items() if not t.get("photo")]
        for title, note, entries in (
                ("Photo themes", "Also sets the photo as your background (Background page).", photo_entries),
                ("Color themes", "", color_entries)):
            head = QLabel(f"<b>{title}</b>" + (f"&nbsp;&nbsp;<span style='color:gray'>{note}</span>" if note else ""))
            outer.addWidget(head)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            for n, (key, name, colors, photo_path) in enumerate(entries):
                card = _ThemeCard(key, name, colors, night, self._pick_theme, photo_path)
                if key == themes.CUSTOM:
                    card.setToolTip("Your own colors (Customize colors below).")
                grid.addWidget(card, n // 4, n % 4)
                self._theme_cards.append(card)
            grid.setColumnStretch(4, 1)
            outer.addLayout(grid)
            outer.addSpacing(4)
        for card in self._theme_cards:
            card.set_selected(card.key == self._theme_key)
        return box

    def _colors_fold(self, colors_group):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(0)
        btn = QToolButton()
        btn.setObjectName("hmFold")
        btn.setCheckable(True)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setArrowType(Qt.ArrowType.RightArrow)
        btn.setText("Customize colors")
        btn.setToolTip("Change any color. Changing one switches the theme to My colors.")
        v.addWidget(btn)
        v.addWidget(colors_group)
        colors_group.setVisible(False)

        def fold(on):
            colors_group.setVisible(on)
            btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        btn.toggled.connect(fold)
        # typing or picking a color makes it your own
        for key, inp in self.color_inputs.items():
            inp.textEdited.connect(lambda *_a: self._colors_edited())
        self._colors_fold_btn = btn
        return wrap

    def _pick_theme(self, key):
        self._theme_key = key
        for card in self._theme_cards:
            card.set_selected(card.key == key)
        vals = self._saved_colors if key == themes.CUSTOM else themes.colors(key, self._night)
        for k, inp in self.color_inputs.items():
            if k in vals and inp.text() != vals[k]:
                inp.setText(vals[k])
                self.on_color_hex_changed(k, vals[k])
        stem = themes.photo(key)
        if stem and background.builtin_file(stem):
            # a photo theme brings its photo: shown on the Background page, saved with Save
            self.bg_source.setCurrentIndex(max(0, self.bg_source.findData(f"builtin:{stem}")))
            self.chk_bg_enabled.setChecked(True)

    def _colors_edited(self):
        """A color was changed by hand: the theme becomes My colors, starting from what's shown."""
        if self._theme_key != themes.CUSTOM:
            self._theme_key = themes.CUSTOM
            for card in self._theme_cards:
                card.set_selected(card.key == themes.CUSTOM)
        mine = {k: inp.text() for k, inp in self.color_inputs.items() if QColor.isValidColor(inp.text())}
        for card in self._theme_cards:
            if card.key == themes.CUSTOM:
                card.set_colors({**self._saved_colors, **mine})

    def create_general_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        heatmap_group = QGroupBox("Heatmap Settings")
        hm_layout = QVBoxLayout()

        combo_layout = QHBoxLayout()
        combo_layout.addWidget(QLabel("Default Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Activity Volume", "volume")
        self.mode_combo.addItem("Retention Rate", "retention")
        self.mode_combo.addItem("Review Speed", "score")
        self.mode_combo.addItem("Time Studied", "time")
        self.mode_combo.addItem("New Cards", "new_cards")
        self.mode_combo.addItem("Focus", "focus")
        # every view is listed, so saving never resets the one you last picked
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(self.cfg.get('display_mode', 'volume'))))
        combo_layout.addWidget(self.mode_combo)
        combo_layout.addStretch()
        hm_layout.addLayout(combo_layout)

        avg_layout = QHBoxLayout()
        avg_layout.addWidget(QLabel("Average Period:"))
        self.avg_combo = QComboBox()
        self.avg_combo.addItem("Past Week", "week")
        self.avg_combo.addItem("Past Month", "month")
        self.avg_combo.addItem("Past Year", "year")
        self.avg_combo.addItem("All Time", "all")
        current_avg = self.cfg.get('avg_period', 'year')
        avg_idx = {"week": 0, "month": 1, "year": 2, "all": 3}.get(current_avg, 2)
        self.avg_combo.setCurrentIndex(avg_idx)
        avg_layout.addWidget(self.avg_combo)
        avg_layout.addStretch()
        hm_layout.addLayout(avg_layout)

        weeks_layout = QHBoxLayout()
        weeks_lbl = QLabel("Weeks ahead:")
        weeks_layout.addWidget(weeks_lbl)
        self.weeks_ahead_spin = QSpinBox()
        self.weeks_ahead_spin.setRange(0, 52)
        self.weeks_ahead_spin.setValue(_weeks_ahead(self.cfg))
        self.weeks_ahead_spin.setSuffix(" wks")
        self.weeks_ahead_spin.setFixedWidth(75)
        weeks_layout.addWidget(self.weeks_ahead_spin)
        weeks_layout.addStretch()
        hm_layout.addLayout(weeks_layout)
        self.chk_sep_months = QCheckBox("Separate months")
        self.chk_sep_months.setChecked(bool(self.cfg.get("separate_months", False)))
        hm_layout.addWidget(self.chk_sep_months)
        self.chk_forecast_shading = QCheckBox("Shade forecast by cards due")
        self.chk_forecast_shading.setChecked(bool(self.cfg.get("forecast_shading", False)))
        _ThemeCard.shade = self.chk_forecast_shading.isChecked()

        def shading(on):
            _ThemeCard.shade = on
            for card in getattr(self, "_theme_cards", ()):
                card.update()
        self.chk_forecast_shading.toggled.connect(shading)
        hm_layout.addWidget(self.chk_forecast_shading)

        heatmap_group.setLayout(hm_layout)
        layout.addWidget(heatmap_group)

        stats_group = QGroupBox("Stats Bar")
        stats_layout = QVBoxLayout()

        self.chk_show_stats_bar = QCheckBox("Show stats bar")
        self.chk_show_stats_bar.setToolTip("Toggle visibility of the stats numerics row (DUE, DONE, SPEED, etc.) above the heatmap.")
        self.chk_show_stats_bar.setChecked(self.cfg.get("show_stats_bar", True))
        stats_layout.addWidget(self.chk_show_stats_bar)

        streak_layout = QHBoxLayout()
        streak_layout.addWidget(QLabel("Streak section displays:"))
        self.streak_combo = QComboBox()
        self.streak_combo.addItem("Current Streak", "streak")
        self.streak_combo.addItem("% Days Studied (Past Week)", "pct_week")
        self.streak_combo.addItem("% Days Studied (Past Month)", "pct_month")
        current_streak = self.cfg.get('streak_display', 'streak')
        streak_idx = {"streak": 0, "pct_week": 1, "pct_month": 2}.get(current_streak, 0)
        self.streak_combo.setCurrentIndex(streak_idx)
        streak_layout.addWidget(self.streak_combo)
        streak_layout.addStretch()
        stats_layout.addLayout(streak_layout)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        threshold_group = QGroupBox("Thresholds")
        th_layout = QVBoxLayout()

        ret_layout = QHBoxLayout()
        ret_layout.addWidget(QLabel("Retention Range (%):"))
        self.ret_min_input = QSpinBox()
        self.ret_min_input.setRange(0, 100)
        self.ret_min_input.setValue(int(self.cfg.get('retention_min', 75)))
        ret_layout.addWidget(self.ret_min_input)
        ret_layout.addWidget(QLabel("-"))
        self.ret_max_input = QSpinBox()
        self.ret_max_input.setRange(0, 100)
        self.ret_max_input.setValue(int(self.cfg.get('retention_max', 95)))
        ret_layout.addWidget(self.ret_max_input)
        ret_layout.addStretch()
        th_layout.addLayout(ret_layout)

        self.chk_exclude_new_retention = QCheckBox("Exclude new cards from retention on their first day")
        self.chk_exclude_new_retention.setToolTip("When enabled, cards introduced as new will not count towards retention on the day they were first studied. They will count normally on subsequent days.")
        self.chk_exclude_new_retention.setChecked(self.cfg.get("exclude_new_cards_from_retention", False))
        th_layout.addWidget(self.chk_exclude_new_retention)

        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Speed Range (sec):"))
        self.speed_min_input = QDoubleSpinBox()
        self.speed_min_input.setRange(0.1, 60.0)
        self.speed_min_input.setSingleStep(0.5)
        self.speed_min_input.setValue(float(self.cfg.get('speed_min', 3.0)))
        speed_layout.addWidget(self.speed_min_input)
        speed_layout.addWidget(QLabel("-"))
        self.speed_max_input = QDoubleSpinBox()
        self.speed_max_input.setRange(0.1, 60.0)
        self.speed_max_input.setSingleStep(0.5)
        self.speed_max_input.setValue(float(self.cfg.get('speed_max', 15.0)))
        speed_layout.addWidget(self.speed_max_input)
        speed_layout.addStretch()
        th_layout.addLayout(speed_layout)

        # --- Idle card exclusion ---
        idle_row = QHBoxLayout()
        self.chk_exclude_idle = QCheckBox("Exclude idle cards from time stats (idled >")
        self.chk_exclude_idle.setToolTip(
            "When enabled, reviews where you spent more than the threshold (e.g. walked away) "
            "are dropped from every time-based figure — the Time/Card average, the total study "
            "time, and the time heatmap and time graphs — so idle time doesn't skew them. "
            "Review counts and retention are unaffected."
        )
        self.chk_exclude_idle.setChecked(self.cfg.get("exclude_idle_cards", True))
        idle_row.addWidget(self.chk_exclude_idle)
        self.idle_threshold_spin = QSpinBox()
        self.idle_threshold_spin.setRange(5, 600)
        self.idle_threshold_spin.setSuffix(" sec)")
        self.idle_threshold_spin.setValue(int(self.cfg.get("idle_threshold_secs", 60)))
        self.idle_threshold_spin.setEnabled(self.chk_exclude_idle.isChecked())
        self.chk_exclude_idle.toggled.connect(self.idle_threshold_spin.setEnabled)
        idle_row.addWidget(self.idle_threshold_spin)
        idle_row.addStretch()
        th_layout.addLayout(idle_row)

        threshold_group.setLayout(th_layout)
        layout.addWidget(threshold_group)

        # Deck Filter Settings
        filter_group = QGroupBox("Deck Filter")
        filter_layout = QVBoxLayout()

        # Overview settings
        self.chk_show_overview = QCheckBox("Show heatmap on overview screen")
        self.chk_show_overview.setToolTip("Display the heatmap on the screen before studying a deck.")
        self.chk_show_overview.setChecked(self.cfg.get("show_overview_heatmap", True))
        filter_layout.addWidget(self.chk_show_overview)

        self.chk_overview_filter = QCheckBox("Filter to current deck on overview")
        self.chk_overview_filter.setToolTip("When enabled, only shows reviews from the selected deck and its sub-decks.")
        self.chk_overview_filter.setChecked(self.cfg.get("overview_filter_current_deck", True))
        filter_layout.addWidget(self.chk_overview_filter)

        self.chk_show_overview.toggled.connect(self.chk_overview_filter.setEnabled)
        self.chk_overview_filter.setEnabled(self.chk_show_overview.isChecked())

        filter_layout.addSpacing(10)

        self.chk_deck_filter = QCheckBox("Enable deck filtering on main heatmap")
        self.chk_deck_filter.setToolTip("Filter the main deck browser heatmap to only show selected decks.")
        self.chk_deck_filter.setChecked(self.cfg.get("heatmap_deck_filter_enabled", False))
        filter_layout.addWidget(self.chk_deck_filter)

        filter_layout.addWidget(QLabel("Select decks to include:"))

        # Deck list in scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(150)
        scroll_widget = QWidget()
        self.deck_list_layout = QVBoxLayout()
        self.deck_list_layout.setSpacing(2)

        self.deck_checkboxes = {}
        filtered_decks = set(self.cfg.get("heatmap_filtered_decks", []))

        try:
            all_decks = mw.col.decks.all_names_and_ids()
            for deck in sorted(all_decks, key=lambda d: d.name if hasattr(d, 'name') else d['name']):
                d_id = deck.id if hasattr(deck, 'id') else deck['id']
                d_name = deck.name if hasattr(deck, 'name') else deck['name']
                chk = QCheckBox(d_name)
                chk.setChecked(d_id in filtered_decks or len(filtered_decks) == 0)
                self.deck_checkboxes[d_id] = chk
                self.deck_list_layout.addWidget(chk)
        except:
            self.deck_list_layout.addWidget(QLabel("Unable to load decks."))

        self.deck_list_layout.addStretch()
        scroll_widget.setLayout(self.deck_list_layout)
        scroll.setWidget(scroll_widget)
        filter_layout.addWidget(scroll)

        # Select All / Deselect All
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_deck_checks(True))
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self._set_all_deck_checks(False))
        btn_layout.addWidget(select_all_btn)
        btn_layout.addWidget(deselect_all_btn)
        btn_layout.addStretch()
        filter_layout.addLayout(btn_layout)

        self.chk_deck_filter.toggled.connect(scroll.setEnabled)
        self.chk_deck_filter.toggled.connect(select_all_btn.setEnabled)
        self.chk_deck_filter.toggled.connect(deselect_all_btn.setEnabled)
        scroll.setEnabled(self.chk_deck_filter.isChecked())
        select_all_btn.setEnabled(self.chk_deck_filter.isChecked())
        deselect_all_btn.setEnabled(self.chk_deck_filter.isChecked())

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # Retention Deck Scope — retention % from a specific deck, other stats from all
        ret_scope_group = QGroupBox("Retention Deck Scope")
        ret_scope_layout = QVBoxLayout()

        self.chk_retention_scope = QCheckBox("Calculate retention from specific decks only")
        self.chk_retention_scope.setToolTip(
            "When enabled, the retention percentage is calculated only from the decks "
            "selected below (and their sub-decks). Reviews, study time, and new-card counts "
            "still reflect all of your studying — only the retention line is scoped.")
        self.chk_retention_scope.setChecked(self.cfg.get("retention_deck_scope_enabled", False))
        ret_scope_layout.addWidget(self.chk_retention_scope)

        ret_scope_layout.addWidget(QLabel("Retention is measured from these decks:"))

        ret_scroll = QScrollArea()
        ret_scroll.setWidgetResizable(True)
        ret_scroll.setMinimumHeight(120)
        ret_scroll.setMaximumHeight(150)
        ret_scroll_widget = QWidget()
        self.retention_deck_list_layout = QVBoxLayout()
        self.retention_deck_list_layout.setSpacing(2)

        self.retention_deck_checkboxes = {}
        scoped_decks = set(self.cfg.get("retention_scope_decks", []))

        try:
            all_decks = mw.col.decks.all_names_and_ids()
            for deck in sorted(all_decks, key=lambda d: d.name if hasattr(d, 'name') else d['name']):
                d_id = deck.id if hasattr(deck, 'id') else deck['id']
                d_name = deck.name if hasattr(deck, 'name') else deck['name']
                chk = QCheckBox(d_name)
                chk.setChecked(d_id in scoped_decks)
                self.retention_deck_checkboxes[d_id] = chk
                self.retention_deck_list_layout.addWidget(chk)
        except:
            self.retention_deck_list_layout.addWidget(QLabel("Unable to load decks."))

        self.retention_deck_list_layout.addStretch()
        ret_scroll_widget.setLayout(self.retention_deck_list_layout)
        ret_scroll.setWidget(ret_scroll_widget)
        ret_scope_layout.addWidget(ret_scroll)

        ret_btn_layout = QHBoxLayout()
        ret_select_all_btn = QPushButton("Select All")
        ret_select_all_btn.clicked.connect(lambda: self._set_all_retention_deck_checks(True))
        ret_deselect_all_btn = QPushButton("Deselect All")
        ret_deselect_all_btn.clicked.connect(lambda: self._set_all_retention_deck_checks(False))
        ret_btn_layout.addWidget(ret_select_all_btn)
        ret_btn_layout.addWidget(ret_deselect_all_btn)
        ret_btn_layout.addStretch()
        ret_scope_layout.addLayout(ret_btn_layout)

        def _toggle_ret_scope(on):
            ret_scroll.setEnabled(on)
            ret_select_all_btn.setEnabled(on)
            ret_deselect_all_btn.setEnabled(on)
        self.chk_retention_scope.toggled.connect(_toggle_ret_scope)
        _toggle_ret_scope(self.chk_retention_scope.isChecked())

        ret_scope_group.setLayout(ret_scope_layout)
        layout.addWidget(ret_scope_group)

        layout.addStretch()
        widget.setLayout(layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def create_reminders_tab(self):
        """Reminders: the pill under your decks that rolls through these, in this order."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        def check(key, text, tip=""):
            c = QCheckBox(text)
            c.setChecked(self.cfg.get(key, True))
            if tip:
                c.setToolTip(tip)
            v.addWidget(c)
            return c

        self.notice_more = {}
        self.notice_more["notice_sync"] = check("notice_sync", "Cards not synced yet, and when you last synced")
        self.chk_time_pill.setToolTip("How long today's cards will take. It needs Time Left (Time Left & Focus).")
        v.addWidget(self.chk_time_pill)
        self.chk_time_pill.setEnabled(self.chk_time_enabled.isChecked())
        self.chk_time_enabled.toggled.connect(self.chk_time_pill.setEnabled)

        self.notice_more["notice_milestone"] = check("notice_milestone", "Streak milestones, on the day you reach them")
        self.chk_exam_countdown = check("exam_countdown", "Your next exam")
        ahead_row = QHBoxLayout()
        ahead_row.setContentsMargins(22, 0, 0, 2)
        ahead_row.addWidget(QLabel("Show it from"))
        self.exam_countdown_days = QSpinBox()
        self.exam_countdown_days.setRange(1, 120)
        self.exam_countdown_days.setSuffix(" days before")
        self.exam_countdown_days.setValue(int(self.cfg.get("exam_countdown_days", 14) or 14))
        ahead_row.addWidget(self.exam_countdown_days)
        ahead_row.addStretch()
        v.addLayout(ahead_row)
        self.exam_countdown_days.setEnabled(self.chk_exam_countdown.isChecked())
        self.chk_exam_countdown.toggled.connect(self.exam_countdown_days.setEnabled)

        self.chk_notice_backlog = check("notice_backlog", "Overdue cards", "When 20 or more review cards are past their due date.")
        self.notice_more["notice_learning"] = check("notice_learning", "Learning cards still coming back today",
                                                    "Once nothing else is due.")
        self.chk_notice_tomorrow = check("notice_tomorrow", "Tomorrow's reviews, in the evening")
        self.chk_notice_streak = check("notice_streak", "Your streak, in the evening if you haven't studied")
        self.notice_more["notice_last_week"] = check("notice_last_week", "Last week, on Mondays")
        self.notice_more["notice_this_week"] = check("notice_this_week", "This week against last week",
                                                     "From Wednesday, when it's 15% or more above or below.")
        v.addStretch()
        return w

    def create_appearance_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        heatmap_group = QGroupBox("Heatmap")
        hm_layout = QVBoxLayout()

        self.chk_glass = QCheckBox("Enable Glass Effect")
        self.chk_glass.setChecked(self.cfg.get("enable_glass", True))
        hm_layout.addWidget(self.chk_glass)

        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Cell Shape:"))
        self.cell_shape_combo = QComboBox()
        self.cell_shape_combo.addItem("Square", "square")
        self.cell_shape_combo.addItem("Rounded", "rounded")
        self.cell_shape_combo.addItem("Circle", "circle")
        self.cell_shape_combo.setCurrentIndex(max(0, self.cell_shape_combo.findData(_cell_shape(self.cfg))))
        shape_row.addWidget(self.cell_shape_combo)
        shape_row.addStretch()
        hm_layout.addLayout(shape_row)

        hw_row = QHBoxLayout()
        hw_row.addWidget(QLabel("Width:"))
        self.heatmap_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.heatmap_width_slider.setRange(540, 900)
        self.heatmap_width_slider.setSingleStep(10)
        self.heatmap_width_slider.setPageStep(20)
        self.heatmap_width_slider.setValue(int(self.cfg.get("heatmap_width", 540) or 540))
        hw_row.addWidget(self.heatmap_width_slider)
        hw_label = QLabel(f"{self.heatmap_width_slider.value()}px")
        hw_label.setFixedWidth(45)
        hw_row.addWidget(hw_label)
        self.heatmap_width_slider.valueChanged.connect(lambda v: hw_label.setText(f"{v}px"))
        hm_layout.addLayout(hw_row)

        anim_row = QHBoxLayout()
        anim_row.addWidget(QLabel("Animations:"))
        self.animations_combo = QComboBox()
        self.animations_combo.addItem("Follow system", "system")
        self.animations_combo.addItem("Always", "on")
        self.animations_combo.addItem("Off", "off")
        self.animations_combo.setToolTip("Follow system: off when your computer is set to reduce motion.")
        self.animations_combo.setCurrentIndex(max(0, self.animations_combo.findData(self.cfg.get("animations", "system"))))
        anim_row.addWidget(self.animations_combo)
        anim_row.addStretch()
        hm_layout.addLayout(anim_row)

        self.chk_low_power = QCheckBox("Low-power mode")
        self.chk_low_power.setToolTip("For slower computers: no blur and no animations.")
        self._low_power_auto = lowpower.chosen(self.cfg.get("low_power")) if self.cfg.get("low_power") is None else None
        self.chk_low_power.setChecked(lowpower.chosen(self.cfg.get("low_power")))
        hm_layout.addWidget(self.chk_low_power)
        self.chk_low_power.toggled.connect(lambda on: self.animations_combo.setEnabled(not on))
        self.animations_combo.setEnabled(not self.chk_low_power.isChecked())

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Glass Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        current_opacity = int(self.cfg.get('glass_opacity', 0.4) * 100)
        self.opacity_slider.setValue(current_opacity)
        self.opacity_slider.valueChanged.connect(self.update_opacity_label)
        self.opacity_label = QLabel(f"{current_opacity}%")
        self.opacity_label.setFixedWidth(35)
        slider_layout.addWidget(self.opacity_slider)
        slider_layout.addWidget(self.opacity_label)
        hm_layout.addLayout(slider_layout)

        self.chk_replace = QCheckBox("Hide Anki default stats")
        self.chk_replace.setToolTip("Hides the default 'Studied X cards in Y minutes' message.")
        self.chk_replace.setChecked(self.cfg.get("replace_stats", True))
        hm_layout.addWidget(self.chk_replace)

        hm_layout.addSpacing(10)

        # Low Activity Visibility slider (controls intensity curve)
        intensity_layout = QHBoxLayout()
        intensity_lbl = QLabel("Low Activity Visibility:")
        intensity_lbl.setToolTip("Controls how visible days with fewer reviews appear.\nHigher values make low-activity days stand out more.")
        intensity_layout.addWidget(intensity_lbl)
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setToolTip("Controls how visible days with fewer reviews are")
        self.intensity_slider.setRange(30, 100)  # 0.3 to 1.0 (inverted display)
        current_curve = self.cfg.get('cell_intensity_curve', 0.7)
        # Convert: lower exponent = higher visibility, so invert for slider
        slider_val = int((1.1 - current_curve) * 100)
        self.intensity_slider.setValue(max(30, min(100, slider_val)))
        self.intensity_slider.valueChanged.connect(self._update_intensity_label)
        self.intensity_label = QLabel()
        self.intensity_label.setFixedWidth(50)
        self._update_intensity_label(self.intensity_slider.value())
        intensity_layout.addWidget(self.intensity_slider)
        intensity_layout.addWidget(self.intensity_label)
        hm_layout.addLayout(intensity_layout)

        # Minimum Cell Opacity slider
        min_opacity_layout = QHBoxLayout()
        min_opacity_lbl = QLabel("Minimum Cell Opacity:")
        min_opacity_lbl.setToolTip("Sets the minimum visibility for any day with at least one review.\nHigher values ensure even single-review days are clearly visible.")
        min_opacity_layout.addWidget(min_opacity_lbl)
        self.min_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_opacity_slider.setToolTip("Sets the minimum opacity for any day with at least one review")
        self.min_opacity_slider.setRange(5, 50)  # 0.05 to 0.50
        current_min = int(self.cfg.get('cell_min_opacity', 0.05) * 100)
        self.min_opacity_slider.setValue(max(5, min(50, current_min)))
        self.min_opacity_slider.valueChanged.connect(self._update_min_opacity_label)
        self.min_opacity_label = QLabel()
        self.min_opacity_label.setFixedWidth(50)
        self._update_min_opacity_label(self.min_opacity_slider.value())
        min_opacity_layout.addWidget(self.min_opacity_slider)
        min_opacity_layout.addWidget(self.min_opacity_label)
        hm_layout.addLayout(min_opacity_layout)

        # Color Gradient Mode
        gradient_layout = QHBoxLayout()
        gradient_lbl = QLabel("Color Gradient Mode:")
        gradient_lbl.setToolTip("How cell colors scale with review count.\nOpacity: transparent→opaque (original).\nShade: dark→bright solid color.\nShade Inverted: bright→dark solid color.")
        gradient_layout.addWidget(gradient_lbl)
        self.gradient_mode_combo = QComboBox()
        self.gradient_mode_combo.addItem("Opacity (Transparent→Opaque)", "opacity")
        self.gradient_mode_combo.addItem("Shade (Dark→Bright)", "shade")
        self.gradient_mode_combo.addItem("Shade Inverted (Bright→Dark)", "shade_inverted")
        self.gradient_mode_combo.addItem("Glow (Even Spread)", "glow")
        current_gradient = self.cfg.get('color_gradient_mode', 'opacity')
        for i in range(self.gradient_mode_combo.count()):
            if self.gradient_mode_combo.itemData(i) == current_gradient:
                self.gradient_mode_combo.setCurrentIndex(i)
                break
        self.gradient_mode_combo.currentIndexChanged.connect(self._on_gradient_mode_changed)
        gradient_layout.addWidget(self.gradient_mode_combo)
        hm_layout.addLayout(gradient_layout)

        # Shade Dark Factor slider (only relevant in shade modes)
        shade_layout = QHBoxLayout()
        shade_lbl = QLabel("Shade Minimum Brightness:")
        shade_lbl.setToolTip("In shade mode, how dark the lowest-activity cells are.\n0% = black, 50% = half-brightness.")
        shade_layout.addWidget(shade_lbl)
        self.shade_slider = QSlider(Qt.Orientation.Horizontal)
        self.shade_slider.setRange(0, 50)
        self.shade_slider.setValue(int(self.cfg.get('shade_dark_factor', 0.15) * 100))
        self.shade_slider.valueChanged.connect(self._update_shade_label)
        self.shade_label = QLabel()
        self.shade_label.setFixedWidth(35)
        shade_layout.addWidget(self.shade_slider)
        shade_layout.addWidget(self.shade_label)
        hm_layout.addLayout(shade_layout)
        self._update_shade_label(self.shade_slider.value())

        # Glow Contrast slider (only relevant in Glow)
        glow_layout = QHBoxLayout()
        glow_layout.addWidget(QLabel("Glow Contrast:"))
        self.glow_slider = QSlider(Qt.Orientation.Horizontal)
        self.glow_slider.setRange(0, 100)
        self.glow_slider.setValue(int(round(float(self.cfg.get('glow_contrast', themes.GLOW_CONTRAST)) * 100)))
        self.glow_label = QLabel(f"{self.glow_slider.value()}%")
        self.glow_label.setFixedWidth(35)
        self.glow_slider.valueChanged.connect(lambda v: self.glow_label.setText(f"{v}%"))
        glow_layout.addWidget(self.glow_slider)
        glow_layout.addWidget(self.glow_label)
        hm_layout.addLayout(glow_layout)
        self._on_gradient_mode_changed(self.gradient_mode_combo.currentIndex())

        # Color Scale Maximum
        scale_max_layout = QHBoxLayout()
        scale_max_lbl = QLabel("Color Scale Maximum:")
        scale_max_lbl.setToolTip(
            "Sets the review count that maps to full color intensity.\n"
            "0 = auto (uses your highest single-day count).\n"
            "Set a fixed value so the scale stays consistent across weeks."
        )
        scale_max_layout.addWidget(scale_max_lbl)
        self.color_scale_max_spin = QSpinBox()
        self.color_scale_max_spin.setRange(0, 9999)
        self.color_scale_max_spin.setSingleStep(10)
        self.color_scale_max_spin.setSpecialValueText("Auto")
        self.color_scale_max_spin.setValue(int(self.cfg.get('color_scale_max', 0)))
        self.color_scale_max_spin.setToolTip(
            "0 = Auto (peak day sets the ceiling).\n"
            "e.g. 200 → any day with ≥200 reviews shows full color."
        )
        scale_max_layout.addWidget(self.color_scale_max_spin)
        scale_max_layout.addStretch()
        hm_layout.addLayout(scale_max_layout)
        self._on_gradient_mode_changed(self.gradient_mode_combo.currentIndex())

        heatmap_group.setLayout(hm_layout)
        layout.addWidget(heatmap_group)

        deck_group = QGroupBox("Deck Browser")
        deck_layout = QVBoxLayout()

        self.chk_modern = QCheckBox("Enable Modern Deck Theme")
        self.chk_modern.setChecked(self.cfg.get("modern_deck_theme", True))
        deck_layout.addWidget(self.chk_modern)

        sub_layout = QVBoxLayout()
        sub_layout.setContentsMargins(20, 0, 0, 0)

        self.chk_deck_glass = QCheckBox("Liquid Glass Background")
        self.chk_deck_glass.setChecked(self.cfg.get("enable_deck_glass", True))
        sub_layout.addWidget(self.chk_deck_glass)

        self.chk_ratio = QCheckBox("Activity Ratio Ring")
        self.chk_ratio.setChecked(self.cfg.get("show_deck_ratio", True))
        sub_layout.addWidget(self.chk_ratio)

        self.chk_count_pills = QCheckBox("Count pills")
        self.chk_count_pills.setChecked(self.cfg.get("deck_count_pills", True))
        sub_layout.addWidget(self.chk_count_pills)

        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Width:"))
        self.deck_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.deck_width_slider.setRange(400, 900)
        self.deck_width_slider.setValue(self.cfg.get("deck_list_width", 540))
        self.deck_width_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.deck_width_slider.setTickInterval(100)
        width_row.addWidget(self.deck_width_slider)
        self.deck_width_label = QLabel(f"{self.cfg.get('deck_list_width', 540)}px")
        self.deck_width_label.setFixedWidth(45)
        width_row.addWidget(self.deck_width_label)
        self.deck_width_slider.valueChanged.connect(lambda v: self.deck_width_label.setText(f"{v}px"))
        sub_layout.addLayout(width_row)

        deck_layout.addLayout(sub_layout)

        self.chk_home_dark = QCheckBox("Always dark")
        self.chk_home_dark.setChecked(self.cfg.get("home_always_dark", False))
        deck_layout.addWidget(self.chk_home_dark)

        self.chk_modern.toggled.connect(self.chk_deck_glass.setEnabled)
        self.chk_modern.toggled.connect(self.chk_ratio.setEnabled)
        self.chk_modern.toggled.connect(self.chk_count_pills.setEnabled)
        self.chk_modern.toggled.connect(self.deck_width_slider.setEnabled)
        self.chk_modern.toggled.connect(self.deck_width_label.setEnabled)
        self.chk_deck_glass.setEnabled(self.chk_modern.isChecked())
        self.chk_ratio.setEnabled(self.chk_modern.isChecked())
        self.chk_count_pills.setEnabled(self.chk_modern.isChecked())
        self.deck_width_slider.setEnabled(self.chk_modern.isChecked())
        self.deck_width_label.setEnabled(self.chk_modern.isChecked())

        deck_group.setLayout(deck_layout)
        layout.addWidget(deck_group)

        text_group = QGroupBox("Text")
        text_layout = QVBoxLayout()

        self.chk_monochrome = QCheckBox("High Contrast Text (Disable Colors)")
        self.chk_monochrome.setChecked(self.cfg.get("monochrome_text", False))
        text_layout.addWidget(self.chk_monochrome)

        self.chk_shadows = QCheckBox("Enable Text Shadows")
        self.chk_shadows.setChecked(self.cfg.get("enable_shadows", True))
        text_layout.addWidget(self.chk_shadows)

        text_group.setLayout(text_layout)
        layout.addWidget(text_group)

        # Colors Section
        colors_group = QGroupBox("Colors")
        colors_layout = QVBoxLayout()

        # Card Counts
        pill_colors = QGroupBox("Deck List")
        pc_layout = QGridLayout()
        pill_color_defs = [
            ("pill_new_color", "New:", "#4a90e2"),
            ("pill_learn_color", "Learning:", "#e74c3c"),
            ("pill_due_color", "Due:", "#f1c40f"),
            ("filtered_deck_color", "Filtered decks:", "#20b2aa"),
        ]
        for row, (key, label, default) in enumerate(pill_color_defs):
            pc_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(80)
            self.color_inputs[key] = color_input
            pc_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #bdc3c7; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self.pick_graph_color(k))
            self.color_btns[key] = color_btn
            pc_layout.addWidget(color_btn, row, 2)
        pill_colors.setLayout(pc_layout)
        colors_layout.addWidget(pill_colors)

        # Heatmap Colors
        heatmap_colors = QGroupBox("Heatmap")
        hc_layout = QGridLayout()
        color_defs = [
            ("base_color", "Volume Color:", "#8e44ad"),
            ("today_color", "Today Cell Border:", "#2ecc71"),
            ("forecast_color", "Forecast Color:", "#bdc3c7"),
            ("forecast_shade_color", "Forecast Shading:", "#20b2aa"),
            ("empty_color", "Empty Cell (Light):", "#ebedf0"),
            ("empty_color_night", "Empty Cell (Dark):", "#282c34"),
        ]
        for row, (key, label, default) in enumerate(color_defs):
            hc_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(80)
            color_input.setPlaceholderText("#RRGGBB")
            color_input.textChanged.connect(lambda t, k=key: self.on_color_hex_changed(k, t))
            self.color_inputs[key] = color_input
            hc_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #bdc3c7; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self.pick_graph_color(k))
            self.color_btns[key] = color_btn
            hc_layout.addWidget(color_btn, row, 2)
        heatmap_colors.setLayout(hc_layout)
        colors_layout.addWidget(heatmap_colors)

        # Graph Colors
        graph_colors = QGroupBox("Graph Lines")
        gc_layout = QGridLayout()
        graph_color_defs = [
            ("graph_reviews_color", "Reviews:", "#3498db"),
            ("graph_time_color", "Time/Card:", "#e67e22"),
            ("graph_time_studied_color", "Time Studied:", "#3498db"),
            ("graph_retention_color", "Retention:", "#f1c40f"),
            ("graph_forecast_color", "Forecast:", "#95a5a6"),
            ("fsrs_prediction_color", "FSRS Forecast:", "#9b59b6"),
        ]
        for row, (key, label, default) in enumerate(graph_color_defs):
            gc_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(80)
            color_input.setPlaceholderText("#RRGGBB")
            color_input.textChanged.connect(lambda t, k=key: self.on_color_hex_changed(k, t))
            self.color_inputs[key] = color_input
            gc_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #bdc3c7; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self.pick_graph_color(k))
            self.color_btns[key] = color_btn
            gc_layout.addWidget(color_btn, row, 2)
        graph_colors.setLayout(gc_layout)
        colors_layout.addWidget(graph_colors)

        colors_group.setLayout(colors_layout)
        layout.addWidget(colors_group)

        # ── Custom Heatmap Modes ──────────────────────────────────────────────
        custom_modes_group = QGroupBox("Custom Heatmap Modes")
        cm_layout = QVBoxLayout()
        cm_layout.setSpacing(6)

        cm_note = QLabel("Enable additional color modes in the heatmap toggle bar.\n"
                         "Both use the same gradient style as Volume (solid color, opacity or shade).")
        cm_note.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        cm_layout.addWidget(cm_note)

        # ─ Time Studied mode ─
        time_header = QHBoxLayout()
        self.chk_show_time_mode = QCheckBox("Show Time Studied mode")
        self.chk_show_time_mode.setChecked(bool(self.cfg.get("show_mode_time", True)))
        time_header.addWidget(self.chk_show_time_mode)
        time_header.addStretch()
        cm_layout.addLayout(time_header)

        time_detail = QHBoxLayout()
        time_detail.setContentsMargins(20, 0, 0, 0)
        time_detail.addWidget(QLabel("Color:"))
        self.time_color_input = QLineEdit()
        self.time_color_input.setText(self.cfg.get("custom_time_color", "#e67e22"))
        self.time_color_input.setFixedWidth(80)
        self.time_color_input.textChanged.connect(lambda t: self.on_color_hex_changed("custom_time_color", t))
        self.color_inputs["custom_time_color"] = self.time_color_input
        time_detail.addWidget(self.time_color_input)
        time_color_btn = QPushButton()
        time_color_btn.setFixedSize(24, 24)
        time_color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        time_color_btn.setStyleSheet(f"background-color: {self.cfg.get('custom_time_color','#e67e22')}; border:1px solid #bdc3c7; border-radius:4px;")
        time_color_btn.clicked.connect(lambda: self.pick_graph_color("custom_time_color"))
        self.color_btns["custom_time_color"] = time_color_btn
        time_detail.addWidget(time_color_btn)
        time_detail.addSpacing(12)
        time_detail.addWidget(QLabel("Scale max (min):"))
        self.time_scale_spin = QSpinBox()
        self.time_scale_spin.setRange(0, 9999)
        self.time_scale_spin.setSpecialValueText("Auto")
        self.time_scale_spin.setValue(int(self.cfg.get("color_scale_max_time", 0)))
        self.time_scale_spin.setToolTip("0 = auto (peak day sets the ceiling). Otherwise minutes studied = full color.")
        time_detail.addWidget(self.time_scale_spin)
        time_detail.addStretch()
        cm_layout.addLayout(time_detail)

        # ─ New Cards mode ─
        nc_header = QHBoxLayout()
        self.chk_show_nc_mode = QCheckBox("Show New Cards mode")
        self.chk_show_nc_mode.setChecked(bool(self.cfg.get("show_mode_newcards", True)))
        nc_header.addWidget(self.chk_show_nc_mode)
        nc_header.addStretch()
        cm_layout.addLayout(nc_header)

        nc_detail = QHBoxLayout()
        nc_detail.setContentsMargins(20, 0, 0, 0)
        nc_detail.addWidget(QLabel("Color:"))
        self.nc_color_input = QLineEdit()
        self.nc_color_input.setText(self.cfg.get("custom_newcards_color", "#27ae60"))
        self.nc_color_input.setFixedWidth(80)
        self.nc_color_input.textChanged.connect(lambda t: self.on_color_hex_changed("custom_newcards_color", t))
        self.color_inputs["custom_newcards_color"] = self.nc_color_input
        nc_detail.addWidget(self.nc_color_input)
        nc_color_btn = QPushButton()
        nc_color_btn.setFixedSize(24, 24)
        nc_color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        nc_color_btn.setStyleSheet(f"background-color: {self.cfg.get('custom_newcards_color','#27ae60')}; border:1px solid #bdc3c7; border-radius:4px;")
        nc_color_btn.clicked.connect(lambda: self.pick_graph_color("custom_newcards_color"))
        self.color_btns["custom_newcards_color"] = nc_color_btn
        nc_detail.addWidget(nc_color_btn)
        nc_detail.addSpacing(12)
        nc_detail.addWidget(QLabel("Scale max (cards):"))
        self.nc_scale_spin = QSpinBox()
        self.nc_scale_spin.setRange(0, 9999)
        self.nc_scale_spin.setSpecialValueText("Auto")
        self.nc_scale_spin.setValue(int(self.cfg.get("color_scale_max_newcards", 0)))
        self.nc_scale_spin.setToolTip("0 = auto (peak day sets the ceiling). Otherwise N new cards = full color.")
        nc_detail.addWidget(self.nc_scale_spin)
        nc_detail.addStretch()
        cm_layout.addLayout(nc_detail)

        # ─ Focus mode ─
        self.chk_show_focus_mode = QCheckBox("Show Focus mode (daily focus score)")
        self.chk_show_focus_mode.setToolTip(
            "Colors each day by the share of cards answered within one standard deviation\n"
            "of that card's usual time (each card has its own spread). A new card's first view\n"
            "gets two standard deviations of your new-card times, since you're reading it.\n"
            "Needs Time Left (Settings → Time Left).")
        self.chk_show_focus_mode.setChecked(bool(self.cfg.get("show_mode_focus", True)))
        cm_layout.addWidget(self.chk_show_focus_mode)

        custom_modes_group.setLayout(cm_layout)
        layout.addWidget(custom_modes_group)

        widget.setLayout(layout)

        # Wrap in scroll area since content is long
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def create_graphs_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        gb = QGroupBox("Graph Panel")
        gl = QVBoxLayout()

        self.chk_show_graph = QCheckBox("Show Bottom Graph Panel")
        self.chk_show_graph.setChecked(self.cfg.get("show_graph", True))
        gl.addWidget(self.chk_show_graph)

        gl.addWidget(QLabel("Active Metrics:"))

        metrics_layout = QVBoxLayout()
        metrics_layout.setContentsMargins(20, 0, 0, 0)

        self.chk_rev = QCheckBox("Review Count")
        self.chk_time = QCheckBox("Time/Card")
        self.chk_time_studied = QCheckBox("Time Studied")
        self.chk_ret = QCheckBox("Retention %")
        self.chk_fut = QCheckBox("Forecast")

        active = self.cfg.get("active_graphs_v14", [])
        self.chk_rev.setChecked("reviews" in active)
        self.chk_time.setChecked("time_card" in active)
        self.chk_time_studied.setChecked("time_studied" in active)
        self.chk_ret.setChecked("retention" in active)
        self.chk_fut.setChecked("forecast" in active)

        self.chk_rev_rolling = QCheckBox("Rolling Average")
        self.chk_rev_rolling.setChecked(self.cfg.get("reviews_rolling_avg", False))
        self.chk_rev_rolling.setEnabled(self.chk_rev.isChecked())
        self.chk_rev.toggled.connect(self.chk_rev_rolling.setEnabled)

        self.rev_rolling_period = QSpinBox()
        self.rev_rolling_period.setRange(2, 30)
        self.rev_rolling_period.setValue(self.cfg.get("reviews_rolling_avg_period", 7))
        self.rev_rolling_period.setSuffix(" days")
        self.rev_rolling_period.setEnabled(self.chk_rev.isChecked() and self.chk_rev_rolling.isChecked())
        self.chk_rev.toggled.connect(lambda on: self.rev_rolling_period.setEnabled(on and self.chk_rev_rolling.isChecked()))
        self.chk_rev_rolling.toggled.connect(lambda on: self.rev_rolling_period.setEnabled(on and self.chk_rev.isChecked()))

        rolling_row = QHBoxLayout()
        rolling_row.setContentsMargins(0, 0, 0, 0)
        rolling_row.addWidget(self.chk_rev_rolling)
        rolling_row.addWidget(self.rev_rolling_period)
        rolling_row.addStretch()

        rev_sub_layout = QVBoxLayout()
        rev_sub_layout.setContentsMargins(20, 0, 0, 0)
        rev_sub_layout.addLayout(rolling_row)

        def _make_rolling_row(parent_chk, cfg_on_key, cfg_period_key):
            """Return (checkbox, spinbox, sub_layout) for a rolling-average sub-row."""
            chk = QCheckBox("Rolling Average")
            chk.setChecked(self.cfg.get(cfg_on_key, False))
            chk.setEnabled(parent_chk.isChecked())
            parent_chk.toggled.connect(chk.setEnabled)

            spin = QSpinBox()
            spin.setRange(2, 30)
            spin.setValue(self.cfg.get(cfg_period_key, 7))
            spin.setSuffix(" days")
            spin.setEnabled(parent_chk.isChecked() and chk.isChecked())
            parent_chk.toggled.connect(lambda on, c=chk, s=spin: s.setEnabled(on and c.isChecked()))
            chk.toggled.connect(lambda on, p=parent_chk, s=spin: s.setEnabled(on and p.isChecked()))

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(chk)
            row.addWidget(spin)
            row.addStretch()

            sub = QVBoxLayout()
            sub.setContentsMargins(20, 0, 0, 0)
            sub.addLayout(row)
            return chk, spin, sub

        self.chk_time_rolling, self.time_rolling_period, time_sub = _make_rolling_row(
            self.chk_time, "time_rolling_avg", "time_rolling_avg_period")
        self.chk_time_studied_rolling, self.time_studied_rolling_period, time_studied_sub = _make_rolling_row(
            self.chk_time_studied, "time_studied_rolling_avg", "time_studied_rolling_avg_period")
        self.chk_ret_rolling, self.ret_rolling_period, ret_sub = _make_rolling_row(
            self.chk_ret, "ret_rolling_avg", "ret_rolling_avg_period")
        self.chk_fut_rolling, self.fut_rolling_period, fut_sub = _make_rolling_row(
            self.chk_fut, "forecast_rolling_avg", "forecast_rolling_avg_period")

        metrics_layout.addWidget(self.chk_rev)
        metrics_layout.addLayout(rev_sub_layout)
        metrics_layout.addWidget(self.chk_time)
        metrics_layout.addLayout(time_sub)
        metrics_layout.addWidget(self.chk_time_studied)
        metrics_layout.addLayout(time_studied_sub)
        metrics_layout.addWidget(self.chk_ret)
        metrics_layout.addLayout(ret_sub)
        metrics_layout.addWidget(self.chk_fut)
        metrics_layout.addLayout(fut_sub)

        gl.addLayout(metrics_layout)

        self.chk_exam_markers = QCheckBox("Show Exam Date Markers")
        self.chk_exam_markers.setChecked(self.cfg.get("show_exam_markers", True))
        gl.addWidget(self.chk_exam_markers)

        gb.setLayout(gl)
        layout.addWidget(gb)

        # FSRS Forecast Simulation Settings (matches Anki's FSRS Simulator)
        fsrs_group = QGroupBox("FSRS Forecast Simulation")
        fsrs_layout = QVBoxLayout()

        # Check FSRS status and get parameters
        fsrs_available = False
        fsrs_weights = None
        try:
            fsrs_available = bool(mw.col.get_config("fsrs")) if mw.col else False
            if fsrs_available:
                fsrs_weights = _saved_fsrs_weights(self._fsrs_weights_deck())
        except:
            pass

        # Enable checkbox
        self.chk_fsrs_enabled = QCheckBox("Enable FSRS Smart Prediction")
        self.chk_fsrs_enabled.setChecked(self.cfg.get("fsrs_simulation_enabled", False))
        self.chk_fsrs_enabled.setEnabled(fsrs_available)
        if not fsrs_available:
            self.chk_fsrs_enabled.setToolTip("FSRS must be enabled in Anki Preferences → Scheduling")
        fsrs_layout.addWidget(self.chk_fsrs_enabled)

        # Status indicator with FSRS params info
        status = QLabel()
        if fsrs_available:
            if fsrs_weights:
                status.setText("Using your optimized FSRS parameters")
            else:
                status.setText("FSRS enabled (using default parameters)")
            status.setStyleSheet("color: #27ae60; font-size: 10px;")
        else:
            status.setText("FSRS not enabled in Anki Preferences")
            status.setStyleSheet("color: #e74c3c; font-size: 10px;")
        fsrs_layout.addWidget(status)

        # Main settings
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(20, 5, 0, 0)

        # Days to simulate
        days_row = QHBoxLayout()
        days_row.addWidget(QLabel("Days to simulate:"))
        self.fsrs_days_spin = QSpinBox()
        self.fsrs_days_spin.setRange(7, 365)
        self.fsrs_days_spin.setValue(self.cfg.get("fsrs_simulation_days", 90))
        days_row.addWidget(self.fsrs_days_spin)
        days_row.addStretch()
        settings_layout.addLayout(days_row)

        # Desired retention slider
        ret_row = QHBoxLayout()
        ret_row.addWidget(QLabel("Desired retention:"))
        self.fsrs_ret_slider = QSlider(Qt.Orientation.Horizontal)
        self.fsrs_ret_slider.setRange(70, 99)
        self.fsrs_ret_slider.setValue(int(self.cfg.get("fsrs_simulation_retention", 0.9) * 100))
        self.fsrs_ret_slider.valueChanged.connect(self._update_fsrs_ret_label)
        self.fsrs_ret_slider.setFixedWidth(120)
        ret_row.addWidget(self.fsrs_ret_slider)
        self.fsrs_ret_label = QLabel(f"{self.fsrs_ret_slider.value()}%")
        self.fsrs_ret_label.setFixedWidth(35)
        ret_row.addWidget(self.fsrs_ret_label)
        ret_row.addStretch()
        settings_layout.addLayout(ret_row)

        # New cards per day (flat rate fed directly to the FSRS simulator)
        new_cards_row = QHBoxLayout()
        new_cards_row.addWidget(QLabel("New cards/day:"))
        self.fsrs_new_cards_spin = QSpinBox()
        self.fsrs_new_cards_spin.setRange(0, 9999)
        # Migrate from old per-weekday config: use the highest weekday value as the flat rate
        try:
            legacy = self.cfg.get("new_cards_per_weekday", {})
            legacy_flat = max(int(v) for v in legacy.values()) if legacy else 0
        except (TypeError, ValueError, AttributeError):
            legacy_flat = 0
        try:
            flat_val = int(self.cfg.get("fsrs_simulation_new_cards", legacy_flat))
        except (TypeError, ValueError):
            flat_val = legacy_flat
        self.fsrs_new_cards_spin.setValue(flat_val)
        self.fsrs_new_cards_spin.setToolTip(
            "New cards you add on each chosen day, in the FSRS forecast.\n"
            "Set to 0 to forecast only your existing scheduled cards."
        )
        new_cards_row.addWidget(self.fsrs_new_cards_spin)
        new_cards_row.addSpacing(6)
        new_cards_row.addWidget(QLabel("on"))
        new_cards_row.addSpacing(4)
        chosen = forecast_band.clean_days(self.cfg.get("fsrs_new_card_days", forecast_band.ALL_DAYS))
        self.fsrs_day_buttons = []
        days_row = QHBoxLayout()
        days_row.setSpacing(3)
        for wd, label in enumerate(forecast_band.WEEKDAYS):
            b = QPushButton(label)
            b.setObjectName("hmDay")
            b.setCheckable(True)
            b.setChecked(wd in chosen)
            b.setAutoDefault(False)
            b.setToolTip("Add new cards on " + ["Mondays", "Tuesdays", "Wednesdays", "Thursdays",
                                               "Fridays", "Saturdays", "Sundays"][wd])
            self.fsrs_day_buttons.append(b)
            days_row.addWidget(b)
        new_cards_row.addLayout(days_row)
        new_cards_row.addStretch()
        settings_layout.addLayout(new_cards_row)

        match_row = QHBoxLayout()
        match_btn = QPushButton(f"Match my last {forecast_band.MATCH_WEEKS} weeks")
        match_btn.setAutoDefault(False)
        match_btn.setToolTip("Fill in the days you usually add new cards on, and how many,\n"
                             "from the forecast deck's last few weeks.")
        match_btn.clicked.connect(self._match_new_card_days)
        match_row.addWidget(match_btn)
        self.fsrs_match_label = QLabel("")
        self.fsrs_match_label.setObjectName("hmPageSub")
        self.fsrs_match_label.setWordWrap(True)
        match_row.addWidget(self.fsrs_match_label, 1)
        settings_layout.addLayout(match_row)

        # Confidence band
        band_row = QHBoxLayout()
        self.chk_fsrs_band = QCheckBox("Show a confidence band")
        self.chk_fsrs_band.setChecked(bool(self.cfg.get("fsrs_band_enabled", False)))
        self.chk_fsrs_band.setToolTip(
            "A shaded range around the forecast, in standard deviations from your own data:\n"
            f"how far your new cards strayed from the plan over the last {forecast_band.BAND_WEEKS} weeks (wider above\n"
            "the line, since an extra batch adds a lot), and how far past forecasts were off,\n"
            "rebuilt from your review history at first, then from the add-on's saved forecasts.\n"
            "Tested on past months, ±1 SD held about 2 in 3 days and ±2 SD about 6 in 7.\n"
            "It can't foresee breaks, exam weeks or starting a new block."
        )
        band_row.addWidget(self.chk_fsrs_band)
        self.fsrs_band_combo = QComboBox()
        self.fsrs_band_combo.addItem("±1 SD (about 2 in 3 days)", 1)
        self.fsrs_band_combo.addItem("±2 SD (about 6 in 7 days)", 2)
        self.fsrs_band_combo.setCurrentIndex(1 if int(self.cfg.get("fsrs_band_sd", 1) or 1) >= 2 else 0)
        self.fsrs_band_combo.setEnabled(self.chk_fsrs_band.isChecked())
        self.chk_fsrs_band.toggled.connect(self.fsrs_band_combo.setEnabled)
        band_row.addWidget(self.fsrs_band_combo)
        band_row.addStretch()
        settings_layout.addLayout(band_row)

        # Maximum reviews/day
        max_rev_row = QHBoxLayout()
        max_rev_row.addWidget(QLabel("Maximum reviews/day:"))
        self.fsrs_max_rev_spin = QSpinBox()
        self.fsrs_max_rev_spin.setRange(1, 9999)
        self.fsrs_max_rev_spin.setValue(self.cfg.get("fsrs_simulation_max_reviews", 9999))
        max_rev_row.addWidget(self.fsrs_max_rev_spin)
        max_rev_row.addStretch()
        settings_layout.addLayout(max_rev_row)

        fsrs_layout.addLayout(settings_layout)

        # Advanced Settings (collapsible)
        self.adv_group = QGroupBox("Advanced Settings")
        self.adv_group.setCheckable(True)
        self.adv_group.setChecked(self.cfg.get("fsrs_advanced_expanded", False))
        adv_layout = QVBoxLayout()
        adv_layout.setContentsMargins(10, 5, 10, 5)

        # Maximum interval
        max_ivl_row = QHBoxLayout()
        max_ivl_row.addWidget(QLabel("Maximum interval (days):"))
        self.fsrs_max_ivl_spin = QSpinBox()
        self.fsrs_max_ivl_spin.setRange(1, 36500)
        self.fsrs_max_ivl_spin.setValue(self.cfg.get("fsrs_simulation_max_interval", 36500))
        max_ivl_row.addWidget(self.fsrs_max_ivl_spin)
        max_ivl_row.addStretch()
        adv_layout.addLayout(max_ivl_row)

        # Learning steps
        learn_row = QHBoxLayout()
        learn_row.addWidget(QLabel("Learning step count:"))
        self.fsrs_learn_spin = QSpinBox()
        self.fsrs_learn_spin.setRange(1, 10)
        self.fsrs_learn_spin.setValue(self.cfg.get("fsrs_learning_steps", 2))
        self.fsrs_learn_spin.setToolTip("Number of learning reviews before graduation")
        learn_row.addWidget(self.fsrs_learn_spin)
        learn_row.addStretch()
        adv_layout.addLayout(learn_row)

        # Relearning steps
        relearn_row = QHBoxLayout()
        relearn_row.addWidget(QLabel("Relearning step count:"))
        self.fsrs_relearn_spin = QSpinBox()
        self.fsrs_relearn_spin.setRange(1, 10)
        self.fsrs_relearn_spin.setValue(self.cfg.get("fsrs_relearning_steps", 1))
        self.fsrs_relearn_spin.setToolTip("Number of relearning reviews after a lapse")
        relearn_row.addWidget(self.fsrs_relearn_spin)
        relearn_row.addStretch()
        adv_layout.addLayout(relearn_row)

        # Overhead calibration checkbox
        self.chk_fsrs_overhead = QCheckBox("Count learning and relearning steps")
        self.chk_fsrs_overhead.setChecked(self.cfg.get("fsrs_simulate_overhead", True))
        self.chk_fsrs_overhead.setToolTip(
            "Counts every answer, as the heatmap and graph do: the learning steps of new cards\n"
            "and the relearning steps after a lapse, from your own last weeks of reviews.\n"
            "Off: only reviews of cards already learned, as in Anki's FSRS simulator."
        )
        adv_layout.addWidget(self.chk_fsrs_overhead)

        # Show observed lapse rate and relearn fail rate so the user knows what's being applied.
        # A few revlog counts (~0.1 s on a big collection): worked out when this section is first
        # shown, not every time Settings opens.
        def observed_text():
            try:
                _cutoff_ms = int(time.time() * 1000) - (90 * 86400 * 1000)
                _n_mature      = mw.col.db.scalar(f"SELECT count() FROM revlog WHERE type=1 AND id > {_cutoff_ms}") if mw.col else 0
                _n_lapse       = mw.col.db.scalar(f"SELECT count() FROM revlog WHERE type=1 AND ease=1 AND id > {_cutoff_ms}") if mw.col else 0
                _n_relearn      = mw.col.db.scalar(f"SELECT count() FROM revlog WHERE type=2 AND id > {_cutoff_ms}") if mw.col else 0
                _n_relearn_fail = mw.col.db.scalar(f"SELECT count() FROM revlog WHERE type=2 AND ease=1 AND id > {_cutoff_ms}") if mw.col else 0
                _lapse_rate        = _n_lapse / _n_mature if _n_mature > 0 else None
                _relearn_fail_rate = _n_relearn_fail / _n_relearn if _n_relearn > 0 else None
            except:
                _lapse_rate = None
                _relearn_fail_rate = None
            _lr_str  = f"{_lapse_rate:.1%}"        if _lapse_rate        is not None else "n/a"
            _rfr_str = f"{_relearn_fail_rate:.1%}" if _relearn_fail_rate is not None else "n/a"
            try:
                _rollover = mw.col.conf.get('rollover', 4)
                _today = datetime.datetime.fromtimestamp(time.time() - _rollover * 3600).date()
                _profile = forecast_band.learning_profile(mw.col, None, _today, _rollover, 0)
                _learn_str = f"{sum(_profile):.1f}" if sum(_profile) else "n/a"
            except Exception:
                _learn_str = "n/a"
            return (f"  Observed: lapse rate {_lr_str}  ·  relearn fail rate {_rfr_str}"
                    f"  ·  {_learn_str} learning answers per new card")

        lapse_info = QLabel("  Observed: …")
        _when_first_shown(lapse_info, lambda: lapse_info.setText(observed_text()))
        lapse_info.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        adv_layout.addWidget(lapse_info)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #555;")
        adv_layout.addWidget(sep)

        # Custom FSRS weights section
        weights_header = QLabel("FSRS Parameters")
        weights_header.setStyleSheet("font-weight: bold; margin-top: 5px;")
        adv_layout.addWidget(weights_header)

        # Show auto-detected weights
        if fsrs_weights:
            auto_label = QLabel(f"From Deck Options: [{', '.join(f'{w:.4f}' for w in fsrs_weights[:5])}...]")
            auto_label.setStyleSheet("color: #7f8c8d; font-size: 9px;")
            auto_label.setToolTip(f"The forecast deck's preset:\n{', '.join(f'{w:.4f}' for w in fsrs_weights)}")
            adv_layout.addWidget(auto_label)

        # Use custom weights checkbox
        self.chk_custom_weights = QCheckBox("Use custom FSRS parameters")
        self.chk_custom_weights.setChecked(self.cfg.get("fsrs_use_custom_weights", False))
        self.chk_custom_weights.setToolTip("Enter your own FSRS weights instead of using deck config")
        adv_layout.addWidget(self.chk_custom_weights)

        # Custom weights input
        weights_input_layout = QVBoxLayout()
        weights_input_layout.setContentsMargins(20, 0, 0, 0)

        weights_hint = QLabel("Paste weights from Deck Options → FSRS parameters:")
        weights_hint.setStyleSheet("color: #7f8c8d; font-size: 9px;")
        weights_input_layout.addWidget(weights_hint)

        self.fsrs_weights_input = QLineEdit()
        self.fsrs_weights_input.setPlaceholderText("e.g., 0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01, 1.49, ...")
        self.fsrs_weights_input.setText(self.cfg.get("fsrs_custom_weights", ""))
        self.fsrs_weights_input.setToolTip(
            "Enter 17 to 21 comma-separated numbers.\n"
            "Copy from: Deck Options → FSRS parameters\n"
            "Example: 0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01, 1.49, 0.14, 0.94, 2.18, 0.05, 0.34, 1.26, 0.29, 2.61"
        )
        weights_input_layout.addWidget(self.fsrs_weights_input)

        # Copy from deck button
        copy_btn_row = QHBoxLayout()
        self.fsrs_copy_weights_btn = QPushButton("Copy from forecast deck")
        self.fsrs_copy_weights_btn.clicked.connect(self._copy_deck_weights)
        self.fsrs_copy_weights_btn.setToolTip("Copy the parameters from the Forecast Deck's preset in Deck Options.")
        copy_btn_row.addWidget(self.fsrs_copy_weights_btn)
        copy_btn_row.addStretch()
        weights_input_layout.addLayout(copy_btn_row)

        adv_layout.addLayout(weights_input_layout)

        self.adv_group.setLayout(adv_layout)
        fsrs_layout.addWidget(self.adv_group)

        fsrs_group.setLayout(fsrs_layout)
        layout.addWidget(fsrs_group)

        # Forecast Deck Selector
        forecast_group = QGroupBox("Forecast Deck")
        fc_layout = QVBoxLayout()

        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("Deck:"))
        self.fsrs_deck_combo = QComboBox()
        self.fsrs_deck_combo.addItem("Most recent deck (auto)", 0)
        if mw.col:
            for deck in sorted(mw.col.decks.all(), key=lambda d: d['name']):
                self.fsrs_deck_combo.addItem(deck['name'], deck['id'])
        saved_deck = self.cfg.get("fsrs_forecast_deck", 0)
        for i in range(self.fsrs_deck_combo.count()):
            if self.fsrs_deck_combo.itemData(i) == saved_deck:
                self.fsrs_deck_combo.setCurrentIndex(i)
                break
        self.fsrs_deck_combo.setToolTip("Select deck for forecast. 'Most recent' automatically uses the deck you last studied.")
        deck_row.addWidget(self.fsrs_deck_combo)
        deck_row.addStretch()
        fc_layout.addLayout(deck_row)

        forecast_group.setLayout(fc_layout)
        layout.addWidget(forecast_group)

        validate_btn = QPushButton("Validate Forecast with Historical Data…")
        self.validate_btn = validate_btn
        validate_btn.setToolTip(
            "Compare FSRS predictions against your actual review history to check model accuracy.")
        validate_btn.clicked.connect(self._open_backtest_dialog)
        layout.addWidget(validate_btn)

        layout.addStretch()
        widget.setLayout(layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _open_backtest_dialog(self):
        dlg = BacktestDialog(self)
        dlg.exec()

    def _match_new_card_days(self):
        """Set the new-card count and days from the forecast deck's last few weeks."""
        if not mw.col:
            return
        did = int(self.fsrs_deck_combo.currentData() or 0)
        if not did:
            try:
                did = FastEngine(cache_only=True)._get_most_recent_deck() or 0
            except Exception:
                did = 0
        dids = forecast_band.scope_dids(mw.col, [did] if did else None)
        rollover = mw.col.conf.get('rollover', 4)
        today = datetime.datetime.fromtimestamp(time.time() - rollover * 3600).date()
        try:
            counts = forecast_band.weekday_counts(mw.col, dids, today, rollover, forecast_band.MATCH_WEEKS)
        except Exception:
            traceback.print_exc()
            self.fsrs_match_label.setText("Couldn't read your review history.")
            return
        per_day, days = forecast_band.match(counts)
        if per_day == 0:
            self.fsrs_match_label.setText(f"No new cards in the last {forecast_band.MATCH_WEEKS} weeks.")
            return
        self.fsrs_new_cards_spin.setValue(per_day)
        for wd, b in enumerate(self.fsrs_day_buttons):
            b.setChecked(wd in days)
        avg = " · ".join(f"{forecast_band.WEEKDAYS[w]} {round(sum(v) / len(v))}"
                         for w, v in counts.items() if v)
        self.fsrs_match_label.setText(f"Average new cards: {avg}")

    def _update_fsrs_ret_label(self, value):
        self.fsrs_ret_label.setText(f"{value}%")

    def _fsrs_weights_deck(self):
        """The deck whose preset the forecast's parameters come from: the Forecast Deck
        choice, else the deck you studied last (else, later, the current deck)."""
        combo = getattr(self, "fsrs_deck_combo", None)
        did = int((combo.currentData() if combo is not None else self.cfg.get("fsrs_forecast_deck", 0)) or 0)
        if not did:
            try:
                did = FastEngine(cache_only=True)._get_most_recent_deck() or 0
            except Exception:
                did = 0
        return did or None

    def _copy_deck_weights(self):
        """Copy the forecast deck's optimized FSRS parameters into the custom field."""
        did = self._fsrs_weights_deck()
        weights = _saved_fsrs_weights(did)
        if not weights:
            QMessageBox.warning(self, "No parameters found",
                "This deck's preset has no optimized FSRS parameters. Optimize them in Deck Options first.")
            return
        name = ""
        try:
            name = mw.col.decks.name(did) if did else mw.col.decks.current()["name"]
        except Exception:
            pass
        self.fsrs_weights_input.setText(", ".join(f"{w:.4f}" for w in weights))
        self.chk_custom_weights.setChecked(True)
        QMessageBox.information(self, "Copied",
            f"Copied {len(weights)} FSRS parameters" + (f" from {name}." if name else "."))

    def update_opacity_label(self, value):
        self.opacity_label.setText(f"{value}%")

    def _update_intensity_label(self, value):
        # Higher slider value = lower exponent = more visible low activity
        if value >= 80:
            text = "High"
        elif value >= 50:
            text = "Medium"
        else:
            text = "Low"
        self.intensity_label.setText(text)

    def _update_min_opacity_label(self, value):
        self.min_opacity_label.setText(f"{value}%")

    def _update_shade_label(self, value):
        self.shade_label.setText(f"{value}%")

    def _on_gradient_mode_changed(self, index):
        mode = self.gradient_mode_combo.itemData(index)
        is_shade = mode in ('shade', 'shade_inverted')
        self.shade_slider.setEnabled(is_shade)
        self.shade_label.setEnabled(is_shade)
        # Glow places days by rank, so these don't apply to it
        for w in ("intensity_slider", "min_opacity_slider", "color_scale_max_spin"):
            if hasattr(self, w):
                getattr(self, w).setEnabled(mode != 'glow')
        for w in ("glow_slider", "glow_label"):
            if hasattr(self, w):
                getattr(self, w).setEnabled(mode == 'glow')

    def on_color_hex_changed(self, key, text):
        if QColor.isValidColor(text) and key in self.color_btns:
            self.color_btns[key].setStyleSheet(f"background-color: {text}; border: 1px solid #bdc3c7; border-radius: 4px;")

    def pick_graph_color(self, key):
        current = self.color_inputs[key].text()
        c = QColorDialog.getColor(QColor(current), self)
        if c.isValid() and c.name() != current:
            self.color_inputs[key].setText(c.name())
            self.color_btns[key].setStyleSheet(f"background-color: {c.name()}; border: 1px solid #bdc3c7; border-radius: 4px;")
            if hasattr(self, "_theme_cards"):
                self._colors_edited()

    def create_time_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        self.chk_time_enabled = QCheckBox("Estimate time left")
        self.chk_time_enabled.setToolTip(
            "Learns how long your cards take from your own review history and estimates how long\n"
            "today's remaining cards will take, with a likely range. It improves itself each day.")
        self.chk_time_enabled.setChecked(self.cfg.get("time_estimate_enabled", False))
        layout.addWidget(self.chk_time_enabled)

        group = QGroupBox("Show it")
        g = QVBoxLayout()
        self.chk_time_column = QCheckBox("Time column in the deck list")
        self.chk_time_column.setChecked(self.cfg.get("time_deck_column", True))
        self.chk_time_pill = QCheckBox("Today's finish time")
        self.chk_time_pill.setChecked(self.cfg.get("time_today_pill", True))
        self.chk_time_overview = QCheckBox("On the deck overview")
        self.chk_time_overview.setChecked(self.cfg.get("time_overview", True))
        self.chk_time_desk = QCheckBox("Include the time between cards")
        self.chk_time_desk.setToolTip("Counts the few seconds you spend between answers, so times match the clock.")
        self.chk_time_desk.setChecked(self.cfg.get("time_desk_time", True))
        g.addWidget(self.chk_time_column)
        g.addWidget(self.chk_time_overview)
        where = QLabel("Today's finish time under your decks is in Reminders.")
        where.setObjectName("hmPageSub")
        g.addWidget(where)
        group.setLayout(g)
        layout.addWidget(group)
        layout.addWidget(self.chk_time_desk)
        self.chk_away_lookup = QCheckBox("Focus score: count leaving Anki during a card as a lookup")
        self.chk_away_lookup.setToolTip(
            "Cards where you open the editor or browser are always left out of the focus score.\n"
            "Switching to another app could be a lookup or a video, so by default it still counts.\n"
            "Tick this if you only leave Anki to look things up.")
        self.chk_away_lookup.setChecked(self.cfg.get("focus_away_is_lookup", False))
        layout.addWidget(self.chk_away_lookup)
        self.chk_reading_counts = QCheckBox("Focus score: don't count time spent reading the answer")
        self.chk_reading_counts.setToolTip(
            "Judges a card by how long the question side took, as long as Anki stayed in front.\n"
            "Off by default: reading the back carefully and staring at it look the same.")
        self.chk_reading_counts.setChecked(self.cfg.get("focus_reading_counts", False))
        layout.addWidget(self.chk_reading_counts)
        sf = QFormLayout()
        self.focus_lookup_key = QKeySequenceEdit(QKeySequence(time_left.lookup_key()))
        if hasattr(self.focus_lookup_key, "setMaximumSequenceLength"):
            self.focus_lookup_key.setMaximumSequenceLength(1)
        if hasattr(self.focus_lookup_key, "setClearButtonEnabled"):
            self.focus_lookup_key.setClearButtonEnabled(True)
        self.focus_lookup_key.setMaximumWidth(120)
        self.focus_lookup_key.setToolTip("Press it during review to leave that card out of the focus score.")
        sf.addRow("Leave a card out of focus:", self.focus_lookup_key)
        key_taken = QLabel("Anki already uses this key.")
        key_taken.setStyleSheet("color: #d1383d;")
        sf.addRow("", key_taken)
        # Keys a review-screen shortcut can't share: Anki's menus (F is Create Filtered
        # Deck) and its reviewer keys. Two shortcuts on one key both stop working.
        taken = {"E", "M", "R", "V", "O", "I", "U", "5", "6", "7", "*", "=", "-", "!", "@",
                 "1", "2", "3", "4", "Space", "Return", "Enter"}
        try:
            taken |= {a.shortcut().toString() for a in mw.findChildren(QAction) if not a.shortcut().isEmpty()}
        except Exception:
            pass

        def check_key():
            k = self.focus_lookup_key.keySequence().toString()
            key_taken.setVisible(bool(k) and k in taken)
        self.focus_lookup_key.keySequenceChanged.connect(lambda _s: check_key())
        check_key()
        self.time_show_as = self._show_as_combo()
        sf.addRow("Show today's time as:", self.time_show_as)
        layout.addLayout(sf)

        btn = QPushButton("Accuracy check…")
        btn.setToolTip("How close the estimate has been on your recent days.")
        btn.clicked.connect(lambda: time_left.show_accuracy())
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        def sync(on):
            group.setEnabled(on)
            self.chk_time_desk.setEnabled(on)
            self.chk_away_lookup.setEnabled(on)
            self.chk_reading_counts.setEnabled(on)
            self.focus_lookup_key.setEnabled(on)
            self.time_show_as.setEnabled(on)
            btn.setEnabled(on and time_left.enabled())
        self.chk_time_enabled.toggled.connect(sync)
        sync(self.chk_time_enabled.isChecked())

        # Preview: each place it shows up, with sample numbers
        def time_html():
            def color(key):
                inp = self.color_inputs.get(key) if hasattr(self, "color_inputs") else None
                c = inp.text() if inp is not None else self.cfg.get(key, "")
                return c if QColor.isValidColor(c) else "#888888"
            return time_left.preview_page(self.chk_time_column.isChecked(), self.chk_time_pill.isChecked(),
                                          self.chk_time_overview.isChecked(),
                                          self.time_show_as.currentData() == "left", _is_dark_mode(),
                                          (color("pill_new_color"), color("pill_learn_color"), color("pill_due_color")))

        self.time_preview = _HtmlPreview(272, time_html)
        cap = QLabel("Preview, with sample numbers.")
        cap.setStyleSheet("color: gray;")
        layout.insertWidget(0, self.time_preview)
        layout.insertWidget(1, cap)
        layout.insertSpacing(2, 6)
        for sig in (self.chk_time_column.toggled, self.chk_time_pill.toggled, self.chk_time_overview.toggled,
                    self.time_show_as.currentIndexChanged):
            sig.connect(self.time_preview.refresh)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_day_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        group = QGroupBox("Topics")
        form = QFormLayout()
        # Tag folders with at least one level under them, as choices; any folder can be typed.
        try:
            tags = mw.col.tags.all() if mw.col else []
        except Exception:
            tags = []
        self._day_tags = tags

        def folders():
            out = set()
            for t in tags:
                parts = t.split("::")
                for k in range(1, min(len(parts), 4)):
                    out.add("::".join(parts[:k]))
            return [""] + sorted(out, key=str.lower)

        # Thousands of folders on a big collection (AnKing): listed the first time the box
        # is opened or typed in, not every time Settings opens.
        self.day_topic_tag = _LazyCombo(folders)
        self.day_topic_tag.setEditable(True)
        self.day_topic_tag.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.day_topic_tag.lineEdit().setPlaceholderText("AnKing systems, else subdecks")
        comp = self.day_topic_tag.completer()
        if comp is not None:
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.day_topic_tag.setCurrentText(self.cfg.get("day_topic_tag", ""))
        self.day_topic_tag.setMinimumWidth(320)
        form.addRow("Group by tags under:", self.day_topic_tag)
        self.day_topic_level = QSpinBox()
        self.day_topic_level.setRange(1, 6)
        self.day_topic_level.setValue(int(self.cfg.get("day_topic_level", 1) or 1))
        form.addRow("Levels below it:", self.day_topic_level)
        self.day_topic_example = QLabel()
        self.day_topic_example.setStyleSheet("color: gray;")
        self.day_topic_example.setWordWrap(True)
        form.addRow("", self.day_topic_example)
        self.stats_topic_level = QSpinBox()
        self.stats_topic_level.setRange(0, 6)
        self.stats_topic_level.setSpecialValueText("Auto")
        self.stats_topic_level.setValue(int(self.cfg.get("stats_topic_level", 0) or 0))
        self.stats_topic_level.setToolTip("Auto: the same as above, at most 2. Exams and finals fold into their course.")
        form.addRow("Levels in Stats:", self.stats_topic_level)
        group.setLayout(form)
        layout.addWidget(group)

        def example():
            prefix = [p.lower() for p in self.day_topic_tag.currentText().strip().strip(":").split("::") if p]
            level = self.day_topic_level.value()
            self.day_topic_level.setEnabled(bool(prefix))
            self.stats_topic_level.setEnabled(bool(prefix))
            if not prefix:
                self.day_topic_example.setText("Leave it blank to group AnKing cards by system, and other cards by subdeck.")
                return
            for t in self._day_tags:
                parts = t.split("::")
                if len(parts) >= len(prefix) + level and [p.lower() for p in parts[:len(prefix)]] == prefix:
                    sub = parts[len(prefix):len(prefix) + level]
                    label = day_view._tidy(sub[-1]) + (f" ({day_view._tidy(sub[-2])})" if level > 1 else "")
                    self.day_topic_example.setText(f"A topic would look like: {label}")
                    return
            self.day_topic_example.setText("No tags go that deep under this folder.")

        self.day_topic_tag.currentTextChanged.connect(lambda _t: example())
        self.day_topic_level.valueChanged.connect(lambda _v: example())
        example()
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _show_as_combo(self):
        # Finish clock or hours left. The Time Left and Live Stats tabs each have one,
        # kept in step, since it's one setting.
        c = QComboBox()
        c.addItem("Finish time (Finish ~9:40 PM)", "finish")
        c.addItem("Time left (~1h 20m left)", "left")
        c.setCurrentIndex(1 if self.cfg.get("time_show_as") == "left" else 0)
        c.setToolTip("Hover Live Stats for the other one.")
        twin = getattr(self, "time_show_as", None)
        if twin is not None:
            c.currentIndexChanged.connect(twin.setCurrentIndex)
            twin.currentIndexChanged.connect(c.setCurrentIndex)
        return c

    def create_review_pill_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        rp = review_pill._cfg()      # current choices, including ones saved by older versions

        def combo(items, current):
            c = QComboBox()
            for label, value in items:
                c.addItem(label, value)
            c.setCurrentIndex(next((n for n, (_, v) in enumerate(items) if v == current), 0))
            return c

        def spin(lo, hi, value, suffix=""):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(value))
            if suffix:
                sp.setSuffix(suffix)
            return sp

        self.chk_rp_enabled = QCheckBox("Show Live Stats while you review")
        self.chk_rp_enabled.setToolTip("Your stats in a corner of the review screen. Hover it for the details.")
        self.chk_rp_enabled.setChecked(self.cfg.get("review_pill_enabled", False))
        layout.addWidget(self.chk_rp_enabled)

        def indented(child_layout):
            box = QWidget()
            child_layout.setContentsMargins(24, 0, 0, 6)
            box.setLayout(child_layout)
            return box

        # Part 1: retention
        self.chk_rp_retention = QCheckBox("Retention")
        self.chk_rp_retention.setToolTip("Your retention for the deck you're studying and how far you are from your target.")
        self.chk_rp_retention.setChecked(rp["show_retention"])
        layout.addWidget(self.chk_rp_retention)
        rf = QFormLayout()
        self.rp_style = combo([("Graph", "graph"), ("Numbers (margin and %)", "numbers"),
                               ("Only when I hover", "hover")], rp["retention_style"])
        self.rp_style.setToolTip("What Live Stats shows for retention. The hover panel always has the full numbers.")
        rf.addRow("Shows:", self.rp_style)
        self.rp_target = spin(50, 99, rp["target_retention"], "%")
        self.rp_target.setToolTip("Live Stats tells you how many more you can miss, or how many you need right, to stay at it.")
        rf.addRow("Target retention:", self.rp_target)
        self.rp_window = combo([("Today", "today"), ("All time", "all")], rp["window"])
        rf.addRow("Count it over:", self.rp_window)
        self.rp_span = spin(10, 2000, rp["rolling_window"], " cards")
        self.rp_span.setToolTip("How many of today's recent cards the graph spans.")
        rf.addRow("Graph spans the last:", self.rp_span)
        self.rp_smooth = spin(0, 10, rp["smoothing"])
        self.rp_smooth.setToolTip("0 = card-by-card steps; higher = smoother. The end point is never smoothed.")
        rf.addRow("Graph smoothing:", self.rp_smooth)
        ret = indented(rf)
        layout.addWidget(ret)

        # Part 2: when you'll finish
        self.chk_rp_time = QCheckBox("When you'll finish")
        self.chk_rp_time.setToolTip("When you'll be done, as a finish time or time left, with its likely range when you hover.")
        self.chk_rp_time.setChecked(bool(rp["show_time_left"]))
        layout.addWidget(self.chk_rp_time)
        ff = QVBoxLayout()
        sf = QFormLayout()
        self.rp_show_as = self._show_as_combo()
        sf.addRow("Show as:", self.rp_show_as)
        ff.addLayout(sf)
        self.chk_rp_focus = QCheckBox("Show a cue when you seem to be drifting")
        self.chk_rp_focus.setToolTip("Amber when several recent cards took far longer than they usually take you.")
        self.chk_rp_focus.setChecked(bool(rp["focus_cue"]))
        ff.addWidget(self.chk_rp_focus)
        ring_row = QHBoxLayout()
        ring_row.addWidget(QLabel("Ring after each answer:"))
        self.rp_ring = QComboBox()
        self.rp_ring.addItem("Drawn outline", "draw")
        self.rp_ring.addItem("Gentle fade", "fade")
        self.rp_ring.addItem("Off", "off")
        self.rp_ring.setToolTip("Green around Live Stats when the card took no longer than its usual time plus one\n"
                                "of its standard deviations, amber when it took longer. No ring for lookups.")
        ring_now = rp.get("ring_style", "draw") if rp.get("focus_ring", True) else "off"
        self.rp_ring.setCurrentIndex(max(0, self.rp_ring.findData(ring_now)))
        ring_row.addWidget(self.rp_ring)
        ring_row.addStretch()
        ff.addLayout(ring_row)
        note = QLabel("Needs Time Left switched on.")
        note.setStyleSheet("color: gray;")
        ff.addWidget(note)
        fin = indented(ff)
        layout.addWidget(fin)

        # Part 3: a pomodoro timer
        pc = pomodoro.cfg()
        self.chk_rp_pomo = QCheckBox("Pomodoro timer")
        self.chk_rp_pomo.setToolTip("A focus timer at the end of Live Stats, with breaks in between.")
        self.chk_rp_pomo.setChecked(bool(self.cfg.get("pomo_enabled", False)))
        layout.addWidget(self.chk_rp_pomo)
        pv = QVBoxLayout()
        pform = QFormLayout()
        self.rp_pomo_focus = spin(5, 120, pc["pomo_focus_min"], " min")
        pform.addRow("Focus blocks:", self.rp_pomo_focus)
        self.rp_pomo_break = spin(1, 60, pc["pomo_break_min"], " min")
        pform.addRow("Breaks:", self.rp_pomo_break)
        long_row = QHBoxLayout()
        self.rp_pomo_long = spin(1, 90, pc["pomo_long_min"], " min")
        self.rp_pomo_every = spin(2, 12, pc["pomo_long_every"])
        long_row.addWidget(self.rp_pomo_long)
        long_row.addWidget(QLabel("after every"))
        long_row.addWidget(self.rp_pomo_every)
        long_row.addWidget(QLabel("blocks"))
        long_row.addStretch()
        pform.addRow("Long breaks:", long_row)
        pv.addLayout(pform)
        self.chk_rp_pomo_pause = QCheckBox("Pause when I leave reviews")
        self.chk_rp_pomo_pause.setChecked(bool(pc["pomo_pause_away"]))
        pv.addWidget(self.chk_rp_pomo_pause)
        self.chk_rp_pomo_drift = QCheckBox("Offer a break when my focus drifts")
        self.chk_rp_pomo_drift.setChecked(bool(pc["pomo_drift_break"]))
        pv.addWidget(self.chk_rp_pomo_drift)
        self.chk_rp_pomo_notify = QCheckBox("Notify me when a break ends")
        self.chk_rp_pomo_notify.setChecked(bool(pc["pomo_notify"]))
        pv.addWidget(self.chk_rp_pomo_notify)
        pomo_box = indented(pv)
        layout.addWidget(pomo_box)

        place = QGroupBox("Where it sits")
        pf = QFormLayout()
        self.rp_corner = combo([("Top right", "top-right"), ("Top left", "top-left"),
                                ("Bottom right", "bottom-right"), ("Bottom left", "bottom-left")], rp["position"])
        pf.addRow("Corner:", self.rp_corner)
        self.chk_rp_drag = QCheckBox("Drag it with the ⋮ handle (double-click the handle to reset)")
        self.chk_rp_drag.setChecked(bool(rp["draggable"]))
        pf.addRow(self.chk_rp_drag)
        place.setLayout(pf)
        layout.addWidget(place)

        def sync(*_):
            on = self.chk_rp_enabled.isChecked()
            for w in (self.chk_rp_retention, self.chk_rp_time, self.chk_rp_pomo, place):
                w.setEnabled(on)
            ret.setEnabled(on and self.chk_rp_retention.isChecked())
            fin.setEnabled(on and self.chk_rp_time.isChecked())
            pomo_box.setEnabled(on and self.chk_rp_pomo.isChecked())
            self.chk_rp_pomo_drift.setEnabled(self.chk_time_enabled.isChecked())
            graph_on = self.rp_style.currentData() == "graph"
            self.rp_span.setEnabled(graph_on)
            self.rp_smooth.setEnabled(graph_on)
            note.setVisible(not self.chk_time_enabled.isChecked())
        for sig in (self.chk_rp_enabled.toggled, self.chk_rp_retention.toggled, self.chk_rp_time.toggled,
                    self.chk_time_enabled.toggled, self.rp_style.currentIndexChanged, self.chk_rp_pomo.toggled):
            sig.connect(sync)
        # At least one part stays on: switching one off while the other is off turns that one on.
        self.chk_rp_retention.toggled.connect(
            lambda on: None if on or self.chk_rp_time.isChecked() else self.chk_rp_time.setChecked(True))
        self.chk_rp_time.toggled.connect(
            lambda on: None if on or self.chk_rp_retention.isChecked() else self.chk_rp_retention.setChecked(True))
        sync()

        # Preview: the real pill and its hover panel, drawn from sample numbers
        self._ring_n = 0

        def pill_html():
            overrides = {
                "show_retention": self.chk_rp_retention.isChecked(),
                "retention_style": self.rp_style.currentData(),
                "target_retention": self.rp_target.value(),
                "window": self.rp_window.currentData(),
                "rolling_window": self.rp_span.value(),
                "smoothing": self.rp_smooth.value(),
                "show_time_left": self.chk_rp_time.isChecked(),
                "focus_cue": self.chk_rp_focus.isChecked(),
                "min_reviews_to_show": 0,
                "pomo": self.chk_rp_pomo.isChecked(),
            }
            night = _is_dark_mode()
            payload = review_pill.preview_payload(overrides, night, self.rp_show_as.currentData() == "left")
            photo = None
            try:      # the background photo, if it shows behind reviews
                bc = background._cfg()
                if bc["background_enabled"] and bc["background_in_review"]:
                    photo = (background.current_path(), bc["background_opacity_review"])
            except Exception:
                photo = None
            return review_pill.preview_page(payload, self.rp_corner.currentData(), night, photo)

        self.rp_preview = _HtmlPreview(372, pill_html, base_dir=os.path.dirname(os.path.abspath(__file__)))
        head = QHBoxLayout()
        cap = QLabel("Preview, with sample numbers. Hovering Live Stats opens this panel.")
        cap.setStyleSheet("color: gray;")
        head.addWidget(cap, 1)
        ring_btn = QPushButton("Show the ring")
        ring_btn.setToolTip("The ring drawn around Live Stats after each answer: green when the card took no\n"
                            "longer than usual, amber when it did.")

        def play_ring():
            style = self.rp_ring.currentData()
            if style == "off":
                return
            self._ring_n += 1
            kind = "focus" if self._ring_n % 2 else "slow"
            self.rp_preview.run_js(review_pill.preview_ring_js(kind, style, self._ring_n))
        ring_btn.clicked.connect(play_ring)
        self.rp_ring.currentIndexChanged.connect(lambda *_: ring_btn.setEnabled(self.rp_ring.currentData() != "off"))
        ring_btn.setEnabled(self.rp_ring.currentData() != "off")
        head.addWidget(ring_btn)
        layout.insertWidget(0, self.rp_preview)
        layout.insertLayout(1, head)
        layout.insertSpacing(2, 6)
        for sig in (self.chk_rp_retention.toggled, self.rp_style.currentIndexChanged, self.rp_target.valueChanged,
                    self.rp_window.currentIndexChanged, self.rp_span.valueChanged, self.rp_smooth.valueChanged,
                    self.chk_rp_time.toggled, self.chk_rp_focus.toggled, self.rp_show_as.currentIndexChanged,
                    self.rp_corner.currentIndexChanged, self.chk_rp_pomo.toggled):
            sig.connect(self.rp_preview.refresh)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_background_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        self.chk_bg_enabled = QCheckBox("Show a background photo")
        self.chk_bg_enabled.setToolTip("A faint photo behind the deck list, overview and review screen.")
        self.chk_bg_enabled.setChecked(bool(self.cfg.get("background_enabled", False)))
        layout.addWidget(self.chk_bg_enabled)

        def strength(key, default):
            row = QHBoxLayout()
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(int(round(float(self.cfg.get(key, default)) * 100)))
            lab = QLabel(f"{sl.value()}%")
            lab.setFixedWidth(35)
            sl.valueChanged.connect(lambda v: lab.setText(f"{v}%"))
            row.addWidget(sl)
            row.addWidget(lab)
            return sl, row

        form = QFormLayout()
        self.bg_source = QComboBox()
        self.bg_source.addItem("My photos", "mine")
        self.bg_source.insertSeparator(1)
        for stem, label in background.BUILTIN.items():
            if background.builtin_file(stem):
                self.bg_source.addItem(label, f"builtin:{stem}")
        self.bg_source.setToolTip("A built-in photo, or your own photos from the folder (Open folder).")
        self.bg_source.setCurrentIndex(max(0, self.bg_source.findData(self.cfg.get("background_source", "builtin:dusk"))))
        form.addRow("Photos:", self.bg_source)
        self.bg_rotation = QComboBox()
        self.bg_rotation.addItem("Every day", "daily")
        self.bg_rotation.addItem("Each time Anki opens", "launch")
        self.bg_rotation.addItem("Keep one photo", "fixed")
        self.bg_rotation.setToolTip("Every day: changes when your next day starts (Preferences › Review),\n"
                                    "and shows every photo once before repeating any.")
        self.bg_rotation.setCurrentIndex(max(0, self.bg_rotation.findData(self.cfg.get("background_rotation", "daily"))))
        form.addRow("New photo:", self.bg_rotation)
        self.bg_image = QComboBox()
        form.addRow("Photo:", self.bg_image)
        self.bg_main, main_row = strength("background_opacity_main", 0.6)
        self.bg_main.setToolTip("The deck list, overview, and top and bottom bars.")
        form.addRow("Strength:", main_row)
        self.chk_bg_review = QCheckBox("Also behind the review screen")
        self.chk_bg_review.setChecked(bool(self.cfg.get("background_in_review", True)))
        form.addRow(self.chk_bg_review)
        self.bg_review, review_row = strength("background_opacity_review", 0.1)
        self.bg_review.setToolTip("Kept low so cards stay easy to read.")
        form.addRow("Review strength:", review_row)
        self.chk_bg_bars = QCheckBox("Also on the top and bottom bars")
        self.chk_bg_bars.setChecked(bool(self.cfg.get("background_on_bars", True)))
        form.addRow(self.chk_bg_bars)
        opts = QWidget()
        form.setContentsMargins(24, 0, 0, 6)
        opts.setLayout(form)
        layout.addWidget(opts)

        today_row = QHBoxLayout()
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(96, 60)
        self.bg_preview.setScaledContents(False)
        today_row.addWidget(self.bg_preview)
        self.bg_today = QLabel()
        today_row.addWidget(self.bg_today, 1)
        self.bg_next = QPushButton("Next photo")
        self.bg_next.setToolTip("Switch now. The new photo stays for the rest of the day.")
        today_row.addWidget(self.bg_next)
        folder_btn = QPushButton("Open folder")
        folder_btn.setToolTip("Add or remove photos here (JPG, PNG, WebP).")
        today_row.addWidget(folder_btn)
        layout.addLayout(today_row)

        self.bg_copy = QPushButton()
        layout.addWidget(self.bg_copy, 0, Qt.AlignmentFlag.AlignLeft)
        self.bg_note = QLabel()
        self.bg_note.setWordWrap(True)
        self.bg_note.setStyleSheet("color: gray;")
        layout.addWidget(self.bg_note)

        def fill():
            files = background.photos()
            keep = self.bg_image.currentData() or self.cfg.get("background_image", "")
            self.bg_image.blockSignals(True)
            self.bg_image.clear()
            for f in files:
                self.bg_image.addItem(f, f)
            self.bg_image.setCurrentIndex(max(0, self.bg_image.findData(keep)))
            self.bg_image.blockSignals(False)
            other = background.other_addon()
            n = len(other["photos"]) if other else 0
            self.bg_copy.setText(f"Copy {n} photo{'s' if n != 1 else ''} from {other['name'] if other else ''}")
            self.bg_copy.setVisible(n > 0)
            notes = []
            if not files and self.bg_source.currentData() == "mine":
                notes.append("The folder is empty. Add photos to it with Open folder.")
            if other and other["enabled"]:
                notes.append(f"Turn off {other['name']} in Tools › Add-ons so the two photos don't stack.")
            self.bg_note.setText("\n".join(notes))
            self.bg_note.setVisible(bool(notes))
            sync()

        preview_of = {}

        def show_preview(path):
            if path not in preview_of:
                img = QImage(path) if path else QImage()
                preview_of[path] = (QPixmap.fromImage(img.scaled(
                    96, 60, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation).copy(0, 0, 96, 60)) if not img.isNull() else None)
            pm = preview_of[path]
            self.bg_preview.setVisible(pm is not None)
            if pm is not None:
                self.bg_preview.setPixmap(pm)

        def sync(*_):
            on = self.chk_bg_enabled.isChecked()
            mine = self.bg_source.currentData() == "mine"
            have = bool(background.photos())
            fixed = self.bg_rotation.currentData() == "fixed"
            opts.setEnabled(on)
            for w in (self.bg_rotation, self.bg_image):     # only your own photos rotate
                w.setVisible(mine)
                form.labelForField(w).setVisible(mine)
            self.bg_image.setEnabled(on and mine and fixed)
            self.bg_review.setEnabled(on and self.chk_bg_review.isChecked())
            self.bg_next.setVisible(mine)
            self.bg_next.setEnabled(on and have and not fixed)
            if not mine:
                stem = self.bg_source.currentData().split(":", 1)[1]
                self.bg_today.setText("")
                show_preview(background.builtin_file(stem))
                return
            st = None if fixed else background.current()    # None until switched on and saved
            if fixed and self.bg_image.currentData():
                st = self.bg_image.currentData()
            if not have:
                self.bg_today.setText("")
            elif st in background.photos():
                self.bg_today.setText(st if fixed else f"Today: {st}")
            else:
                self.bg_today.setText(f"{len(background.photos())} photos in the folder")
            show_preview(os.path.join(background.FOLDER, st) if st in background.photos() else None)

        def next_photo():
            if not self.cfg.get("background_enabled"):
                return
            background.next_photo()
            sync()

        def copy():
            n = background.copy_from_other()
            tooltip(f"Copied {n} photo{'s' if n != 1 else ''}.", parent=self)
            fill()

        self.bg_next.clicked.connect(next_photo)
        folder_btn.clicked.connect(lambda: openFolder(background.FOLDER))
        self.bg_copy.clicked.connect(copy)
        for sig in (self.chk_bg_enabled.toggled, self.chk_bg_review.toggled, self.bg_rotation.currentIndexChanged,
                    self.bg_image.currentIndexChanged):
            sig.connect(sync)
        self.bg_source.currentIndexChanged.connect(fill)
        fill()

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_browser_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout()

        # Enable browser theme checkbox
        self.chk_browser_theme = QCheckBox("Enable Card Browser Theme")
        self.chk_browser_theme.setToolTip("Apply modern theme styling to the card browser window.")
        self.chk_browser_theme.setChecked(self.cfg.get("enable_browser_theme", True))
        layout.addWidget(self.chk_browser_theme)

        # Enable editor theme checkbox (browser edit panel + add cards window)
        self.chk_editor_theme = QCheckBox("Enable Note Editor Theme")
        self.chk_editor_theme.setToolTip("Style the note editor fields (browser edit panel and Add Cards window).\nTakes effect for newly opened editors.")
        self.chk_editor_theme.setChecked(self.cfg.get("enable_editor_theme", True))
        layout.addWidget(self.chk_editor_theme)

        # Row spacing option
        spacing_row = QHBoxLayout()
        spacing_row.addWidget(QLabel("Row Spacing:"))
        self.browser_spacing_combo = QComboBox()
        self.browser_spacing_combo.addItem("Comfortable", "comfortable")
        self.browser_spacing_combo.addItem("Compact", "compact")
        self.browser_spacing_combo.addItem("Tight", "tight")
        current_spacing = self.cfg.get("browser_row_spacing", "comfortable")
        spacing_index = {"comfortable": 0, "compact": 1, "tight": 2}.get(current_spacing, 0)
        self.browser_spacing_combo.setCurrentIndex(spacing_index)
        spacing_row.addWidget(self.browser_spacing_combo)
        spacing_row.addStretch()
        layout.addLayout(spacing_row)

        self.chk_state_icons = QCheckBox("Show card state symbols (‖ suspended, ● buried, ★ marked)")
        self.chk_state_icons.setToolTip("Drawn before the first column. Takes effect for newly opened browsers.")
        self.chk_state_icons.setChecked(self.cfg.get("browser_state_icons", True))
        layout.addWidget(self.chk_state_icons)

        tags_row = QHBoxLayout()
        tags_row.addWidget(QLabel("Tags Column:"))
        self.browser_tags_combo = QComboBox()
        self.browser_tags_combo.addItem("Full tags (A::B::C)", "full")
        self.browser_tags_combo.addItem("Last part only (C)", "leaf")
        self.browser_tags_combo.addItem("Arrows (A › B › C)", "arrows")
        tags_index = self.browser_tags_combo.findData(self.cfg.get("browser_tag_display", "full"))
        self.browser_tags_combo.setCurrentIndex(max(tags_index, 0))
        self.browser_tags_combo.setToolTip("Takes effect for newly opened browsers.")
        tags_row.addWidget(self.browser_tags_combo)
        tags_row.addStretch()
        layout.addLayout(tags_row)

        layout.addSpacing(10)

        # Theme selection group
        theme_group = QGroupBox("Theme")
        theme_layout = QVBoxLayout()

        # Theme dropdown — lists theme families; each swaps between a dark and a
        # light variant automatically to match Anki's current mode.
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.browser_theme_combo = QComboBox()
        current_family = _theme_family_for_key(self.cfg.get("browser_color_theme", "default"))
        theme_index = 0
        for i, (key, fam) in enumerate(THEME_FAMILIES.items()):
            self.browser_theme_combo.addItem(fam["name"], key)
            if key == current_family:
                theme_index = i
        self.browser_theme_combo.setCurrentIndex(theme_index)
        self.browser_theme_combo.currentIndexChanged.connect(self._update_theme_preview)
        self.browser_theme_combo.currentIndexChanged.connect(self._load_theme_to_custom)
        theme_row.addWidget(self.browser_theme_combo)
        theme_row.addStretch()
        theme_layout.addLayout(theme_row)

        # Preview: sample rows drawn the way the browser draws them
        self.browser_preview = _BrowserPreview()
        theme_layout.addWidget(self.browser_preview)
        preview_note = QLabel("Clozes are colored by number. Suspended, buried and marked cards get a tint and a "
                              "symbol, flags tint the whole row. Follows Anki's light/dark mode.")
        preview_note.setWordWrap(True)
        preview_note.setStyleSheet("color: gray;")
        theme_layout.addWidget(preview_note)
        for sig in (self.browser_spacing_combo.currentIndexChanged, self.chk_state_icons.toggled,
                    self.browser_tags_combo.currentIndexChanged):
            sig.connect(lambda *_a: self._update_theme_preview())

        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)

        # Custom colors checkbox
        self.chk_custom_colors = QCheckBox("Use Custom Colors (override preset theme)")
        self.chk_custom_colors.setChecked(self.cfg.get("browser_custom_colors", False))
        layout.addWidget(self.chk_custom_colors)

        # Custom colors group
        custom_group = QGroupBox("Custom Card Colors")
        custom_layout = QVBoxLayout()

        # Initialize browser color inputs dict
        self.browser_color_inputs = {}
        self.browser_color_btns = {}

        # Card state colors
        state_colors = QGroupBox("Card States")
        state_layout = QGridLayout()
        state_color_defs = [
            ("browser_bg_primary", "Background:", self.cfg.get("browser_bg_primary", "#1e1e1e")),
            ("browser_bg_secondary", "Alt Row:", self.cfg.get("browser_bg_secondary", "#252525")),
            ("browser_text_normal", "Text:", self.cfg.get("browser_text_normal", "#e0e0e0")),
            ("browser_selection", "Selection:", self.cfg.get("browser_selection", "#8e44ad")),
        ]
        for row, (key, label, default) in enumerate(state_color_defs):
            state_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(70)
            color_input.textChanged.connect(lambda t, k=key: self._on_browser_color_changed(k, t))
            self.browser_color_inputs[key] = color_input
            state_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #888; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self._pick_browser_color(k))
            self.browser_color_btns[key] = color_btn
            state_layout.addWidget(color_btn, row, 2)
        state_colors.setLayout(state_layout)
        custom_layout.addWidget(state_colors)

        # Suspended/Buried/Marked colors
        special_colors = QGroupBox("Suspended / Buried / Marked")
        special_layout = QGridLayout()
        special_color_defs = [
            ("browser_bg_suspended", "Suspended BG:", self.cfg.get("browser_bg_suspended", "#3a2f1a")),
            ("browser_text_suspended", "Suspended Text:", self.cfg.get("browser_text_suspended", "#d4af37")),
            ("browser_bg_buried", "Buried BG:", self.cfg.get("browser_bg_buried", "#1a2a3a")),
            ("browser_text_buried", "Buried Text:", self.cfg.get("browser_text_buried", "#6c91b0")),
            ("browser_bg_marked", "Marked BG:", self.cfg.get("browser_bg_marked", "#3a1a3a")),
            ("browser_text_marked", "Marked Text:", self.cfg.get("browser_text_marked", "#c792ea")),
        ]
        for row, (key, label, default) in enumerate(special_color_defs):
            special_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(70)
            color_input.textChanged.connect(lambda t, k=key: self._on_browser_color_changed(k, t))
            self.browser_color_inputs[key] = color_input
            special_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #888; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self._pick_browser_color(k))
            self.browser_color_btns[key] = color_btn
            special_layout.addWidget(color_btn, row, 2)
        special_colors.setLayout(special_layout)
        custom_layout.addWidget(special_colors)

        # Flag colors
        flag_colors = QGroupBox("Flag Colors")
        flag_layout = QGridLayout()
        flag_color_defs = [
            ("browser_flag_1", "Flag 1 (Red):", self.cfg.get("browser_flag_1", "#e25555")),
            ("browser_flag_2", "Flag 2 (Orange):", self.cfg.get("browser_flag_2", "#ff9632")),
            ("browser_flag_3", "Flag 3 (Green):", self.cfg.get("browser_flag_3", "#32cd32")),
            ("browser_flag_4", "Flag 4 (Blue):", self.cfg.get("browser_flag_4", "#56b4e9")),
            ("browser_flag_5", "Flag 5 (Pink):", self.cfg.get("browser_flag_5", "#ff82ab")),
            ("browser_flag_6", "Flag 6 (Teal):", self.cfg.get("browser_flag_6", "#009688")),
            ("browser_flag_7", "Flag 7 (Purple):", self.cfg.get("browser_flag_7", "#7c4dff")),
        ]
        for row, (key, label, default) in enumerate(flag_color_defs):
            flag_layout.addWidget(QLabel(label), row, 0)
            color_input = QLineEdit()
            color_input.setText(self.cfg.get(key, default))
            color_input.setFixedWidth(70)
            color_input.textChanged.connect(lambda t, k=key: self._on_browser_color_changed(k, t))
            self.browser_color_inputs[key] = color_input
            flag_layout.addWidget(color_input, row, 1)
            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setStyleSheet(f"background-color: {self.cfg.get(key, default)}; border: 1px solid #888; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key: self._pick_browser_color(k))
            self.browser_color_btns[key] = color_btn
            flag_layout.addWidget(color_btn, row, 2)
        flag_colors.setLayout(flag_layout)
        custom_layout.addWidget(flag_colors)

        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)

        # Enable/disable based on checkboxes
        self.chk_browser_theme.toggled.connect(theme_group.setEnabled)
        self.chk_browser_theme.toggled.connect(self.chk_custom_colors.setEnabled)
        self.chk_browser_theme.toggled.connect(lambda checked: custom_group.setEnabled(checked and self.chk_custom_colors.isChecked()))
        self.chk_custom_colors.toggled.connect(custom_group.setEnabled)
        self.chk_custom_colors.toggled.connect(self._update_theme_preview)

        theme_group.setEnabled(self.chk_browser_theme.isChecked())
        self.chk_custom_colors.setEnabled(self.chk_browser_theme.isChecked())
        custom_group.setEnabled(self.chk_browser_theme.isChecked() and self.chk_custom_colors.isChecked())

        self._update_theme_preview()

        layout.addStretch()
        widget.setLayout(layout)
        scroll.setWidget(widget)
        return scroll

    def _load_theme_to_custom(self):
        """Load selected preset theme colors into custom color inputs.

        The combo holds a family key; load the variant matching Anki's mode so
        the custom fields start from what the user actually sees.
        """
        family_key = self.browser_theme_combo.currentData()
        theme_key = _theme_variant_key(family_key, _is_dark_mode())
        if theme_key and theme_key in BROWSER_THEMES:
            theme = BROWSER_THEMES[theme_key]
            mappings = {
                "browser_bg_primary": "bg_primary",
                "browser_bg_secondary": "bg_secondary",
                "browser_bg_suspended": "bg_suspended",
                "browser_bg_buried": "bg_buried",
                "browser_bg_marked": "bg_marked",
                "browser_text_normal": "text_normal",
                "browser_text_suspended": "text_suspended",
                "browser_text_buried": "text_buried",
                "browser_text_marked": "text_marked",
                "browser_selection": "selection",
                "browser_flag_1": "flag_1",
                "browser_flag_2": "flag_2",
                "browser_flag_3": "flag_3",
                "browser_flag_4": "flag_4",
                "browser_flag_5": "flag_5",
                "browser_flag_6": "flag_6",
                "browser_flag_7": "flag_7",
            }
            for cfg_key, theme_key_name in mappings.items():
                if cfg_key in self.browser_color_inputs:
                    color = theme.get(theme_key_name, "#888888")
                    self.browser_color_inputs[cfg_key].setText(color)
                    if cfg_key in self.browser_color_btns:
                        self.browser_color_btns[cfg_key].setStyleSheet(f"background-color: {color}; border: 1px solid #888; border-radius: 4px;")

    def _on_browser_color_changed(self, key, text):
        if QColor.isValidColor(text) and key in self.browser_color_btns:
            self.browser_color_btns[key].setStyleSheet(f"background-color: {text}; border: 1px solid #888; border-radius: 4px;")
            self._update_theme_preview()

    def _pick_browser_color(self, key):
        current = self.browser_color_inputs[key].text()
        c = QColorDialog.getColor(QColor(current), self)
        if c.isValid():
            self.browser_color_inputs[key].setText(c.name())
            self.browser_color_btns[key].setStyleSheet(f"background-color: {c.name()}; border: 1px solid #888; border-radius: 4px;")

    def _update_theme_preview(self):
        # Check if using custom colors
        use_custom = hasattr(self, 'chk_custom_colors') and self.chk_custom_colors.isChecked()

        if use_custom and hasattr(self, 'browser_color_inputs'):
            # Use custom colors from inputs
            colors = {
                'bg_primary': self.browser_color_inputs.get('browser_bg_primary', QLineEdit()).text() or "#1e1e1e",
                'bg_secondary': self.browser_color_inputs.get('browser_bg_secondary', QLineEdit()).text() or "#252525",
                'bg_suspended': self.browser_color_inputs.get('browser_bg_suspended', QLineEdit()).text() or "#3a2f1a",
                'bg_buried': self.browser_color_inputs.get('browser_bg_buried', QLineEdit()).text() or "#1a2a3a",
                'bg_marked': self.browser_color_inputs.get('browser_bg_marked', QLineEdit()).text() or "#3a1a3a",
                'text_normal': self.browser_color_inputs.get('browser_text_normal', QLineEdit()).text() or "#e0e0e0",
                'text_suspended': self.browser_color_inputs.get('browser_text_suspended', QLineEdit()).text() or "#d4af37",
                'text_buried': self.browser_color_inputs.get('browser_text_buried', QLineEdit()).text() or "#6c91b0",
                'text_marked': self.browser_color_inputs.get('browser_text_marked', QLineEdit()).text() or "#c792ea",
                'selection': self.browser_color_inputs.get('browser_selection', QLineEdit()).text() or "#8e44ad",
                'flag_1': self.browser_color_inputs.get('browser_flag_1', QLineEdit()).text() or "#e25555",
                'flag_2': self.browser_color_inputs.get('browser_flag_2', QLineEdit()).text() or "#ff9632",
                'flag_3': self.browser_color_inputs.get('browser_flag_3', QLineEdit()).text() or "#32cd32",
                'flag_4': self.browser_color_inputs.get('browser_flag_4', QLineEdit()).text() or "#56b4e9",
                'flag_5': self.browser_color_inputs.get('browser_flag_5', QLineEdit()).text() or "#ff82ab",
                'flag_6': self.browser_color_inputs.get('browser_flag_6', QLineEdit()).text() or "#009688",
                'flag_7': self.browser_color_inputs.get('browser_flag_7', QLineEdit()).text() or "#7c4dff",
            }
        else:
            # Use preset theme colors — resolve the family to the variant that
            # matches Anki's current mode, so the preview shows what will apply.
            family_key = self.browser_theme_combo.currentData()
            theme_key = _theme_variant_key(family_key, _is_dark_mode())
            colors = BROWSER_THEMES.get(theme_key, BROWSER_THEMES["default"])

        if hasattr(self, "browser_preview"):
            self.browser_preview.apply(colors, self.browser_spacing_combo.currentData(),
                                       self.chk_state_icons.isChecked(), self.browser_tags_combo.currentData())

    def _set_all_deck_checks(self, checked):
        """Set all deck checkboxes to checked or unchecked."""
        for chk in self.deck_checkboxes.values():
            chk.setChecked(checked)

    def _set_all_retention_deck_checks(self, checked):
        """Set all retention-scope deck checkboxes to checked or unchecked."""
        for chk in self.retention_deck_checkboxes.values():
            chk.setChecked(checked)

    def save(self):
        try:
            self._do_save()
        except Exception as e:
            traceback.print_exc()
            showInfo(f"Elemental could not save settings:\n\n{e}\n\n"
                     "Your other settings were not changed. Please report this on AnkiWeb.")

    def _do_save(self):
        ag = []
        if self.chk_rev.isChecked(): ag.append("reviews")
        if self.chk_time.isChecked(): ag.append("time_card")
        if self.chk_time_studied.isChecked(): ag.append("time_studied")
        if self.chk_ret.isChecked(): ag.append("retention")
        if self.chk_fut.isChecked(): ag.append("forecast")

        self.cfg['active_graphs_v14'] = ag
        self.cfg['reviews_rolling_avg']        = self.chk_rev_rolling.isChecked()
        self.cfg['reviews_rolling_avg_period'] = self.rev_rolling_period.value()
        self.cfg['time_rolling_avg']           = self.chk_time_rolling.isChecked()
        self.cfg['time_rolling_avg_period']    = self.time_rolling_period.value()
        self.cfg['time_studied_rolling_avg']        = self.chk_time_studied_rolling.isChecked()
        self.cfg['time_studied_rolling_avg_period'] = self.time_studied_rolling_period.value()
        self.cfg['ret_rolling_avg']            = self.chk_ret_rolling.isChecked()
        self.cfg['ret_rolling_avg_period']     = self.ret_rolling_period.value()
        self.cfg['forecast_rolling_avg']       = self.chk_fut_rolling.isChecked()
        self.cfg['forecast_rolling_avg_period']= self.fut_rolling_period.value()
        self.cfg['show_exam_markers'] = self.chk_exam_markers.isChecked()
        self.cfg['exam_countdown'] = self.chk_exam_countdown.isChecked()
        self.cfg['exam_countdown_days'] = self.exam_countdown_days.value()
        self.cfg['show_graph'] = self.chk_show_graph.isChecked()
        self.cfg['monochrome_text'] = self.chk_monochrome.isChecked()
        self.cfg['enable_shadows'] = self.chk_shadows.isChecked()
        self.cfg['enable_glass'] = self.chk_glass.isChecked()
        self.cfg['cell_shape'] = self.cell_shape_combo.currentData()
        self.cfg['heatmap_width'] = self.heatmap_width_slider.value()
        self.cfg['animations'] = self.animations_combo.currentData()
        # never set and left as it was: stays automatic (on only without the graphics chip)
        lp = self.chk_low_power.isChecked()
        self.cfg['low_power'] = None if self._low_power_auto is not None and lp == self._low_power_auto else lp
        self.cfg['enable_browser_theme'] = self.chk_browser_theme.isChecked()
        self.cfg['enable_editor_theme'] = self.chk_editor_theme.isChecked()
        self.cfg['browser_color_theme'] = self.browser_theme_combo.currentData()
        self.cfg['browser_row_spacing'] = self.browser_spacing_combo.currentData()
        self.cfg['browser_state_icons'] = self.chk_state_icons.isChecked()
        self.cfg['browser_tag_display'] = self.browser_tags_combo.currentData()
        self.cfg['browser_custom_colors'] = self.chk_custom_colors.isChecked()

        # Save custom browser colors
        for key, inp in self.browser_color_inputs.items():
            color = inp.text().strip()
            if QColor.isValidColor(color):
                self.cfg[key] = color

        self.cfg['modern_deck_theme'] = self.chk_modern.isChecked()
        self.cfg['enable_deck_glass'] = self.chk_deck_glass.isChecked()
        self.cfg['show_deck_ratio'] = self.chk_ratio.isChecked()
        self.cfg['deck_count_pills'] = self.chk_count_pills.isChecked()
        self.cfg['home_always_dark'] = self.chk_home_dark.isChecked()
        self.cfg['deck_list_width'] = self.deck_width_slider.value()
        self.cfg['replace_stats'] = self.chk_replace.isChecked()

        self.cfg['display_mode'] = self.mode_combo.currentData()
        self.cfg['avg_period'] = self.avg_combo.currentData()
        self.cfg['glass_opacity'] = self.opacity_slider.value() / 100.0

        # Intensity settings - convert slider back to exponent
        # Slider: 30-100, where higher = more visible low activity
        # Exponent: 1.0-0.3, where lower = more visible low activity
        intensity_val = self.intensity_slider.value()
        self.cfg['cell_intensity_curve'] = round(1.1 - (intensity_val / 100.0), 2)
        self.cfg['cell_min_opacity'] = self.min_opacity_slider.value() / 100.0
        self.cfg['color_gradient_mode'] = self.gradient_mode_combo.currentData()
        self.cfg['shade_dark_factor'] = self.shade_slider.value() / 100.0
        self.cfg['glow_contrast'] = self.glow_slider.value() / 100.0
        self.cfg['color_scale_max'] = self.color_scale_max_spin.value()

        self.cfg['weeks_ahead'] = self.weeks_ahead_spin.value()
        self.cfg['separate_months'] = self.chk_sep_months.isChecked()
        self.cfg['forecast_shading'] = self.chk_forecast_shading.isChecked()

        self.cfg['retention_min'] = self.ret_min_input.value()
        self.cfg['retention_max'] = self.ret_max_input.value()
        self.cfg['exclude_new_cards_from_retention'] = self.chk_exclude_new_retention.isChecked()
        self.cfg['speed_min'] = self.speed_min_input.value()
        self.cfg['speed_max'] = self.speed_max_input.value()
        self.cfg['exclude_idle_cards'] = self.chk_exclude_idle.isChecked()
        self.cfg['idle_threshold_secs'] = self.idle_threshold_spin.value()

        for key, inp in self.color_inputs.items():
            color = inp.text().strip()
            if QColor.isValidColor(color):
                self.cfg[key] = color
        self.cfg['heatmap_theme'] = self._theme_key    # write_config keeps My colors while a theme is chosen

        # Save custom heatmap mode settings
        self.cfg['show_mode_time']           = self.chk_show_time_mode.isChecked()
        self.cfg['show_mode_newcards']       = self.chk_show_nc_mode.isChecked()
        self.cfg['show_mode_focus']          = self.chk_show_focus_mode.isChecked()
        self.cfg['color_scale_max_time']     = self.time_scale_spin.value()
        self.cfg['color_scale_max_newcards'] = self.nc_scale_spin.value()

        # Save deck filter settings
        self.cfg['show_overview_heatmap'] = self.chk_show_overview.isChecked()
        self.cfg['overview_filter_current_deck'] = self.chk_overview_filter.isChecked()
        self.cfg['heatmap_deck_filter_enabled'] = self.chk_deck_filter.isChecked()

        # Save selected decks for filtering
        selected_decks = []
        for d_id, chk in self.deck_checkboxes.items():
            if chk.isChecked():
                selected_decks.append(d_id)
        self.cfg['heatmap_filtered_decks'] = selected_decks

        # Save retention deck scope
        self.cfg['retention_deck_scope_enabled'] = self.chk_retention_scope.isChecked()
        scoped_decks = []
        for d_id, chk in self.retention_deck_checkboxes.items():
            if chk.isChecked():
                scoped_decks.append(d_id)
        self.cfg['retention_scope_decks'] = scoped_decks

        # Save FSRS simulation settings
        self.cfg['fsrs_simulation_enabled'] = self.chk_fsrs_enabled.isChecked()
        self.cfg['fsrs_simulation_days'] = self.fsrs_days_spin.value()
        self.cfg['fsrs_simulation_retention'] = self.fsrs_ret_slider.value() / 100.0
        self.cfg['fsrs_simulation_max_reviews'] = self.fsrs_max_rev_spin.value()
        self.cfg['fsrs_simulation_max_interval'] = self.fsrs_max_ivl_spin.value()
        self.cfg['fsrs_learning_steps'] = self.fsrs_learn_spin.value()
        self.cfg['fsrs_relearning_steps'] = self.fsrs_relearn_spin.value()
        self.cfg['fsrs_simulate_overhead'] = self.chk_fsrs_overhead.isChecked()
        self.cfg['fsrs_use_custom_weights'] = self.chk_custom_weights.isChecked()
        self.cfg['fsrs_custom_weights'] = self.fsrs_weights_input.text().strip()
        self.cfg['fsrs_advanced_expanded'] = self.adv_group.isChecked()
        try:
            self.cfg['fsrs_forecast_deck'] = int(self.fsrs_deck_combo.currentData() or 0)
        except (TypeError, ValueError):
            self.cfg['fsrs_forecast_deck'] = 0
        self.cfg['fsrs_simulation_new_cards'] = self.fsrs_new_cards_spin.value()
        self.cfg['fsrs_new_card_days'] = [i for i, b in enumerate(self.fsrs_day_buttons) if b.isChecked()]
        self.cfg['fsrs_band_enabled'] = self.chk_fsrs_band.isChecked()
        self.cfg['fsrs_band_sd'] = int(self.fsrs_band_combo.currentData() or 1)


        # Time left
        self.cfg['time_estimate_enabled'] = self.chk_time_enabled.isChecked()
        self.cfg['time_deck_column'] = self.chk_time_column.isChecked()
        self.cfg['time_today_pill'] = self.chk_time_pill.isChecked()
        self.cfg['notice_backlog'] = self.chk_notice_backlog.isChecked()
        self.cfg['notice_tomorrow'] = self.chk_notice_tomorrow.isChecked()
        self.cfg['notice_streak'] = self.chk_notice_streak.isChecked()
        for key, c in self.notice_more.items():
            self.cfg[key] = c.isChecked()
        self.cfg['time_overview'] = self.chk_time_overview.isChecked()
        self.cfg['time_desk_time'] = self.chk_time_desk.isChecked()
        if (bool(self.cfg.get('focus_away_is_lookup', False)) != self.chk_away_lookup.isChecked()
                or bool(self.cfg.get('focus_reading_counts', False)) != self.chk_reading_counts.isChecked()):
            time_left.refit()       # past days' focus scores use these too
        self.cfg['focus_away_is_lookup'] = self.chk_away_lookup.isChecked()
        self.cfg['focus_reading_counts'] = self.chk_reading_counts.isChecked()
        self.cfg['focus_lookup_key'] = self.focus_lookup_key.keySequence().toString()
        self.cfg['time_show_as'] = self.time_show_as.currentData()
        self.cfg['day_topic_tag'] = self.day_topic_tag.currentText().strip().strip(":")
        self.cfg['day_topic_level'] = self.day_topic_level.value()
        self.cfg['stats_topic_level'] = self.stats_topic_level.value()

        # Review pill
        self.cfg['review_pill_enabled'] = self.chk_rp_enabled.isChecked()
        self.cfg['review_pill_show_retention'] = self.chk_rp_retention.isChecked()
        self.cfg['review_pill_retention_style'] = self.rp_style.currentData()
        self.cfg['review_pill_show_time'] = self.chk_rp_time.isChecked()
        self.cfg['review_pill_target'] = self.rp_target.value()
        self.cfg['review_pill_window'] = self.rp_window.currentData()
        self.cfg['review_pill_focus_cue'] = self.chk_rp_focus.isChecked()
        ring = self.rp_ring.currentData()
        self.cfg['review_pill_focus_ring'] = ring != "off"
        if ring != "off":
            self.cfg['review_pill_ring_style'] = ring
        self.cfg['review_pill_position'] = self.rp_corner.currentData()
        self.cfg['review_pill_draggable'] = self.chk_rp_drag.isChecked()
        self.cfg['review_pill_span'] = self.rp_span.value()
        self.cfg['review_pill_smoothing'] = self.rp_smooth.value()
        self.cfg['pomo_enabled'] = self.chk_rp_pomo.isChecked()
        self.cfg['pomo_focus_min'] = self.rp_pomo_focus.value()
        self.cfg['pomo_break_min'] = self.rp_pomo_break.value()
        self.cfg['pomo_long_min'] = self.rp_pomo_long.value()
        self.cfg['pomo_long_every'] = self.rp_pomo_every.value()
        self.cfg['pomo_pause_away'] = self.chk_rp_pomo_pause.isChecked()
        self.cfg['pomo_drift_break'] = self.chk_rp_pomo_drift.isChecked()
        self.cfg['pomo_notify'] = self.chk_rp_pomo_notify.isChecked()

        # Background photo
        self.cfg['background_enabled'] = self.chk_bg_enabled.isChecked()
        self.cfg['background_source'] = self.bg_source.currentData()
        self.cfg['background_rotation'] = self.bg_rotation.currentData()
        if self.bg_image.currentData():
            self.cfg['background_image'] = self.bg_image.currentData()
        self.cfg['background_opacity_main'] = self.bg_main.value() / 100.0
        self.cfg['background_opacity_review'] = self.bg_review.value() / 100.0
        self.cfg['background_in_review'] = self.chk_bg_review.isChecked()
        self.cfg['background_on_bars'] = self.chk_bg_bars.isChecked()
        if self.cfg['background_enabled'] and self.cfg['background_source'] == "mine" and not background.photos():
            other = background.other_addon()
            if other and other["photos"] and askUser(
                    f"Your background folder is empty. Copy the {len(other['photos'])} photos "
                    f"from {other['name']}?", parent=self):
                background.copy_from_other()

        # Stats bar settings
        self.cfg['show_stats_bar'] = self.chk_show_stats_bar.isChecked()
        self.cfg['streak_display'] = self.streak_combo.currentData()

        write_config(self.cfg)
        self.accept()
        mw.reset()
        background._redraw_toolbar()    # mw.reset() leaves the top bar as it was

class HeatmapNoteDialog(QDialog):
    """Exams and a note for one day, styled like the settings window."""

    def __init__(self, date_str, current_note="", exam_data=None, parent=None):
        super().__init__(parent)
        self.setObjectName("hmSettings")
        self.date_str = date_str
        self.note_text = current_note
        try:
            d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            self.nice_date = f"{d.strftime('%A, %B')} {d.day}" + ("" if d.year == date.today().year else f", {d.year}")
        except ValueError:
            self.nice_date = date_str
        self.setWindowTitle(self.nice_date)
        self.setMinimumWidth(420)

        # Convert old single-exam format to list format
        if exam_data is None:
            self.exams = []
        elif isinstance(exam_data, list):
            self.exams = exam_data.copy()
        else:
            # Old format: single dict
            self.exams = [exam_data]

        self.exam_widgets = []
        self.night = _is_dark_mode()
        self.pal = _settings_palette(self.night)
        self.setStyleSheet(_settings_css(self.night) + """
QLabel#hmSection {{ font-weight: 600; color: {text}; padding-top: 12px; }}
QDialog#hmSettings QLineEdit#hmField {{ padding: 4px 9px; min-height: 22px; border-radius: 7px;
    border: 1px solid {border}; background: {win}; color: {text}; }}
QDialog#hmSettings QPlainTextEdit#hmNote {{ background: {card}; border: 1px solid {border}; border-radius: 10px;
    padding: 6px 8px; color: {text}; }}
QDialog#hmSettings QLineEdit#hmField:focus, QDialog#hmSettings QPlainTextEdit#hmNote:focus {{ border-color: {accent}; }}
QToolButton#hmAdd {{ border: none; color: {accent}; font-weight: 600; padding: 2px 0px; }}
QToolButton#hmRemove {{ border: none; color: {sub}; padding: 2px 2px; }}
QToolButton#hmRemove:hover {{ color: {text}; }}
""".format(**self.pal))
        self.setup_ui()

    def setup_ui(self):
        body = QWidget()
        body.setObjectName("hmPageBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(6)
        title = QLabel(self.nice_date)
        title.setObjectName("hmPageTitle")
        v.addWidget(title)
        sub = QLabel("Mark an exam or write a note for this day.")
        sub.setObjectName("hmPageSub")
        v.addWidget(sub)

        def section(text):
            lbl = QLabel(text)
            lbl.setObjectName("hmSection")
            return lbl

        # Exams: a card with one row per exam and the add button under them
        v.addWidget(section("Exams and deadlines"))
        card = QFrame()
        card.setObjectName("hmCard")
        eg = QVBoxLayout(card)
        eg.setContentsMargins(12, 10, 12, 10)
        eg.setSpacing(8)
        self.exams_container = QWidget()
        self.exams_layout = QVBoxLayout(self.exams_container)
        self.exams_layout.setContentsMargins(0, 0, 0, 0)
        self.exams_layout.setSpacing(8)
        eg.addWidget(self.exams_container)
        add_btn = QToolButton()
        add_btn.setObjectName("hmAdd")
        add_btn.setText("+ Add exam")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(lambda: self.add_exam_row("", "#e74c3c", focus=True))
        eg.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(card)
        for exam in self.exams:
            self.add_exam_row(exam.get("label", "Exam"), exam.get("color", "#e74c3c"))
        self.exams_container.setVisible(bool(self.exam_widgets))

        # Note: the text box is the card
        v.addWidget(section("Note"))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("hmNote")
        self.text_edit.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)   # the border shows focus
        self.text_edit.setPlaceholderText("What happened this day?")
        self.text_edit.setPlainText(self.note_text)
        self.text_edit.setFixedHeight(96)
        v.addWidget(self.text_edit)
        v.addStretch()

        footer = QWidget()
        footer.setObjectName("hmFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        fl.addWidget(btns)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(body, 1)
        layout.addWidget(footer)

    def _swatch_css(self, color):
        return (f"QPushButton {{ background-color: {color}; border: 2px solid {self.pal['card']}; border-radius: 11px; }}"
                f"QPushButton:hover {{ border-color: {self.pal['border']}; }}")

    def add_exam_row(self, label="", color="#e74c3c", focus=False):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        color_btn = QPushButton()
        color_btn.setFixedSize(22, 22)
        color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        color_btn.setToolTip("Color")
        color_btn.setStyleSheet(self._swatch_css(color))
        row_layout.addWidget(color_btn)

        lbl_input = QLineEdit()
        lbl_input.setObjectName("hmField")
        lbl_input.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        lbl_input.setPlaceholderText("Exam name")
        lbl_input.setText(label)
        row_layout.addWidget(lbl_input, 1)

        del_btn = QToolButton()
        del_btn.setObjectName("hmRemove")
        del_btn.setText("Remove")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row_layout.addWidget(del_btn)

        widget_data = {"row": row, "label": lbl_input, "color": color, "color_btn": color_btn}

        def pick_color(checked=False, wd=widget_data):
            c = QColorDialog.getColor(QColor(wd["color"]), self)
            if c.isValid():
                wd["color"] = c.name()
                wd["color_btn"].setStyleSheet(self._swatch_css(c.name()))
        color_btn.clicked.connect(pick_color)

        self.exam_widgets.append(widget_data)
        self.exams_layout.addWidget(row)
        self.exams_container.setVisible(True)
        if focus:
            lbl_input.setFocus()

        def remove_row(checked=False, wd=widget_data):
            self.exam_widgets.remove(wd)
            wd["row"].deleteLater()
            self.exams_container.setVisible(bool(self.exam_widgets))
        del_btn.clicked.connect(remove_row)

    def get_text(self):
        return self.text_edit.toPlainText().strip()

    def get_exam_result(self):
        result = []
        for wd in self.exam_widgets:
            label = wd["label"].text().strip()
            color = wd["color"]
            if label:  # Only include if label is not empty
                if not QColor.isValidColor(color):
                    color = "#e74c3c"
                result.append({"label": label, "color": color})
        return result if result else None

class BacktestDialog(QDialog):
    """
    Validates the FSRS new-card predictor against your actual historical review data.

    Columns:
      New Cards  – cards you introduced that day (first-ever review in revlog)
      Predicted  – reviews FSRS expects from those cards on this day
      + Baseline – predicted + estimated daily existing-card workload
      Actual     – all reviews you actually did (new + existing cards)
      Diff       – Actual minus (Predicted + Baseline)

    "Calibrate from History" fits the two unknowns (stability scale, baseline)
    to minimise Diff.  "Save Calibration" applies them to future forecasts.
    """

    WINDOWS = [("30 days", 30), ("60 days", 60), ("90 days", 90), ("180 days", 180)]
    COLS    = ["Date", "New Cards", "Predicted", "+ Baseline", "Actual", "Diff"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FSRS Forecast Validation")
        self.setMinimumSize(820, 560)
        self._calib = None   # holds last calibration result
        self._data  = None   # holds last backtest data

        # Theme colours
        try:
            from aqt.theme import theme_manager
            night = theme_manager.get_night_mode()
        except Exception:
            night = False

        if night:
            self._bg        = "#1e1e2e"
            self._alt_bg    = "#262636"
            self._text      = "#cdd6f4"
            self._header_bg = "#313244"
            self._border    = "#45475a"
            self._hi_bg     = "#1e3a5f"   # new-card row highlight (dark blue)
            self._hi_text   = "#89b4fa"
            self._good      = "#a6e3a1"
            self._bad       = "#f38ba8"
        else:
            self._bg        = "#ffffff"
            self._alt_bg    = "#f4f4f8"
            self._text      = "#1a1a2e"
            self._header_bg = "#e0e0f0"
            self._border    = "#c0c0d0"
            self._hi_bg     = "#dbeeff"   # new-card row highlight (light blue)
            self._hi_text   = "#1a5fa0"
            self._good      = "#2d7a4f"
            self._bad       = "#b00020"

        self._apply_theme()
        self._build_ui()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QDialog, QWidget {{
                background: {self._bg};
                color: {self._text};
                font-size: 12px;
            }}
            QLabel {{ color: {self._text}; }}
            QPushButton {{
                background: {self._header_bg};
                color: {self._text};
                border: 1px solid {self._border};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{ background: {self._border}; }}
            QComboBox {{
                background: {self._alt_bg};
                color: {self._text};
                border: 1px solid {self._border};
                border-radius: 4px;
                padding: 2px 6px;
            }}
            QTableWidget {{
                background: {self._bg};
                color: {self._text};
                gridline-color: {self._border};
                border: 1px solid {self._border};
                alternate-background-color: {self._alt_bg};
            }}
            QHeaderView::section {{
                background: {self._header_bg};
                color: {self._text};
                border: 1px solid {self._border};
                padding: 4px;
                font-weight: bold;
            }}
            QTableWidget::item:selected {{
                background: {self._hi_bg};
                color: {self._hi_text};
            }}
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Controls row ──────────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Window:"))
        self._window_combo = QComboBox()
        for label, days in self.WINDOWS:
            self._window_combo.addItem(label, days)
        self._window_combo.setCurrentIndex(2)
        ctrl.addWidget(self._window_combo)
        ctrl.addSpacing(12)

        self._run_btn = QPushButton("Run Validation")
        self._run_btn.clicked.connect(self._run)
        ctrl.addWidget(self._run_btn)

        self._calib_btn = QPushButton("Calibrate from History")
        self._calib_btn.setToolTip(
            "Fit baseline + stability-scale to your actual review data, "
            "then fill the '+ Baseline' column.")
        self._calib_btn.clicked.connect(self._calibrate)
        self._calib_btn.setEnabled(False)
        ctrl.addWidget(self._calib_btn)

        self._save_btn = QPushButton("Save Calibration")
        self._save_btn.setToolTip(
            "Write the calibrated values to config so future forecasts use them.")
        self._save_btn.clicked.connect(self._save_calibration)
        self._save_btn.setEnabled(False)
        ctrl.addWidget(self._save_btn)

        ctrl.addStretch()
        root.addLayout(ctrl)

        # ── Stats / calibration bar ───────────────────────────────────────────
        self._stats_lbl = QLabel("Run validation to see results.")
        self._stats_lbl.setWordWrap(True)
        self._stats_lbl.setStyleSheet(
            f"color:{self._text}; padding:6px; border:1px solid {self._border};"
            f"border-radius:4px; background:{self._alt_bg};")
        root.addWidget(self._stats_lbl)

        # ── Legend ────────────────────────────────────────────────────────────
        legend = QLabel(
            f"<span style='background:{self._hi_bg};color:{self._hi_text};"
            f"padding:1px 6px;border-radius:3px;'>■ New cards introduced</span>"
            f"&nbsp;&nbsp;"
            f"<i style='color:{self._text};font-size:11px;'>"
            f"Predicted = new-card reviews only.&nbsp; "
            f"+ Baseline adds estimated existing-deck workload after calibration.&nbsp; "
            f"Actual = all reviews (new + existing).</i>"
        )
        legend.setWordWrap(True)
        root.addWidget(legend)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(self.COLS))
        self._table.setHorizontalHeaderLabels(self.COLS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        for col, w in enumerate([90, 80, 78, 82, 72, 60]):
            self._table.setColumnWidth(col, w)
        root.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run(self):
        self._run_btn.setEnabled(False)
        self._stats_lbl.setText("Running…")
        QApplication.processEvents()
        try:
            days_back = self._window_combo.currentData()
            eng = FastEngine()
            self._data = eng.get_backtest_data(days_back=days_back)
            self._calib = None
            self._populate()
            self._calib_btn.setEnabled(True)
        except Exception as exc:
            import traceback
            self._stats_lbl.setText(
                f"<span style='color:{self._bad};'>Error: {exc}</span>")
            traceback.print_exc()
        finally:
            self._run_btn.setEnabled(True)

    # ── Calibrate ─────────────────────────────────────────────────────────────

    def _calibrate(self):
        if self._data is None:
            return
        self._calib_btn.setEnabled(False)
        self._stats_lbl.setText("Calibrating…")
        QApplication.processEvents()
        try:
            days_back = self._window_combo.currentData()
            eng = FastEngine()
            self._calib = eng._compute_calibration(days_back=days_back)
            self._populate()
            self._save_btn.setEnabled(True)
        except Exception as exc:
            import traceback
            self._stats_lbl.setText(
                f"<span style='color:{self._bad};'>Calibration error: {exc}</span>")
            traceback.print_exc()
        finally:
            self._calib_btn.setEnabled(True)

    def _save_calibration(self):
        if self._calib is None:
            return
        cfg = get_config()
        cfg['backtest_stability_scale']    = self._calib['stability_scale']
        cfg['backtest_existing_baseline']  = self._calib['baseline_per_day']
        write_config(cfg)
        self._stats_lbl.setText(
            self._stats_lbl.text() +
            f"<br><b style='color:{self._good};'>Calibration saved.</b> "
            f"Future forecasts will use scale = {self._calib['stability_scale']:.3f}, "
            f"baseline = {self._calib['baseline_per_day']:.1f} reviews/day.")
        self._save_btn.setEnabled(False)

    # ── Populate table ────────────────────────────────────────────────────────

    def _populate(self):
        data      = self._data
        dates     = data['dates']
        new_cards = data['new_cards']
        predicted = data['predicted']
        actual    = data['actual']

        baseline  = self._calib['baseline_per_day'] if self._calib else 0.0
        scale     = self._calib['stability_scale']  if self._calib else 1.0

        rows = [(d, new_cards.get(d, 0), predicted.get(d, 0), actual.get(d, 0))
                for d in dates
                if new_cards.get(d, 0) or predicted.get(d, 0) or actual.get(d, 0)]

        self._table.setRowCount(len(rows))
        for r, (d, nc, raw_pred, act) in enumerate(rows):
            pred     = int(round(raw_pred * scale))
            adj_pred = int(round(pred + baseline))
            diff     = act - adj_pred
            is_new   = nc > 0
            diff_str = (f"+{diff}" if diff >= 0 else str(diff))

            vals = [d.strftime("%Y-%m-%d"), str(nc), str(pred),
                    str(adj_pred) if self._calib else "—",
                    str(act), diff_str if self._calib else "—"]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Row tint for days with new cards
                if is_new:
                    item.setForeground(QColor(self._hi_text))
                    item.setBackground(QColor(self._hi_bg))
                # Colour the Diff cell
                if c == 5 and self._calib and v not in ("—", ""):
                    try:
                        dv = int(v.lstrip("+"))
                        frac = abs(dv) / max(1, act)
                        item.setForeground(
                            QColor(self._bad if frac > 0.25 else self._good))
                    except ValueError:
                        pass
                self._table.setItem(r, c, item)

        # ── Stats bar ─────────────────────────────────────────────────────────
        total_new  = sum(new_cards.values())
        total_pred = sum(int(round(predicted.get(d, 0) * scale)) for d in dates)
        total_act  = sum(actual.values())

        # MAE and correlation using adjusted predictions on days where pred > 0
        pred_days = [(int(round(predicted[d] * scale + baseline)), actual.get(d, 0))
                     for d in predicted if predicted[d] > 0]

        if pred_days:
            mae = sum(abs(p - a) for p, a in pred_days) / len(pred_days)
            ps  = [float(p) for p, _ in pred_days]
            as_ = [float(a) for _, a in pred_days]
            n   = len(ps)
            mp, ma = sum(ps)/n, sum(as_)/n
            num  = sum((p-mp)*(a-ma) for p, a in zip(ps, as_))
            den  = (sum((p-mp)**2 for p in ps) * sum((a-ma)**2 for a in as_))**0.5
            corr = num / den if den > 0 else 0.0

            calib_info = ""
            if self._calib:
                calib_info = (
                    f"&nbsp;|&nbsp; <b>Scale:</b> {scale:.3f} "
                    f"&nbsp;|&nbsp; <b>Baseline:</b> {baseline:.1f} rev/day"
                )
            self._stats_lbl.setText(
                f"<b>New cards:</b> {total_new}"
                f"&nbsp;|&nbsp; <b>Predicted:</b> {total_pred}"
                f"&nbsp;|&nbsp; <b>Actual:</b> {total_act}"
                f"&nbsp;|&nbsp; <b>MAE:</b> {mae:.1f}"
                f"&nbsp;|&nbsp; <b>r:</b> {corr:.3f}"
                f"{calib_info}"
            )
        else:
            self._stats_lbl.setText(
                f"<b>New cards tracked:</b> {total_new} &nbsp;|&nbsp; "
                f"<b>Total actual:</b> {total_act}<br>"
                f"No predicted review days — introduce new cards or extend the window."
            )

def get_deck_and_children_ids(deck_id):
    """Get a deck ID and all its children deck IDs for hierarchical filtering."""
    deck_ids = [deck_id]
    try:
        all_decks = mw.col.decks.all_names_and_ids()
        parent_name = mw.col.decks.name(deck_id)

        for deck in all_decks:
            d_id = deck.id if hasattr(deck, 'id') else deck['id']
            d_name = deck.name if hasattr(deck, 'name') else deck['name']
            # Check if this deck is a child of the parent
            if d_name.startswith(parent_name + "::"):
                deck_ids.append(d_id)
    except:
        pass
    return deck_ids

def _cards_due(col, deck_ids, today_int, now_int):
    """The heatmap's DUE number: reviews due today and learning cards due now."""
    deck_filter = f"AND did IN ({','.join(map(str, deck_ids))})" if deck_ids else ""
    rev = col.db.scalar(f"SELECT count() FROM cards WHERE queue = 2 AND due <= {today_int} {deck_filter}")
    # queue 1's due is a time, queue 3's (steps of a day or more) a day number
    lrn = col.db.scalar(f"SELECT count() FROM cards WHERE ((queue = 1 AND due <= {now_int}) "
                        f"OR (queue = 3 AND due <= {today_int})) {deck_filter}")
    return rev + lrn


def _merge_day_rows(rows):
    """Per-day total rows added up by day (pieces of the history can share a day at their
    edges, e.g. across a clock change). Every field after the day is a count or a sum."""
    out = {}
    for r in rows:
        if r[0] in out:
            out[r[0]] = (r[0],) + tuple((a or 0) + (b or 0) for a, b in zip(out[r[0]][1:], r[1:]))
        else:
            out[r[0]] = tuple(r)
    return [out[d] for d in sorted(out)]


class FastEngine:
    def __init__(self, cache_only=False):
        self.col = mw.col
        self.cfg = get_config()
        self.rollover = self.col.conf.get('rollover', 4)
        # cache_only: never run the slow parts (full revlog history, FSRS
        # simulation). Missing history renders empty and a missing forecast falls
        # back to the simple one (self.missing); an expired forecast is served
        # anyway (self.stale). _heatmap_html then computes them in the background.
        self.cache_only = cache_only
        self.missing = False
        self.stale = False
        self._forecast_key = None
        # {date_str: (low, high)} around the FSRS forecast when the band is on
        self.fsrs_band = {}
        # {date_str: (review, learn, relearn)} reviews by kind, for the day tooltip
        self.kinds = {}
        # Set by the background job: a read-only sqlite connection of its own for
        # the long history statements (see _hist_all).
        self._hist_db = None

    def _hist_all(self, sql):
        """col.db.all() for the full-history aggregation. In the background job it
        runs on its own read-only connection, so its second-long statements don't
        hold Anki's collection lock (which would stall anything the UI asks of the
        collection meanwhile). Falls back to col.db, quietly, if that connection
        fails. (On Windows there's none: Anki's lock shuts it out, see estimator.connect.)"""
        if self._hist_db is not None:
            try:
                return [list(row) for row in self._hist_db.execute(sql)]
            except Exception as e:
                # No traceback: anything printed to stderr pops up Anki's error window.
                print("Elemental: reading history through Anki instead:", e)
                try:
                    self._hist_db.close()
                except Exception:
                    pass
                self._hist_db = None
        return self.col.db.all(sql)
    
    def get_start_date(self):
        """The first day (a Sunday) of the heatmap as it opens: 53 weeks, ending
        weeks_ahead weeks after this one. Older weeks load as you scroll back."""
        today = date.today()
        this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        return this_sunday - timedelta(weeks=52 - _weeks_ahead(self.cfg))

    def _aggregate_revlog(self, deck_ids, rollover_ms, exclude_new, exclude_idle, idle_threshold_ms, id_hi=None, id_lo=None):
        """Per-day revlog aggregates, computed fully in SQL.

        Returns rows of (day_str, revs, time_sum, new_cards, ret_total,
        ret_pass, non_idle_revs, non_idle_time, learn_revs, relearn_revs). Semantics match the original
        per-row Python loop:
          - a card's "first review" is its earliest type<4 row within the same
            deck filter (the old seen_cards logic)
          - retention counts reviews/relearns/filtered plus non-first learning
            reviews; exclude_new additionally drops all reviews of a new card
            on the day it was introduced

        id_hi: when set, only rows with id < id_hi are considered (both the
        aggregated rows and the first-review lookup). This yields the immutable
        "everything before today" slice, which can be cached for the session;
        today's rows are aggregated separately by _aggregate_today().
        """
        day_expr = f"strftime('%Y-%m-%d', (r.id - {rollover_ms}) / 1000, 'unixepoch', 'localtime')"
        idle_cond = f"r.time <= {idle_threshold_ms}" if exclude_idle else "1"
        # Optional upper id bound (historical slice)
        r_hi = f"AND r.id < {int(id_hi)}" if id_hi is not None else ""
        fr2_hi = f"AND fr2.id < {int(id_hi)}" if id_hi is not None else ""
        r2_hi = f"AND r2.id < {int(id_hi)}" if id_hi is not None else ""
        # Optional lower bound: only rows from id_lo on (a stretch to add to saved totals,
        # or one piece of the history done a piece at a time). Whether a row is a card's
        # first answer still looks at all its earlier answers; the first-answer lookup
        # only needs the cards answered in the stretch.
        r_lo = f"AND r.id >= {int(id_lo)}" if id_lo is not None else ""
        fr2_lo = (f"AND fr2.cid IN (SELECT cid FROM revlog WHERE id >= {int(id_lo)}"
                  + (f" AND id < {int(id_hi)}" if id_hi is not None else "") + ")") if id_lo is not None else ""

        if deck_ids:
            did_list = ",".join(str(int(d)) for d in deck_ids)
            deck_join = "JOIN cards c ON r.cid = c.id"
            deck_where = f"AND c.did IN ({did_list})"
            first_join = "JOIN cards fc ON fr2.cid = fc.id"
            first_where = f"AND fc.did IN ({did_list})"
        else:
            deck_join = deck_where = first_join = first_where = ""

        if exclude_new:
            # Retention here also drops every review of a new card on its
            # introduction day, which needs each card's first-review day+type.
            # Compute those ONCE per card in the join subquery (fst) rather than
            # strftime-ing the first-review date on every one of the ~270k revlog
            # rows, and derive the row's own day once in the inner SELECT so the
            # outer aggregate compares plain strings. Semantically identical to
            # the old double-strftime double-join query, ~2x faster.
            first_day_expr = f"strftime('%Y-%m-%d', (f.fid - {rollover_ms}) / 1000, 'unixepoch', 'localtime')"
            first_sub = f"""
                SELECT f.cid AS cid, f.fid AS fid, fr.type AS ftype,
                       {first_day_expr} AS fday
                FROM (
                    SELECT fr2.cid AS cid, MIN(fr2.id) AS fid
                    FROM revlog fr2 {first_join}
                    WHERE fr2.type < 4 {first_where} {fr2_hi} {fr2_lo}
                    GROUP BY fr2.cid
                ) f
                JOIN revlog fr ON fr.id = f.fid
            """
            ret_cond = ("NOT (ftype = 0 AND day = fday) AND (rtype > 0 OR rid != fid)")
            idle_sub = "time <= {}".format(idle_threshold_ms) if exclude_idle else "1"
            return self._hist_all(f"""
                SELECT day, COUNT(*), SUM(time),
                    SUM(CASE WHEN rid = fid AND rtype = 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN {ret_cond} THEN 1 ELSE 0 END),
                    SUM(CASE WHEN {ret_cond} AND ease > 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN {idle_sub} THEN 1 ELSE 0 END),
                    SUM(CASE WHEN {idle_sub} THEN time ELSE 0 END),
                    SUM(CASE WHEN rtype = 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN rtype = 2 THEN 1 ELSE 0 END)
                FROM (
                    SELECT {day_expr} AS day, r.time AS time, r.ease AS ease,
                           r.type AS rtype, r.id AS rid,
                           fst.fid AS fid, fst.ftype AS ftype, fst.fday AS fday
                    FROM revlog r
                    JOIN ({first_sub}) fst ON r.cid = fst.cid
                    {deck_join}
                    WHERE r.type < 4 {deck_where} {r_hi} {r_lo}
                ) sub
                GROUP BY day
            """)

        # Default path: a review is excluded from retention only when it is a
        # card's first-ever review in learning mode. Those rows are exactly the
        # "new card" rows, so retention = totals minus new-card rows — no big
        # join needed, just one scan plus a first-review lookup.
        totals = self._hist_all(f"""
            SELECT
                {day_expr} AS day,
                COUNT(*),
                SUM(r.time),
                SUM(CASE WHEN r.ease > 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN {idle_cond} THEN 1 ELSE 0 END),
                SUM(CASE WHEN {idle_cond} THEN r.time ELSE 0 END),
                SUM(CASE WHEN r.type = 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN r.type = 2 THEN 1 ELSE 0 END)
            FROM revlog r {deck_join}
            WHERE r.type < 4 {deck_where} {r_hi} {r_lo}
            GROUP BY day
        """)
        if deck_ids:
            ne_join = "JOIN cards c2 ON r2.cid = c2.id"
            ne_where = f"AND c2.did IN ({did_list})"
        else:
            ne_join = ne_where = ""
        new_rows = self._hist_all(f"""
            SELECT
                {day_expr} AS day,
                COUNT(*),
                SUM(CASE WHEN r.ease > 1 THEN 1 ELSE 0 END)
            FROM revlog r {deck_join}
            WHERE r.type = 0 {deck_where} {r_hi} {r_lo}
            AND NOT EXISTS (
                SELECT 1 FROM revlog r2 {ne_join}
                WHERE r2.cid = r.cid AND r2.id < r.id AND r2.type < 4 {ne_where}
            )
            GROUP BY day
        """)
        new_by_day = {d: (n, p) for (d, n, p) in new_rows}
        rows = []
        for (d_str, revs, t_sum, pass_cnt, ni_revs, ni_time, n_learn, n_relearn) in totals:
            n_new, new_pass = new_by_day.get(d_str, (0, 0))
            rows.append((d_str, revs, t_sum, n_new,
                         revs - n_new, pass_cnt - new_pass, ni_revs, ni_time, n_learn, n_relearn))
        return rows

    def _aggregate_today(self, deck_ids, rollover_ms, exclude_new, exclude_idle, idle_threshold_ms, id_lo):
        """Aggregate only the rows with id >= id_lo (today), in Python.

        Today's rows are few (tens–hundreds), so a Python pass is trivially cheap
        and lets us reuse the cached immutable history for everything before today.
        Whether a today-card is "new" is decided by looking for any earlier
        (id < id_lo) review — matching _aggregate_revlog's global first-review rule.
        Output rows use the exact same 10-tuple shape as _aggregate_revlog.
        """
        if deck_ids:
            # Each of today's answers' deck, looked up: a join walks every card in the
            # decks instead (~30 ms on AnKing, not ~1).
            did_list = ",".join(str(int(d)) for d in deck_ids)
            deck_where = f"AND (SELECT c.did FROM cards c WHERE c.id = r.cid) IN ({did_list})"
        else:
            deck_where = ""

        day_expr = f"strftime('%Y-%m-%d', (r.id - {rollover_ms}) / 1000, 'unixepoch', 'localtime')"
        today_rows = self.col.db.all(f"""
            SELECT r.id, r.cid, r.ease, r.time, r.type, {day_expr} AS day
            FROM revlog r
            WHERE r.type < 4 AND r.id >= {int(id_lo)} {deck_where}
            ORDER BY r.id
        """)
        if not today_rows:
            return []

        # Which of today's cards already had a review before today? Those are NOT
        # "new" today. One grouped query instead of a per-row EXISTS check.
        cids = {row[1] for row in today_rows}
        cid_list = ",".join(str(int(c)) for c in cids)
        has_history = set(self.col.db.list(f"""
            SELECT DISTINCT cid FROM revlog
            WHERE type < 4 AND id < {int(id_lo)} AND cid IN ({cid_list})
        """))

        # First today-row per card (its id and type) — only matters for cards
        # without earlier history, to identify the introduction review.
        first_today = {}
        for (rid, cid, ease, t, rtype, day) in today_rows:
            if cid not in first_today:
                first_today[cid] = (rid, rtype)

        agg = {}  # day -> [revs, time, new, ret_total, ret_pass, ni_revs, ni_time, learn, relearn]
        for (rid, cid, ease, t, rtype, day) in today_rows:
            a = agg.get(day)
            if a is None:
                a = [0, 0, 0, 0, 0, 0, 0, 0, 0]
                agg[day] = a
            a[0] += 1
            a[1] += t or 0
            introduced_today = cid not in has_history
            f_rid, f_rtype = first_today.get(cid, (None, None))
            is_first_ever = introduced_today and rid == f_rid
            if is_first_ever and rtype == 0:
                a[2] += 1  # new card introduced
            # Retention: same rule as the original per-row loop
            is_new_same_day = exclude_new and introduced_today and f_rtype == 0
            if (not is_new_same_day) and (rtype > 0 or not is_first_ever):
                a[3] += 1
                if ease > 1:
                    a[4] += 1
            # Non-idle counters (for today's avg time/card)
            if (not exclude_idle) or (t <= idle_threshold_ms):
                a[5] += 1
                a[6] += t or 0
            if rtype == 0:
                a[7] += 1
            elif rtype == 2:
                a[8] += 1

        return [(day, *a) for day, a in agg.items()]

    def _fingerprint(self, bound):
        """(newest answer id, number of answers) before bound: changes only if the review
        log before it changes (an answer undone or deleted). Counted as all rows minus
        those after it: SQLite counts a whole table from its pages, a range row by row."""
        return tuple(self._hist_all(
            f"SELECT (SELECT MAX(id) FROM revlog WHERE id < {int(bound)}), "
            f"(SELECT COUNT(*) FROM revlog) - (SELECT COUNT(*) FROM revlog WHERE id >= {int(bound)})")[0]
            or (0, 0))

    def _history_rows(self, hist_key, deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms,
                      today_start_ms, hist_fp, compute=True):
        """The per-day totals before today: from this session's cache, else saved from an
        earlier run (startup_cache), else (with compute) saved totals topped up with the
        days since, else worked out in full. None when not cached and not computing."""
        rows = _REVLOG_AGG_CACHE.get(hist_key)
        if rows is not None:
            return rows
        col_path = self.col.path
        base = [sorted(int(d) for d in deck_ids) if deck_ids else None, bool(exclude_new),
                bool(exclude_idle), int(idle_ms), int(rollover_ms)]
        rows = startup_cache.history_exact(col_path, base, today_start_ms, hist_fp)
        if rows is None and compute:
            for entry in startup_cache.history_older(col_path, base, today_start_ms)[:1]:
                try:
                    if self._fingerprint(entry["bound"]) != tuple(entry["fp"]):
                        continue        # an earlier day's answers changed: start over
                    new = self._aggregate_revlog(deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms,
                                                 id_hi=today_start_ms, id_lo=entry["bound"])
                    rows = _merge_day_rows([tuple(r) for r in entry["rows"]] + [tuple(r) for r in new])
                except Exception:
                    rows = None
            if rows is None:
                rows = self._aggregate_history_full(deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms,
                                                    today_start_ms)
            startup_cache.history_put(col_path, base, today_start_ms, hist_fp, rows)
        if rows is not None:
            if len(_REVLOG_AGG_CACHE) > 8:
                _REVLOG_AGG_CACHE.clear()
            _REVLOG_AGG_CACHE[hist_key] = rows
        return rows

    def _aggregate_history_full(self, deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms, id_hi):
        """All the per-day totals before id_hi. Through Anki's own connection (Windows),
        a stretch of 30 days at a time: each statement holds Anki's database while it runs,
        and in one go that froze the window for a second or more on a big collection."""
        from . import estimator
        if not isinstance(self._hist_db, estimator.AnkiReader):
            return self._aggregate_revlog(deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms, id_hi=id_hi)
        first = self._hist_all("SELECT MIN(id) FROM revlog")[0][0]
        if first is None:
            return []
        step, hi, rows = 30 * 86400 * 1000, int(id_hi), []
        while hi > first:
            lo = hi - step
            rows += [tuple(r) for r in self._aggregate_revlog(
                deck_ids, rollover_ms, exclude_new, exclude_idle, idle_ms,
                id_hi=hi, id_lo=lo if lo > first else None)]
            hi = lo
        return _merge_day_rows(rows)

    def prepare_history(self, deck_ids=None, retention_deck_ids=None):
        """The slow part of get_data, ahead of it and off Anki's collection queue: the
        per-day totals before today, for the heatmap's decks (and the retention decks).
        Everything through this job's own connection (_hist_db)."""
        rollover_ms = self.rollover * 3600 * 1000
        today_date = datetime.datetime.fromtimestamp(time.time() - self.rollover * 3600).date()
        today_str = today_date.strftime("%Y-%m-%d")
        today_start_ms = int(time.mktime(today_date.timetuple())) * 1000 + rollover_ms
        exclude_new = self.cfg.get("exclude_new_cards_from_retention", False)
        exclude_idle = self.cfg.get("exclude_idle_cards", True)
        idle_ms = int(self.cfg.get("idle_threshold_secs", 60) * 1000)
        fp = self._fingerprint(today_start_ms)
        scopes = [deck_ids]
        if retention_deck_ids and not (deck_ids and sorted(deck_ids) == sorted(retention_deck_ids)):
            scopes.append(retention_deck_ids)
        for dids in scopes:
            key = (tuple(dids) if dids else None, bool(exclude_new), bool(exclude_idle), idle_ms,
                   rollover_ms, today_str, fp)
            self._history_rows(key, dids, rollover_ms, exclude_new, exclude_idle, idle_ms, today_start_ms, fp)

    def _compute_rows(self, deck_ids, rollover_ms, exclude_new, exclude_idle,
                      idle_threshold_ms, today_start_ms, today_str):
        """Per-day 10-tuple aggregates for one deck filter, using the split
        history/today cache. Extracted so it can be run twice — once for the main
        stats and once, with a different deck filter, purely for the retention %.
        See get_data for why the today/history split exists.
        """
        if today_start_ms is None:
            return self._aggregate_revlog(deck_ids, rollover_ms, exclude_new,
                                          exclude_idle, idle_threshold_ms)
        # Historical fingerprint only changes if pre-today rows change (e.g.
        # undoing a review from an earlier day), so this cache holds all day.
        # (Counted as all rows minus today's: SQLite counts a whole table from its
        # page counts, but a range row by row — ~1 ms instead of ~10-30.)
        hist_fp = tuple(self.col.db.first(
            f"SELECT (SELECT MAX(id) FROM revlog WHERE id < {today_start_ms}), "
            f"(SELECT COUNT(*) FROM revlog) - (SELECT COUNT(*) FROM revlog WHERE id >= {today_start_ms})")
            or (0, 0))
        hist_key = (
            tuple(deck_ids) if deck_ids else None,
            bool(exclude_new), bool(exclude_idle), idle_threshold_ms,
            rollover_ms, today_str, hist_fp,
        )
        hist_rows = self._history_rows(hist_key, deck_ids, rollover_ms, exclude_new, exclude_idle,
                                       idle_threshold_ms, today_start_ms, hist_fp, compute=not self.cache_only)
        if hist_rows is None:
            self.missing = True
            hist_rows = []
        today_agg = self._aggregate_today(
            deck_ids, rollover_ms, exclude_new, exclude_idle,
            idle_threshold_ms, id_lo=today_start_ms)
        return hist_rows + today_agg

    def get_data(self, deck_ids=None, retention_deck_ids=None):
        rollover_ms = self.rollover * 3600 * 1000
        now_ts = time.time()
        anki_today_dt = datetime.datetime.fromtimestamp(now_ts - (self.rollover * 3600))
        today_str = anki_today_dt.strftime("%Y-%m-%d")
        today_date = anki_today_dt.date()
        start_date = self.get_start_date()
        cutoff_ts = int(time.mktime(start_date.timetuple()) * 1000)

        history = {}
        time_history = {}       # per-day study time (idle-filtered when exclude_idle is on)
        time_revs_history = {}   # per-day review count for the time/card denominator (idle-filtered)
        new_cards_history = {}
        retention = {}
        today_revs = 0
        today_time_ms = 0
        today_revs_retention = 0
        today_pass_retention = 0
        # Separate counters for avg time/card calculation (respects idle + back-time filters)
        today_time_revs = 0       # cards counted toward avg time
        today_time_ms_filtered = 0  # time sum for those cards
        exclude_new = self.cfg.get("exclude_new_cards_from_retention", False)
        exclude_idle = self.cfg.get("exclude_idle_cards", True)
        idle_threshold_ms = int(self.cfg.get("idle_threshold_secs", 60) * 1000)

        # Aggregate the revlog in SQL instead of streaming every row into Python.
        # This runs on every deck-browser render (including every return from the
        # reviewer), so we split it: everything BEFORE today is immutable, so it's
        # computed once and cached for the session; only today's handful of rows —
        # which change as you review — is recomputed each render. That turns a
        # ~0.5s recompute-on-every-return into a one-time-per-day cost.
        # (deck stats / due counts below are NOT cached — they must stay fresh.)
        # Boundary between "history" and "today", derived from the SAME day
        # formula the SQL uses (strftime of (id - rollover_ms) as a local date),
        # so it lands exactly on the day edge: a row has day == today_str iff its
        # id >= today_start_ms. This guarantees history and today never share a
        # day (no split-day double counting).
        try:
            today_start_ms = int(time.mktime(today_date.timetuple())) * 1000 + rollover_ms
        except Exception:
            today_start_ms = None

        rows = self._compute_rows(deck_ids, rollover_ms, exclude_new, exclude_idle,
                                  idle_threshold_ms, today_start_ms, today_str)

        # Optionally scope the retention % to a different set of decks than the
        # rest of the stats. When active we run the same aggregation a second time
        # for the retention decks and use ONLY its per-day ret_total/ret_pass; all
        # other counters (reviews, time, new cards) still come from `rows` above.
        ret_by_day = None
        if retention_deck_ids:
            same_scope = bool(deck_ids) and sorted(deck_ids) == sorted(retention_deck_ids)
            if not same_scope:
                ret_rows = self._compute_rows(
                    retention_deck_ids, rollover_ms, exclude_new, exclude_idle,
                    idle_threshold_ms, today_start_ms, today_str)
                ret_by_day = {r[0]: (r[4], r[5]) for r in ret_rows}  # day -> (total, pass)

        for (d_str, revs, t_sum, n_new, ret_total, ret_pass, ni_revs, ni_time, n_learn, n_relearn) in rows:
            history[d_str] = revs
            self.kinds[d_str] = (revs - (n_learn or 0) - (n_relearn or 0), n_learn or 0, n_relearn or 0)
            # Study time (and its per-card denominator) honor the idle-card
            # threshold, so the time heatmap / time graphs match the Time/Card
            # average. When exclude_idle is off, ni_time == t_sum and ni_revs ==
            # revs, so this is identical to the raw totals.
            time_history[d_str] = ni_time or 0
            time_revs_history[d_str] = ni_revs
            if n_new:
                new_cards_history[d_str] = n_new
            if ret_by_day is None and ret_total:
                retention[d_str] = [ret_pass, ret_total]
            if d_str == today_str:
                today_revs = revs
                today_time_ms = t_sum or 0
                if ret_by_day is None:
                    today_revs_retention = ret_total
                    today_pass_retention = ret_pass
                today_time_revs = ni_revs
                today_time_ms_filtered = ni_time or 0

        # Retention scoped to its own deck subset: overwrite the retention series
        # (and today's retention counters) from the scoped aggregation.
        if ret_by_day is not None:
            for d_str, (ret_total, ret_pass) in ret_by_day.items():
                if ret_total:
                    retention[d_str] = [ret_pass, ret_total]
                if d_str == today_str:
                    today_revs_retention = ret_total
                    today_pass_retention = ret_pass

        try:
            today_int = self.col.sched.today
            day_cutoff = self.col.sched.day_cutoff 
            now_int = int(time.time())
        except:
            today_int = 0
            day_cutoff = int(time.time()) + 86400
            now_int = int(time.time())

        deck_stats = {} 
        def add_stat(did, key, val):
            d_str = str(did)
            if d_str not in deck_stats: deck_stats[d_str] = {'n':0, 'l':0, 'd':0, 'done':0}
            deck_stats[d_str][key] = val

        rows = self.col.db.all("SELECT did, count() FROM cards WHERE queue=0 GROUP BY did")
        for did, cnt in rows: add_stat(did, 'n', cnt)
        rows = self.col.db.all(f"SELECT did, count() FROM cards WHERE (queue = 1 AND due <= {now_int}) "
                               f"OR (queue = 3 AND due <= {today_int}) GROUP BY did")
        for did, cnt in rows: add_stat(did, 'l', cnt)
        rows = self.col.db.all(f"SELECT did, count() FROM cards WHERE queue=2 AND due <= {today_int} GROUP BY did")
        for did, cnt in rows: add_stat(did, 'd', cnt)

        today_start_ts = int(day_cutoff - 86400) * 1000
        # Today's cards first, then each one looked up (a join walks every card instead).
        done_rows = self.col.db.all(f"""
            SELECT c.did, count()
            FROM cards c
            WHERE c.id IN (SELECT cid FROM revlog WHERE id > {today_start_ts})
            AND (
                (c.queue IN (2, 3) AND c.due > {today_int})
                OR
                (c.queue IN (0, 1) AND c.due > {day_cutoff})
                OR
                (c.queue < 0)
            )
            GROUP BY c.did
        """)
        for did, cnt in done_rows: add_stat(did, 'done', cnt)

        all_decks = self.col.decks.all_names_and_ids()
        id_to_name = { (d.id if hasattr(d,'id') else d['id']): (d.name if hasattr(d,'name') else d['name']) for d in all_decks }
        name_to_id = { name: did for did, name in id_to_name.items() }
        
        snapshot = list(deck_stats.items()) 
        for did_str, stats in snapshot:
            try: did_int = int(did_str)
            except: continue
            if did_int in id_to_name:
                parts = id_to_name[did_int].split("::")
                current = ""
                for i in range(len(parts) - 1):
                    if i > 0: current += "::"
                    current += parts[i]
                    if current in name_to_id:
                        pid = str(name_to_id[current])
                        if pid not in deck_stats: deck_stats[pid] = {'n':0, 'l':0, 'd':0, 'done':0}
                        deck_stats[pid]['n'] += stats['n']
                        deck_stats[pid]['l'] += stats['l']
                        deck_stats[pid]['d'] += stats['d']
                        deck_stats[pid]['done'] += stats['done']

        forecast = {}
        # Check if FSRS simulation is enabled and FSRS is available
        fsrs_enabled = self.cfg.get('fsrs_simulation_enabled', False) and _get_fsrs_params() is not None

        if fsrs_enabled:
            # Use FSRS smart prediction with your personal optimized parameters
            # Check if a specific deck is selected for forecast
            forecast_deck_id = self.cfg.get('fsrs_forecast_deck', 0)
            if forecast_deck_id and forecast_deck_id != 0:
                # Use the selected forecast deck
                forecast = self.get_fsrs_forecast(deck_ids=[forecast_deck_id])
            else:
                # Default to most recently studied deck instead of all decks
                recent_deck_id = self._get_most_recent_deck()
                if recent_deck_id:
                    forecast = self.get_fsrs_forecast(deck_ids=[recent_deck_id])
                else:
                    # Fall back to deck_ids from filter (or all decks if none)
                    forecast = self.get_fsrs_forecast(deck_ids=deck_ids)
            if forecast is None:
                # Simulator unavailable (old Anki version) or failed —
                # fall back to the simple due-count forecast below.
                fsrs_enabled = False
        if not fsrs_enabled:
            # Use simple forecast - count cards by due date
            # One row per due day (not per card), and the scheduler's day asked once:
            # each sched.today is a call into Anki, and this ran once per card.
            forecast = {}
            sched_today = self.col.sched.today
            deck_filter = f"AND did IN ({','.join(map(str, deck_ids))})" if deck_ids else ""
            rows = self.col.db.all(f"SELECT due, count() FROM cards WHERE queue IN (2,3) "
                                   f"AND due >= {sched_today} {deck_filter} GROUP BY due")
            base_dt = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
            for due_val, n in rows:
                try:
                    f_str = (base_dt + timedelta(days=due_val - sched_today)).strftime("%Y-%m-%d")
                    forecast[f_str] = forecast.get(f_str, 0) + n
                except Exception:
                    pass

        today_rate = round((today_pass_retention/today_revs_retention)*100, 1) if today_revs_retention > 0 else 0.0
        avg_time = round((today_time_ms_filtered/today_time_revs)/1000, 1) if today_time_revs > 0 else 0
        # Total study minutes today also drops idle time so it agrees with the
        # time heatmap/graph (today_time_ms_filtered == today_time_ms when the
        # idle filter is off).
        total_mins = int(round((today_time_ms_filtered/1000)/60))

        # Calculate daily average based on selected period
        avg_period = self.cfg.get("avg_period", "year")
        if avg_period == "week":
            period_start = today_date - timedelta(days=7)
        elif avg_period == "month":
            period_start = today_date - timedelta(days=30)
        elif avg_period == "year":
            period_start = today_date - timedelta(days=365)
        else:  # "all"
            period_start = start_date

        period_revs = sum(v for k, v in history.items()
                         if datetime.date.fromisoformat(k) >= period_start)
        period_days = max(1, (today_date - period_start).days + 1)
        daily_avg = int(period_revs / period_days)
        
        cards_due = 0
        try:
            cards_due = _cards_due(self.col, deck_ids, today_int, now_int)
        except: pass

        streak = 0
        dates = sorted(history.keys())
        ords = [datetime.date.fromisoformat(d).toordinal() for d in dates]
        today_ord = today_date.toordinal()
        if ords and (today_ord - ords[-1]) <= 1:
            streak = 1
            for i in range(len(ords)-1, 0, -1):
                if ords[i] == ords[i-1] + 1: streak += 1
                elif ords[i] == ords[i-1]: continue
                else: break

        # Compute percentage of days studied over past week and month
        date_set = set(dates)
        pct_week = round(sum(1 for d in range(7) if (today_date - timedelta(days=d)).strftime("%Y-%m-%d") in date_set) / 7 * 100)
        pct_month = round(sum(1 for d in range(30) if (today_date - timedelta(days=d)).strftime("%Y-%m-%d") in date_set) / 30 * 100)

        return history, time_history, time_revs_history, new_cards_history, retention, forecast, today_revs, today_rate, avg_time, total_mins, cards_due, daily_avg, streak, pct_week, pct_month, today_str, start_date, deck_stats, avg_period

    def _get_most_recent_deck(self):
        """Get the deck ID of the most recently studied card."""
        try:
            # Get the most recent review and find its deck
            result = self.col.db.first("""
                SELECT c.did FROM revlog r
                JOIN cards c ON r.cid = c.id
                ORDER BY r.id DESC
                LIMIT 1
            """)
            if result:
                return result[0]
        except:
            pass
        return None

    def get_fsrs_forecast(self, deck_ids=None):
        """
        Generate FSRS-based forecast using Anki's built-in simulator — identical to
        the Stats → FSRS Simulator tab.  A single SimulateFsrsReviewRequest handles
        both existing scheduled cards and the hypothetical new-card ramp-up in one pass.

        Returns a {date_str: reviews} dict, or None when the simulator is
        unavailable/fails so the caller can fall back to the simple due-count
        forecast instead of showing an empty line (or crashing on older Anki
        versions where the protobuf API differs).
        """
        try:
            return self._get_fsrs_forecast_inner(deck_ids)
        except Exception:
            _log_exc()      # the caller falls back to the plain due-count forecast
            # Remember the failure like a result, so it isn't retried (seconds of
            # work) on every render; it's tried again once the entry expires.
            if self._forecast_key is not None:
                _FSRS_FORECAST_CACHE[self._forecast_key] = (time.time(), None, {})
            return None

    def _get_fsrs_forecast_inner(self, deck_ids=None):
        import anki.errors
        import anki.scheduler_pb2

        first_deck = deck_ids[0] if deck_ids else None
        params = _get_fsrs_params(first_deck)
        if params is None:
            return None

        # Resolve weights (custom override or deck config)
        use_custom = self.cfg.get("fsrs_use_custom_weights", False)
        custom_weights_str = self.cfg.get("fsrs_custom_weights", "")
        if use_custom and custom_weights_str:
            try:
                weights = [float(w.strip()) for w in custom_weights_str.split(",") if w.strip()]
                if len(weights) < 17:
                    weights.extend(FSRS_DEFAULT_WEIGHTS[len(weights):])
            except:
                weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)
        else:
            weights = params.get('weights', FSRS_DEFAULT_WEIGHTS)

        def _cfg_int(key, default):
            try:
                return int(self.cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        simulation_days  = _cfg_int("fsrs_simulation_days", 90)
        try:
            target_retention = float(self.cfg.get("fsrs_simulation_retention", 0.9))
        except (TypeError, ValueError):
            target_retention = 0.9
        max_reviews      = _cfg_int("fsrs_simulation_max_reviews", 9999)
        max_interval     = _cfg_int("fsrs_simulation_max_interval", 36500)
        learning_steps   = _cfg_int("fsrs_learning_steps", 2)
        relearning_steps = _cfg_int("fsrs_relearning_steps", 1)
        new_cards_per_day = _cfg_int("fsrs_simulation_new_cards", 0)
        new_card_days    = forecast_band.clean_days(self.cfg.get("fsrs_new_card_days", forecast_band.ALL_DAYS))
        band_on          = bool(self.cfg.get("fsrs_band_enabled", False))
        band_k           = 2 if _cfg_int("fsrs_band_sd", 1) >= 2 else 1

        today_str = datetime.datetime.fromtimestamp(
            time.time() - (self.rollover * 3600)
        ).strftime("%Y-%m-%d")
        today_date = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()

        # Simulation is expensive (blocks the main thread for hundreds of ms on
        # large collections) and runs on every deck browser render, so cache the
        # result briefly. Config changes clear the cache via write_config().
        cache_key = (
            today_str,
            tuple(deck_ids) if deck_ids else None,
            tuple(weights),
            simulation_days, target_retention, max_reviews, max_interval,
            learning_steps, relearning_steps, new_cards_per_day,
            bool(self.cfg.get('fsrs_simulate_overhead', True)),
            tuple(new_card_days), band_on, band_k,
        )
        cached = _FSRS_FORECAST_CACHE.get(cache_key)
        if cached is None:
            # saved by an earlier run (startup_cache): shown now, refreshed in the background
            cached = startup_cache.forecast_get(self.col.path, cache_key)
            if cached is not None:
                _FSRS_FORECAST_CACHE[cache_key] = cached
        if cached is not None:
            self.fsrs_band = cached[2]
            if (time.time() - cached[0]) < 600:
                return cached[1]
            if self.cache_only or time.time() < _STARTUP_HOLD_UNTIL:
                # (just after startup the simulation waits: it holds Anki's backend for a second or more)
                self.stale = True
                return cached[1]
        if self.cache_only:
            self.missing = True
            return None
        self._forecast_key = cache_key

        # Overhead calibration factors
        simulate_overhead = bool(self.cfg.get('fsrs_simulate_overhead', True))
        lapse_rate = 1.0 - target_retention
        relearn_fail_rate = 0.0
        if simulate_overhead:
            try:
                _cutoff_ms = int(time.time() * 1000) - (90 * 86400 * 1000)
                _n_mature       = self.col.db.scalar(f"SELECT count() FROM revlog WHERE type=1 AND id > {_cutoff_ms}")
                _n_lapse        = self.col.db.scalar(f"SELECT count() FROM revlog WHERE type=1 AND ease=1 AND id > {_cutoff_ms}")
                _n_relearn      = self.col.db.scalar(f"SELECT count() FROM revlog WHERE type=2 AND id > {_cutoff_ms}")
                _n_relearn_fail = self.col.db.scalar(f"SELECT count() FROM revlog WHERE type=2 AND ease=1 AND id > {_cutoff_ms}")
                if _n_mature > 0:
                    lapse_rate = _n_lapse / _n_mature
                if _n_relearn > 0:
                    relearn_fail_rate = min(_n_relearn_fail / _n_relearn, 0.99)
            except:
                pass

        search = ""
        if deck_ids:
            deck_names = []
            for did in deck_ids:
                deck = self.col.decks.get(did)
                if deck:
                    name = deck["name"].replace('"', '\\"')
                    deck_names.append(f'"deck:{name}"')
            if deck_names:
                search = " OR ".join(deck_names)

        backend = getattr(self.col, "_backend", None)
        if backend is None:
            backend = self.col.backend
        available = anki.scheduler_pb2.SimulateFsrsReviewRequest.DESCRIPTOR.fields_by_name

        def run_sim(sim_search, deck_size, new_limit, review_limit=max_reviews):
            # Only pass fields that exist in this Anki version's protobuf schema —
            # e.g. learning_step_count/relearning_step_count are missing on older
            # versions, and unknown kwargs raise ValueError.
            req_kwargs = {
                "params": weights,
                "desired_retention": target_retention,
                "deck_size": deck_size,
                "days_to_simulate": simulation_days,
                "new_limit": new_limit,
                "review_limit": review_limit,
                "max_interval": max_interval,
                "search": sim_search,
                "learning_step_count": learning_steps,
                "relearning_step_count": relearning_steps,
            }
            req_kwargs = {k: v for k, v in req_kwargs.items() if k in available}
            request = anki.scheduler_pb2.SimulateFsrsReviewRequest(**req_kwargs)
            try:
                return list(backend.simulate_fsrs_review(request).daily_review_count)
            except anki.errors.InvalidInput as e:
                # an empty deck with no new cards planned: nothing is due, so nothing to forecast
                if "no cards" in str(e).lower():
                    return [0] * simulation_days
                raise

        # New cards on only some weekdays: Anki's simulator takes one count for every
        # day, so simulate your cards without new ones and add the reviews of each
        # day's new cards from a run on a batch of new cards alone.
        some_days = new_cards_per_day > 0 and len(new_card_days) < 7
        curve = None
        if (new_cards_per_day > 0 and some_days) or band_on:
            curve = forecast_band.batch_curve(
                lambda s, size, limit: run_sim(s, size, limit, review_limit=9999), simulation_days)
        intro = forecast_band.intro_schedule(today_date, simulation_days, new_cards_per_day,
                                             new_card_days if some_days else forecast_band.ALL_DAYS)
        if some_days:
            review_counts = run_sim(search, 0, 0)
            review_counts += [0] * (simulation_days - len(review_counts))
            review_counts = [min(max_reviews, v)
                             for v in forecast_band.add_new_cards(review_counts[:simulation_days], curve, intro)]
        else:
            # deck_size = total new card pool; large enough to last the full window
            deck_size = new_cards_per_day * simulation_days if new_cards_per_day > 0 else 0
            review_counts = run_sim(search, deck_size, new_cards_per_day)

        scope = forecast_band.scope_key(deck_ids)
        dids = forecast_band.scope_dids(self.col, deck_ids)

        # The simulator puts every overdue card on today, but a backlog gets cleared over
        # several days: spread it at the rate you've cleared yours in recent weeks.
        try:
            deck_where = f"AND did IN ({','.join(map(str, dids))})" if dids else ""
            backlog = self.col.db.scalar(
                f"SELECT count() FROM cards WHERE queue = 2 AND due < {self.col.sched.today} {deck_where}") or 0
            if backlog:
                rate = forecast_band.backlog_rate(self.col, dids, today_date, self.rollover)
                review_counts = forecast_band.spread_backlog(review_counts, backlog, rate)
        except Exception:
            _log_exc()

        # Counting every answer, as the graph does: relearning steps scale the reviews, and
        # each new card's learning steps (which the simulator leaves out) come from your
        # own recent new cards.
        relearn_multiplier = relearning_steps / max(1e-9, 1.0 - relearn_fail_rate)
        scale = (1 + lapse_rate * relearn_multiplier) if simulate_overhead else 1.0
        profile = [0.0] * forecast_band.LEARN_DAYS
        learn = [0.0] * len(intro)
        if simulate_overhead:
            profile = forecast_band.learning_profile(self.col, dids, today_date, self.rollover, learning_steps)
            # today: the planned new cards, or the ones you've already started if more
            started = forecast_band.started_recently(self.col, dids, today_date, self.rollover)
            intro_now = list(intro)
            if intro_now:
                intro_now[0] = max(intro_now[0], started[2])
            learn = forecast_band.add_learning(intro_now, profile)
            # steps still to come from the cards you started the last two days
            for d in range(min(2, len(learn))):
                for back, n in ((1, started[1]), (2, started[0])):
                    if d + back < len(profile):
                        learn[d] += n * profile[d + back]
            # today shows what's left: take off the learning answers already done
            if learn:
                learn[0] = max(0.0, learn[0] - forecast_band.learning_done_today(
                    self.col, dids, today_date, self.rollover))

        fsrs_forecast = {}
        values = []
        for day_offset, reviews in enumerate(review_counts):
            reviews = int(round(reviews * scale + (learn[day_offset] if day_offset < len(learn) else 0)))
            values.append(reviews)
            if reviews <= 0:
                continue
            date_str = (today_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            fsrs_forecast[date_str] = fsrs_forecast.get(date_str, 0) + reviews

        try:
            forecast_band.log_forecast(scope, today_date, values)
        except Exception:
            _log_exc()

        band = {}
        if band_on:
            try:
                if curve is not None:
                    # each new card's answers on each later day: reviews (scaled) + learning
                    curve = [scale * c + (profile[t] if t < len(profile) else 0) for t, c in enumerate(curve)]
                band = self._fsrs_band(values, curve, today_date, scope, dids, new_cards_per_day,
                                       new_card_days, band_k, simulate_overhead)
            except Exception:
                _log_exc()
        self.fsrs_band = band

        _FSRS_FORECAST_CACHE.clear()
        _FSRS_FORECAST_CACHE[cache_key] = (time.time(), fsrs_forecast, band)
        if fsrs_forecast is not None:
            startup_cache.forecast_put(self.col.path, cache_key, time.time(), fsrs_forecast, band)
        return fsrs_forecast

    def _fsrs_band(self, values, curve, today_date, scope, dids, per_day, days, k, every_answer):
        """{date_str: (low, high)}: the forecast ± k standard deviations. Each day's spread
        combines how far your new cards have strayed from the plan (carried through to the
        answers they cause; wider above than below, since an extra batch adds a lot) with
        how far past forecasts this far ahead were off, as a share of the forecast, so the
        band grows with the forecast and further out. Until enough forecasts are saved,
        past forecasts are rebuilt from your review history."""
        n = min(len(values), 91)    # the graph and heatmap show at most the next few weeks
        up = down = [0.0] * n
        if curve is not None:
            counts = forecast_band.weekday_counts(self.col, dids, today_date, self.rollover,
                                                  forecast_band.BAND_WEEKS)
            up, down = forecast_band.habit_spread(curve, today_date, n, per_day, days, counts)
        logged = forecast_band.forecast_errors(self.col, scope, dids, today_date, self.rollover,
                                               every_answer)
        rebuilt = None
        band = {}
        for d in range(1, n):
            rel = forecast_band.error_rel(logged, d)
            if rel:
                # past forecasts already include new-card swings: take the larger
                err = rel * values[d]
                hi, lo = max(up[d], err), max(down[d], err)
            else:
                if rebuilt is None:
                    rebuilt = forecast_band.schedule_errors(self.col, dids, today_date, self.rollover)
                # rebuilt schedules leave out new cards: add their spread
                err = forecast_band.error_rel(rebuilt, d) * values[d]
                hi, lo = math.hypot(up[d], err), math.hypot(down[d], err)
            if hi <= 0 and lo <= 0:
                continue
            date_str = (today_date + timedelta(days=d)).strftime("%Y-%m-%d")
            band[date_str] = (max(0, int(round(values[d] - k * lo))), int(round(values[d] + k * hi)))
        return band

    def get_backtest_data(self, days_back=90, deck_ids=None):
        """
        Backtest the FSRS new-card predictor against historical revlog data.

        Identifies cards introduced during the window (first-ever revlog entry in range),
        runs _simulate_new_card_reviews_dated with those actual introduction dates, then
        compares the predicted review counts against the real daily totals from revlog.

        Returns a dict with keys:
            dates            – sorted list of datetime.date objects covering the window
            new_cards        – {date: count}  actual new cards introduced
            predicted        – {date: count}  predicted reviews (new cards only)
            actual           – {date: count}  actual total reviews (all card types)
        """
        rollover = self.col.conf.get('rollover', 4)
        anki_today = datetime.datetime.fromtimestamp(time.time() - rollover * 3600).date()
        start_date = anki_today - timedelta(days=days_back)

        # ms timestamps for SQL
        start_ts = int(time.mktime(datetime.datetime.combine(
            start_date, datetime.time(rollover, 0)).timetuple()) * 1000)
        end_ts   = int(time.mktime(datetime.datetime.combine(
            anki_today, datetime.time(rollover, 0)).timetuple()) * 1000)

        deck_join   = "JOIN cards c ON r.cid = c.id" if deck_ids else ""
        deck_filter = f"AND c.did IN ({','.join(map(str, deck_ids))})" if deck_ids else ""

        # First-ever revlog entry per card that falls inside the window
        # (cards whose very first review happened during this period = newly introduced)
        rows = self.col.db.all(f"""
            SELECT x.cid, x.first_ts FROM (
                SELECT r.cid, MIN(r.id) AS first_ts
                FROM revlog r {deck_join}
                WHERE 1=1 {deck_filter}
                GROUP BY r.cid
            ) x WHERE x.first_ts >= {start_ts} AND x.first_ts < {end_ts}
        """)
        new_cards_by_date = {}
        for _cid, first_ts in rows:
            d = datetime.datetime.fromtimestamp(
                first_ts / 1000 - rollover * 3600).date()
            new_cards_by_date[d] = new_cards_by_date.get(d, 0) + 1

        # Actual reviews per day (all types)
        rev_rows = self.col.db.all(f"""
            SELECT r.id FROM revlog r {deck_join}
            WHERE r.id >= {start_ts} AND r.id < {end_ts} {deck_filter}
        """)
        actual_by_date = {}
        for (ts,) in rev_rows:
            d = datetime.datetime.fromtimestamp(
                ts / 1000 - rollover * 3600).date()
            actual_by_date[d] = actual_by_date.get(d, 0) + 1

        # Run FSRS simulation with actual new-card introduction dates
        first_deck = deck_ids[0] if deck_ids else None
        params = _get_fsrs_params(first_deck)
        if params is None:
            params = {'weights': FSRS_DEFAULT_WEIGHTS, 'desired_retention': 0.9,
                      'decay': -0.5, 'factor': 0.9 ** (1 / -0.5) - 1}

        target_ret = self.cfg.get('fsrs_simulation_retention', 0.9)
        params = dict(params)
        params['desired_retention'] = target_ret

        predicted_by_date = _simulate_new_card_reviews_dated(
            new_cards_by_date, anki_today, params, start_date)

        dates = [start_date + timedelta(days=i) for i in range(days_back)]
        return {
            'dates':      dates,
            'new_cards':  new_cards_by_date,
            'predicted':  predicted_by_date,
            'actual':     actual_by_date,
        }

    def _compute_calibration(self, days_back=90, deck_ids=None):
        """
        Fit two calibration parameters to historical review data:

        stability_scale  – multiply FSRS initial stability by this to match real
                           first-review intervals (< 1 → cards harder than expected,
                           > 1 → cards easier / intervals longer).
        baseline_per_day – average existing-deck reviews per day, estimated from
                           the first round(s0) days of the window (before any
                           new-window cards can return).

        Algorithm
        ---------
        1. stability_scale: for every card introduced in the window that has ≥ 2
           revlog entries, compare the actual gap between review 1 and review 2
           to the FSRS-predicted first interval (≈ round(s0)).  The median ratio
           is the scale factor.
        2. baseline_per_day: average daily total reviews over the first s0 days,
           when no new-window cards have yet come back.

        Returns {'stability_scale': float, 'baseline_per_day': float}.
        """
        rollover = self.col.conf.get('rollover', 4)
        anki_today = datetime.datetime.fromtimestamp(time.time() - rollover * 3600).date()
        start_date  = anki_today - timedelta(days=days_back)
        start_ts = int(time.mktime(datetime.datetime.combine(
            start_date, datetime.time(rollover, 0)).timetuple()) * 1000)
        end_ts = int(time.mktime(datetime.datetime.combine(
            anki_today, datetime.time(rollover, 0)).timetuple()) * 1000)

        deck_join   = "JOIN cards c ON r.cid = c.id" if deck_ids else ""
        deck_filter = f"AND c.did IN ({','.join(map(str, deck_ids))})" if deck_ids else ""

        params = _get_fsrs_params(deck_ids[0] if deck_ids else None)
        weights = params['weights'] if params else FSRS_DEFAULT_WEIGHTS
        s0 = weights[2] if len(weights) > 2 else 3.126
        predicted_first_ivl = max(1.0, float(round(s0)))

        # ── Baseline: avg daily reviews in the first s0 days ─────────────────
        baseline_days = max(1, int(round(s0)))
        baseline_end_ts = int(time.mktime(datetime.datetime.combine(
            start_date + timedelta(days=baseline_days),
            datetime.time(rollover, 0)).timetuple()) * 1000)
        baseline_count = self.col.db.scalar(f"""
            SELECT COUNT(*) FROM revlog r {deck_join}
            WHERE r.id >= {start_ts} AND r.id < {baseline_end_ts} {deck_filter}
        """) or 0
        baseline_per_day = baseline_count / baseline_days

        # ── Stability scale: actual vs predicted first review intervals ────────
        # Get all revlog entries for cards first introduced in the window,
        # ordered per card chronologically.
        all_rows = self.col.db.all(f"""
            SELECT r.cid, r.id
            FROM revlog r {deck_join}
            WHERE r.cid IN (
                SELECT inner_cid FROM (
                    SELECT r2.cid AS inner_cid, MIN(r2.id) AS first_ts
                    FROM revlog r2
                    WHERE r2.id >= {start_ts} {deck_filter.replace('AND c.', 'AND ')}
                    GROUP BY r2.cid
                ) WHERE first_ts >= {start_ts} AND first_ts < {end_ts}
            ) AND r.id < {end_ts} {deck_filter}
            ORDER BY r.cid, r.id
        """)

        # Group by card and compute interval between 1st and 2nd review
        intervals = []
        from itertools import groupby
        for _cid, group in groupby(all_rows, key=lambda x: x[0]):
            ts_list = [row[1] for row in group]
            if len(ts_list) >= 2:
                actual_days = (ts_list[1] - ts_list[0]) / 86_400_000.0
                if actual_days > 0:
                    intervals.append(actual_days)

        if intervals:
            intervals.sort()
            # Median is more robust than mean against outliers (e.g. vacation gaps)
            mid = len(intervals) // 2
            median_interval = (intervals[mid] if len(intervals) % 2
                               else (intervals[mid-1] + intervals[mid]) / 2)
            stability_scale = median_interval / predicted_first_ivl
            # Clamp to avoid wild values
            stability_scale = max(0.3, min(3.0, stability_scale))
        else:
            stability_scale = 1.0

        return {
            'stability_scale':   round(stability_scale, 4),
            'baseline_per_day':  round(baseline_per_day, 2),
        }

    @staticmethod
    def _band_path(lo, hi, color, mx, x_offset, x_span, h, pad=5):
        """A soft filled area between lo and hi on the graph's scale (the confidence band)."""
        if len(lo) < 2:
            return ""
        step = x_span / (len(lo) - 1)
        y = lambda v: (h - pad) - (max(0, min(v, mx)) / (mx or 1)) * (h - 2 * pad)
        top = [f"{x_offset + i * step:.1f},{y(v):.1f}" for i, v in enumerate(hi)]
        bottom = [f"{x_offset + i * step:.1f},{y(v):.1f}" for i, v in reversed(list(enumerate(lo)))]
        return (f'<path class="hm-fill" d="M {" L ".join(top + bottom)} Z" fill="{color}" fill-opacity="0.3" '
                f'stroke="none" />')

    def get_graph_points(self, history, time_hist, time_revs_hist, retention, forecast, today_str):
        days = 30
        w, h = 530, 60
        today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
        active = self.cfg.get("active_graphs_v14", ["reviews", "time_card", "retention", "forecast"])
        is_extended = "forecast" in active

        # Collect historical data (past 30 days)
        raw_rev, raw_time, raw_ret, raw_time_studied = [], [], [], []
        hist_meta = []
        for i in range(days-1, -1, -1):
            d = today - timedelta(days=i)
            d_s = d.strftime("%Y-%m-%d")
            r = history.get(d_s, 0)
            t = time_hist.get(d_s, 0)
            rt = time_revs_hist.get(d_s, r)  # idle-filtered count for time/card
            s = round((t/rt)/1000, 1) if rt > 0 else 0
            ts_mins = round(t / 1000 / 60, 1)  # total study time in minutes
            ret_data = retention.get(d_s, [0, 0])
            ret_pct = round((ret_data[0] / ret_data[1]) * 100, 1) if ret_data[1] > 0 else 0.0
            raw_rev.append(r)
            raw_time.append(s)
            raw_ret.append(ret_pct)
            raw_time_studied.append(ts_mins)
            hist_meta.append({"label": d.strftime("%b %d").upper(), "rev": r, "time": s, "ret": ret_pct, "fut": 0, "ts_mins": ts_mins})

        # Backfill rolling averages into hist_meta (always computed so hover reflects plotted line)
        def _rolling(arr, period):
            return [round(sum(arr[max(0, i - period + 1):i + 1]) / len(arr[max(0, i - period + 1):i + 1]), 1)
                    for i in range(len(arr))]

        for _i, _avg in enumerate(_rolling(raw_rev,  self.cfg.get('reviews_rolling_avg_period', 7))):
            hist_meta[_i]['rev_avg']  = _avg
        for _i, _avg in enumerate(_rolling(raw_time, self.cfg.get('time_rolling_avg_period', 7))):
            hist_meta[_i]['time_avg'] = _avg
        for _i, _avg in enumerate(_rolling(raw_ret,  self.cfg.get('ret_rolling_avg_period', 7))):
            hist_meta[_i]['ret_avg']  = _avg
        for _i, _avg in enumerate(_rolling(raw_time_studied, self.cfg.get('time_studied_rolling_avg_period', 7))):
            hist_meta[_i]['ts_avg'] = _avg

        # Collect future forecast data (next 30 days)
        raw_fut = []
        fut_meta = []
        for j in range(1, days + 1):
            f_d = today + timedelta(days=j)
            f_s = f_d.strftime("%Y-%m-%d")
            f = forecast.get(f_s, 0)
            raw_fut.append(f)
            fut_meta.append({"label": f_d.strftime("%b %d").upper(), "rev": 0, "time": 0, "ret": 0, "fut": f,
                             "rev_avg": 0, "time_avg": 0, "ret_avg": 0, "fut_avg": 0, "ts_mins": 0, "ts_avg": 0, "exams": []})
            if f_s in self.fsrs_band:
                fut_meta[-1]["fut_lo"], fut_meta[-1]["fut_hi"] = self.fsrs_band[f_s]

        # Backfill forecast rolling average
        for _i, _avg in enumerate(_rolling(raw_fut, self.cfg.get('forecast_rolling_avg_period', 7))):
            fut_meta[_i]['fut_avg'] = _avg

        # In extended mode the hover covers all 60 days; in 30-day mode only history
        meta_data = hist_meta + (fut_meta if is_extended else [])

        def get_path(arr, invert=False, fill=False, is_retention=False, line_color=None, smooth=True, auto_scale=False, shared_max=None, x_offset=0.0, x_span=None):
            if not arr: return ""
            clean_arr = [x if x is not None else 0 for x in arr]
            eff_w = x_span if x_span is not None else w
            if shared_max is not None:
                mx = shared_max
                min_v = 0
            else:
                mx = max(clean_arr) if max(clean_arr) > 0 else 1
                min_v = 0
                if is_retention:
                    valid = [v for v in clean_arr if v > 0]
                    if valid:
                        true_min = min(valid)
                        true_max = max(valid)
                        rng = true_max - true_min
                        if rng > 0:
                            padding = max(2, rng * 0.25)
                            min_v = max(0, true_min - padding)
                            mx = min(100, true_max + padding)
                        else:
                            min_v = max(0, true_min - 5)
                            mx = min(100, true_max + 5)
                    else:
                        min_v = 0
                        mx = 100
                elif auto_scale:
                    valid = [v for v in clean_arr if v > 0]
                    if valid:
                        true_min = min(valid)
                        true_max = max(valid)
                        rng = true_max - true_min
                        if rng > 0:
                            min_v = max(0, true_min - rng * 0.1)
                            mx = true_max + rng * 0.1
            pts = []
            step = eff_w / (len(clean_arr) - 1) if len(clean_arr) > 1 else eff_w
            pad = 5
            draw_h = h - (2 * pad)
            for i, val in enumerate(clean_arr):
                x = x_offset + i * step
                v_clamped = val
                if is_retention:
                    if v_clamped < min_v: v_clamped = min_v
                    if v_clamped > mx: v_clamped = mx
                rng = mx - min_v
                if rng <= 0: rng = 1
                ratio = (v_clamped - min_v) / rng
                if invert: y = pad + (ratio * draw_h)
                else: y = (h - pad) - (ratio * draw_h)
                pts.append(f"{x:.1f},{y:.1f}")
            d = f"M {pts[0]}"
            # smooth can be True (default tension), False (no smoothing), or a float (custom tension)
            if smooth:
                tension = smooth if isinstance(smooth, float) else 0.2
                for i in range(len(pts)-1):
                    p0 = pts[max(0, i - 1)]
                    p1 = pts[i]
                    p2 = pts[i + 1]
                    p3 = pts[min(len(pts) - 1, i + 2)]
                    def pc(s): return [float(v) for v in s.split(',')]
                    c0, c1, c2, c3 = pc(p0), pc(p1), pc(p2), pc(p3)
                    cp1x = c1[0] + (c2[0] - c0[0]) * tension
                    cp1y = c1[1] + (c2[1] - c0[1]) * tension
                    cp2x = c2[0] - (c3[0] - c1[0]) * tension
                    cp2y = c2[1] - (c3[1] - c1[1]) * tension
                    d += f" C {cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {c2[0]:.1f},{c2[1]:.1f}"
            else:
                for pt in pts[1:]:
                    d += f" L {pt}"
            if fill:
                d_fill = d + f" L {x_offset + eff_w:.1f},{h} L {x_offset:.1f},{h} Z"
                stroke_c = line_color or self.cfg['base_color']
                # Generate a unique gradient per fill color so each filled graph
                # uses its own line_color for the shading, not the base theme color.
                import hashlib
                grad_id = "gfill_" + hashlib.md5(stroke_c.encode()).hexdigest()[:8]
                grad_def = (f'<linearGradient id="{grad_id}" x1="0%" y1="0%" x2="0%" y2="100%">'
                            f'<stop offset="0%" style="stop-color:{stroke_c};stop-opacity:0.3" />'
                            f'<stop offset="100%" style="stop-color:{stroke_c};stop-opacity:0" />'
                            f'</linearGradient>')
                return (f'<defs>{grad_def}</defs><path class="hm-fill" d="{d_fill}" fill="url(#{grad_id})" stroke="none" /> '
                        f'<path class="hm-line" pathLength="1" d="{d}" fill="none" stroke="{stroke_c}" stroke-width="2" />')
            color = line_color or "#95a5a6"
            return f'<path class="hm-line" pathLength="1" d="{d}" fill="none" stroke="{color}" stroke-width="2" />'

        svg_layers = ""
        legend_items = []

        if is_extended:
            # ── Extended 60-day view ─────────────────────────────────────────────
            # Reviews fill the left half (x=0→265), forecast the right (x=265→530).
            # Both share the same y-scale so the lines connect smoothly at today.
            x_mid = w / 2.0
            band_hi = [m.get("fut_hi", f) for m, f in zip(fut_meta, raw_fut)]
            shared_max = max(max(raw_rev) if raw_rev else 0, max(raw_fut) if raw_fut else 0,
                             max(band_hi) if self.fsrs_band and band_hi else 0) or 1

            # _rev_plot tracks whichever version of reviews data is actually drawn,
            # so the forecast bridge always starts exactly where the reviews line ends.
            _rev_plot = raw_rev
            if "reviews" in active:
                rev_color = self.cfg.get('graph_reviews_color', '#3498db')
                if self.cfg.get('reviews_rolling_avg', False):
                    window = self.cfg.get('reviews_rolling_avg_period', 7)
                    _rev_plot = [
                        sum(raw_rev[max(0, i - window + 1):i + 1]) / len(raw_rev[max(0, i - window + 1):i + 1])
                        for i in range(len(raw_rev))
                    ]
                    rev_label = f"REVIEWS ({window}d avg)"
                else:
                    rev_label = "REVIEWS"
                svg_layers += get_path(_rev_plot, False, True, line_color=rev_color,
                                       shared_max=shared_max, x_offset=0.0, x_span=x_mid)
                legend_items.append(f'<span style="color:{rev_color}">■ {rev_label}</span>')

            fsrs_active = self.cfg.get('fsrs_simulation_enabled', False) and _get_fsrs_params() is not None
            fut_color = self.cfg.get('fsrs_prediction_color', '#9b59b6') if fsrs_active else self.cfg.get('graph_forecast_color', '#95a5a6')
            smooth_val = 0.08 if fsrs_active else True
            if self.cfg.get('forecast_rolling_avg', False):
                fw = self.cfg.get('forecast_rolling_avg_period', 7)
                fut_draw = [sum(raw_fut[max(0,i-fw+1):i+1])/len(raw_fut[max(0,i-fw+1):i+1]) for i in range(len(raw_fut))]
                fut_base = "FSRS FORECAST" if fsrs_active else "FORECAST"
                fut_label = f"{fut_base} ({fw}d avg)"
            else:
                fut_draw = raw_fut
                fut_label = "FSRS FORECAST" if fsrs_active else "FORECAST"
            # Bridge: use the last plotted reviews value so the forecast begins exactly
            # where the reviews line ends — continuous even when rolling avg is on.
            bridge = _rev_plot[-1] if _rev_plot else 0
            if self.fsrs_band and fsrs_active:
                lo = [m.get("fut_lo", f) for m, f in zip(fut_meta, raw_fut)]
                hi = band_hi
                if self.cfg.get('forecast_rolling_avg', False):
                    lo = [sum(lo[max(0, i-fw+1):i+1]) / len(lo[max(0, i-fw+1):i+1]) for i in range(len(lo))]
                    hi = [sum(hi[max(0, i-fw+1):i+1]) / len(hi[max(0, i-fw+1):i+1]) for i in range(len(hi))]
                svg_layers += self._band_path([bridge] + lo, [bridge] + hi, fut_color, shared_max,
                                              x_mid, w - x_mid, h)
            svg_layers += get_path([bridge] + fut_draw, False, False, line_color=fut_color,
                                    smooth=smooth_val, shared_max=shared_max,
                                    x_offset=x_mid, x_span=w - x_mid)
            legend_items.append(f'<span style="color:{fut_color}">■ {fut_label}</span>')

            if "time_card" in active:
                time_color = self.cfg.get('graph_time_color', '#e67e22')
                if self.cfg.get('time_rolling_avg', False):
                    tw = self.cfg.get('time_rolling_avg_period', 7)
                    time_data = [sum(raw_time[max(0,i-tw+1):i+1])/len(raw_time[max(0,i-tw+1):i+1]) for i in range(len(raw_time))]
                    time_lbl = f"TIME/CARD ({tw}d avg)"
                else:
                    time_data = raw_time
                    time_lbl = "TIME/CARD"
                svg_layers += get_path(time_data, True, False, line_color=time_color,
                                       x_offset=0.0, x_span=x_mid)
                legend_items.append(f'<span style="color:{time_color}">■ {time_lbl}</span>')

            if "time_studied" in active:
                ts_color = self.cfg.get('graph_time_studied_color', '#3498db')
                if self.cfg.get('time_studied_rolling_avg', False):
                    tsw = self.cfg.get('time_studied_rolling_avg_period', 7)
                    ts_data = [sum(raw_time_studied[max(0,i-tsw+1):i+1])/len(raw_time_studied[max(0,i-tsw+1):i+1]) for i in range(len(raw_time_studied))]
                    ts_lbl = f"TIME STUDIED ({tsw}d avg)"
                else:
                    ts_data = raw_time_studied
                    ts_lbl = "TIME STUDIED"
                svg_layers += get_path(ts_data, False, True, line_color=ts_color,
                                       x_offset=0.0, x_span=x_mid)
                legend_items.append(f'<span style="color:{ts_color}">■ {ts_lbl}</span>')

            if "retention" in active:
                ret_color = self.cfg.get('graph_retention_color', '#f1c40f')
                if self.cfg.get('ret_rolling_avg', False):
                    rw = self.cfg.get('ret_rolling_avg_period', 7)
                    ret_data = [sum(raw_ret[max(0,i-rw+1):i+1])/len(raw_ret[max(0,i-rw+1):i+1]) for i in range(len(raw_ret))]
                    ret_lbl = f"RETENTION ({rw}d avg)"
                else:
                    ret_data = raw_ret
                    ret_lbl = "RETENTION"
                svg_layers += get_path(ret_data, False, False, is_retention=True,
                                       line_color=ret_color, x_offset=0.0, x_span=x_mid)
                legend_items.append(f'<span style="color:{ret_color}">■ {ret_lbl}</span>')

            # Subtle "today" centre divider
            svg_layers += (f'<line x1="{x_mid:.1f}" y1="5" x2="{x_mid:.1f}" y2="55"'
                           f' stroke="white" stroke-width="0.5" stroke-opacity="0.25" stroke-dasharray="2,3"/>')
        else:
            # ── Original 30-day historical view ─────────────────────────────────
            if "reviews" in active:
                rev_color = self.cfg.get('graph_reviews_color', '#3498db')
                if self.cfg.get('reviews_rolling_avg', False):
                    window = self.cfg.get('reviews_rolling_avg_period', 7)
                    rev_data = [
                        sum(raw_rev[max(0, i - window + 1):i + 1]) / len(raw_rev[max(0, i - window + 1):i + 1])
                        for i in range(len(raw_rev))
                    ]
                    rev_label = f"REVIEWS ({window}d avg)"
                else:
                    rev_data = raw_rev
                    rev_label = "REVIEWS"
                svg_layers += get_path(rev_data, False, True, line_color=rev_color)
                legend_items.append(f'<span style="color:{rev_color}">■ {rev_label}</span>')
            if "time_card" in active:
                time_color = self.cfg.get('graph_time_color', '#e67e22')
                if self.cfg.get('time_rolling_avg', False):
                    tw = self.cfg.get('time_rolling_avg_period', 7)
                    time_data = [sum(raw_time[max(0,i-tw+1):i+1])/len(raw_time[max(0,i-tw+1):i+1]) for i in range(len(raw_time))]
                    time_lbl = f"TIME/CARD ({tw}d avg)"
                else:
                    time_data = raw_time
                    time_lbl = "TIME/CARD"
                svg_layers += get_path(time_data, True, False, line_color=time_color)
                legend_items.append(f'<span style="color:{time_color}">■ {time_lbl}</span>')
            if "time_studied" in active:
                ts_color = self.cfg.get('graph_time_studied_color', '#3498db')
                if self.cfg.get('time_studied_rolling_avg', False):
                    tsw = self.cfg.get('time_studied_rolling_avg_period', 7)
                    ts_data = [sum(raw_time_studied[max(0,i-tsw+1):i+1])/len(raw_time_studied[max(0,i-tsw+1):i+1]) for i in range(len(raw_time_studied))]
                    ts_lbl = f"TIME STUDIED ({tsw}d avg)"
                else:
                    ts_data = raw_time_studied
                    ts_lbl = "TIME STUDIED"
                svg_layers += get_path(ts_data, False, True, line_color=ts_color)
                legend_items.append(f'<span style="color:{ts_color}">■ {ts_lbl}</span>')
            if "retention" in active:
                ret_color = self.cfg.get('graph_retention_color', '#f1c40f')
                if self.cfg.get('ret_rolling_avg', False):
                    rw = self.cfg.get('ret_rolling_avg_period', 7)
                    ret_data = [sum(raw_ret[max(0,i-rw+1):i+1])/len(raw_ret[max(0,i-rw+1):i+1]) for i in range(len(raw_ret))]
                    ret_lbl = f"RETENTION ({rw}d avg)"
                else:
                    ret_data = raw_ret
                    ret_lbl = "RETENTION"
                svg_layers += get_path(ret_data, False, False, is_retention=True, line_color=ret_color)
                legend_items.append(f'<span style="color:{ret_color}">■ {ret_lbl}</span>')

        return svg_layers, meta_data, " &nbsp;&nbsp; ".join(legend_items), is_extended

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

def interpolate_color(color_start, color_end, ratio):
    ratio = max(0, min(1, ratio))
    r = int(color_start[0] + (color_end[0] - color_start[0]) * ratio)
    g = int(color_start[1] + (color_end[1] - color_start[1]) * ratio)
    b = int(color_start[2] + (color_end[2] - color_start[2]) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"

def blend_colors(c1_hex, c2_hex, ratio):
    r1, g1, b1 = hex_to_rgb(c1_hex)
    r2, g2, b2 = hex_to_rgb(c2_hex)
    r = r1 + (r2 - r1) * ratio
    g = g1 + (g2 - g1) * ratio
    b = b1 + (b2 - b1) * ratio
    return rgb_to_hex((r, g, b))

def _shade_color(hex_color, brightness):
    """Scale hex_color toward black by brightness factor (0.0=black, 1.0=full color)."""
    r, g, b = hex_to_rgb(hex_color)
    brightness = max(0.0, min(1.0, brightness))
    return rgb_to_hex((int(r * brightness), int(g * brightness), int(b * brightness)))

c_bad = (255, 85, 85)    # Red
c_mid = (255, 204, 0)    # Bright Yellow
c_good = (0, 204, 51)    # Green

def get_speed_color(seconds, cfg=None):
    if cfg is None: cfg = get_config()
    best_sec = float(cfg.get('speed_min', 3.0))
    worst_sec = float(cfg.get('speed_max', 15.0))
    if seconds <= best_sec: return rgb_to_hex(c_good)
    if seconds >= worst_sec: return rgb_to_hex(c_bad)
    ratio = (worst_sec - seconds) / (worst_sec - best_sec)
    if ratio < 0.5:
        local_ratio = ratio * 2
        return interpolate_color(c_bad, c_mid, local_ratio)
    else:
        local_ratio = (ratio - 0.5) * 2
        return interpolate_color(c_mid, c_good, local_ratio)

def _focus_color(score, rng):
    """Red → yellow → green across your own usual range of focus scores"""
    lo, hi = rng
    ratio = 0.5 if hi <= lo else max(0.0, min(1.0, (score - lo) / (hi - lo)))
    if ratio < 0.5:
        return interpolate_color(c_bad, c_mid, ratio * 2)
    return interpolate_color(c_mid, c_good, (ratio - 0.5) * 2)

def get_retention_color(percentage, cfg=None):
    if cfg is None: cfg = get_config()
    min_threshold = float(cfg.get('retention_min', 75)) / 100.0
    max_threshold = float(cfg.get('retention_max', 95)) / 100.0
    if percentage <= min_threshold: ratio = 0.0
    elif percentage >= max_threshold: ratio = 1.0
    else: ratio = (percentage - min_threshold) / (max_threshold - min_threshold)
    if ratio < 0.5:
        local_ratio = ratio * 2
        return interpolate_color(c_bad, c_mid, local_ratio)
    else:
        local_ratio = (ratio - 0.5) * 2
        return interpolate_color(c_mid, c_good, local_ratio)

def setup_timer():
    global refresh_timer
    cfg = get_config()
    interval = cfg.get('refresh_interval', 60) * 1000
    if refresh_timer:
        # Called on every deck browser render — keep the existing timer unless
        # the configured interval actually changed.
        try:
            if refresh_timer.interval() == interval:
                return
            refresh_timer.stop()
        except RuntimeError:
            pass
        refresh_timer = None
    refresh_timer = QTimer()
    refresh_timer.timeout.connect(on_refresh_timer)
    refresh_timer.start(interval)

_drawn_key = None      # _refresh_key() when the deck list's heatmap was last drawn


def _refresh_key():
    """What the deck list's heatmap is drawn from: the collection's last change, the
    latest answer, the Anki day and the theme. While it's the same, the minute's refresh
    has nothing new to show."""
    try:
        mod_, last = mw.col.db.first("SELECT (SELECT mod FROM col), (SELECT MAX(id) FROM revlog)")
        return (mod_, last, mw.col.sched.today, _is_dark_mode() or _home_always_dark())
    except Exception:
        return None


def on_refresh_timer():
    with _HomeDark():
        _on_refresh_timer()


def _on_refresh_timer():
    global _drawn_key
    if mw.state == "deckBrowser":
        key = _refresh_key()
        if key is not None and key == _drawn_key:
            return
        try:
            # Same scope as the deck screen, and never the slow parts: if they're
            # missing, warm them and leave the current heatmap up until next time.
            status = {}
            args = _main_heatmap_args(get_config())
            html_body = get_html_body_content(cache_only=QueryOp is not None, status=status, **args)
            if status.get("missing") or status.get("stale"):
                _warm_in_background("deckBrowser", args["deck_ids"], args["retention_deck_ids"], None)
            if status.get("missing"):
                return
            safe_html = json.dumps(html_body)
            js = f"var root = document.getElementById('heatmap-root'); if(root) {{ root.outerHTML = {safe_html}; if(window.initHeatmap) window.initHeatmap(); }}"
            mw.deckBrowser.web.eval(js)
            _drawn_key = key
        except: pass

def _exam_countdown(exam_days, today_str, ahead_days=14):
    """The next exam, once it's ahead_days away or closer: a small calendar page with its
    date, then the name and how many days away it is."""
    today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
    ahead = sorted(d for d in exam_days if today_str <= d)
    if not ahead:
        return ""
    day_s = ahead[0]
    exam_day = datetime.datetime.strptime(day_s, "%Y-%m-%d")
    days = (exam_day.date() - today).days
    if days > ahead_days:
        return ""
    names = " and ".join(_html.escape(e.get("label", "Exam")) for e in exam_days[day_s])
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    page = (f'<div class="hm-cal"><div class="hm-cal-m">{exam_day.strftime("%b").upper()}</div>'
            f'<div class="hm-cal-d">{exam_day.day}</div></div>')
    return f'{page}<b class="hm-exam-n">{names}</b><span class="hm-exam-w">{when}</span>'


_home_facts = {}        # numbers from the last deck-list heatmap, for the notices (render())


def _streak_runs(hist):
    """(day, length of the streak through that day) for each studied day, in order."""
    out, run, prev = [], 0, None
    for d in sorted(k for k, v in hist.items() if v):
        try:
            o = datetime.date.fromisoformat(d).toordinal()
        except ValueError:
            continue
        run = run + 1 if prev is not None and o == prev + 1 else 1
        prev = o
        out.append((d, run))
    return out


def _longest_streak(hist):
    return max((n for _d, n in _streak_runs(hist)), default=0)


def _milestone_days(hist):
    """{day: label} for the days a streak reached 100 days (or a multiple), 365 or 500."""
    return {d: moments.milestone_label(n) for d, n in _streak_runs(hist)
            if moments.milestone(n) in ("100", "500", "year")}
_EXAM_CSS = """
.hm-notes { display: flex; flex-direction: column; align-items: center; gap: 4px; margin: 0 auto 14px; }
.glass-deck-container .hm-notes { margin: 10px auto 2px; }
.hm-note { display: flex; align-items: center; justify-content: center; gap: 7px; font-size: 12.5px; }
.hm-note-ic { display: flex; }
.hm-note-ic.amber { color: #d08a1e; }
.hm-note-ic.flame { color: #e0772e; }
.hm-note-ic.gold { color: #e2b03f; }
.hm-note-ic.gray { opacity: .6; }
.hm-note-ic.blue { color: #3a8ee6; }
.hm-note-ic.green { color: #3bab5a; }
.hm-note-ic.teal { color: #2aa892; }
/* a calendar page: the month on red over a white page with the day in black */
.hm-cal { width: 24px; flex: none; border-radius: 5px; overflow: hidden; background: #fff; text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,.22), 0 0 0 1px rgba(0,0,0,.06); }
.hm-cal-m { background: #e5484d; color: #fff; font-size: 6.5px; font-weight: 700; letter-spacing: .6px; line-height: 9px; }
.hm-cal-d { color: #111; font-size: 12px; font-weight: 700; line-height: 15px; }
.hm-exam-n { font-size: 12.5px; font-weight: 600; color: var(--txt); }
.hm-exam-w { font-size: 12px; color: var(--sub); }
/* With the Today pill: one pill that rolls between the finish time and the exam */
.hm-car { display: flex; flex-direction: column; align-items: center; }
.hm-car-win { position: relative; height: 32px; overflow: hidden; }
/* Each side stays on its own layer, resting at blur(0) rather than none: otherwise the
   browser moves it onto a layer as a slide starts and back off as it ends, and its text
   is drawn differently on and off a layer, so it flashes as it arrives and dims as it settles. */
.hm-car-s { position: absolute; left: 0; right: 0; top: 3px; display: flex; justify-content: center;
  transform: translateY(0); opacity: 1; filter: blur(0);
  will-change: transform, opacity, filter; backface-visibility: hidden;
  transition: transform .55s cubic-bezier(.3,.7,.3,1), opacity .55s ease, filter .55s ease; }
.hm-car-s.below { transform: translateY(100%); opacity: 0; filter: blur(2px); }
.hm-car-s.above { transform: translateY(-100%); opacity: 0; filter: blur(2px); }
.hm-car.still .hm-car-s { transition: none; }
.hm-car-dots { display: flex; gap: 4px; margin-top: 1px; }
.hm-car-dots i { width: 4px; height: 4px; border-radius: 50%; background: currentColor; opacity: .2; transition: opacity .3s; }
.hm-car-dots i.on { opacity: .55; }
.hm-note-pill > span { display: flex; align-items: center; gap: 7px; }
.hm-note-pill .hm-cal, .hm-note .hm-cal { width: 18px; border-radius: 3.5px; }
.hm-note-pill .hm-cal-m, .hm-note .hm-cal-m { font-size: 5px; letter-spacing: .4px; line-height: 6.5px; }
.hm-note-pill .hm-cal-d, .hm-note .hm-cal-d { font-size: 9.5px; line-height: 11.5px; }
.hm-note-pill .hm-exam-w, .hm-note-w { font-weight: 500; opacity: .6; }
.hm-note-pill .hm-exam-n { font-size: inherit; }
"""


def _fmt_mins(ms):
    m = ms / 60000
    if m >= 60:
        return f"{int(m // 60)}h {int(m % 60)}m"
    return f"{int(m)}m" if m >= 1 else "<1m"


def _rgb(hex_color):
    h = str(hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return None


def _rgba(hex_color, alpha, fallback="rgba(255,255,255,0.12)"):
    rgb = _rgb(hex_color)
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha})" if rgb else fallback


def _toward_white(hex_color, t):
    """The color moved a share t of the way to white, for lighter tints on the dark tooltip."""
    rgb = _rgb(hex_color)
    if not rgb:
        return f"rgba(255,255,255,{1 - 0.6 * t:.2f})"
    return "#%02x%02x%02x" % tuple(round(c + (255 - c) * t) for c in rgb)


# Review / learn / relearn segments: the heatmap color, then lighter tints of it.
_KIND_TINTS = ((0.0, "review"), (0.45, "learn"), (0.78, "relearn"))


# A small four-point star, for a milestone day's line in its tooltip
_STAR_SVG = ('<svg viewBox="0 0 10 10" width="1em" height="1em" style="display:inline-block;vertical-align:-0.12em">'
             '<path d="M5 0.8 L6.1 3.9 L9.2 5 L6.1 6.1 L5 9.2 L3.9 6.1 L0.8 5 L3.9 3.9 Z" fill="currentColor"/></svg>')


# The icons a day's tooltip can hold, as short marks in the page: every cell carries its
# tooltip, and the same few icons made up about a third of the deck list's page.
_TIP_ICONS = {"up": icon("up", "1em", 2.2), "down": icon("down", "1em", 2.2), "flag": icon("flag"),
              "star": _STAR_SVG}


def _tip_attr(tip: str) -> str:
    """A tooltip as a data-tooltip value: its icons as ⟦name⟧ marks (the page puts them
    back on hover), and escaped only as much as a quoted attribute needs (& and ")."""
    for k, v in _TIP_ICONS.items():
        if v in tip:
            tip = tip.replace(v, f"\u27e6{k}\u27e7")
    return tip.replace("&", "&amp;").replace('"', "&quot;")


def _day_tip(day, count, ms, spd, new, ret, focus, fut, band, is_today, avg, kinds, color, note, exams, mile=None):
    """A heatmap day's tooltip: the date and time spent, reviews with a chip against your
    average, a bar split into review / learn / relearn, retention, focus, speed and new
    cards, then the forecast, your note and exams."""
    esc = _html.escape
    head = f"{day.strftime('%a, %b')} {day.day}"
    out = [f'<div class="tt-h"><b>{head}</b>' + (f'<span>{_fmt_mins(ms)}</span>' if ms else "") + "</div>"]
    if count:
        vs = ""
        if avg:
            d = round(100 * (count - avg) / avg)
            if abs(d) >= 5:
                up = d > 0
                bg = _rgba(color, 0.3) if up else "rgba(255,255,255,0.1)"
                vs = (f'<span class="tt-chip{"" if up else " tt-low"}" style="background:{bg}">'
                      f'{icon("up" if up else "down", "1em", 2.2)}{abs(d)}% {"above" if up else "below"} avg</span>')
        out.append(f'<div class="tt-r"><span>{count:,} reviews</span>{vs}</div>')
        parts = [(n, _toward_white(color, t), label) for n, (t, label) in zip(kinds or (), _KIND_TINTS) if n > 0]
        if len(parts) > 1:
            out.append('<div class="tt-split">' + "".join(
                f'<i style="flex:{n};background:{c}"></i>' for n, c, _ in parts) + "</div>")
            out.append('<div class="tt-key">' + "".join(
                f'<span><i style="background:{c}"></i>{n:,} {label}</span>' for n, c, label in parts) + "</div>")
        cells = [f"Retention {ret:.0f}%" if ret is not None else None,
                 f"Focus {round(100 * focus)}%" if focus is not None else None,
                 f"{spd} s a card" if spd else None,
                 f"{new} new" if new else None]
        cells = [c for c in cells if c]
        out.append('<div class="tt-g">' + "".join(f"<span>{c}</span>" for c in cells) + "</div>")
    elif not fut:
        out.append('<div class="tt-m">No reviews</div>')
    if fut:
        rng = f" ({band[0]}–{band[1]})" if band else ""
        out.append(f'<div class="tt-r tt-m"><span>{fut:,} {"left" if is_today else "forecast"}{rng}</span></div>')
    if mile:
        out.append(f'<div class="tt-ex"><span style="color:#e2b03f">{_STAR_SVG}</span>{esc(mile)}</div>')
    if note:
        out.append(f'<div class="tt-note">{esc(note)}</div>')
    for ex in exams:
        out.append(f'<div class="tt-ex"><span style="color:{esc(ex.get("color", "#e74c3c"))}">{icon("flag")}</span>'
                   f'{esc(ex.get("label", "Exam"))}</div>')
    return "".join(out)


def _cell_shape(cfg):
    """'square' | 'rounded' | 'circle'. Configs from before the Cell Shape setting
    only have border_radius, so infer the shape from it (circle once the radius
    reaches half the cell) and nobody's heatmap changes on update."""
    shape = cfg.get("cell_shape")
    if shape in ("square", "rounded", "circle"):
        return shape
    r, size = cfg.get("border_radius", 2), cfg.get("cell_size", 10)
    if r * 2 >= size:
        return "circle"
    return "square" if r <= 0 else "rounded"


def _cell_radius_css(cfg):
    # Percentages of the cell, so each shape looks the same at any cell size.
    # Square keeps a slight softening; rounded sits between it and the circle.
    return {"square": "12%", "rounded": "30%", "circle": "50%"}[_cell_shape(cfg)]


def _weeks_ahead(cfg) -> int:
    """Empty weeks after this one when the heatmap opens (0-52). Before 1.9.5 the setting
    was weeks of history in a one-year window; that's carried over."""
    v = cfg.get("weeks_ahead")
    try:
        v = int(v) if v is not None else 52 - int(cfg.get("weeks_back", 26))
    except (TypeError, ValueError):
        v = 26
    return max(0, min(52, v))


_OLDER = {}             # page token -> how that heatmap draws its older weeks
_older_seq = 0
OLDER_WEEKS = 26        # weeks per load when scrolling back


def _older_register(start, end, hist, cells, labels, cell_w) -> str:
    """Remember how this heatmap draws its cells, for the older weeks it loads as you
    scroll back. The page's token, or "" when there's no older history."""
    global _older_seq
    days = [d for d, v in hist.items() if v]
    if not days:
        return ""
    try:
        first = date.fromisoformat(min(days))
    except ValueError:
        return ""
    first -= timedelta(days=(first.weekday() + 1) % 7)       # its Sunday
    if first >= start:
        return ""
    _older_seq += 1
    tok = str(_older_seq)
    _OLDER[tok] = {"start": start, "end": end, "first": first, "cells": cells,
                   "labels": labels, "cell_w": cell_w}
    for old in list(_OLDER)[:-4]:
        _OLDER.pop(old, None)
    return tok


def _older_weeks(tok: str, web) -> None:
    """The next OLDER_WEEKS weeks before what the heatmap shows, added to its left."""
    o = _OLDER.get(tok)
    if not o or web is None:
        return
    start = max(o["first"], o["start"] - timedelta(weeks=OLDER_WEEKS))
    cells = o["cells"](start, o["start"] - timedelta(days=1)) if start < o["start"] else ""
    o["start"] = start
    labels, width = o["labels"](start, o["end"])
    web.eval("window.hmOlder && hmOlder(%s, %s, %d, %s);" % (
        json.dumps(cells), json.dumps(labels), width,
        "true" if start <= o["first"] else "false"))


@functools.lru_cache(maxsize=4096)
def _rgba_css(hex_color, alpha: str) -> str:
    """'#rrggbb' at this opacity as rgba(); the same few colors come up for every cell."""
    try:
        h_clean = hex_color.lstrip('#')
        r, g, b = tuple(int(h_clean[i:i+2], 16) for i in (0, 2, 4))
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return hex_color


# Order of the per-view colors in each heatmap cell's data-bgs attribute.
HEATMAP_MODES = ('volume', 'retention', 'score', 'time', 'new_cards', 'focus')

def get_html_body_content(deck_ids=None, is_overview=False, retention_deck_ids=None,
                          cache_only=False, status=None):
    """Heatmap HTML. With cache_only, skips the slow parts (see FastEngine) and
    fills status with 'missing' / 'stale' so the caller can compute them later."""
    cfg = get_config()
    eng = FastEngine(cache_only=cache_only)
    
    active_graphs = cfg.get("active_graphs_v14", [])
    show_graph = cfg.get("show_graph", True)
    
    try: opacity = float(cfg.get("glass_opacity", 0.4))
    except: opacity = 0.4
        
    monochrome = cfg.get("monochrome_text", False)
    enable_shadows = cfg.get("enable_shadows", True)
    
    modern_theme = cfg.get("modern_deck_theme", True)
    enable_glass_bg = cfg.get("enable_deck_glass", True)
    show_ratio = cfg.get("show_deck_ratio", True)

    # Pill colors
    pill_new = cfg.get("pill_new_color", "#4a90e2")
    pill_learn = cfg.get("pill_learn_color", "#e74c3c")
    pill_due = cfg.get("pill_due_color", "#f1c40f")
    filtered_color = cfg.get("filtered_deck_color", "#20b2aa")

    # Deck list width
    deck_width = cfg.get("deck_list_width", 60)

    enable_glass = cfg.get("enable_glass", True)

    notes = cfg.get('daily_notes', {})
    base_c = cfg.get('base_color', "#8e44ad") 
    
    # Normalize exam data to list format per day
    raw_exams = cfg.get("exam_days", {})
    exam_days = {}
    if isinstance(raw_exams, list):
        # Very old format: list of date strings
        for ex_date in raw_exams:
            exam_days[ex_date] = [{"label": "Exam", "color": "#e74c3c"}]
    else:
        for ex_date, ex_data in raw_exams.items():
            if isinstance(ex_data, list):
                exam_days[ex_date] = ex_data
            else:
                # Old format: single dict per day
                exam_days[ex_date] = [ex_data]

    hist, time_hist, time_revs_hist, new_cards_hist, retention, forecast, today_revs, today_rate, avg_time, total_mins, cards_due, daily_avg, streak, pct_week, pct_month, today_str, start_dt, deck_stats, avg_period = eng.get_data(deck_ids=deck_ids, retention_deck_ids=retention_deck_ids)
    
    deck_stats_json = json.dumps(deck_stats)
    if status is not None:
        status.update(missing=eng.missing, stale=eng.stale)
    exam_inner = (_exam_countdown(exam_days, today_str, int(cfg.get('exam_countdown_days', 14) or 14))
                  if cfg.get('exam_countdown', True) and not is_overview else "")
    hud_class = "hud hm-loading" if eng.missing else "hud"
    # Elemental's logo: its dots orbit while the history loads (shown only if that takes a
    # moment), and it sits over the grid of a profile with no reviews yet
    _bnight = _is_dark_mode()
    loadmark_html = ""
    if eng.missing:
        _still = brand.still_js(lowpower.motion(cfg))
        loadmark_html = (
            f'<div class="hm-loadmark" id="hm-loadmark">{brand.svg(base_c, _bnight, 16)}'
            f'<span>Loading your history</span></div>'
            f'<script>{brand.SCRIPT}(function(){{var m=document.getElementById("hm-loadmark");'
            f'if(!m)return;var still={_still};'
            f'setTimeout(function(){{m.classList.add("on")}},still?0:400);'
            f'window.hmLogo(m.querySelector("svg"),true,still);}})();</script>')
    try:
        _no_reviews = not eng.missing and not any(hist.values()) and not int(today_revs or 0)
    except (TypeError, ValueError):
        _no_reviews = False
    empty_html = (f'<div class="hm-empty">{brand.svg(base_c, _bnight, 34)}'
                  f'<div>Do a review and your first square lights up.</div></div>') if _no_reviews else ""
    
    svg_paths, meta_data, legend_html, is_extended_forecast = eng.get_graph_points(hist, time_hist, time_revs_hist, retention, forecast, today_str)

    # Inject exam info and ensure exams field exists on historical entries
    _meta_today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
    for _mi, _me in enumerate(meta_data):
        if is_extended_forecast:
            _md = _meta_today - timedelta(days=(29 - _mi)) if _mi < 30 else _meta_today + timedelta(days=(_mi - 29))
        else:
            _md = _meta_today - timedelta(days=(29 - _mi))
        _ex_list = exam_days.get(_md.strftime("%Y-%m-%d"), [])
        _me.setdefault('rev_avg', 0)
        _me['exams'] = [{'label': _ex.get('label', 'Exam'), 'color': _ex.get('color', '#e74c3c')} for _ex in _ex_list]

    # Overlay exam markers on the graph SVG (viewBox 530x60, data area y=5..55, bottom strip y=55..60)
    _svg_w = 530
    _today_dt = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()

    if is_extended_forecast:
        # 60-point window: positions 0-29 = past 30 days, positions 30-59 = future 30 days
        _total_pts = 60
        _step = _svg_w / (_total_pts - 1)
        _exam_pts = []
        for _i in range(30):
            _d = _today_dt - timedelta(days=(29 - _i))
            _d_s = _d.strftime("%Y-%m-%d")
            if _d_s in exam_days:
                _ex = exam_days[_d_s]
                _color = _ex[0].get("color", "#e74c3c") if _ex else "#e74c3c"
                _exam_pts.append((_i, _color))
        for _j in range(1, 31):
            _d = _today_dt + timedelta(days=_j)
            _d_s = _d.strftime("%Y-%m-%d")
            if _d_s in exam_days:
                _ex = exam_days[_d_s]
                _color = _ex[0].get("color", "#e74c3c") if _ex else "#e74c3c"
                _exam_pts.append((29 + _j, _color))
    else:
        # 30-point window: positions 0-29 = past 30 days
        _total_pts = 30
        _step = _svg_w / (_total_pts - 1)
        _exam_pts = []
        for _i in range(30):
            _d = _today_dt - timedelta(days=(29 - _i))
            _d_s = _d.strftime("%Y-%m-%d")
            if _d_s in exam_days:
                _ex = exam_days[_d_s]
                _color = _ex[0].get("color", "#e74c3c") if _ex else "#e74c3c"
                _exam_pts.append((_i, _color))

    _exam_groups = []
    if _exam_pts:
        _grp = [_exam_pts[0]]
        for _pt in _exam_pts[1:]:
            if _pt[0] == _grp[-1][0] + 1:
                _grp.append(_pt)
            else:
                _exam_groups.append(_grp)
                _grp = [_pt]
        _exam_groups.append(_grp)

    _exam_svg = ""
    for _grp in _exam_groups:
        _color = _grp[0][1]
        if len(_grp) == 1:
            # Single exam: tall vertical band + thin bottom accent line + circle "!" badge.
            # ViewBox is 0 0 530 66. Graph data area y=5..55, badge area y=55..66.
            _x = _grp[0][0] * _step
            _band_w = 10
            _bx = max(0.0, _x - _band_w / 2)
            _exam_svg += (
                # Tall semi-transparent band covering the graph area (y=1..53)
                f'<rect x="{_bx:.1f}" y="1" width="{_band_w}" height="52"'
                f' fill="{_color}" fill-opacity="0.18" rx="3"'
                f' stroke="white" stroke-width="0.5" stroke-opacity="0.15"/>'
                # Circle badge: cy=59.5, r=3.5 → top y=56, bottom y=63 — fits in viewBox 66
                f'<circle cx="{_x:.1f}" cy="59.5" r="3.5"'
                f' fill="{_color}" fill-opacity="0.7"'
                f' stroke="white" stroke-width="0.8" stroke-opacity="0.8"/>'
                f'<text x="{_x:.1f}" y="61.6" text-anchor="middle"'
                f' font-size="5.5" font-weight="bold" fill="white" fill-opacity="0.95">!</text>'
            )
        else:
            # Consecutive block: tall band + circle "!" at center.
            _x1 = _grp[0][0] * _step
            _x2 = _grp[-1][0] * _step
            _bx1 = max(0.0, _x1 - _step * 0.4)
            _bx2 = min(float(_svg_w), _x2 + _step * 0.4)
            _bw = _bx2 - _bx1
            _cx = (_bx1 + _bx2) / 2
            _exam_svg += (
                # Tall semi-transparent band covering the graph area (y=1..53)
                f'<rect x="{_bx1:.1f}" y="1" width="{_bw:.1f}" height="52"'
                f' fill="{_color}" fill-opacity="0.15" rx="3"'
                f' stroke="white" stroke-width="0.5" stroke-opacity="0.15"/>'
                # Circle badge: cy=59.5, r=3.5 → top y=56, bottom y=63 — fits in viewBox 66
                f'<circle cx="{_cx:.1f}" cy="59.5" r="3.5"'
                f' fill="{_color}" fill-opacity="0.7"'
                f' stroke="white" stroke-width="0.8" stroke-opacity="0.8"/>'
                f'<text x="{_cx:.1f}" y="61.6" text-anchor="middle"'
                f' font-size="5.5" font-weight="bold" fill="white" fill-opacity="0.95">!</text>'
            )

    if cfg.get('show_exam_markers', True):
        svg_paths += _exam_svg

    # Total window is always 365 days from start; snap end to the Saturday of that week
    raw_end_dt = start_dt + timedelta(days=364)
    days_to_sat = (5 - raw_end_dt.weekday()) % 7
    end_dt = raw_end_dt + timedelta(days=days_to_sat)

    cell_w = cfg['cell_size'] + cfg['cell_gap']
    total_days = (end_dt - start_dt).days + 1
    num_weeks = (total_days // 7)
    total_width_px = num_weeks * cell_w
    
    sep_months = bool(cfg.get("separate_months", False))
    month_gap = max(4, round(cfg['cell_size'] * 0.6))     # between months, with separate_months

    def _month_name(day):
        name = day.strftime("%b").upper()
        return name + day.strftime(" ’%y") if day.month == 1 else name    # JAN ’26: years apart once you scroll back

    def _month_labels(a, b):
        """Month labels for the weeks from a (a Sunday) to b, and the grid's width. With
        separate months, the week a month starts in is split in two columns, plus a gap
        (as _cells_between lays it out), and each name is centered over its month."""
        month_html = ""
        temp_curr = a
        col_idx = 0
        x = 0
        last_label_end_pos = -50
        blocks = []         # separate months: [name, left, right] of each month's block

        while temp_curr <= b:
            m_label = ""
            left_pos = x
            for d in range(7):
                check_day = temp_curr + timedelta(days=d)
                if check_day.day == 1:
                    m_label = _month_name(check_day)
                    if sep_months:
                        if d:       # the old month keeps this column
                            if blocks:
                                blocks[-1][2] = x + cfg['cell_size']
                            x += cell_w
                        left_pos = x + month_gap
                        x = left_pos        # the next week's column comes right after this one
                        blocks.append([m_label, left_pos, left_pos + cfg['cell_size']])
                    break
            if sep_months:
                if not blocks:      # the first block: whatever month the grid starts in
                    blocks.append([_month_name(temp_curr), x, x])
                blocks[-1][2] = x + cfg['cell_size']
            else:
                if not m_label and col_idx == 0:
                    m_label = _month_name(temp_curr)
                if m_label and left_pos > last_label_end_pos + 10:
                    month_html += f'<div style="position:absolute; left:{left_pos}px;">{m_label}</div>'
                    last_label_end_pos = left_pos + (38 if "’" in m_label else 25)
            temp_curr += timedelta(days=7)
            col_idx += 1
            x += cell_w

        for name, lo, hi in blocks:
            w = len(name) * 6 + 2               # about how wide the name is (9px bold)
            if hi - lo >= w:
                left = round((lo + hi - w) / 2)
            elif lo + w <= x:                   # a month only partly shown: from its left edge
                left = lo
            else:
                continue
            if left > last_label_end_pos + 6:
                month_html += (f'<div style="position:absolute; left:{left}px; width:{w}px; '
                               f'text-align:center; white-space:nowrap;">{name}</div>')
                last_label_end_pos = left + w
        return month_html, x

    month_html, total_width_px = _month_labels(start_dt, end_dt)

    _custom_max = int(cfg.get('color_scale_max', 0))
    max_rev = _custom_max if _custom_max > 0 else (max(hist.values()) if hist else 1)
    max_score = 1
    for d_key, r_data in retention.items():
        if r_data[0] > max_score: max_score = r_data[0]

    curr_mode = cfg.get('display_mode', 'volume')
    # FOCUS view: each day's focus score (Time Left's model; all decks). Without
    # Time Left there's no score, so the view is hidden and falls back to volume.
    focus_days, focus_range = {}, (0.6, 0.85)
    if cfg.get("show_mode_focus", True):
        try:
            got = time_left.lock_days() if time_left.enabled() else None
            if got:
                focus_days, focus_range = got
        except Exception:
            pass
    if curr_mode == 'focus' and not focus_days:
        curr_mode = 'volume'
    # Every view's color is computed for every cell and stored on it (data-bgs,
    # in HEATMAP_MODES order), so switching views is a recolor in the page.
    intensity_curve = cfg.get('cell_intensity_curve', 0.7)
    gradient_mode = cfg.get('color_gradient_mode', 'opacity')
    dark_factor = max(0.0, min(1.0, cfg.get('shade_dark_factor', 0.15)))
    min_opacity = cfg.get('cell_min_opacity', 0.05)

    glow_night = _is_dark_mode()
    glow_contrast = cfg.get('glow_contrast', themes.GLOW_CONTRAST)
    glow_rank = {}
    if gradient_mode == 'glow':
        # Rank against the days on the heatmap only: the history goes back further,
        # and older, lighter years would push every day shown up into the top shades.
        lo_s = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, "strftime") else str(start_dt)

        def shown(h):
            return [v for d, v in h.items() if lo_s <= d <= today_str]
        glow_rank = {'volume': themes.glow_ranker(shown(hist)),
                     'time': themes.glow_ranker(shown(time_hist)),
                     'new_cards': themes.glow_ranker(shown(new_cards_hist))}

    def scaled_fill(color, ratio, view=None, value=0):
        """(hex, alpha) for a single-color gradient at ratio 0..1. Glow places the
        value by rank among that view's days instead (see themes.glow)."""
        if gradient_mode == 'glow' and view in glow_rank:
            return themes.glow(color, glow_rank[view](value), glow_night, glow_contrast), 1.0
        scaled = ratio ** intensity_curve
        if gradient_mode in ('shade', 'shade_inverted'):
            if gradient_mode == 'shade':
                brightness = dark_factor + (1.0 - dark_factor) * scaled
            else:
                brightness = 1.0 - (1.0 - dark_factor) * scaled
            return _shade_color(color, brightness), 1.0
        return color, max(min_opacity, scaled)

    # Forecast days: shaded by predicted cards in their own color, on the same scale as
    # past days (glow: placed among the days shown). Off: one flat forecast color.
    shade_fc = bool(cfg.get('forecast_shading', False))
    shade_c = cfg.get('forecast_shade_color') or DEFAULT_CONFIG['forecast_shade_color']

    # Before the history has loaded (the first draw), scale against the forecast itself.
    has_hist = any(v > 0 for v in hist.values())
    fc_max = max_rev if has_hist else max(list(forecast.values()) + [1])

    def forecast_fill(f):
        if not shade_fc:
            return cfg['forecast_color'], 0.5
        if gradient_mode == 'glow':
            t = glow_rank['volume'](f) if has_hist and 'volume' in glow_rank else min(1.0, f / fc_max)
            return themes.glow(shade_c, t, glow_night, glow_contrast), 1.0
        return scaled_fill(shade_c, min(1.0, f / max(fc_max, 1)))

    # Pre-compute scale ceilings for the two custom solid-color modes
    _time_max_cfg = int(cfg.get('color_scale_max_time', 0))
    _nc_max_cfg   = int(cfg.get('color_scale_max_newcards', 0))
    max_time_mins = _time_max_cfg if _time_max_cfg > 0 else (
        max((v / 1000 / 60) for v in time_hist.values()) if time_hist else 1)
    max_nc = _nc_max_cfg if _nc_max_cfg > 0 else (
        max(new_cards_hist.values()) if new_cards_hist else 1)
    # Colors for custom modes
    time_cell_color = cfg.get('custom_time_color', '#e67e22')
    nc_cell_color   = cfg.get('custom_newcards_color', '#27ae60')

    # Days a streak reached 100 (or a multiple), a year or 500: a line in that day's tooltip
    try:
        mile_days = _milestone_days(hist)
    except Exception:
        mile_days = {}

    def _cells_between(a, b):
        """The grid's cells for the days from a to b."""
        curr, cells_html = a, ""
        m1_until = None
        while curr <= b:
            d_s = curr.strftime("%Y-%m-%d")
            m1 = ""
            if sep_months:
                # a month starts: blanks finish this week's column and start the next one at
                # the 1st's weekday; that column (class m1) sits after the gap
                wd = (curr.weekday() + 1) % 7
                if curr.day == 1:
                    if wd:
                        cells_html += '<div class="hm-pad"></div>' * (7 - wd) + '<div class="hm-pad m1"></div>' * wd
                    m1_until = curr + timedelta(days=6 - wd)
                if m1_until is not None and curr <= m1_until:
                    m1 = " m1"
            mile = mile_days.get(d_s)
            d_nice = curr.strftime("%b %d").upper()
            count = hist.get(d_s, 0)
            is_today = (d_s == today_str)
            is_fut = curr > _today_dt
            exam_list = exam_days.get(d_s, [])
            is_exam = len(exam_list) > 0

            bg_hex = cfg['empty_color']

            alpha = 0.2 if enable_glass else 0.4

            border = "1px solid transparent"
            outline = "none"
            inner_content = ""

            t_val  = time_hist.get(d_s, 0)
            t_rev  = time_revs_hist.get(d_s, count)  # idle-filtered count for time/card
            nc_val = new_cards_hist.get(d_s, 0)
            spd = round((t_val/t_rev)/1000, 1) if t_rev > 0 else 0
            ret_data = retention.get(d_s, [0, 0])
            correct_count = ret_data[0]
            ret_pct = round((ret_data[0]/ret_data[1])*100, 1) if ret_data[1] > 0 else 0.0
            f_val = forecast.get(d_s, 0)

            if t_rev > 0: daily_score = (t_val / t_rev) / 1000
            else: daily_score = 0

            info_str = _day_tip(curr, count, t_val, spd, nc_val, ret_pct if ret_data[1] else None,
                                focus_days[d_s][0] if d_s in focus_days else None, f_val,
                                eng.fsrs_band.get(d_s), d_s == today_str, daily_avg, eng.kinds.get(d_s), base_c,
                                notes.get(d_s, "").strip(), exam_list, mile)

            is_future_exam = is_exam and (is_fut or is_today)

            if is_future_exam:
                # Use first exam's color for cell background
                ex_color = exam_list[0].get("color", "#e74c3c")
                bg_hex = ex_color
                alpha = 1.0
                inner_content = "<div style='display:flex;justify-content:center;align-items:center;height:100%;font-size:8px;color:#fff;font-weight:bold;'>!</div>"

            rev_c = cfg.get('graph_reviews_color', '#3498db')
            time_c = cfg.get('graph_time_color', '#e67e22')
            ret_c = cfg.get('graph_retention_color', '#f1c40f')
            fut_c = cfg.get('graph_forecast_color', '#95a5a6')
            legend_info = f"{d_nice} &nbsp;&nbsp; <span style='color:{rev_c}'>{count} REV</span>"
            if count > 0:
                legend_info += f" &nbsp;&nbsp; <span style='color:{time_c}'>{spd} S/C</span>"
                legend_info += f" &nbsp;&nbsp; <span style='color:{ret_c}'>{ret_pct}% RET</span>"
            if f_val > 0:
                legend_info += f" &nbsp;&nbsp; <span style='color:{fut_c}'>{f_val} FUT</span>"
            for ex in exam_list:
                ex_label = ex.get("label", "Exam")
                ex_color = ex.get("color", "#e74c3c")
                legend_info += f" &nbsp;&nbsp; <span style='color:{ex_color}'>{icon('flag')} {ex_label.upper()}</span>"

            safe_legend = legend_info.replace("'", "&#39;").replace('"', "&quot;")
            safe_tooltip = _tip_attr(info_str)

            # Shaded by cards due in Volume; the other views keep the flat forecast color.
            fc_flat = (cfg['forecast_color'], 0.5) if is_fut and f_val > 0 else None
            fc_fill = forecast_fill(f_val) if fc_flat else None

            def mode_bg(mode):
                """This cell's background (CSS color) in one heatmap view"""
                m_hex, m_alpha = bg_hex, alpha
                if mode == 'focus':
                    if not is_future_exam and d_s in focus_days:
                        m_hex, m_alpha = _focus_color(focus_days[d_s][0], focus_range), 1.0
                    elif not is_future_exam and fc_flat:
                        m_hex, m_alpha = fc_flat
                elif not is_future_exam:
                    if count > 0 or (mode == 'time' and t_val > 0) or (mode == 'new_cards' and nc_val > 0):
                        if mode == 'retention':
                            rate = (correct_count / ret_data[1]) if ret_data[1] > 0 else 0
                            m_hex, m_alpha = get_retention_color(rate, cfg), 1.0
                        elif mode == 'score':
                            real_sec = (t_val / count) / 1000 if count > 0 else 0
                            m_hex, m_alpha = get_speed_color(real_sec, cfg), 1.0
                        elif mode == 'time':
                            # Solid-color gradient scaled by minutes studied
                            time_mins = t_val / 1000 / 60
                            m_hex, m_alpha = scaled_fill(time_cell_color, min(1.0, time_mins / max(max_time_mins, 1)), 'time', t_val)
                        elif mode == 'new_cards':
                            # Solid-color gradient scaled by new cards done
                            m_hex, m_alpha = scaled_fill(nc_cell_color, min(1.0, nc_val / max(max_nc, 1)), 'new_cards', nc_val)
                        else:
                            m_hex, m_alpha = scaled_fill(base_c, count / max_rev, 'volume', count)
                    elif fc_flat:
                        m_hex, m_alpha = fc_fill if mode == 'volume' else fc_flat
                if is_today and count == 0 and f_val == 0 and not is_exam:
                    return "transparent"
                return _rgba_css(m_hex, f"{m_alpha:.2f}")

            mode_bgs = [mode_bg(m) for m in HEATMAP_MODES]
            bgs_attr = ";".join(mode_bgs)
            rgba_bg = mode_bgs[HEATMAP_MODES.index(curr_mode)] if curr_mode in HEATMAP_MODES else mode_bgs[0]

            if is_today:
                today_c = cfg.get('today_color', '#2ecc71')
                outline = f"2px solid {today_c}"

            today_id = ' id="hm-today"' if is_today else ''
            cells_html += f'<div{today_id} class="cell tooltip-target{m1}" style="background:{rgba_bg}; opacity:1.0; border:{border}; outline:{outline}; outline-offset:-1px;" onclick="pycmd((event.ctrlKey || event.metaKey ? \'heatmap:browse:\' : \'heatmap:note:\') + \'{d_s}\')" data-tooltip="{safe_tooltip}" data-legend="{safe_legend}" data-bgs="{bgs_attr}">{inner_content}</div>'
            curr += timedelta(days=1)
        return cells_html

    cells_html = _cells_between(start_dt, end_dt)
    older_token = _older_register(start_dt, end_dt, hist, _cells_between, _month_labels, cell_w)

    if total_mins >= 60:
        display_time = f"{total_mins/60:.1f}"
        time_unit = "h"
    else:
        display_time = str(total_mins)
        time_unit = "m"

    workload = today_revs + cards_due
    ratio = today_revs / max(1, workload)
    
    if monochrome:
        c_today = "var(--txt)"
        c_time = "var(--txt)"
        c_qual = "var(--txt)"
        base_text_color = "var(--txt)"
    else:
        c_today = "#2ecc71" if ratio >= 0.8 else ("#f1c40f" if ratio >= 0.5 else "#e74c3c")
        c_time = get_speed_color(avg_time)
        c_qual = get_retention_color(today_rate / 100.0)
        base_text_color = base_c

    # Streak / percentage toggle
    streak_mode = cfg.get("streak_display", "streak")
    if streak_mode == "pct_week":
        streak_val = f"{pct_week}<span style=\"font-size:10px\">%</span>"
        streak_label = "7D ACT"
    elif streak_mode == "pct_month":
        streak_val = f"{pct_month}<span style=\"font-size:10px\">%</span>"
        streak_label = "30D ACT"
    else:
        streak_val = str(streak)
        streak_label = "STREAK"

    # Stats bar visibility
    stats_bar_display = "" if cfg.get("show_stats_bar", True) else "display:none"

    meta_json = json.dumps(meta_data)

    vol_class  = "active" if curr_mode == "volume"     else ""
    ret_class  = "active" if curr_mode == "retention"  else ""
    scr_class  = "active" if curr_mode == "score"      else ""
    time_class = "active" if curr_mode == "time"       else ""
    nc_class   = "active" if curr_mode == "new_cards"  else ""
    focus_class = "active" if curr_mode == "focus"     else ""
    show_time_btn = cfg.get("show_mode_time",     True)
    show_nc_btn   = cfg.get("show_mode_newcards", True)
    time_btn_html = f'<div class="toggle-opt {time_class}" data-mode="time" onclick="hmSetMode(\'time\')">TIME</div>' \
                    if show_time_btn else ""
    nc_btn_html   = f'<div class="toggle-opt {nc_class}" data-mode="new_cards" onclick="hmSetMode(\'new_cards\')">NEW</div>' \
                    if show_nc_btn else ""
    focus_btn_html = f'<div class="toggle-opt {focus_class}" data-mode="focus" onclick="hmSetMode(\'focus\')">FOCUS</div>' \
                    if focus_days else ""
    stats_link_html = ('<div class="stats-link" onclick="pycmd(\'heatmap:stats\')" title="Your stats over weeks and months"'
                       ' onmouseenter="window.hmLogoTurn&&hmLogoTurn(this.querySelector(\'svg\'),' + _html.escape(brand.still_js(lowpower.motion(cfg))) + ')">'
                       + brand.svg(base_c, _bnight, 12, 'hm-stats-logo') + 'STATS</div>'
                       + '<script>' + brand.TURN_SCRIPT + '</script>'
                       if stats_view.available() else "")
    graph_display_style = "display: block;" if show_graph else "display: none;"
    if is_extended_forecast:
        graph_x_labels = '<div>30 DAYS AGO</div><div>TODAY</div><div>30 DAYS FROM NOW</div>'
    else:
        graph_x_labels = '<div>30 DAYS AGO</div><div>TODAY</div>'

    mono_js = "true" if monochrome else "false"
    
    if enable_glass:
        base_glass = f"""
            background: linear-gradient(135deg, rgba(255,255,255,{opacity}) 0%, rgba(255,255,255,{max(0, opacity-0.2)}) 100%);
            backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.18);
            box-shadow: 0 8px 32px 0 rgba(0,0,0,0.1), inset 0 0 0 1px rgba(255,255,255,0.05);
        """
        night_glass = f"""
            background: linear-gradient(135deg, rgba(30,30,30,{opacity}) 0%, rgba(10,10,10,{max(0, opacity-0.2)}) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 8px 32px 0 rgba(0,0,0,0.4), inset 0 0 0 1px rgba(255,255,255,0.02);
        """
    else:
        base_glass = f"""
            background: rgba(255,255,255,{opacity});
            border: 1px solid var(--border); box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        """
        night_glass = f"""
            background: rgba(30,30,30,{opacity});
            border: 1px solid var(--border); box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        """

    if not is_overview:
        # for the deck list's notices (render() builds them)
        global _home_facts
        tomorrow_s = (datetime.datetime.strptime(today_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        _home_facts = {"exam": exam_inner, "tomorrow": forecast.get(tomorrow_s, 0), "streak": streak,
                       "today_revs": today_revs, "cards_due": cards_due, "deck_ids": deck_ids,
                       "missing": eng.missing, "today_str": today_str, "hist": hist, "retention": retention,
                       "total_mins": total_mins, "today_rate": today_rate}

    try:
        hud_width = max(540, min(900, int(cfg.get("heatmap_width", 540))))
    except (TypeError, ValueError):
        hud_width = 540
    deck_css = ""
    if modern_theme:
        if enable_glass_bg:
            cont_bg_light = base_glass
            cont_bg_dark = night_glass
        else:
            cont_bg_light = "background: transparent; border: none; box-shadow: none;"
            cont_bg_dark = "background: transparent; border: none; box-shadow: none;"

        deck_css = f"""
        .glass-deck-container {{
            {cont_bg_light}
            border-radius: 16px !important;
            margin: 30px auto !important;
            padding: 15px !important;
            width: {deck_width}px !important; min-width: fit-content !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        }}
        .night_mode .glass-deck-container {{
            {cont_bg_dark}
        }}
        .glass-deck-container table {{
            background: transparent !important;
            border: none !important;
            /* Anki's default "fancy" deck list styles the <table> itself with a
               border, rounded corners, a translucent fill AND a drop shadow. We
               already null the border/fill, but the leftover border-radius + shadow
               rendered as a second rounded outline peeking out from under our glass
               panel. Clear them so the glass container is the only frame. */
            border-radius: 0 !important;
            box-shadow: none !important;
            border-collapse: separate !important;
            border-spacing: 0 1px !important;
            width: 100% !important;
            table-layout: auto !important;
        }}
        .glass-deck-container tr {{
            background: transparent !important;
        }}
        .glass-deck-container th {{
            padding: 0px 5px 8px 5px !important;
            border: none !important;
            border-bottom: 1px solid rgba(140, 140, 140, 0.15) !important;
            font-weight: 700 !important;
            font-size: 10px !important;
            text-transform: uppercase;
            letter-spacing: 1px;
            opacity: 0.5;
            vertical-align: bottom !important;
        }}
        .glass-deck-container td {{
            padding: 5px 5px !important;
            border: none !important;
            vertical-align: middle !important;
        }}
        .glass-deck-container th:first-child,
        .glass-deck-container td:first-child {{
            text-align: left !important;
            width: auto !important;
            padding-left: 10px !important;
        }}
        .glass-deck-container th:nth-child(2), .glass-deck-container td:nth-child(2),
        .glass-deck-container th:nth-child(3), .glass-deck-container td:nth-child(3),
        .glass-deck-container th:nth-child(4), .glass-deck-container td:nth-child(4) {{
            text-align: center !important;
            width: 60px !important;
        }}
        .glass-deck-container th:nth-child(5),
        .glass-deck-container td:nth-child(5) {{
            text-align: center !important;
            width: 45px !important;
        }}
        /* Anki's deck-options gear lives in a trailing column. Keep it in normal
           flow with a slim reserved width. An earlier version collapsed this column
           to zero width and floated the gear absolutely at the right edge; because
           the RATIO ring is inserted just before it, the gear then rendered on top
           of the ring on the current/hovered row. Reserving real width makes an
           overlap structurally impossible, while staying narrower than Anki's
           default so the row still reaches close to the frame edge. */
        .glass-deck-container th:last-child,
        .glass-deck-container td:last-child {{
            width: 28px !important;
            padding: 0 2px !important;
            text-align: center !important;
        }}
        .stat-badge {{
            display: inline-block;
            padding: 3px 0px;
            width: 42px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-align: center;
            transition: all 0.2s ease;
        }}
        /* "N later" pill from the Later-button addon: its inline styles leave it
           sitting low next to the deck name. Middle-align the name, the +/- and
           the pill together so they center on each other at any font size. */
        .glass-deck-container td.decktd > a {{
            vertical-align: middle !important;
        }}
        /* Rows: a soft highlight under the mouse, and a small chevron after the name. */
        .glass-deck-container tr.deck > td {{ transition: background-color .15s ease; }}
        .glass-deck-container tr.deck:hover > td {{ background: rgba(0, 0, 0, 0.05) !important; }}
        .night_mode .glass-deck-container tr.deck:hover > td, .nightMode .glass-deck-container tr.deck:hover > td,
        .night-mode .glass-deck-container tr.deck:hover > td {{ background: rgba(255, 255, 255, 0.08) !important; }}
        .glass-deck-container tr.deck:hover > td:first-child {{ border-radius: 8px 0 0 8px; }}
        .glass-deck-container tr.deck:hover > td:last-child {{ border-radius: 0 8px 8px 0; }}
        .glass-deck-container a.deck::after {{
            content: ''; display: inline-block; width: .7em; height: .7em; margin-left: 5px; vertical-align: -0.02em;
            background: currentColor; -webkit-mask: {CHEVRON_MASK} center / contain no-repeat; mask: {CHEVRON_MASK} center / contain no-repeat;
            opacity: 0; transform: translateX(-3px); transition: opacity .15s ease, transform .15s ease;
        }}
        .glass-deck-container tr.deck:hover a.deck::after {{ opacity: .45; transform: none; }}
        .glass-deck-container .later-pill {{
            display: inline-block !important;
            line-height: 16px !important;
            padding: 1px 8px !important;
            vertical-align: middle !important;
        }}
        .badge-dim {{ color: currentColor; opacity: 0.15; font-weight: 400; }}
        .badge-new {{ color: {pill_new}; background: {pill_new}38; border: 1px solid {pill_new}80; }}
        .badge-lrn {{ color: {pill_learn}; background: {pill_learn}38; border: 1px solid {pill_learn}80; }}
        .badge-due {{ color: {pill_due}; background: {pill_due}38; border: 1px solid {pill_due}80; }}
        {PLAIN_COUNTS_CSS if not cfg.get("deck_count_pills", True) else ""}
        .activity-ring-svg {{
            width: 24px;
            height: 24px;
            transform: rotate(-90deg);
            display: block; 
            margin: 0 auto;
        }}
        .ring-bg {{ fill: none; stroke: currentColor; opacity: 0.1; }}
        .ring-seg {{ fill: none; stroke-linecap: round; transition: stroke-dasharray 0.5s ease; }}
        .ring-checkmark {{ fill: none; stroke: #2ecc71; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }}
        .glass-deck-container a {{
            font-family: system-ui, -apple-system, sans-serif !important;
            color: var(--link) !important;
            text-decoration: none !important;
            font-weight: 500 !important; 
            font-size: 14px !important;
            letter-spacing: -0.2px !important;
        }}
        /* Anki marks filtered decks with a.deck.filtered and tints them, but the
           rule above (more specific, also !important) painted every deck name the
           same. Give filtered decks their own color back. */
        .glass-deck-container a.deck.filtered {{
            color: {filtered_color} !important;
        }}
        body .deck-browser tr:hover td {{
            background-color: rgba(255, 255, 255, 0.3) !important;
        }}
        .night_mode body .deck-browser tr:hover td {{
            background-color: rgba(255, 255, 255, 0.05) !important;
        }}

        """

    # Overview glass CSS - always defined
    overview_css = f"""
        /* Overview screen glass container */
        .overview-glass-container {{
            {base_glass}
            border-radius: 16px !important;
            margin: 20px auto !important;
            padding: 20px 30px !important;
            width: fit-content !important;
            min-width: 300px !important;
        }}
        .night_mode .overview-glass-container {{
            {night_glass}
        }}
        .overview-glass-container table {{
            background: transparent !important;
            border: none !important;
            border-collapse: collapse !important;
        }}
        .overview-glass-container td {{
            padding: 8px 15px !important;
            border: none !important;
            font-size: 16px !important;
        }}
        .overview-glass-container td:first-child {{
            font-weight: 500 !important;
            opacity: 0.8;
        }}
        .overview-glass-container td:last-child {{
            font-weight: 700 !important;
            font-size: 20px !important;
        }}
        .overview-glass-container button, .overview-glass-container .btn {{
            margin-top: 15px !important;
        }}
    """

    if monochrome or not enable_shadows:
        shadow_style = "none"
        night_shadow_style = "none"
    else:
        shadow_style = "0 4px 10px rgba(0,0,0,0.1)"
        night_shadow_style = "0 2px 5px rgba(0,0,0,0.5)"

    style = f"""
    <style>
        :root {{ --bg-empty: {cfg["empty_color"]}; --txt: #24292e; --sub: #95a5a6; --border: #dfe6e9; }}
        .night_mode {{ --bg-empty: {cfg["empty_color_night"]}; --txt: #ecf0f1; --sub: #7f8c8d; --border: #34495e; }}
        
        #heatmap-root {{ width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; cursor: default; }}
        #heatmap-root, .leaderboard-wrapper, .ankileaderboard {{ display: block !important; }}
        
        .hud {{
            padding: 15px;
            width: {hud_width}px !important; min-width: {hud_width}px !important; max-width: {hud_width}px !important;
            margin: 10px auto;
            border-radius: 16px;
            {base_glass}
        }}
        
        /* Shown while the full history / forecast is computed in the background */
        .hm-loading .graph-container, .hm-loading .spark-wrapper, .hm-loading .mid {{ opacity: 0.35; transition: opacity 0.3s; }}
        .night_mode .hud {{
            {night_glass}
        }}
        
        {deck_css}
        {overview_css}

        .top {{ display: flex; justify-content: flex-end; margin-bottom: 5px; }}
        .sets {{ cursor: pointer; color: var(--sub); font-size: 14px; opacity: 0.5; transition: 0.2s; display: flex; }}
        .sets:hover {{ opacity: 1; transform: rotate(90deg); }}
        
        .mid {{ display: flex; align-items: center; margin-bottom: 25px; height: 50px; }}
        .stat-group {{ display: flex; flex-direction: column; align-items: center; min-width: 35px; }}
        
        .stat-val {{ 
            font-size: 22px; 
            font-weight: 400; 
            color: var(--txt); 
            line-height: 1.1; 
            letter-spacing: -0.5px;
            text-shadow: {shadow_style};
        }}
        
        .night_mode .stat-val {{ text-shadow: {night_shadow_style}; }}
        
        .stat-lbl {{ font-size: 8px; font-weight: 700; color: var(--sub); margin-top: 2px; letter-spacing: 0.5px; text-shadow: none; opacity: 0.8; }}
        .divider {{ width: 1px; height: 25px; background: var(--border); margin: 0 10px; opacity: 0.5; }}
        .spacer {{ flex-grow: 1; }}

        .toggle-wrapper {{ display: flex; align-items: center; margin-bottom: 2px; width: 100%; }}
        .mode-toggle {{ display: flex; background: rgba(0,0,0,0.1); border-radius: 12px; padding: 2px; height: 18px; flex-shrink: 0; border: 1px solid rgba(255,255,255,0.1); }}
        .toggle-opt {{ font-size: 9px; padding: 0 12px; border-radius: 10px; cursor: pointer; line-height: 18px; color: var(--sub); font-weight: 700; }}
        .toggle-opt:hover {{ color: var(--txt); }}
        .toggle-opt.active {{ background: {cfg['base_color']}; color: {themes.readable_text(cfg['base_color'])}; box-shadow: 0 1px 4px rgba(0,0,0,0.2); }}
        .h-divider {{ border-bottom: 1px solid var(--border); flex-grow: 1; margin-left: 15px; height: 0px; opacity: 0.5; }}
        .stats-link {{ display: inline-flex; align-items: center; gap: 4px; font-size: 9px; font-weight: 700; color: var(--sub); cursor: pointer; margin-left: 10px; padding: 0 4px; line-height: 18px; letter-spacing: 0.3px; }}
        .stats-link .hm-icon {{ width: 11px; height: 11px; vertical-align: 0; }}
        .stats-link:hover {{ color: var(--txt); }}
        .stats-link .hm-stats-logo {{ opacity: .75; transition: opacity .2s; }}
        .stats-link:hover .hm-stats-logo {{ opacity: 1; }}
        
        .graph-container {{ margin-bottom: 15px; display: flex; gap: 5px; position: relative; }}
        .hm-loadmark {{ margin-right: auto; display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 700; letter-spacing: .3px; color: var(--sub); opacity: 0; transition: opacity .3s; }}
        .hm-loadmark.on {{ opacity: .9; }}
        .hm-empty {{ position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; pointer-events: none; }}
        .hm-empty > div {{ font-size: 12px; font-weight: 600; color: var(--sub); background: rgba(127,127,127,.14); -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); padding: 3px 10px; border-radius: 8px; }}
        .day-labels {{ display: grid; grid-template-rows: repeat(7, {cfg['cell_size']}px); gap: {cfg['cell_gap']}px; padding-top: 21px; }}
        .day-labels div {{ font-size: 9px; line-height: {cfg['cell_size']}px; color: var(--sub); width: 12px; text-align: center; font-weight: 600; text-shadow: none; }}
        
        .scroll-wrapper {{ overflow: hidden; flex-grow: 1; position: relative; }}
        .scroll {{ overflow-x: auto; padding: 4px; }}
        .scroll::-webkit-scrollbar {{ height: 0px; }}
        .grid {{ display: grid; grid-auto-flow: column; }}
        
        .cell {{ width: {cfg['cell_size']}px; height: {cfg['cell_size']}px; border-radius: {_cell_radius_css(cfg)}; box-sizing: border-box; }}
        .hm-pad {{ width: {cfg['cell_size']}px; height: {cfg['cell_size']}px; }}
        .grid .m1 {{ margin-left: {max(4, round(cfg['cell_size'] * 0.6))}px; }}
        #heatmap-root.hm-fade .cell {{ transition: background-color .2s ease; }}
        .cell:hover {{ transform: scale(1.2); transition: 0.1s; z-index: 10; }}
        
        #heatmap-tooltip {{
            position: fixed; 
            top: 0; left: 0;
            background: rgba(0,0,0,0.92);
            color: #fff;
            padding: 9px 11px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 500;
            line-height: 1.45;
            min-width: 170px;
            width: max-content;
            max-width: 280px;
            word-wrap: break-word;
            z-index: 9999;
            pointer-events: none;
            display: none;
            text-align: left;
            font-variant-numeric: tabular-nums;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
            text-shadow: none;
        }}
        #heatmap-tooltip .tt-h, #heatmap-tooltip .tt-r {{ display: flex; justify-content: space-between; gap: 14px; }}
        #heatmap-tooltip .tt-h b {{ font-weight: 700; }}
        #heatmap-tooltip .tt-h span, #heatmap-tooltip .tt-m {{ color: rgba(255,255,255,0.6); }}
        #heatmap-tooltip .tt-r {{ margin-top: 5px; }}
        #heatmap-tooltip .tt-r {{ align-items: center; white-space: nowrap; }}
        #heatmap-tooltip .tt-chip {{ display: inline-flex; align-items: center; gap: 3px; padding: 0 6px; border-radius: 6px; font-size: 0.92em; line-height: 1.6; color: rgba(255,255,255,0.92); white-space: nowrap; }}
        #heatmap-tooltip .tt-chip.tt-low {{ color: rgba(255,255,255,0.7); }}
        #heatmap-tooltip .tt-split {{ display: flex; gap: 2px; height: 5px; margin: 6px 0 4px; border-radius: 3px; overflow: hidden; }}
        #heatmap-tooltip .tt-split i {{ display: block; min-width: 3px; }}
        #heatmap-tooltip .tt-key {{ display: flex; gap: 0 8px; font-size: 0.88em; white-space: nowrap; color: rgba(255,255,255,0.6); margin-bottom: 4px; }}
        #heatmap-tooltip .tt-key span {{ display: inline-flex; align-items: center; gap: 4px; }}
        #heatmap-tooltip .tt-key i {{ width: 7px; height: 7px; border-radius: 2px; }}
        #heatmap-tooltip .tt-g {{ display: grid; grid-template-columns: 1fr auto; gap: 1px 14px; color: rgba(255,255,255,0.6); }}
        #heatmap-tooltip .tt-g span:nth-child(even) {{ text-align: right; }}
        #heatmap-tooltip .tt-note {{ margin-top: 7px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.12); white-space: pre-wrap; }}
        #heatmap-tooltip .tt-ex {{ margin-top: 5px; display: flex; align-items: center; gap: 6px; font-weight: 700; }}

        .spark-wrapper {{ width: 100%; }}
        .spark-header {{ display: flex; justify-content: center; height: 14px; font-size: 9px; font-weight: 700; color: var(--sub); letter-spacing: 0.5px; margin-bottom: 2px; text-shadow: {shadow_style}; }}
        .night_mode .spark-header {{ text-shadow: {night_shadow_style}; }}
        
        .svg-container {{ position: relative; width: 100%; height: 60px; }}
        .graph-labels {{ display: flex; justify-content: space-between; font-size: 8px; color: var(--sub); font-weight: 700; margin-top: 4px; padding: 0 2px; opacity: 0.6; text-shadow: none; }}
    </style>
    """
    
    return f"""
    <div id="heatmap-root">
        <div id="heatmap-tooltip"></div>
        <script>
            // Switch heatmap views in place: each cell carries every view's color.
            window.hmSetMode = function(mode) {{
                const modes = {json.dumps(list(HEATMAP_MODES))};
                const i = modes.indexOf(mode);
                if (i < 0) return;
                // The colors fade across (0.2 s) rather than snap, unless motion is off
                const anim = {json.dumps(lowpower.motion(cfg))};
                const still = window.hmStill ? window.hmStill() : (anim === 'off' ||
                    (anim === 'system' && !!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches));
                const root = document.getElementById('heatmap-root');
                if (root && !still) {{
                    root.classList.add('hm-fade');
                    clearTimeout(window.hmFadeT);
                    window.hmFadeT = setTimeout(function () {{ root.classList.remove('hm-fade'); }}, 260);
                }}
                window.hmModeIdx = i;
                document.querySelectorAll('#heatmap-root .cell[data-bgs]').forEach(function(cell) {{
                    const bg = cell.getAttribute('data-bgs').split(';')[i];
                    if (bg) cell.style.background = bg;
                }});
                document.querySelectorAll('#heatmap-root .toggle-opt[data-mode]').forEach(function(btn) {{
                    btn.classList.toggle('active', btn.getAttribute('data-mode') === mode);
                }});
                pycmd('heatmap:savemode:' + mode);
            }};
        </script>
        {style}
        <div class="{hud_class}">
            <div class="top">
                {loadmark_html}
                <div class="sets" onclick="pycmd('heatmap:settings')" title="Settings">{icon('settings', '14px', 1.8)}</div>
            </div>
            <div class="mid" style="{stats_bar_display}">
                <div class="stat-group"><div class="stat-val" style="color:{base_text_color}">{cards_due}</div><div class="stat-lbl">DUE</div></div>
                <div class="divider"></div>
                <div class="stat-group"><div class="stat-val" style="color:{c_today}">{today_revs}</div><div class="stat-lbl">DONE</div></div>
                <div class="divider"></div>
                <div class="stat-group"><div class="stat-val" style="color:{c_time}">{avg_time}<span style="font-size:10px">s</span></div><div class="stat-lbl">SPEED</div></div>
                <div class="divider"></div>
                <div class="stat-group"><div class="stat-val">{display_time}<span style="font-size:10px">{time_unit}</span></div><div class="stat-lbl">TIME</div></div>
                <div class="divider"></div>
                <div class="stat-group"><div class="stat-val" style="color:{c_qual}">{today_rate}<span style="font-size:10px">%</span></div><div class="stat-lbl">RET</div></div>
                <div class="spacer"></div>
                <div class="stat-group"><div class="stat-val">{daily_avg}</div><div class="stat-lbl">AVG</div></div>
                <div class="divider"></div>
                <div class="stat-group"><div class="stat-val"{' id="hm-streak"' if streak_mode not in ("pct_week", "pct_month") else ""}>{streak_val}</div><div class="stat-lbl">{streak_label}</div></div>
            </div>

            <div class="toggle-wrapper">
                <div class="mode-toggle">
                    <div class="toggle-opt {vol_class}" data-mode="volume" onclick="hmSetMode('volume')">VOLUME</div>
                    <div class="toggle-opt {ret_class}" data-mode="retention" onclick="hmSetMode('retention')">RETENTION</div>
                    <div class="toggle-opt {scr_class}" data-mode="score" onclick="hmSetMode('score')">SPEED</div>
                    {time_btn_html}
                    {nc_btn_html}
                    {focus_btn_html}
                </div>
                <div class="h-divider"></div>
                {stats_link_html}
            </div>
            
            <div class="graph-container">
                {empty_html}
                <div class="day-labels"><div>S</div><div>M</div><div>T</div><div>W</div><div>T</div><div>F</div><div>S</div></div>
                <div class="scroll-wrapper">
                    <div class="scroll" id="heatmap-scroll">
                        <div id="hm-months" style="width: {total_width_px}px; position:relative; height:15px; margin-bottom:2px; font-size:9px; font-weight:700; color:#95a5a6; display:flex;">
                            {month_html}
                        </div>
                        <div class="grid" style="width: max-content; grid-template-rows:repeat(7,{cfg["cell_size"]}px); gap:{cfg["cell_gap"]}px">
                            {cells_html}
                        </div>
                    </div>
                </div>
            </div>

            <div class="spark-wrapper" style="{graph_display_style}">
                <div id="heatmap-legend" class="spark-header">{legend_html}</div>
                <div class="svg-container" id="heatmap-graph-container">
                    <svg width="100%" height="100%" preserveAspectRatio="none" viewBox="0 0 530 66">
                        <defs>
                            <linearGradient id="grad" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" style="stop-color:{cfg['base_color']};stop-opacity:0.3" />
                                <stop offset="100%" style="stop-color:{cfg['base_color']};stop-opacity:0" />
                            </linearGradient>
                        </defs>
                        {svg_paths}
                    </svg>
                    <div id="heatmap-touch" style="position:absolute; top:0; left:0; width:100%; height:100%; cursor:crosshair;"></div>
                </div>
                <div class="graph-labels">{graph_x_labels}</div>
            </div>
        </div>

        <script>
            (function() {{
                window.initHeatmap = function() {{
                    const meta = {meta_json};
                    const fullDeckStats = {deck_stats_json}; 
                    
                    const touch = document.getElementById('heatmap-touch');
                    const legend = document.getElementById('heatmap-legend');
                    const scrollBox = document.getElementById('heatmap-scroll');
                    const tooltip = document.getElementById('heatmap-tooltip');
                    const baseColor = "{cfg['base_color']}";
                    const revColor = "{cfg.get('graph_reviews_color', '#3498db')}";
                    const timeColor = "{cfg.get('graph_time_color', '#e67e22')}";
                    const tsColor = "{cfg.get('graph_time_studied_color', '#3498db')}";
                    const retColor = "{cfg.get('graph_retention_color', '#f1c40f')}";
                    const futColor = "{cfg.get('fsrs_prediction_color', '#9b59b6') if cfg.get('fsrs_simulation_enabled', False) else cfg.get('graph_forecast_color', '#95a5a6')}";
                    const futLabel = "{'FSRS' if cfg.get('fsrs_simulation_enabled', False) else 'FUT'}";
                    const defaultHTML = legend ? legend.innerHTML : "";
                    const isMono = {mono_js};
                    const revRolling  = {'true' if cfg.get('reviews_rolling_avg',  False) else 'false'};
                    const revPeriod   = {cfg.get('reviews_rolling_avg_period',  7)};
                    const timeRolling = {'true' if cfg.get('time_rolling_avg',    False) else 'false'};
                    const timePeriod  = {cfg.get('time_rolling_avg_period',  7)};
                    const retRolling  = {'true' if cfg.get('ret_rolling_avg',     False) else 'false'};
                    const retPeriod   = {cfg.get('ret_rolling_avg_period',   7)};
                    const futRolling  = {'true' if cfg.get('forecast_rolling_avg',False) else 'false'};
                    const futPeriod   = {cfg.get('forecast_rolling_avg_period',  7)};
                    const tsRolling   = {'true' if cfg.get('time_studied_rolling_avg', False) else 'false'};
                    const tsPeriod    = {cfg.get('time_studied_rolling_avg_period', 7)};
                    const activeGraphs = {json.dumps(cfg.get('active_graphs_v14', ['reviews', 'time_card', 'retention', 'forecast']))};

                    const modernTheme = {str(modern_theme).lower()};
                    const showRatio = {str(show_ratio).lower()};

                    function showTooltip(evt, el) {{
                        let text = el.getAttribute('data-tooltip');
                        if(!text || !tooltip) return;
                        // icons travel as short marks (see _tip_attr); put them back
                        if (text.indexOf('\u27e6') >= 0) {{
                            const icons = {json.dumps(_TIP_ICONS)};
                            text = text.replace(/\u27e6(\\w+)\u27e7/g, function (m, k) {{ return icons[k] || m; }});
                        }}
                        tooltip.innerHTML = text;
                        tooltip.style.display = 'block';
                        
                        let x = evt.clientX - (tooltip.offsetWidth / 2);
                        if (x < 10) x = 10;
                        tooltip.style.left = x + 'px';
                        tooltip.style.top = (evt.clientY - tooltip.offsetHeight - 15) + 'px';
                    }}

                    if (scrollBox) {{
                        scrollBox.onmouseover = function(e) {{
                            const cell = e.target.closest('.cell');
                            if (cell) {{
                                showTooltip(e, cell);
                                const lg = cell.getAttribute('data-legend');
                                if (lg && legend) legend.innerHTML = lg;
                            }}
                        }};
                        scrollBox.onmouseout = function() {{
                            if(tooltip) tooltip.style.display = 'none';
                            if(legend) legend.innerHTML = defaultHTML;
                        }};
                    }}

                    if (touch && legend) {{
                        touch.onmousemove = function(e) {{
                            const rect = touch.getBoundingClientRect();
                            const x = e.clientX - rect.left;
                            const idx = Math.floor((x / rect.width) * meta.length);
                            if (idx >= 0 && idx < meta.length) {{
                                const d = meta[idx];
                                
                                const c_rev = isMono ? "var(--txt)" : revColor;
                                const c_time = isMono ? "var(--txt)" : timeColor;
                                const c_ts   = isMono ? "var(--txt)" : tsColor;
                                const c_ret  = isMono ? "var(--txt)" : retColor;
                                const c_fut  = isMono ? "var(--txt)" : futColor;

                                let html = `<span>${{d.label}}</span>`;

                                // Review count — skip for pure-future days (rev=0, fut>0)
                                const showRev = activeGraphs.includes("reviews") && (d.rev > 0 || (revRolling && d.rev_avg > 0 && d.fut === 0));
                                if (showRev) {{
                                    const revVal    = (revRolling && d.rev_avg > 0) ? d.rev_avg : d.rev;
                                    const revSuffix = " REV";
                                    html += ` &nbsp;&nbsp; <span style="color:${{c_rev}}">${{revVal}}${{revSuffix}}</span>`;
                                }}

                                // Time per card
                                const timeVal = (timeRolling && d.time_avg > 0) ? d.time_avg : d.time;
                                if (activeGraphs.includes("time_card") && timeVal > 0) {{
                                    const timeSuffix = " S/C";
                                    html += ` &nbsp;&nbsp; <span style="color:${{c_time}}">${{timeVal}}${{timeSuffix}}</span>`;
                                }}

                                // Time studied
                                const tsRaw = (tsRolling && d.ts_avg > 0) ? d.ts_avg : (d.ts_mins || 0);
                                if (activeGraphs.includes("time_studied") && tsRaw > 0) {{
                                    let tsFmt;
                                    if (tsRaw >= 60) {{
                                        const tsH = Math.floor(tsRaw / 60);
                                        const tsM = Math.round(tsRaw % 60);
                                        tsFmt = tsH + ` h ` + tsM + ` m`;
                                    }} else if (tsRaw >= 1) {{
                                        tsFmt = Math.round(tsRaw) + ` m`;
                                    }} else {{
                                        tsFmt = `< 1 m`;
                                    }}
                                    const tsSuffix = ``;
                                    html += ` &nbsp;&nbsp; <span style="color:${{c_ts}}">${{tsFmt}}${{tsSuffix}}</span>`;
                                }}

                                // Retention
                                if (activeGraphs.includes("retention") && d.rev > 0) {{
                                    const retVal    = (retRolling && d.ret_avg > 0) ? d.ret_avg : d.ret;
                                    const retSuffix = "% RET";
                                    html += ` &nbsp;&nbsp; <span style="color:${{c_ret}}">${{retVal}}${{retSuffix}}</span>`;
                                }}

                                // Forecast
                                if (activeGraphs.includes("forecast") && d.fut > 0) {{
                                    const futVal    = (futRolling && d.fut_avg > 0) ? d.fut_avg : d.fut;
                                    const futSuffix = ` ${{futLabel}}`;
                                    const futRange  = (!futRolling && d.fut_hi !== undefined) ? ` (${{d.fut_lo}}–${{d.fut_hi}})` : "";
                                    html += ` &nbsp;&nbsp; <span style="color:${{c_fut}}">${{futVal}}${{futSuffix}}${{futRange}}</span>`;
                                }}
                                if (d.exams && d.exams.length > 0) {{
                                    for (const ex of d.exams) {{
                                        html += ` &nbsp;&nbsp; <span style="color:${{ex.color}}">{icon('flag')} ${{ex.label.toUpperCase()}}</span>`;
                                    }}
                                }}

                                legend.innerHTML = html;
                            }}
                        }};
                        touch.onmouseleave = function() {{ legend.innerHTML = defaultHTML; }};
                    }}

                    function applyDeckGlass() {{
                        if (!modernTheme) return;
                        const tables = document.getElementsByTagName('table');
                        if (tables.length === 0) return;
                        const table = tables[0];
                        if (table.parentElement.classList.contains('glass-deck-container')) return;
                        const wrapper = document.createElement('div');
                        wrapper.className = 'glass-deck-container';
                        table.parentNode.insertBefore(wrapper, table);
                        wrapper.appendChild(table);
                        enhanceDeckRows(table);
                    }}
                    
                    function enhanceDeckRows(table) {{
                        const rows = table.getElementsByTagName('tr');
                        if (showRatio) {{
                            const headerRow = rows[0];
                            if (headerRow) {{
                                if (!headerRow.querySelector('.heatmap-ratio-header')) {{
                                    const th = document.createElement('th');
                                    th.innerText = 'RATIO'; 
                                    th.className = 'heatmap-ratio-header';
                                    headerRow.insertBefore(th, headerRow.lastElementChild);
                                }}
                            }}
                        }}
                        // Anki's own counts for each deck, passed from Python (render()).
                        // Preferred over reading the cell text, which comes out empty
                        // if anything has cleared or not yet filled the cell.
                        const knownCounts = window.hmDeckCounts || {{}};
                        // The counts at the last deck list: ones that went down tick down to
                        // their new value (back from reviewing). Off with reduced motion.
                        const prevCounts = window.hmPrevCounts || {{}};
                        const still = window.hmStill ? window.hmStill() : false;
                        const drain = (span, from, to, type) => {{
                            span.className = 'stat-badge ' + type;
                            span.innerText = from;
                            let t0 = null;
                            const step = (now) => {{
                                if (t0 === null) t0 = now;
                                const p = Math.max(0, Math.min(1, (now - t0) / 700));
                                span.innerText = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)));
                                if (p < 1) requestAnimationFrame(step);
                                else span.className = 'stat-badge ' + (to > 0 ? type : 'badge-dim');
                            }};
                            // once the page is on screen (moments.py), after a short beat on the old number
                            (window.hmWhenShown || ((f) => f()))(() => setTimeout(() => requestAnimationFrame(step), 300));
                        }};
                        for (let i = 1; i < rows.length; i++) {{
                            const row = rows[i];
                            const cells = row.getElementsByTagName('td');
                            if (cells.length < 5) continue;

                            const did = row.id.replace('deck-', '');
                            const known = knownCounts[did];
                            const before = prevCounts[did];

                            const wrap = (cell, type, knownVal, fromVal) => {{
                                if (cell.querySelector('.stat-badge')) return;
                                let val = knownVal;
                                if (typeof val !== 'number') {{
                                    const raw = cell.textContent.replace(/[^0-9]/g, '');
                                    val = parseInt(raw, 10) || 0;
                                }}
                                const span = document.createElement('span');
                                span.innerText = val;
                                span.className = 'stat-badge ' + (val > 0 ? type : 'badge-dim');
                                cell.innerHTML = '';
                                cell.appendChild(span);
                                if (!still && typeof fromVal === 'number' && fromVal > val) drain(span, fromVal, val, type);
                            }};

                            wrap(cells[1], 'badge-new', known && known[0], before && before[0]);
                            wrap(cells[2], 'badge-lrn', known && known[1], before && before[1]);
                            wrap(cells[3], 'badge-due', known && known[2], before && before[2]);

                            if (!showRatio) continue;

                            const stats = fullDeckStats[did];
                            if (!stats) continue;

                            const n = stats.n || 0;
                            const l = stats.l || 0;
                            const d = stats.d || 0;
                            const done = stats.done || 0;
                            const total = n + l + d + done;
                            
                            let ringTd = row.querySelector('.heatmap-ring-cell');
                            if (!ringTd) {{
                                ringTd = document.createElement('td');
                                ringTd.className = 'heatmap-ring-cell';
                                row.insertBefore(ringTd, row.lastElementChild);
                            }}
                            
                            const RING = 'd="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" stroke-width="4"';
                            const ringSvg = (n, l, d, done) => {{
                                if (total <= 0) return `<svg class="activity-ring-svg" viewBox="0 0 36 36"><path class="ring-bg" ${{RING}} /></svg>`;
                                const n_pct = (n / total) * 100;
                                const l_pct = (l / total) * 100;
                                const d_pct = (d / total) * 100;
                                const done_pct = (done / total) * 100;

                                const off_n = done_pct;
                                const off_l = done_pct + n_pct;
                                const off_d = done_pct + n_pct + l_pct;

                                let paths = `<path class="ring-bg" ${{RING}} />`;
                                if (done > 0) paths += `<path class="ring-seg" stroke="#2ecc71" stroke-dasharray="${{done_pct}}, 100" ${{RING}} />`;
                                if (n > 0) paths += `<path class="ring-seg" stroke="{pill_new}" stroke-dasharray="${{n_pct}}, 100" stroke-dashoffset="-${{off_n}}" ${{RING}} />`;
                                if (l > 0) paths += `<path class="ring-seg" stroke="{pill_learn}" stroke-dasharray="${{l_pct}}, 100" stroke-dashoffset="-${{off_l}}" ${{RING}} />`;
                                if (d > 0) paths += `<path class="ring-seg" stroke="{pill_due}" stroke-dasharray="${{d_pct}}, 100" stroke-dashoffset="-${{off_d}}" ${{RING}} />`;

                                // Add checkmark when all reviews are complete
                                if (done >= total - 1e-6) {{
                                    paths += `<path class="ring-checkmark" d="M12 18.5 l 4 4 l 8.5 -8.5" transform="rotate(90 18 18)" />`;
                                }}
                                return `<svg class="activity-ring-svg" viewBox="0 0 36 36">${{paths}}</svg>`;
                            }};
                            ringTd.innerHTML = ringSvg(n, l, d, done);

                            // Back from studying this deck: the ring fills from where it was at
                            // the last deck list (its counts then) to where it is now.
                            if (!still && total > 0 && before && known) {{
                                const from = [n + before[0] - known[0], l + before[1] - known[1], d + before[2] - known[2]]
                                    .map((v) => Math.max(0, v));
                                const doneFrom = Math.max(0, total - from[0] - from[1] - from[2]);
                                if (doneFrom < done) {{
                                    ringTd.innerHTML = ringSvg(from[0], from[1], from[2], doneFrom);
                                    let t0 = null;
                                    const grow = (now) => {{
                                        if (t0 === null) t0 = now;
                                        const p = Math.max(0, Math.min(1, (now - t0) / 650));
                                        const e = 1 - Math.pow(1 - p, 3), at = (a, b) => a + (b - a) * e;
                                        ringTd.innerHTML = ringSvg(at(from[0], n), at(from[1], l), at(from[2], d), at(doneFrom, done));
                                        if (p < 1) requestAnimationFrame(grow);
                                    }};
                                    (window.hmWhenShown || ((f) => f()))(() => requestAnimationFrame(grow));
                                }}
                            }}
                        }}
                    }}

                    function cleanStats() {{
                        const ov = document.getElementById('overview');
                        if(!ov) return;
                        ov.childNodes.forEach(n => {{
                            if(n.textContent && n.textContent.includes('Studied') && n.textContent.includes('cards')) {{
                                if(n.nodeType === 3) n.textContent = '';
                                else n.style.display = 'none';
                            }}
                        }});
                    }}
                    cleanStats();
                    const isOverview = {str(is_overview).lower()};
                    if (!isOverview) {{
                        applyDeckGlass();
                    }} else {{
                        // Apply glass styling to overview content
                        applyOverviewGlass();
                    }}
                    setTimeout(() => {{ if(scrollBox) scrollBox.scrollLeft = scrollBox.scrollWidth; }}, 50);

                    // Older weeks load as you scroll back near the left edge (heatmap:older)
                    if (scrollBox && "{older_token}" && !scrollBox.hmOlderOn) {{
                        scrollBox.hmOlderOn = true;
                        const grid = scrollBox.querySelector('.grid');
                        const months = document.getElementById('hm-months');
                        let busy = false, finished = false, lastLeft = scrollBox.scrollLeft;
                        scrollBox.addEventListener('scroll', function () {{
                            // only on scrolling left (not the jump to the right end as it opens)
                            const left = scrollBox.scrollLeft, back = left < lastLeft;
                            lastLeft = left;
                            if (busy || finished || !back || left > 300) return;
                            busy = true;
                            pycmd('heatmap:older:{older_token}');
                        }}, {{passive: true}});
                        window.hmOlder = function (cells, labels, width, last) {{
                            const t = document.createElement('template');
                            t.innerHTML = cells;
                            if (window.hmModeIdx !== undefined) {{
                                t.content.querySelectorAll('.cell[data-bgs]').forEach(function (cell) {{
                                    const bg = cell.getAttribute('data-bgs').split(';')[window.hmModeIdx];
                                    if (bg) cell.style.background = bg;
                                }});
                            }}
                            const before = scrollBox.scrollWidth, left = scrollBox.scrollLeft;
                            grid.prepend(t.content);
                            if (months) {{ months.innerHTML = labels; months.style.width = width + 'px'; }}
                            scrollBox.scrollLeft = lastLeft = left + (scrollBox.scrollWidth - before);
                            finished = !!last;
                            busy = false;
                        }};
                    }}

                    function applyOverviewGlass() {{
                        const tables = document.getElementsByTagName('table');
                        if (tables.length === 0) return;
                        const table = tables[0];
                        if (table.closest('.overview-glass-container')) return;

                        // Create glass wrapper for the overview table
                        const wrapper = document.createElement('div');
                        wrapper.className = 'overview-glass-container';
                        table.parentNode.insertBefore(wrapper, table);
                        wrapper.appendChild(table);
                    }}
                }};
                window.initHeatmap();
            }})();
        </script>
    </div>
    """

try:
    from aqt.operations import QueryOp
except ImportError:         # very old Anki: everything is computed on the spot
    QueryOp = None

# Background jobs by screen key -> refresh to run when done (None = just fill caches)
_WARMING = {}
# Screens whose next render should compute anything still missing on the spot,
# so a render after a background job can never start another one.
_FORCE_FULL_RENDER = set()
# Screens showing the dimmed heatmap while the background job runs (it redraws them after).
_PLACEHOLDER = set()


def _heatmap_html(screen_key, refresh, **kwargs):
    """Heatmap HTML built from cached data only. The slow parts (full review
    history, FSRS forecast) take seconds on a big collection, so when they're
    missing the heatmap shows dimmed, they're computed in the background, and
    refresh() redraws the screen. An expired forecast is shown as is and renewed
    in the background without a redraw."""
    full = QueryOp is None or screen_key in _FORCE_FULL_RENDER
    _FORCE_FULL_RENDER.discard(screen_key)
    status = {}
    html = get_html_body_content(cache_only=not full, status=status, **kwargs)
    _PLACEHOLDER.discard(screen_key)
    if status.get("missing") or status.get("stale"):
        started = _warm_in_background(screen_key, kwargs.get("deck_ids"), kwargs.get("retention_deck_ids"),
                                      refresh if status.get("missing") else None)
        if status.get("missing") and not started:
            # No background job possible: compute it here, the old way.
            html = get_html_body_content(**kwargs)
        elif status.get("missing"):
            _PLACEHOLDER.add(screen_key)
    return html


def _warm_in_background(screen_key, deck_ids, retention_deck_ids, refresh):
    """Start (or join) the background job for this screen; False if it can't run."""
    if screen_key in _WARMING:
        if refresh:
            _WARMING[screen_key] = refresh
        return True
    _WARMING[screen_key] = refresh
    eng = FastEngine()      # reads config here, on the main thread

    def done(_result=None):
        if eng.stale and time.time() < _STARTUP_HOLD_UNTIL:
            # the forecast was left as saved, to refresh once startup has settled
            QTimer.singleShot(int((_STARTUP_HOLD_UNTIL - time.time()) * 1000) + 500,
                              lambda: _warm_in_background(screen_key, deck_ids, retention_deck_ids, None))
        then = _WARMING.pop(screen_key, None)
        if then:
            _FORCE_FULL_RENDER.add(screen_key)
            if screen_key == "deckBrowser" and time_left.fitting():
                # Time Left is still learning your pace and redraws when it's done: one
                # redraw for both at startup instead of two
                time_left.after_fit(then)
                return
            then()

    def failed(err):
        _WARMING.pop(screen_key, None)
        print("Elemental: background update failed:", err)
        _end_loading(screen_key)

    # Two steps. First the slow part, the per-day totals of the whole review log, on the
    # job's own read-only connection (Anki's on Windows, a stretch at a time) and off
    # Anki's collection queue, so opening a deck or syncing doesn't wait behind it. Then
    # the rest (fingerprints, today's rows, the FSRS simulation) as a QueryOp on
    # Anki's queue, as before: quick now the totals are ready.
    path = mw.col.path

    def history():
        from . import estimator
        try:
            eng._hist_db = estimator.connect(path)
        except Exception:
            eng._hist_db = None
            return
        try:
            eng.prepare_history(deck_ids, retention_deck_ids)
        finally:
            try:
                eng._hist_db.close()
            except Exception:
                pass
            eng._hist_db = None

    def op(col):
        from . import estimator
        try:
            eng._hist_db = estimator.connect(col.path, fallback=False)
        except Exception:
            eng._hist_db = None
        try:
            return eng.get_data(deck_ids=deck_ids, retention_deck_ids=retention_deck_ids)
        finally:
            if eng._hist_db is not None:
                eng._hist_db.close()

    def rest(_fut=None):
        if mw.col is None or mw.col.path != path:
            _WARMING.pop(screen_key, None)
            return
        try:
            QueryOp(parent=mw, op=op, success=done).failure(failed).run_in_background()
        except Exception:
            # no background job possible: redraw, working it out there, the old way
            _log_exc()
            then = _WARMING.pop(screen_key, None)
            if then:
                _FORCE_FULL_RENDER.add(screen_key)
                then()

    try:
        time_left._background(history, rest)
    except Exception:
        _log_exc()
        _WARMING.pop(screen_key, None)
        return False
    return True


_END_LOADING_JS = """(function(){
  var m = document.getElementById('hm-loadmark'); if (m) m.remove();
  [].forEach.call(document.querySelectorAll('.hm-loading'), function (e) { e.classList.remove('hm-loading'); });
})();"""


def _end_loading(screen_key):
    """A background job failed, so no redraw is coming: take the screen out of its loading
    look. The next time it's drawn, the job is tried again."""
    _PLACEHOLDER.discard(screen_key)
    try:
        if screen_key == "deckBrowser" and mw.state == "deckBrowser":
            mw.deckBrowser.web.eval(_END_LOADING_JS)
        elif isinstance(screen_key, tuple) and screen_key[0] == "overview" and mw.state == "overview":
            mw.overview.web.eval(_END_LOADING_JS)
    except Exception:
        _log_exc()


def _main_heatmap_args(cfg):
    """deck_ids / retention_deck_ids for the deck-screen heatmap"""
    # Determine deck filter for main heatmap
    deck_ids = None
    if cfg.get('heatmap_deck_filter_enabled', False):
        filtered = cfg.get('heatmap_filtered_decks', [])
        if filtered:
            deck_ids = filtered

    # Determine the (separate) deck scope for the retention % only. Selected decks
    # are expanded to include their sub-decks so picking a parent covers its tree.
    retention_deck_ids = None
    if cfg.get('retention_deck_scope_enabled', False):
        scoped = cfg.get('retention_scope_decks', [])
        if scoped:
            expanded = set()
            for d in scoped:
                expanded.update(get_deck_and_children_ids(d))
            retention_deck_ids = sorted(expanded)
    return dict(deck_ids=deck_ids, retention_deck_ids=retention_deck_ids)


def _refresh_deck_browser():
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()


def _request_deck_refresh():
    """Time Left's redraw of the deck list: while the heatmap's background job runs, it waits
    and redraws with it (one redraw for both at startup)."""
    if "deckBrowser" in _WARMING:
        _WARMING["deckBrowser"] = _refresh_deck_browser
        return
    _refresh_deck_browser()


time_left.deck_refresh = _request_deck_refresh


def _refresh_overview():
    if mw.state == "overview":
        mw.overview.refresh()


BACKLOG_MIN = 20        # overdue cards before they count as a backlog worth a notice


TODAY_SLOT = "TODAY"    # where today's finish time (Time Left's pill) goes among the reminders


def _deck_notices(cfg, today_pill=False):
    """The deck list's reminders, one pill's worth of HTML each, in the order they roll in:
    cards not synced yet, today's finish time (TODAY_SLOT, when Time Left shows it), the next
    exam, an overdue backlog, learning cards coming back, tomorrow's reviews in the evening,
    your streak late in the day before you've studied, and the week's numbers."""
    f = _home_facts
    if not f or f.get("missing"):
        return []
    out = [f["exam"]] if f.get("exam") else []
    roll = mw.col.conf.get('rollover', 4)
    now = datetime.datetime.now()
    evening = now.hour >= 18 or now.hour < roll
    if cfg.get("notice_backlog", True):
        try:
            dids = forecast_band.scope_dids(mw.col, f.get("deck_ids"))
            where = f"AND did IN ({','.join(map(str, dids))})" if dids else ""
            n = mw.col.db.scalar(f"SELECT count() FROM cards WHERE queue = 2 AND due < {mw.col.sched.today} {where}") or 0
            if n >= BACKLOG_MIN:
                out.append(f'<span class="hm-note-ic amber">{icon("layers")}</span>'
                           f'<span>{n:,} overdue</span><span class="hm-note-w">{"card" if n == 1 else "cards"}</span>')
        except Exception:
            _log_exc()
    done = f.get("cards_due") == 0 and f.get("today_revs", 0) > 0
    nothing_now = f.get("cards_due") == 0
    if cfg.get("notice_learning", True) and nothing_now:
        # learning steps still to come back today: Anki hides them until they're due
        try:
            dids = forecast_band.scope_dids(mw.col, f.get("deck_ids"))
            where = f"AND did IN ({','.join(map(str, dids))})" if dids else ""
            n, last = mw.col.db.first(f"SELECT count(), max(due) FROM cards WHERE queue = 1 AND due > {int(time.time())} "
                                      f"AND due < {mw.col.sched.day_cutoff} {where}") or (0, 0)
            if n:
                t = datetime.datetime.fromtimestamp(last)
                out.append(f'<span class="hm-note-ic blue">{icon("clock")}</span>'
                           f'<span>{n:,} learning {"card" if n == 1 else "cards"}</span>'
                           f'<span class="hm-note-w">back by {t.hour % 12 or 12}:{t.minute:02d} {"am" if t.hour < 12 else "pm"}</span>')
        except Exception:
            _log_exc()
    if cfg.get("notice_tomorrow", True) and (evening or done) and f.get("tomorrow", 0) > 0:
        out.append(f'<span class="hm-note-ic gray">{icon("sunrise")}</span>'
                   f'<span>Tomorrow</span><span class="hm-note-w">~{round(f["tomorrow"]):,} due</span>')
    if cfg.get("notice_streak", True) and evening and not f.get("today_revs") and f.get("streak", 0) >= 3:
        out.append(f'<span class="hm-note-ic flame">{icon("flame")}</span>'
                   f'<span>{f["streak"]}-day streak</span><span class="hm-note-w">no reviews yet today</span>')
    if cfg.get("notice_milestone", True) and f.get("today_revs") and moments.milestone(f.get("streak", 0)):
        # inserted first, so it lands just after the sync note and the finish time
        out.insert(0, f'<span class="hm-note-ic gold">{icon("flame")}</span>'
                      f'<span>{moments.milestone_label(f["streak"])}</span>')
    if cfg.get("notice_sync", True):
        # cards changed here that haven't gone to AnkiWeb yet, and when you last synced:
        # the time if that was today, else the date (never shown if you don't sync)
        try:
            ls = mw.col.db.scalar("SELECT ls FROM col") or 0
            n = mw.col.db.scalar("SELECT count() FROM cards WHERE usn = -1") or 0 if ls else 0
            if n:
                d = datetime.datetime.fromtimestamp(ls / 1000)
                since = (f"{d.hour % 12 or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"
                         if d.date() == now.date() else f"{d.strftime('%b')} {d.day}")
                out.insert(0, f'<span class="hm-note-ic gray">{icon("cloud-off")}</span>'
                              f'<span>Not synced since {since}</span>'
                              f'<span class="hm-note-w">{n:,} {"card" if n == 1 else "cards"} unsynced</span>')
        except Exception:
            _log_exc()
    out += _week_notices(cfg, f)
    if today_pill and out:
        synced = 1 if "Not synced" in out[0] else 0
        out.insert(synced, TODAY_SLOT)
    pomo = _pomo_notice()
    if pomo:
        out.insert(0, pomo)
    return out


def _pomo_notice():
    """The pomodoro's reminder on the deck list: a break counting down (it turns into
    'Break over' when it ends, without a redraw), a break that's over, or a paused block.
    Nothing when it's stopped."""
    if not pomodoro.enabled():
        return None
    st = pomodoro.state()
    ph = st.get("phase")
    if ph == "brk":
        end = st["brk_end_ms"]
        left = max(0, end / 1000 - time.time())
        nxt = st["block"] % st["of"] + 1        # after the long break, block 1 of a new set
        over = (f'<span class="hm-note-ic teal">{icon("play")}</span><span>Break over</span>'
                f'<span class="hm-note-w">block {nxt} of {st["of"]}</span>')
        return (f'<span class="hm-note-ic teal">{icon("coffee")}</span><span>Break</span>'
                f'<span class="hm-note-w"><span class="hm-pomo-t" data-end="{end}" data-over="{_html.escape(over)}">'
                f'{pomodoro.mmss(left)}</span> left · back at {pomodoro.clock(end / 1000)}</span>' + _POMO_JS)
    if ph == "over":
        return (f'<span class="hm-note-ic teal">{icon("play")}</span><span>Break over</span>'
                f'<span class="hm-note-w">block {st["next"]} of {st["of"]}</span>')
    if ph == "focus" and not st.get("running") and st.get("left", 0) > 0:
        return (f'<span class="hm-note-ic teal">{icon("clock")}</span><span>Block {st["block"]} paused</span>'
                f'<span class="hm-note-w">{pomodoro.mmss(st["left"])} left</span>')
    return None


# Counts the break down wherever the roll has put it; at the end the reminder reads Break over.
_POMO_JS = """<script>(function(){
  if (window.hmPomoTick) return;
  window.hmPomoTick = setInterval(function () {
    var now = Date.now();
    [].forEach.call(document.querySelectorAll('.hm-pomo-t[data-end]'), function (e) {
      var s = Math.max(0, Math.round((+e.getAttribute('data-end') - now) / 1000));
      if (s > 0) { e.textContent = Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2); return; }
      var box = e.parentNode && e.parentNode.parentNode;
      if (box) box.innerHTML = e.getAttribute('data-over');
    });
  }, 1000);
})();</script>"""


WEEK_CHANGE = 0.15      # this week against last week: shown once they differ by this much


def _week_notices(cfg, f):
    """Last week's reviews and retention on the first day of the week (Monday), and this
    week so far against the same days last week when they differ a lot (from Wednesday, so
    there are at least two whole days to compare)."""
    out = []
    try:
        today = datetime.datetime.strptime(f["today_str"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return out
    hist, ret = f.get("hist") or {}, f.get("retention") or {}
    day = lambda d: d.strftime("%Y-%m-%d")
    monday = today - timedelta(days=today.weekday())
    if cfg.get("notice_last_week", True) and today.weekday() == 0:
        days = [monday - timedelta(days=i) for i in range(1, 8)]
        n = sum(hist.get(day(d), 0) for d in days)
        ok = sum(ret.get(day(d), [0, 0])[0] for d in days)
        seen = sum(ret.get(day(d), [0, 0])[1] for d in days)
        if n:
            bits = [f"{n:,} reviews"] + ([f"{round(100 * ok / seen)}%"] if seen else [])
            out.append(f'<span class="hm-note-ic gray">{icon("calendar")}</span>'
                       f'<span>Last week</span><span class="hm-note-w">{" · ".join(bits)}</span>')
    if cfg.get("notice_this_week", True) and today.weekday() >= 2:
        # through yesterday, so a day in progress doesn't count as a slow one
        this = sum(hist.get(day(monday + timedelta(days=i)), 0) for i in range(today.weekday()))
        last = sum(hist.get(day(monday - timedelta(days=7 - i)), 0) for i in range(today.weekday()))
        if last >= 50 and abs(this - last) / last >= WEEK_CHANGE:
            pct = round(100 * (this - last) / last)
            out.append(f'<span class="hm-note-ic gray">{icon("up" if pct > 0 else "down")}</span>'
                       f'<span>This week</span><span class="hm-note-w">{"+" if pct > 0 else "−"}{abs(pct)}% reviews vs last</span>')
    return out


# The deck list's reminders: one pill that rolls up every few seconds through each in turn,
# one dot per side (held while the mouse is on it; without the slide when animations are
# off). Today's finish time, when Time Left shows it, is one of them (its slot in the order
# is marked data-today); a single reminder just sits as a line.
_EXAM_JS = """<script>(function(){
  var n = 0, EVERY = 4000, built = false;
  function build() {
    var e = document.getElementById('hm-notes'), t = document.getElementById('rt-today'),
        b = document.querySelector('.glass-deck-container');
    if (built || !e) return;
    if (!(b && (!t || t.parentNode === b))) { if (++n < 60) setTimeout(build, 60); return; }
    var pill = t && t.querySelector('.rt-pill'), notes = [].slice.call(e.children);
    built = true;
    if (!pill) {
      notes.filter(function (x) { return x.hasAttribute('data-today'); }).forEach(function (x) { x.remove(); });
      notes = notes.filter(function (x) { return !x.hasAttribute('data-today'); });
    } else if (!notes.some(function (x) { return x.hasAttribute('data-today'); })) {
      notes.unshift(null);                      // no slot given: the finish time goes first
    }
    if (!pill && notes.length < 2) { b.appendChild(e); return; }
    var host = t || e;
    if (!t) b.appendChild(e);
    var sides = notes.map(function (x) {
      if (!x || x.hasAttribute('data-today')) return pill;
      var p = document.createElement('span');
      p.className = 'rt-pill hm-note-pill';
      p.innerHTML = '<span>' + x.innerHTML + '</span>';
      host.appendChild(p);                      // measured side by side, before they stack
      return p;
    });
    var width = Math.max.apply(null, sides.map(function (p) { return p.offsetWidth; })) + 6;
    if (t) e.remove();
    var car = document.createElement('div'), win = document.createElement('div'), dots = document.createElement('div');
    car.className = 'hm-car'; win.className = 'hm-car-win'; dots.className = 'hm-car-dots';
    var slides = sides.map(function (p, i) {
      var s = document.createElement('div');
      s.className = 'hm-car-s' + (i ? ' below' : '');
      s.appendChild(p); win.appendChild(s);
      dots.appendChild(document.createElement('i'));
      return s;
    });
    var titles = sides.map(function (p) { return p === pill ? t.title : ''; });
    car.appendChild(win); car.appendChild(dots);
    host.innerHTML = ''; host.appendChild(car);
    win.style.width = width + 'px';
    var cur = 0, hold = false;
    function show(i) {
      [].forEach.call(dots.children, function (d, k) { d.className = k === i ? 'on' : ''; });
      if (t) t.title = titles[i];
    }
    show(cur);
    car.addEventListener('mouseenter', function () { hold = true; });
    car.addEventListener('mouseleave', function () { hold = false; });
    setInterval(function () {
      if (hold || document.visibilityState !== 'visible') return;
      car.classList.toggle('still', !!(window.hmStill && window.hmStill()));
      var next = (cur + 1) % slides.length, a = slides[cur], z = slides[next];
      z.style.transition = 'none'; z.className = 'hm-car-s below'; void z.offsetWidth; z.style.transition = '';
      z.className = 'hm-car-s'; a.className = 'hm-car-s above';
      cur = next; show(cur);
    }, EVERY);
  }
  (window.hmAfterGlass = window.hmAfterGlass || []).push(build);
  setTimeout(build, 0);
})();</script>"""

# After the heatmap's script has built the deck list's glass box: runs what was waiting to go
# into it (the Today pill, the notices) right away, before the page first shows, so nothing
# jumps into place afterwards.
_AFTER_GLASS = """<script>(function(){
  var q = window.hmAfterGlass || [];
  window.hmAfterGlass = { push: function (f) { f(); } };
  q.forEach(function (f) { try { f(); } catch (e) {} });
})();</script>"""
_last_counts = None     # {deck id: [new, learn, due]} at the last finished deck list
_last_rows = None       # deck ids shown at the last deck list, in order
_ROW_ID = re.compile(r"<tr class='deck[^']*' id='(\d+)'")


def _row_enter_css(mode):
    css = ("@keyframes hmRowIn { from { opacity: 0 } to { opacity: 1 } }"
           "tr.hm-enter > td { animation: hmRowIn .28s ease-out both }")
    return f"<style>{css}</style>" if mode == "on" else f"<style>@media (prefers-reduced-motion: no-preference) {{{css}}}</style>"


def render(deck_browser, content):
    with _HomeDark():
        _render(deck_browser, content)


def _render(deck_browser, content):
    global _drawn_key, _page_key
    _page_key = None
    cfg = get_config()
    setup_timer()

    hide_studied_css = lowpower.style(cfg)
    if cfg.get('replace_stats', True):
        hide_studied_css += "<style>#studiedToday { display: none !important; }</style>"

    # Done for today: nothing left in any deck, after studying some today.
    done = False
    try:
        tree = deck_browser._render_data.tree
        left = sum(c.new_count + c.learn_count + c.review_count for c in tree.children)
        done = not left and bool(mw.col.db.scalar(
            "SELECT 1 FROM revlog WHERE id > ? LIMIT 1", (mw.col.sched.day_cutoff - 86400) * 1000))
    except Exception:
        pass

    # Time left: adds the deck list's Time column, and returns today's total pill
    # to sit between the deck list and the heatmap.
    try:
        time_html = time_left.deck_browser(deck_browser, content, done)
    except Exception:
        time_html = ""

    # Subdecks you just opened (rows that weren't there last time, none gone) ease in.
    global _last_rows
    try:
        rows = _ROW_ID.findall(content.tree or "")
        shown = set(_last_rows or ())
        new = [r for r in rows if r not in shown]
        if (_last_rows and new and shown.issubset(rows) and lowpower.motion(cfg) != 'off'):
            new = set(new)
            content.tree = _ROW_ID.sub(lambda mo: mo.group(0).replace("class='deck", "class='deck hm-enter", 1)
                                       if mo.group(1) in new else mo.group(0), content.tree)
            hide_studied_css += _row_enter_css(lowpower.motion(cfg))
        _last_rows = rows
    except Exception:
        pass

    # The deck list's badges take their numbers from here (Anki's own tree, the
    # same data the table was rendered from) rather than parsing the cells.
    counts_js = ""
    try:
        counts = {}
        def walk(node):
            for child in node.children:
                counts[str(child.deck_id)] = [child.new_count, child.learn_count, child.review_count]
                walk(child)
        walk(deck_browser._render_data.tree)
        counts_js = f"<script>window.hmDeckCounts = {json.dumps(counts)};</script>"
    except Exception:
        counts = None

    try:
        heatmap_html = _heatmap_html("deckBrowser", _refresh_deck_browser, **_main_heatmap_args(cfg))
        # Drawn in full: the minute's refresh can skip until something changes. (A
        # dimmed placeholder or a forecast still renewing leaves it on.)
        _drawn_key = None if "deckBrowser" in _PLACEHOLDER or "deckBrowser" in _WARMING else _refresh_key()
        existing = content.stats or ""

        # The deck list's animations, only on one with final numbers (not the dimmed one
        # shown while the background job runs, which is redrawn when it's done).
        moments_css = ""
        if "deckBrowser" not in _PLACEHOLDER:
            try:
                f = _home_facts
                rolls = (cfg.get("streak_display", "streak") not in ("pct_week", "pct_month")
                         and cfg.get("show_stats_bar", True) and f.get("today_revs", 0) > 0)
                moments_css = moments.deck_browser(str(mw.col.sched.today), done, cfg.get('today_color', '#2ecc71'),
                                                   lowpower.motion(cfg),
                                                   streak=int(f.get("streak", 0) or 0) if rolls else 0,
                                                   longest=_longest_streak(f.get("hist") or {}) if rolls else 0)
                if lowpower.motion(cfg) != 'off':
                    moments_css += time_left.finish_roll()
                else:
                    time_left.finish_roll()     # still remember what this deck list shows
            except Exception:
                pass
            # last deck list's counts, for the ones that went down to tick down
            global _last_counts
            if counts:
                if _last_counts and _last_counts != counts and lowpower.motion(cfg) != 'off':
                    moments_css += f"<script>window.hmPrevCounts = {json.dumps(_last_counts)};</script>"
                _last_counts = counts
                _page_key = _refresh_key()

        exam_html = ""
        notes = (_deck_notices(cfg, today_pill='id="rt-today"' in time_html)
                 if "deckBrowser" not in _PLACEHOLDER else [])
        if notes:
            exam_html = (f'<style>{_EXAM_CSS}</style><div class="hm-notes" id="hm-notes">'
                         + "".join('<div class="hm-note" data-today></div>' if n == TODAY_SLOT else f'<div class="hm-note">{n}</div>'
                                   for n in notes) + "</div>" + _EXAM_JS)

        content.stats = hide_studied_css + counts_js + moments_css + time_html + exam_html + heatmap_html + _AFTER_GLASS + existing

    except Exception as e:
        import traceback
        error_msg = f"<div style='color:red; padding:10px;'>HEATMAP ERROR: {str(e)}<br>{traceback.format_exc()}</div>"
        content.stats += error_msg

def on_msg(h, m, c):
    if m == "heatmap:settings": open_settings(); return True, None
    if m == "heatmap:rt:missing":
        review_pill.marker_missing()
        return True, None
    if m.startswith("heatmap:rt:shown:"):
        review_pill.card_shown(m[len("heatmap:rt:shown:"):])
        return True, None
    if m.startswith("heatmap:ringlog:"):
        review_pill.on_ring_report(m[len("heatmap:ringlog:"):])
        return True, None
    if m.startswith("heatmap:older:"):
        try:
            _older_weeks(m[len("heatmap:older:"):], getattr(c, "web", None))
        except Exception:
            _log_exc()
        return True, None
    if m == "heatmap:pomo:click":
        pomodoro.click()
        return True, None
    if m == "heatmap:pomo:stop":
        pomodoro.stop()
        return True, None
    if m == "heatmap:pomo:start":
        pomodoro.start()
        return True, None
    if m.startswith("heatmap:savemode:"):
        # The page already recolored itself (hmSetMode); just remember the view.
        new_mode = m.split(":")[2]
        if new_mode in HEATMAP_MODES:
            cfg = get_config()
            cfg['display_mode'] = new_mode
            write_config(cfg, clear_caches=False)
        return True, None
    if m.startswith("heatmap:setmode:"):
        new_mode = m.split(":")[2]
        cfg = get_config()
        cfg['display_mode'] = new_mode
        write_config(cfg, clear_caches=False)
        _refresh_heatmap_screen()
        return True, None

    if m.startswith("heatmap:moment:"):
        try:
            moments.mark(m.split(":")[2], str(mw.col.sched.today))
        except Exception:
            pass
        return True, None
    if m == "heatmap:stats":
        _open_stats()
        return True, None
    if m.startswith("heatmap:browse:"):
        _browse_day(m.split(":")[2])
        return True, None
    if m.startswith("heatmap:note:"):
        date_str = m.split(":")[2]
        if day_view.available() and _open_day_view(date_str):
            return True, None
        _edit_day_note(date_str)
        return True, None
    return h


def _heatmap_scope():
    """(deck ids, label) of the heatmap on screen: the overview's deck, else the deck
    browser's deck filter."""
    cfg = get_config()
    if mw.state == "overview":
        deck = mw.col.decks.current()
        deck_ids = get_deck_and_children_ids(deck['id']) if cfg.get('overview_filter_current_deck', True) else None
        return deck_ids, (deck['name'] if deck_ids else "All decks")
    deck_ids = _main_heatmap_args(cfg)["deck_ids"]
    return deck_ids, ("Selected decks" if deck_ids else "All decks")


def _open_day_view(date_str):
    """Past days and today open the day view, in the scope of the heatmap that was
    clicked; future days (exam dates) go straight to the note dialog."""
    try:
        roll = int(mw.col.get_config("rollover", 4))
        if date_str > (datetime.datetime.now() - datetime.timedelta(hours=roll)).date().isoformat():
            return False
        deck_ids, scope = _heatmap_scope()
        day_view.show(date_str, deck_ids, scope)
        return True
    except Exception:
        _log_exc()
        return False


def _browse_day(date_str):
    """Ctrl/Cmd-click on a day: the Browser with the cards due that day (today: everything
    due now), or for a past day the cards you answered, in the heatmap's decks."""
    try:
        roll = int(mw.col.get_config("rollover", 4))
        today = (datetime.datetime.now() - datetime.timedelta(hours=roll)).date()
        n = (datetime.date.fromisoformat(date_str) - today).days
        if n > 0:
            query = f"prop:due={n}"
        elif n == 0:
            query = "is:due"
        else:
            query = f"prop:rated={n}"
        deck_ids, _scope = _heatmap_scope()
        if deck_ids:
            query = f"did:{','.join(str(int(d)) for d in deck_ids)} {query}"
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(query)
    except Exception:
        _log_exc()


def _open_stats():
    if mw.col is None or not stats_view.available():
        return
    try:
        deck_ids, scope = _heatmap_scope()
    except Exception:
        _log_exc()
        deck_ids, scope = None, "All decks"
    stats_view.show(deck_ids, scope)


def _edit_day_note(date_str):
    """The note and exam dialog for one day; True when it saved."""
    cfg = get_config()
    notes = cfg.get('daily_notes', {})
    raw_exams = cfg.get("exam_days", {})
    if isinstance(raw_exams, list):
        exams = {d: {"label": "Exam", "color": "#e74c3c"} for d in raw_exams}
    else:
        exams = raw_exams
        
    exam_data = exams.get(date_str)
    current_note = notes.get(date_str, "")
    
    dlg = HeatmapNoteDialog(date_str, current_note, exam_data, mw)
    
    if dlg.exec():
        new_text = dlg.get_text()
        new_exam_data = dlg.get_exam_result()
        
        if new_text: notes[date_str] = new_text
        elif date_str in notes: del notes[date_str]
        cfg['daily_notes'] = notes
        
        if new_exam_data: exams[date_str] = new_exam_data
        elif date_str in exams: del exams[date_str]
        cfg['exam_days'] = exams

        write_config(cfg, clear_caches=False)
        _refresh_heatmap_screen()
        return True
    return False

gui_hooks.webview_did_receive_js_message.append(on_msg)
day_view.setup(get_config, _edit_day_note)
stats_view.setup(get_config)


_settings_dialog = None


def open_settings():
    # A plain window, not exec(): the Time Left tab opens a web view (the accuracy
    # window), and on macOS a web view created inside a modal exec() loop breaks it,
    # leaving Anki unable to take clicks. One Settings window at a time.
    global _settings_dialog
    try:
        if _settings_dialog is not None and _settings_dialog.isVisible():
            _settings_dialog.raise_()
            _settings_dialog.activateWindow()
            return
    except RuntimeError:        # already deleted
        pass
    _settings_dialog = HeatmapSettingsDialog(mw)
    _settings_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    _settings_dialog.finished.connect(_settings_dialog.deleteLater)     # Save and Cancel only hide it
    _settings_dialog.show()
    _settings_dialog.raise_()
    _settings_dialog.activateWindow()


mw.addonManager.setConfigAction(__name__, open_settings)
try:
    _settings_action = QAction("Elemental Settings…", mw)
    try:
        _settings_action.setIcon(brand.icon(get_config().get("base_color", "#8e44ad"), _is_dark_mode()))
    except Exception:
        pass
    qconnect(_settings_action.triggered, lambda: open_settings())
    mw.form.menuTools.addAction(_settings_action)
    _stats_action = QAction("Your Stats…", mw)
    qconnect(_stats_action.triggered, lambda: _open_stats())
    mw.form.menuTools.addAction(_stats_action)
except Exception:
    pass
try: gui_hooks.deck_browser_will_render_content.remove(render)
except: pass
gui_hooks.deck_browser_will_render_content.append(render)


# Anki redraws the deck list every 10 minutes (onRefreshTimer) so learning cards that came
# due show up. That reloads the whole page (photo, glass, heatmap, notices) and shows as a
# flash. For that redraw only, the numbers are changed in place: the counts, the Time
# column and the Today pill. The page still reloads when more changed (a new day, an
# answer or edit, the theme, the decks shown) or when it went from done to not done.
_page_key = None        # _refresh_key() when the deck list on screen got its final numbers

_QUIET_JS = """(function (d) {
  window.hmDeckCounts = d.counts;
  if (typeof d.due === 'number') [].forEach.call(document.querySelectorAll('.stat-group'), function (g) {
    var l = g.querySelector('.stat-lbl'), v = g.querySelector('.stat-val');
    if (l && v && l.textContent.trim() === 'DUE') v.textContent = d.due;
  });
  var kinds = [['badge-new', 'new-count'], ['badge-lrn', 'learn-count'], ['badge-due', 'review-count']];
  Object.keys(d.changed).forEach(function (did) {
    var row = document.getElementById(did), v = d.changed[did];
    var cells = row ? row.getElementsByTagName('td') : [];
    if (cells.length < 5) return;
    for (var k = 0; k < 3; k++) {
      var span = cells[k + 1].querySelector('.stat-badge');
      if (span) { span.innerText = v[k]; span.className = 'stat-badge ' + (v[k] > 0 ? kinds[k][0] : 'badge-dim'); }
      else cells[k + 1].innerHTML = '<span class="' + (v[k] ? kinds[k][1] : 'zero-count') + '">' + v[k] + '</span>';
    }
  });
  Object.keys(d.cells).forEach(function (did) {
    var row = document.getElementById(did), old = row && row.querySelector('td.rt-time');
    if (!old || !d.cells[did]) return;
    var t = document.createElement('table'); t.innerHTML = '<tbody><tr>' + d.cells[did] + '</tr></tbody>';
    var td = t.querySelector('td'); if (td) old.replaceWith(td);
  });
  // The Today pill may sit in the notices' carousel: change just its text, not the box.
  var t = document.getElementById('rt-today'), old = t && t.querySelector('.rt-pill:not(.hm-note-pill)');
  if (old && d.pill) {
    var w = document.createElement('div'); w.innerHTML = d.pill;
    var nt = w.querySelector('#rt-today'), np = nt && nt.querySelector('.rt-pill');
    if (np) {
      old.className = np.className; old.innerHTML = np.innerHTML;
      if (t.title && nt.title) t.title = nt.title;
      var win = t.querySelector('.hm-car-win');
      if (win) win.style.width = Math.max(parseFloat(win.style.width) || 0, old.offsetWidth + 6) + 'px';
    }
  }
})(%s);"""


def _tree_rows(tree):
    """(deck ids shown, in order; {deck id: [new, learn, due]} for every deck)"""
    rows, counts = [], {}

    def walk(node, shown):
        for c in node.children:
            did = str(c.deck_id)
            counts[did] = [c.new_count, c.learn_count, c.review_count]
            if shown:
                rows.append(did)
            walk(c, shown and not c.collapsed)
    walk(tree, True)
    return rows, counts


def _quiet_refresh(full):
    if QueryOp is None or _page_key is None or "deckBrowser" in _PLACEHOLDER or "deckBrowser" in _WARMING:
        return full()

    deck_ids = _main_heatmap_args(get_config())["deck_ids"]

    def op(col):
        try:
            due = _cards_due(col, deck_ids, col.sched.today, int(time.time()))
        except Exception:
            due = None
        return col.sched.deck_due_tree(), due

    def done(result):
        global _last_counts
        if mw.state != "deckBrowser":
            return
        tree, due = result
        try:
            rows, counts = _tree_rows(tree)
            if (_refresh_key() != _page_key or rows != _last_rows or not _last_counts
                    or not any(sum(v) for v in _last_counts.values())
                    or not any(sum(counts[r]) for r in rows)):
                return full()
            changed = {did: v for did, v in counts.items() if _last_counts.get(did) != v}
            cells, pill = {}, ""
            try:
                fake = types.SimpleNamespace(tree="<th class=optscol></th>" + "".join(
                    f"<tr class='deck' id='{r}'><td align=center class=opts>" for r in rows))
                pill = time_left.deck_browser(types.SimpleNamespace(
                    _render_data=types.SimpleNamespace(tree=tree)), fake, False)
                time_left.finish_roll()     # what the pill shows now, so the next redraw rolls from it
                cells = dict(re.findall(r"<tr class='deck' id='(\d+)'>(.*?)<td align=center class=opts>",
                                        fake.tree, flags=re.S))
            except Exception:
                _log_exc()
            mw.deckBrowser.web.eval(_QUIET_JS % json.dumps(
                {"counts": counts, "changed": changed, "cells": cells, "pill": pill, "due": due}))
            _last_counts = counts
        except Exception:
            _log_exc()
            full()

    def drawn(result):
        with _HomeDark():
            done(result)

    QueryOp(parent=mw, op=op, success=drawn) \
        .failure(lambda _e: full()).run_in_background()


def _patch_timer_refresh():
    """Route Anki's 10-minute redraw of the deck list to _quiet_refresh. Anki set its timer
    up before add-ons load, so the deck list's refresh is wrapped and only a call from
    onRefreshTimer goes the quiet way; every other redraw is Anki's own."""
    db = getattr(mw, "deckBrowser", None)
    if db is None or getattr(db.refresh, "_hm_quiet", False):
        return
    full = db.refresh

    def refresh(*args, **kwargs):
        try:
            from_timer = sys._getframe(1).f_code.co_name == "onRefreshTimer"
        except Exception:
            from_timer = False
        if from_timer and mw.state == "deckBrowser" and not args and not kwargs:
            try:
                return _quiet_refresh(full)
            except Exception:
                _log_exc()
        return full(*args, **kwargs)
    refresh._hm_quiet = True
    db.refresh = refresh


_patch_timer_refresh()


_HOME_SCREENS = ("deckBrowser", "overview")

# Anki's own dark/light marks on a page that's already up (as Anki does on a theme change)
_DARK_MARKS_JS = """(function(dark){
    var doc = document.documentElement, body = document.body;
    doc.classList.toggle('night-mode', dark);
    doc.dataset.bsTheme = dark ? 'dark' : 'light';
    if (body) { body.classList.toggle('nightMode', dark); body.classList.toggle('night_mode', dark); }
})(%s);"""


def _home_forced() -> bool:
    """"Always dark" is on and Anki is light: the home screens are drawn dark by us."""
    try:
        from aqt.theme import theme_manager
        return _home_always_dark() and not theme_manager.night_mode
    except Exception:
        return False


def _web_backdrop(web, forced: bool) -> None:
    """The web view's own color (what shows before its page paints). Only touched when
    forced, or to undo an earlier forced one; otherwise it's Anki's."""
    if not forced and not getattr(web, "_hm_forced", False):
        return
    from aqt.theme import theme_manager
    from aqt import colors
    web.page().setBackgroundColor(QColor(colors.CANVAS["dark"]) if forced else theme_manager.qcolor(colors.CANVAS))
    web._hm_forced = forced


def _home_dark_page(web_content, context):
    """With "Always dark" on and Anki light: the deck list, the overview and their top and
    bottom bars get Anki's own dark-mode marks (so its CSS and ours turn dark) before
    anything paints, and a dark backdrop. The review screen and its bottom bar stay light."""
    try:
        from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar
        from aqt.overview import Overview, OverviewBottomBar
        from aqt.reviewer import Reviewer, ReviewerBottomBar
        from aqt.toolbar import TopToolbar
        if isinstance(context, (DeckBrowser, Overview)):
            web, home = mw.web, True
        elif isinstance(context, Reviewer):
            web, home = mw.web, False
        elif isinstance(context, (DeckBrowserBottomBar, OverviewBottomBar)):
            web, home = mw.bottomWeb, True
        elif isinstance(context, ReviewerBottomBar):
            web, home = mw.bottomWeb, False
        elif isinstance(context, TopToolbar):
            web, home = mw.toolbar.web, mw.state in _HOME_SCREENS
        else:
            return
        forced = home and _home_forced()
        _web_backdrop(web, forced)
        if forced:
            web_content.head += ("<script>document.documentElement.classList.add('night-mode');"
                                 "document.documentElement.dataset.bsTheme = 'dark';</script>")
            web_content.body = ("<script>document.body.classList.add('nightMode', 'night_mode');</script>"
                                + web_content.body)
    except Exception:
        _log_exc()


def _home_dark_marks(web, forced: bool) -> None:
    """Switch a page that's already up between our dark and Anki's own theme."""
    if not forced and not getattr(web, "_hm_forced", False):
        return
    from aqt.theme import theme_manager
    _web_backdrop(web, forced)
    web.eval(_DARK_MARKS_JS % ("true" if forced or theme_manager.night_mode else "false"))


def _home_dark_toolbar(new_state, old_state):
    """The top bar isn't redrawn with each screen: dark on the home screens, light in review."""
    try:
        _home_dark_marks(mw.toolbar.web, new_state in _HOME_SCREENS and _home_forced())
    except Exception:
        _log_exc()


def _home_dark_congrats(web):
    """The overview's "Congratulations" page is one Anki loads itself (no set-content hook)."""
    try:
        if web is mw.web and mw.state == "overview" and _home_forced():
            _home_dark_marks(web, True)
    except Exception:
        _log_exc()


try: gui_hooks.webview_will_set_content.remove(_home_dark_page)
except Exception: pass
gui_hooks.webview_will_set_content.append(_home_dark_page)
try: gui_hooks.state_did_change.remove(_home_dark_toolbar)
except Exception: pass
gui_hooks.state_did_change.append(_home_dark_toolbar)
try: gui_hooks.webview_did_inject_style_into_page.remove(_home_dark_congrats)
except Exception: pass
gui_hooks.webview_did_inject_style_into_page.append(_home_dark_congrats)


def _note_return_home(new_state, old_state):
    # before the deck list draws, so that drawing knows it's a return (the graph draws on)
    if new_state == "deckBrowser" and old_state != "deckBrowser":
        moments.came_home()


try: gui_hooks.state_will_change.remove(_note_return_home)
except Exception: pass
gui_hooks.state_will_change.append(_note_return_home)

def render_overview(overview, content):
    with _HomeDark():
        _render_overview(overview, content)


def _render_overview(overview, content):
    """Render heatmap on the overview screen (before studying a deck)."""
    cfg = get_config()

    # Time left goes right under the counts table, above everything appended below.
    try:
        time_left.overview(overview, content)
    except Exception:
        pass

    # Always inject pill styling for the count badges (New / Learning / Due)
    pill_new   = cfg.get('pill_new_color',   '#4a90e2')
    pill_learn = cfg.get('pill_learn_color', '#e74c3c')
    pill_due   = cfg.get('pill_due_color',   '#f1c40f')
    pill_inject = rf"""
<style>
.ov-pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    min-width: 42px;
    text-align: center;
}}
.ov-pill-dim {{ opacity: 0.15; font-weight: 400; }}
.ov-pill-new {{ color: {pill_new};   background: {pill_new}38;   border: 1px solid {pill_new}80; }}
.ov-pill-lrn {{ color: {pill_learn}; background: {pill_learn}38; border: 1px solid {pill_learn}80; }}
.ov-pill-due {{ color: {pill_due};   background: {pill_due}38;   border: 1px solid {pill_due}80; }}
/* Row labels ("To Review:") stay on one line */
.overview-glass-container td:first-child {{ white-space: nowrap; }}
/* Keep "Study Now" on one line */
#study, .overview-glass-container button {{ white-space: nowrap !important; }}
</style>
<script>
(function() {{
    function applyOvPills() {{
        var bolds = Array.from(document.querySelectorAll('b'));
        var numBolds = bolds.filter(function(b) {{
            return !b.querySelector('.later-count') && /^\s*\d+\s*$/.test(b.innerText);
        }});
        applyLaterPill();
        var types = ['ov-pill-new', 'ov-pill-lrn', 'ov-pill-due'];
        for (var j = 0; j < Math.min(3, numBolds.length); j++) {{
            var b = numBolds[j];
            if (b.querySelector('.ov-pill')) return;
            var val = parseInt(b.innerText.trim(), 10);
            var span = document.createElement('span');
            span.innerText = val;
            span.className = 'ov-pill ' + (val > 0 ? types[j] : 'ov-pill-dim');
            b.innerHTML = '';
            b.appendChild(span);
        }}
    }}
    // Later-button addon adds a 4th row: <b><span class=later-count>N</span></b>
    // followed by "(next one back in about X cards)". Match the other pills.
    function applyLaterPill() {{
        var lc = document.querySelector('span.later-count');
        if (!lc || lc.classList.contains('ov-pill')) return;
        var val = parseInt(lc.innerText.trim(), 10) || 0;
        var c = lc.style.color || '#9b7ede';
        lc.className = 'later-count ov-pill' + (val > 0 ? '' : ' ov-pill-dim');
        if (val > 0) {{
            lc.style.cssText = 'color:' + c + ';background:color-mix(in srgb,' + c + ' 13%,transparent);'
                + 'border:1px solid color-mix(in srgb,' + c + ' 31%,transparent)';
        }}
        // Drop the "(next one back in about X cards)" estimate.
        var b = lc.closest('b');
        var note = b && b.nextElementSibling;
        if (note && note.tagName === 'SPAN') note.remove();
    }}
    applyOvPills();
    setTimeout(applyOvPills, 80);
}})();
</script>"""
    if not cfg.get("deck_count_pills", True):     # Anki's own plain numbers: keep only the layout fixes
        pill_inject = pill_inject[:pill_inject.index("<script>")]
    content.table = (content.table or "") + pill_inject + lowpower.style(cfg)

    if not cfg.get('show_overview_heatmap', True):
        return

    try:
        # Get current deck ID
        current_deck_id = mw.col.decks.current()['id']

        # Determine deck filtering
        deck_ids = None
        if cfg.get('overview_filter_current_deck', True):
            # Get all child deck IDs (for parent decks)
            deck_ids = get_deck_and_children_ids(current_deck_id)

        # Generate heatmap HTML filtered to this deck (skip deck browser modifications)
        heatmap_html = _heatmap_html(("overview", current_deck_id), _refresh_overview,
                                     deck_ids=deck_ids, is_overview=True)

        # Append heatmap below the study button and card counts
        content.table = (content.table or "") + heatmap_html
    except Exception as e:
        import traceback
        error_msg = f"<div style='color:red; padding:10px;'>HEATMAP ERROR: {str(e)}<br>{traceback.format_exc()}</div>"
        content.table = (content.table or "") + error_msg

try: gui_hooks.overview_will_render_content.remove(render_overview)
except: pass
gui_hooks.overview_will_render_content.append(render_overview)


def _plain_later_button():
    """The Later-button addon gives its reviewer button purple text and a purple
    hover/press fill via an inline <style>. Strip it so the button uses Anki's
    default look, same as Again/Hard/Good/Easy. Wrapped after all addons load so
    it sits on top of Later's own _answerButtons patch."""
    from aqt.reviewer import Reviewer
    orig = Reviewer._answerButtons
    if getattr(orig, "_hm_plain_later", False):
        return

    def _answerButtons(self):
        html = orig(self)
        return re.sub(r"<style>#laterbut\{.*?</style>", "", html, count=1, flags=re.S)

    _answerButtons._hm_plain_later = True
    Reviewer._answerButtons = _answerButtons

try: gui_hooks.main_window_did_init.remove(_plain_later_button)
except: pass
gui_hooks.main_window_did_init.append(_plain_later_button)

from aqt import mw, gui_hooks
from aqt.qt import *
from anki.cards import Card
import re
import sys
import types

# Count pills off: the counts look like Anki's own (its colors, plain text, faint zeros).
PLAIN_COUNTS_CSS = """
        .stat-badge { padding: 0; width: auto; min-width: 0; border-radius: 0; font-size: 14px; font-weight: 400;
                      background: none !important; border: none !important; }
        .badge-new { color: var(--state-new, #3b82f6); }
        .badge-lrn { color: var(--state-learn, #dc2626); }
        .badge-due { color: var(--state-review, #16a34a); }
        .badge-dim { color: var(--fg-faint, #afafaf); opacity: 1; }
"""


class ModernBrowserDelegate(QStyledItemDelegate):
    def __init__(self, browser, theme_color="#8e44ad"):
        super().__init__(browser)
        self.browser = browser
        self.theme_color = theme_color

        # Load color theme from config
        try:
            config = mw.addonManager.getConfig(__name__)
            use_custom = config.get("browser_custom_colors", False)

            if use_custom:
                # Use custom colors from config
                self.color_theme = {
                    "bg_primary": config.get("browser_bg_primary", "#1e1e1e"),
                    "bg_secondary": config.get("browser_bg_secondary", "#252525"),
                    "bg_suspended": config.get("browser_bg_suspended", "#3a2f1a"),
                    "bg_buried": config.get("browser_bg_buried", "#1a2a3a"),
                    "bg_marked": config.get("browser_bg_marked", "#3a1a3a"),
                    "text_normal": config.get("browser_text_normal", "#e0e0e0"),
                    "text_suspended": config.get("browser_text_suspended", "#d4af37"),
                    "text_buried": config.get("browser_text_buried", "#6c91b0"),
                    "text_marked": config.get("browser_text_marked", "#c792ea"),
                    "selection": config.get("browser_selection", "#8e44ad"),
                    "flag_1": config.get("browser_flag_1", "#e25555"),
                    "flag_2": config.get("browser_flag_2", "#ff9632"),
                    "flag_3": config.get("browser_flag_3", "#32cd32"),
                    "flag_4": config.get("browser_flag_4", "#56b4e9"),
                    "flag_5": config.get("browser_flag_5", "#ff82ab"),
                    "flag_6": config.get("browser_flag_6", "#009688"),
                    "flag_7": config.get("browser_flag_7", "#7c4dff"),
                }
            else:
                # Use preset theme (default follows Anki's light/dark mode)
                theme_key = _resolve_browser_theme_key(config)
                self.color_theme = BROWSER_THEMES.get(theme_key, BROWSER_THEMES["default"])
        except:
            self.color_theme = BROWSER_THEMES["default"]

        try:
            config = mw.addonManager.getConfig(__name__) or {}
        except Exception:
            config = {}
        self.show_state_icons = config.get("browser_state_icons", True)
        self.tag_display = config.get("browser_tag_display", "full")

        # Cloze colors optimized for both dark and suspended backgrounds
        self.cloze_colors = [
            "#3b82f6",  # Bright blue
            "#10b981",  # Emerald
            "#FFB8FA",  # Pink
            "#8b5cf6",  # Purple
            "#ec4899",  # Hot pink
            "#14b8a6",  # Teal
            "#f97316",  # Orange
            "#06b6d4",  # Cyan
        ]

        # Cache for card IDs
        self._card_cache = {}
    
    def _get_card_id_from_index(self, index):
        """Get card ID from index"""
        try:
            row = index.row()
            if hasattr(self.browser, 'table'):
                table = self.browser.table
                if hasattr(table, 'get_card_id'):
                    return table.get_card_id(row)
                if hasattr(table, '_model') and hasattr(table._model, '_items'):
                    items = table._model._items
                    if row < len(items):
                        return items[row]
        except:
            pass
        return None

    def _get_card_state(self, card_id):
        """Get card state: suspended, buried, marked, flag"""
        default_state = {"suspended": False, "buried": False, "marked": False, "flag": 0}
        if card_id is None:
            return default_state

        cache_key = f"state_{card_id}"
        if cache_key in self._card_cache:
            return self._card_cache[cache_key]

        if len(self._card_cache) > 1000:
            self._card_cache.clear()

        try:
            if not mw or not mw.col:
                return default_state
            card = mw.col.get_card(card_id)
            if not card:
                return default_state

            is_marked = False
            try:
                note = card.note()
                if note and hasattr(note, 'has_tag'):
                    is_marked = note.has_tag("marked")
                elif note:
                    is_marked = any(t.lower().startswith("marked") for t in note.tags)
            except:
                pass

            state = {
                "suspended": card.queue == -1,
                "buried": card.queue in (-2, -3),
                "marked": is_marked,
                "flag": card.flags if hasattr(card, 'flags') else 0
            }
            self._card_cache[cache_key] = state
            return state
        except:
            return default_state
    
    def paint(self, painter, option, index):
        """Custom paint with modern dark styling"""
        try:
            self._custom_paint(painter, option, index)
        except Exception:
            # Fallback to default painting if custom paint fails
            super().paint(painter, option, index)

    def _custom_paint(self, painter, option, index):
        """Internal custom paint implementation"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get card state
        card_id = self._get_card_id_from_index(index)
        card_state = self._get_card_state(card_id)
        is_suspended = card_state.get("suspended", False)
        is_buried = card_state.get("buried", False)
        is_marked = card_state.get("marked", False)
        flag = card_state.get("flag", 0)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Flag colors from theme
        flag_colors = {
            1: self.color_theme.get("flag_1", "#e25555"),
            2: self.color_theme.get("flag_2", "#ff9632"),
            3: self.color_theme.get("flag_3", "#32cd32"),
            4: self.color_theme.get("flag_4", "#56b4e9"),
            5: self.color_theme.get("flag_5", "#ff82ab"),
            6: self.color_theme.get("flag_6", "#009688"),
            7: self.color_theme.get("flag_7", "#7c4dff"),
        }

        # Determine background color based on state priority (using theme colors)
        if is_selected:
            bg_color = QColor(self.color_theme.get("selection", self.theme_color))
        elif flag > 0 and flag in flag_colors:
            # Subtle flag tint
            fc = QColor(flag_colors[flag])
            fc.setAlpha(40)
            bg_color = fc
        elif is_suspended:
            bg_color = QColor(self.color_theme.get("bg_suspended", "#3a2f1a"))
        elif is_buried:
            bg_color = QColor(self.color_theme.get("bg_buried", "#1a2a3a"))
        elif is_marked:
            bg_color = QColor(self.color_theme.get("bg_marked", "#3a1a3a"))
        else:
            # Subtle alternating rows
            if index.row() % 2 == 0:
                bg_color = QColor(self.color_theme.get("bg_primary", "#1e1e1e"))
            else:
                bg_color = QColor(self.color_theme.get("bg_secondary", "#252525"))

        # Paint background
        rect = QRectF(option.rect)
        rect.adjust(2, 1, -2, -1)
        painter.fillRect(rect, bg_color)

        # Draw state icon in first column
        icon_offset = 0
        if index.column() == 0 and self.show_state_icons:
            icon_size = 14
            icon_x = rect.x() + 8
            icon_y = rect.y() + (rect.height() - icon_size) / 2

            if is_suspended:
                # Pause bars (‖). Drawn in the suspended color even on flagged rows,
                # where the flag tint replaces the suspended background and text
                # color — the bars are then the only sign the card is suspended.
                bar_color = QColor(self.color_theme.get("text_suspended", "#d4af37"))
                if is_selected:
                    bar_color = QColor("#ffffff")
                painter.setBrush(bar_color)
                painter.setPen(Qt.PenStyle.NoPen)
                bar_w, bar_h = 3, 11
                bar_y = icon_y + (icon_size - bar_h) / 2
                painter.drawRoundedRect(QRectF(icon_x + 3, bar_y, bar_w, bar_h), 1, 1)
                painter.drawRoundedRect(QRectF(icon_x + 8, bar_y, bar_w, bar_h), 1, 1)
                icon_offset = 24
            elif is_buried:
                # Draw a buried indicator (blue circle)
                painter.setBrush(QColor(self.color_theme.get("text_buried", "#6c91b0")))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(icon_x + icon_size/2, icon_y + icon_size/2), 5, 5)
                icon_offset = 24
            elif is_marked:
                # Draw a star icon for marked cards
                marked_color = QColor(self.color_theme.get("text_marked", "#c792ea"))
                painter.setBrush(marked_color)
                painter.setPen(Qt.PenStyle.NoPen)
                cx, cy = icon_x + icon_size/2, icon_y + icon_size/2
                if QPolygonF:
                    # Draw a 5-point star
                    outer_r, inner_r = 7, 3
                    points = []
                    for i in range(10):
                        angle = math.pi/2 + i * math.pi/5
                        r = outer_r if i % 2 == 0 else inner_r
                        points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
                    painter.drawPolygon(QPolygonF(points))
                else:
                    # Fallback: draw a simple diamond
                    painter.drawEllipse(QPointF(cx, cy), 6, 6)
                icon_offset = 24

        # Process text with cloze styling
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            text = str(text)
            text = self._clean_text(text)
            if self.tag_display != "full" and self._column_key(index) == "noteTags":
                text = self._format_tags(text)

            # Determine text color based on state (using theme colors)
            if is_selected:
                text_color = QColor(themes.readable_text(self.color_theme.get("selection", self.theme_color)))
            elif flag > 0 and flag in flag_colors:
                text_color = QColor(flag_colors[flag])
            elif is_suspended:
                text_color = QColor(self.color_theme.get("text_suspended", "#d4af37"))
            elif is_buried:
                text_color = QColor(self.color_theme.get("text_buried", "#6c91b0"))
            elif is_marked:
                text_color = QColor(self.color_theme.get("text_marked", "#c792ea"))
            else:
                text_color = QColor(self.color_theme.get("text_normal", "#e0e0e0"))
            
            text_x = rect.x() + icon_offset + 12
            text_width = rect.width() - icon_offset - 24
            text_y = rect.y() + (rect.height() - option.fontMetrics.height()) / 2

            if "{{c" in text:
                self._paint_text_with_clozes(painter, text, text_x, text_y, text_width, 
                                            option, text_color, is_selected, is_suspended)
            else:
                painter.setPen(text_color)
                painter.setFont(option.font)
                plain_text = re.sub(r'<[^>]+>', '', text)
                elided_text = option.fontMetrics.elidedText(
                    plain_text, 
                    Qt.TextElideMode.ElideRight, 
                    int(text_width)
                )
                # Center text vertically properly
                text_rect = QRectF(text_x, rect.y(), text_width, rect.height())
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_text)
        
        painter.restore()
    
    def _column_key(self, index):
        """Browser column key ('noteTags', 'deck', ...) for this cell, or None"""
        try:
            return self.browser.table._state.column_key_at(index.column())
        except Exception:
            return None

    def _format_tags(self, text):
        """Shorten hierarchical tags: last part only ('leaf') or '::' shown as ' › '"""
        tags = text.split()
        if self.tag_display == "leaf":
            seen, out = set(), []
            for t in tags:
                leaf = t.rstrip(":").split("::")[-1] or t
                if leaf not in seen:
                    seen.add(leaf)
                    out.append(leaf)
            return "  ".join(out)
        if self.tag_display == "arrows":
            return "   ".join(t.replace("::", " › ") for t in tags)
        return text

    def _clean_text(self, text):
        """Clean HTML and formatting from text"""
        text = text.replace("&nbsp;", " ")
        text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<div[^>]*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'</div>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
        text = ' '.join(text.split())
        return text
    
    def _paint_text_with_clozes(self, painter, text, x, y, max_width, option, base_color, is_selected, is_suspended):
        """Paint text with minimal styled clozes"""
        # Parse clozes and regular text
        parts = []
        last_end = 0
        
        for match in re.finditer(r'\{\{c(\d+)::(.*?)(?:::.*?)?\}\}', text):
            # Add text before cloze
            if match.start() > last_end:
                before_text = text[last_end:match.start()]
                before_text = re.sub(r'<[^>]+>', '', before_text)
                parts.append(('text', before_text))
            
            # Add cloze
            cloze_num = int(match.group(1))
            cloze_content = match.group(2)
            cloze_content = re.sub(r'<[^>]+>', '', cloze_content)
            parts.append(('cloze', cloze_content, cloze_num))
            
            last_end = match.end()
        
        # Add remaining text
        if last_end < len(text):
            after_text = text[last_end:]
            after_text = re.sub(r'<[^>]+>', '', after_text)
            parts.append(('text', after_text))
        
        # Draw parts
        current_x = x
        font = option.font
        metrics = QFontMetrics(font)
        line_height = metrics.height()
        baseline_y = y + metrics.ascent()
        
        for part in parts:
            if current_x >= x + max_width:
                break
            
            if part[0] == 'text':
                # Regular text
                painter.setFont(font)
                painter.setPen(base_color)
                
                text_content = part[1]
                text_width = metrics.horizontalAdvance(text_content)
                
                if current_x + text_width > x + max_width:
                    # Truncate
                    available = x + max_width - current_x
                    text_content = metrics.elidedText(text_content, Qt.TextElideMode.ElideRight, int(available))
                    text_width = available
                
                painter.drawText(QPointF(current_x, baseline_y), text_content)
                current_x += text_width
                
            elif part[0] == 'cloze':
                # Minimal cloze styling - just colored text with subtle background
                cloze_text = part[1]
                cloze_num = part[2]
                
                painter.setFont(font)
                
                # Choose color based on cloze number
                color_idx = (cloze_num - 1) % len(self.cloze_colors)
                cloze_color = QColor(self.cloze_colors[color_idx])
                
                # Measure text
                text_width = metrics.horizontalAdvance(cloze_text)
                
                if current_x + text_width > x + max_width:
                    # Truncate if needed
                    available = x + max_width - current_x
                    cloze_text = metrics.elidedText(cloze_text, Qt.TextElideMode.ElideRight, int(available))
                    text_width = available
                
                # Draw very subtle background highlight with slight padding
                padding = 4
                bg_rect = QRectF(current_x - padding, y - 1, text_width + padding * 2, line_height + 2)
                
                # Adjust background based on selection state
                if is_selected:
                    # On selected background, use darker tinted background
                    bg_color = QColor(cloze_color)
                    bg_color.setAlpha(50)  # More visible on selection
                else:
                    bg_color = QColor(cloze_color)
                    bg_color.setAlpha(30)  # Very subtle
                
                painter.setBrush(bg_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(bg_rect, 3, 3)
                
                # Draw colored text - MUCH brighter on selected rows
                if is_selected:
                    # white or dark, whichever reads on the selection color
                    text_color = QColor(themes.readable_text(self.color_theme.get("selection", self.theme_color)))
                elif QColor(self.color_theme.get("bg_primary", "#1e1e1e")).lightnessF() > 0.5:
                    # light theme: a deeper shade, or pale clozes vanish on light rows
                    text_color = cloze_color.darker(135)
                else:
                    # Use bright color for unselected
                    text_color = cloze_color.lighter(120)
                
                painter.setPen(text_color)
                painter.drawText(QPointF(current_x, baseline_y), cloze_text)
                
                current_x += text_width + 4  # Small spacing after cloze
        
        # Add ellipsis if text was cut off
        if parts and last_end > 0 and current_x >= x + max_width - 20:
            painter.setFont(font)
            painter.setPen(base_color)
            painter.drawText(QPointF(x + max_width - 20, baseline_y), "...")


class BrowserEnhancer:
    """Main enhancer class"""
    
    def __init__(self):
        self.installed_browsers = set()
        gui_hooks.browser_will_show.append(self.on_browser_will_show)
    
    def on_browser_will_show(self, browser):
        self.install_enhancements(browser)
    
    def install_enhancements(self, browser, force=False):
        if id(browser) in self.installed_browsers and not force:
            return

        try:
            config = mw.addonManager.getConfig(__name__)
            if not config.get('enable_browser_theme', True):
                return
        except:
            pass

        self.installed_browsers.add(id(browser))
        theme_color = self._get_theme_color()

        self._apply_styles(browser, theme_color)
        self._install_table_delegate(browser, theme_color, force=force)
    
    def _get_theme_color(self):
        try:
            return get_config().get('base_color', '#8e44ad')      # the heatmap theme's, if one is chosen
        except:
            return '#8e44ad'
    
    def _get_arrow_paths(self, color):
        """Create SVG arrow and indentation guide files, return their paths for stylesheet use"""
        # Use addon directory for arrow files (persistent)
        addon_dir = os.path.dirname(__file__)
        arrows_dir = os.path.join(addon_dir, ".arrows")
        os.makedirs(arrows_dir, exist_ok=True)

        # Create a color-safe filename
        color_safe = color.replace("#", "").lower()

        closed_path = os.path.join(arrows_dir, f"arrow_closed_{color_safe}.svg")
        open_path = os.path.join(arrows_dir, f"arrow_open_{color_safe}.svg")
        vline_path = os.path.join(arrows_dir, f"vline_{color_safe}.svg")
        branch_more_path = os.path.join(arrows_dir, f"branch_more_{color_safe}.svg")
        branch_end_path = os.path.join(arrows_dir, f"branch_end_{color_safe}.svg")

        # SVG for right-pointing arrow (closed)
        closed_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">
            <path fill="{color}" d="M4 2l4 4-4 4z"/>
        </svg>'''

        # SVG for down-pointing arrow (open)
        open_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">
            <path fill="{color}" d="M2 4l4 4 4-4z"/>
        </svg>'''

        # Indentation guide SVGs - subtle lines for tree structure
        vline_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="24">
            <line x1="8" y1="0" x2="8" y2="24" stroke="{color}" stroke-width="1" opacity="0.2"/>
        </svg>'''

        branch_more_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="24">
            <line x1="8" y1="0" x2="8" y2="24" stroke="{color}" stroke-width="1" opacity="0.2"/>
            <line x1="8" y1="12" x2="16" y2="12" stroke="{color}" stroke-width="1" opacity="0.2"/>
        </svg>'''

        branch_end_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="24">
            <line x1="8" y1="0" x2="8" y2="12" stroke="{color}" stroke-width="1" opacity="0.2"/>
            <line x1="8" y1="12" x2="16" y2="12" stroke="{color}" stroke-width="1" opacity="0.2"/>
        </svg>'''

        # Write files
        with open(closed_path, 'w') as f:
            f.write(closed_svg)
        with open(open_path, 'w') as f:
            f.write(open_svg)
        with open(vline_path, 'w') as f:
            f.write(vline_svg)
        with open(branch_more_path, 'w') as f:
            f.write(branch_more_svg)
        with open(branch_end_path, 'w') as f:
            f.write(branch_end_svg)

        # These go into Qt stylesheet url("...") strings, where a backslash starts a
        # CSS escape: on Windows "C:\Users\...\AppData" became garbage ("\A" is a
        # newline), Qt dropped every arrow/guide rule, and the tree lost its
        # expand arrows. Qt accepts forward slashes on every platform.
        return tuple(p.replace("\\", "/") for p in
                     (closed_path, open_path, vline_path, branch_more_path, branch_end_path))

    def _apply_styles(self, browser, theme_color):
        """Apply modern dark mode styles using selected theme"""

        # Get color theme from config
        try:
            config = mw.addonManager.getConfig(__name__)
            use_custom = config.get("browser_custom_colors", False)

            if use_custom:
                # Use custom colors
                color_theme = {
                    "bg_primary": config.get("browser_bg_primary", "#1e1e1e"),
                    "bg_secondary": config.get("browser_bg_secondary", "#252525"),
                    "text_normal": config.get("browser_text_normal", "#e0e0e0"),
                    "selection": config.get("browser_selection", "#8e44ad"),
                }
            else:
                # Use preset theme (default follows Anki's light/dark mode)
                theme_key = _resolve_browser_theme_key(config)
                color_theme = BROWSER_THEMES.get(theme_key, BROWSER_THEMES["default"])
        except:
            color_theme = BROWSER_THEMES["default"]

        bg_primary = color_theme.get("bg_primary", "#1e1e1e")
        bg_secondary = color_theme.get("bg_secondary", "#252525")
        text_normal = color_theme.get("text_normal", "#e0e0e0")
        selection = color_theme.get("selection", theme_color)

        # Third-party toolbars (e.g. Fastbar) color their icons for Anki's own
        # light/dark mode, not for this addon's theme. If the chosen theme's
        # brightness disagrees with Anki's mode (light theme while Anki is dark,
        # or vice versa), painting the toolbar with the theme background makes
        # those icons invisible (white-on-white / black-on-black). In that case
        # keep toolbars colored for Anki's mode so foreign icons stay legible.
        def _is_light_color(hex_c):
            try:
                r, g, b = hex_to_rgb(hex_c)
                return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.5
            except Exception:
                return False
        anki_dark = _is_dark_mode()
        theme_dark = not _is_light_color(bg_primary)
        if theme_dark == anki_dark:
            toolbar_bg, toolbar_fg, toolbar_hover = bg_primary, text_normal, bg_secondary
        elif anki_dark:
            toolbar_bg, toolbar_fg, toolbar_hover = "#2c2c2c", "#e0e0e0", "#3d3d3d"
        else:
            toolbar_bg, toolbar_fg, toolbar_hover = "#f2f2f2", "#202020", "#e2e2e2"

        # Get arrow and indentation guide image paths for tree view
        arrow_closed, arrow_open, guide_vline, guide_branch_more, guide_branch_end = self._get_arrow_paths(text_normal)

        # Get row spacing setting
        try:
            row_spacing = config.get("browser_row_spacing", "comfortable")
        except:
            row_spacing = "comfortable"

        # Padding values based on spacing
        spacing_values = {
            "comfortable": ("10px 12px", "10px 12px"),  # (item_padding, header_padding)
            "compact": ("6px 10px", "8px 10px"),
            "tight": ("3px 8px", "6px 8px"),
        }
        item_padding, header_padding = spacing_values.get(row_spacing, spacing_values["comfortable"])

        stylesheet = f"""
        /* ===== MAIN BROWSER WINDOW ===== */
        QMainWindow {{
            background-color: {bg_primary};
        }}

        /* ===== SIDEBAR TREE VIEW ===== */
        QTreeView {{
            font-size: 13px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: {bg_primary};
            alternate-background-color: {bg_primary};
            color: {text_normal};
            border: none;
            outline: none;
            padding: 8px 4px;
        }}

        QTreeView::item {{
            padding: 5px 8px;
            border: none;
            border-radius: 4px;
            margin: 0px 4px;
            background-color: transparent;
            color: {text_normal};
        }}

        QTreeView::item:hover {{
            background-color: {bg_secondary};
            color: {text_normal};
        }}

        QTreeView::item:selected {{
            background-color: {selection};
            color: white;
        }}

        QTreeView::item:selected:hover {{
            background-color: {selection};
            color: white;
        }}

        /* Branch indicators - fix selection boxes and show arrows */
        QTreeView::branch {{
            background: transparent;
        }}

        QTreeView::branch:selected,
        QTreeView::branch:hover,
        QTreeView::branch:selected:hover {{
            background: transparent;
        }}

        /* Arrow indicators for expandable items */
        QTreeView::branch:has-children:!has-siblings:closed,
        QTreeView::branch:closed:has-children:has-siblings {{
            image: url("{arrow_closed}");
        }}

        QTreeView::branch:open:has-children:!has-siblings,
        QTreeView::branch:open:has-children:has-siblings {{
            image: url("{arrow_open}");
        }}

        /* Indentation guides - subtle vertical lines for tree structure */
        QTreeView::branch:has-siblings:!adjoins-item {{
            border-image: url("{guide_vline}") 0;
        }}
        QTreeView::branch:has-siblings:adjoins-item {{
            border-image: url("{guide_branch_more}") 0;
        }}
        QTreeView::branch:!has-siblings:adjoins-item {{
            border-image: url("{guide_branch_end}") 0;
        }}

        /* ===== CARD TABLE ===== */
        QTableView {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 13px;
            background-color: {bg_primary};
            color: {text_normal};
            selection-background-color: {selection};
            gridline-color: transparent;
            border: none;
            outline: none;
            show-decoration-selected: 0;
        }}
        
        QTableView::item {{
            padding: {item_padding};
            border: none;
        }}

        QTableView::item:selected {{
            background-color: {selection};
            color: white;
        }}

        /* ===== TABLE HEADERS ===== */
        QHeaderView {{
            background-color: {bg_primary};
            border: none;
        }}

        QHeaderView::section {{
            background-color: {bg_primary};
            border: none;
            border-bottom: 2px solid {selection};
            padding: {header_padding};
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: {text_normal};
            opacity: 0.7;
        }}

        QHeaderView::section:hover {{
            background-color: {bg_secondary};
            color: {selection};
        }}

        /* ===== SCROLLBARS ===== */
        QScrollBar:vertical {{
            background-color: {bg_primary};
            width: 12px;
            border: none;
        }}

        QScrollBar::handle:vertical {{
            background-color: {bg_secondary};
            border-radius: 6px;
            min-height: 30px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {selection};
        }}

        QScrollBar:horizontal {{
            background-color: {bg_primary};
            height: 12px;
            border: none;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {bg_secondary};
            border-radius: 6px;
            min-width: 30px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: {selection};
        }}

        QScrollBar::add-line, QScrollBar::sub-line {{
            border: none;
            background: none;
        }}

        /* ===== SEARCH BAR & INPUT FIELDS ===== */
        QLineEdit {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: 1px solid {bg_secondary};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 13px;
            selection-background-color: {selection};
        }}

        QLineEdit:focus {{
            border: 1px solid {selection};
        }}

        /* Inline editor for renaming tags/decks in sidebar */
        QTreeView QLineEdit {{
            padding: 2px 4px;
            border-radius: 3px;
            margin: 0px;
        }}

        /* ===== COMBO BOXES ===== */
        QComboBox {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: 1px solid {bg_secondary};
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
        }}

        QComboBox:hover {{
            border: 1px solid {selection};
        }}

        QComboBox::drop-down {{
            border: none;
            padding-right: 8px;
        }}

        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            color: {text_normal};
            selection-background-color: {selection};
            selection-color: white;
            border: 1px solid {bg_secondary};
            border-radius: 6px;
        }}

        /* ===== SPLITTER ===== */
        QSplitter::handle {{
            background-color: {bg_secondary};
        }}

        QSplitter::handle:horizontal {{
            width: 2px;
        }}

        QSplitter::handle:vertical {{
            height: 2px;
        }}

        /* ===== TOOL BUTTONS ===== */
        QToolButton {{
            background-color: transparent;
            color: {text_normal};
            border: none;
            border-radius: 4px;
            padding: 6px;
        }}

        QToolButton:hover {{
            background-color: {bg_secondary};
        }}

        QToolButton:pressed {{
            background-color: {selection};
        }}

        /* ===== MENU BAR ===== */
        QMenuBar {{
            background-color: {bg_primary};
            color: {text_normal};
            border: none;
        }}

        QMenuBar::item {{
            background-color: transparent;
            color: {text_normal};
            padding: 6px 12px;
        }}

        QMenuBar::item:selected {{
            background-color: {bg_secondary};
        }}

        /* ===== MENUS ===== */
        QMenu {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: 1px solid {bg_primary};
            border-radius: 6px;
            padding: 4px;
        }}

        QMenu::item {{
            padding: 6px 24px;
            border-radius: 4px;
        }}

        QMenu::item:selected {{
            background-color: {selection};
            color: white;
        }}

        QMenu::separator {{
            height: 1px;
            background-color: {bg_primary};
            margin: 4px 8px;
        }}

        /* ===== STATUS BAR ===== */
        QStatusBar {{
            background-color: {bg_primary};
            color: {text_normal};
            border-top: 1px solid {bg_secondary};
        }}

        /* ===== PUSH BUTTONS ===== */
        QPushButton {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}

        QPushButton:hover {{
            background-color: {selection};
            color: white;
        }}

        QPushButton:pressed {{
            background-color: {selection};
        }}

        /* ===== LABELS ===== */
        QLabel {{
            color: {text_normal};
        }}

        /* ===== FRAME & WIDGET BACKGROUNDS ===== */
        QFrame {{
            background-color: {bg_primary};
            border: none;
        }}

        QWidget {{
            background-color: {bg_primary};
            color: {text_normal};
        }}

        /* ===== TOOLBARS (third-party addons like Fastbar) =====
           Placed after the QWidget rule so it wins; colored for whichever
           mode the toolbar icons were drawn for (see toolbar_bg above). */
        QToolBar {{
            background-color: {toolbar_bg};
            border: none;
            spacing: 2px;
        }}
        QToolBar QToolButton {{
            background-color: transparent;
            color: {toolbar_fg};
            border: none;
            border-radius: 4px;
            padding: 6px;
        }}
        QToolBar QToolButton:hover {{
            background-color: {toolbar_hover};
        }}
        QToolBar QToolButton:pressed {{
            background-color: {toolbar_hover};
        }}

        /* ===== TAB WIDGET ===== */
        QTabWidget::pane {{
            background-color: {bg_primary};
            border: none;
        }}

        QTabBar::tab {{
            background-color: {bg_secondary};
            color: {text_normal};
            padding: 8px 16px;
            border: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }}

        QTabBar::tab:selected {{
            background-color: {selection};
            color: white;
        }}

        QTabBar::tab:hover:!selected {{
            background-color: {bg_primary};
        }}

        /* ===== CHECKBOXES ===== */
        QCheckBox {{
            color: {text_normal};
            spacing: 8px;
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 2px solid {bg_secondary};
            background-color: {bg_primary};
        }}

        QCheckBox::indicator:checked {{
            background-color: {selection};
            border-color: {selection};
        }}

        QCheckBox::indicator:hover {{
            border-color: {selection};
        }}

        /* ===== RADIO BUTTONS ===== */
        QRadioButton {{
            color: {text_normal};
            spacing: 8px;
        }}

        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: 2px solid {bg_secondary};
            background-color: {bg_primary};
        }}

        QRadioButton::indicator:checked {{
            background-color: {selection};
            border-color: {selection};
        }}

        /* ===== SPIN BOX ===== */
        QSpinBox, QDoubleSpinBox {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: 1px solid {bg_secondary};
            border-radius: 6px;
            padding: 6px 8px;
        }}

        QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {selection};
        }}

        /* ===== GROUP BOX ===== */
        QGroupBox {{
            background-color: {bg_primary};
            color: {text_normal};
            border: 1px solid {bg_secondary};
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 8px;
        }}

        QGroupBox::title {{
            color: {text_normal};
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 8px;
            background-color: {bg_primary};
        }}

        /* ===== TOOLTIPS ===== */
        QToolTip {{
            background-color: {bg_secondary};
            color: {text_normal};
            border: 1px solid {selection};
            border-radius: 4px;
            padding: 4px 8px;
        }}

        /* ===== PROGRESS BAR ===== */
        QProgressBar {{
            background-color: {bg_secondary};
            border: none;
            border-radius: 4px;
            text-align: center;
            color: {text_normal};
        }}

        QProgressBar::chunk {{
            background-color: {selection};
            border-radius: 4px;
        }}

        /* ===== TEXT EDITORS (Popup Editor) ===== */
        QTextEdit, QPlainTextEdit {{
            background-color: {bg_primary};
            color: {text_normal};
            border: 1px solid {bg_secondary};
            border-radius: 6px;
            padding: 8px;
            selection-background-color: {selection};
            selection-color: white;
        }}

        QTextEdit:focus, QPlainTextEdit:focus {{
            border-color: {selection};
        }}

        /* ===== WEB VIEW (Editor Content) ===== */
        QWebEngineView {{
            background-color: {bg_primary};
        }}

        /* ===== DOCK WIDGETS ===== */
        QDockWidget {{
            background-color: {bg_primary};
            color: {text_normal};
            titlebar-close-icon: none;
            titlebar-normal-icon: none;
        }}

        QDockWidget::title {{
            background-color: {bg_secondary};
            color: {text_normal};
            padding: 8px;
            border: none;
        }}

        /* ===== STACKED WIDGET ===== */
        QStackedWidget {{
            background-color: {bg_primary};
        }}

        /* ===== DIALOG BACKGROUNDS ===== */
        QDialog {{
            background-color: {bg_primary};
            color: {text_normal};
        }}
        """
        
        browser.setStyleSheet(stylesheet)
        
        # Fix tree view - minimal indentation for narrow sidebars
        try:
            sidebar = None
            if hasattr(browser, 'sidebarTree'):
                sidebar = browser.sidebarTree
            elif hasattr(browser, 'sidebar') and hasattr(browser.sidebar, 'tree'):
                sidebar = browser.sidebar.tree
            
            if sidebar:
                # Set indentation for arrows to show properly
                sidebar.setRootIsDecorated(True)
                sidebar.setIndentation(16)  # Need enough space for arrow indicators
                sidebar.setWordWrap(True)  # Allow text wrapping for long names
                sidebar.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # Show start and end of long names

                # Apply direct sidebar styling for consistency
                sidebar_style = f"""
                QTreeView {{
                    background-color: {bg_primary};
                    alternate-background-color: {bg_primary};
                    color: {text_normal};
                    border: none;
                    outline: none;
                }}
                QTreeView::item {{
                    background-color: transparent;
                    color: {text_normal};
                    padding: 5px 8px;
                    border-radius: 4px;
                    margin: 0px 4px;
                }}
                QTreeView::item:hover {{
                    background-color: {bg_secondary};
                }}
                QTreeView::item:selected {{
                    background-color: {selection};
                    color: white;
                }}
                QTreeView::branch {{
                    background: transparent;
                }}
                QTreeView::branch:selected,
                QTreeView::branch:hover {{
                    background: transparent;
                }}
                QTreeView::branch:has-children:!has-siblings:closed,
                QTreeView::branch:closed:has-children:has-siblings {{
                    image: url("{arrow_closed}");
                }}
                QTreeView::branch:open:has-children:!has-siblings,
                QTreeView::branch:open:has-children:has-siblings {{
                    image: url("{arrow_open}");
                }}
                QTreeView::branch:has-siblings:!adjoins-item {{
                    border-image: url("{guide_vline}") 0;
                }}
                QTreeView::branch:has-siblings:adjoins-item {{
                    border-image: url("{guide_branch_more}") 0;
                }}
                QTreeView::branch:!has-siblings:adjoins-item {{
                    border-image: url("{guide_branch_end}") 0;
                }}
                QScrollBar:vertical {{
                    background-color: {bg_primary};
                    width: 10px;
                }}
                QScrollBar::handle:vertical {{
                    background-color: {bg_secondary};
                    border-radius: 5px;
                    min-height: 20px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background-color: {selection};
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    border: none;
                    background: none;
                    height: 0px;
                }}
                QTreeView QLineEdit {{
                    padding: 2px 4px;
                    border-radius: 3px;
                    margin: 0px;
                    background-color: {bg_secondary};
                    color: {text_normal};
                    border: 1px solid {selection};
                }}
                """
                sidebar.setStyleSheet(sidebar_style)
        except:
            pass
    
    def _install_table_delegate(self, browser, theme_color, force=False):
        """Install the custom delegate"""

        table_view = None
        try:
            if hasattr(browser, 'table') and hasattr(browser.table, '_view'):
                table_view = browser.table._view
            elif hasattr(browser, 'form') and hasattr(browser.form, 'tableView'):
                table_view = browser.form.tableView
        except:
            pass

        if not table_view:
            return

        current_delegate = table_view.itemDelegate()
        if isinstance(current_delegate, ModernBrowserDelegate) and not force:
            return

        delegate = ModernBrowserDelegate(browser, theme_color)
        table_view.setItemDelegate(delegate)
        try:
            table_view.viewport().update()
        except Exception:
            pass
        
        # Configure table
        table_view.setWordWrap(False)
        table_view.setAlternatingRowColors(False)
        table_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        table_view.setShowGrid(False)
        
        # Set row height based on spacing setting
        if hasattr(table_view, 'verticalHeader'):
            try:
                config = mw.addonManager.getConfig(__name__)
                row_spacing = config.get("browser_row_spacing", "comfortable")
            except:
                row_spacing = "comfortable"

            # Row heights for each spacing option
            row_heights = {
                "comfortable": 38,
                "compact": 30,
                "tight": 24,
            }
            row_height = row_heights.get(row_spacing, 38)

            v_header = table_view.verticalHeader()
            v_header.setDefaultSectionSize(row_height)
            v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        
        # Connect to changes
        try:
            model = table_view.model()
            if model:
                def refresh_view():
                    if hasattr(delegate, '_card_cache'):
                        delegate._card_cache.clear()
                    table_view.viewport().update()
                
                model.layoutChanged.connect(refresh_view)
                model.modelReset.connect(refresh_view)
                model.dataChanged.connect(refresh_view)
        except:
            pass
        
        # Hook state changes
        try:
            from aqt import gui_hooks
            
            # Use a wrapper that checks if objects still exist
            def on_state_change(new_state, old_state):
                try:
                    if hasattr(delegate, '_card_cache'):
                        delegate._card_cache.clear()
                    # Try to update viewport, will fail silently if deleted
                    if table_view is not None:
                        table_view.viewport().update()
                except RuntimeError:
                    # Object has been deleted, ignore
                    pass
                except:
                    # Any other error, ignore
                    pass
            
            gui_hooks.state_did_change.append(on_state_change)

            # Hook for when browser search completes (catches mark/unmark)
            def on_browser_did_search(browser_instance):
                try:
                    if browser_instance == browser and hasattr(delegate, '_card_cache'):
                        delegate._card_cache.clear()
                        table_view.viewport().update()
                except:
                    pass

            if hasattr(gui_hooks, 'browser_did_search'):
                gui_hooks.browser_did_search.append(on_browser_did_search)

        except:
            pass


enhancer = BrowserEnhancer()

class EditorEnhancer:
    def __init__(self):
        gui_hooks.editor_did_init.append(self.on_editor_init)

    def on_editor_init(self, editor):
        try:
            self._apply_editor_theme(editor)
        except Exception:
            traceback.print_exc()

    def _apply_editor_theme(self, editor):
        cfg = get_config()
        if not cfg.get('enable_editor_theme', True):
            return
        base_color = cfg.get('base_color', "#8e44ad")
        cloze_color = "#f1c40f"

        # Resolve the SAME color theme the browser window uses, so the editor
        # matches the rest of the addon's styling.
        try:
            if cfg.get("browser_custom_colors", False):
                bg_primary   = cfg.get("browser_bg_primary", "#1e1e1e")
                bg_secondary = cfg.get("browser_bg_secondary", "#252525")
                text_normal  = cfg.get("browser_text_normal", "#e0e0e0")
                selection    = cfg.get("browser_selection", base_color)
            else:
                theme = BROWSER_THEMES.get(_resolve_browser_theme_key(cfg), BROWSER_THEMES["default"])
                bg_primary   = theme["bg_primary"]
                bg_secondary = theme["bg_secondary"]
                text_normal  = theme["text_normal"]
                selection    = theme.get("selection", base_color)
        except Exception:
            theme = BROWSER_THEMES["default"]
            bg_primary, bg_secondary = theme["bg_primary"], theme["bg_secondary"]
            text_normal, selection = theme["text_normal"], theme["selection"]

        # Derived shades so borders/muted text fit the theme
        try:
            border_c    = blend_colors(bg_primary, text_normal, 0.18)
            border_sub  = blend_colors(bg_primary, text_normal, 0.10)
            fg_subtle   = blend_colors(text_normal, bg_primary, 0.35)
            canvas_code = blend_colors(bg_secondary, bg_primary, 0.5)
        except Exception:
            border_c = border_sub = bg_secondary
            fg_subtle = text_normal
            canvas_code = bg_secondary
        try:
            _r, _g, _b = hex_to_rgb(selection)
        except Exception:
            _r, _g, _b = (142, 68, 173)
        accent_glow = f"rgba({_r},{_g},{_b},0.18)"

        # Re-theme the whole editor page by overriding Anki's own CSS variables
        # with the addon theme's colors. Everything Anki draws (fields, labels,
        # tag editor — including shadow DOM content, since custom properties
        # inherit through shadow boundaries) follows automatically, and the body
        # gets an OPAQUE theme background — never `transparent`, which is what
        # previously exposed the raw black webview background in dark mode.
        # `:root:root` outranks Anki's `:root` / `:root.night-mode` rules.
        css = f"""
        :root:root {{
            --hm-accent: {selection};
            --hm-cloze: {cloze_color};
            --canvas: {bg_primary};
            --canvas-elevated: {bg_secondary};
            --canvas-inset: {bg_secondary};
            --canvas-code: {canvas_code};
            --canvas-overlay: {bg_secondary};
            --fg: {text_normal};
            --fg-subtle: {fg_subtle};
            --border: {border_c};
            --border-subtle: {border_sub};
            --border-strong: {border_c};
            --border-focus: {selection};
            --button-bg: {bg_secondary};
            --button-gradient-start: {bg_secondary};
            --button-gradient-end: {bg_secondary};
        }}

        body {{
            background: {bg_primary} !important;
            color: {text_normal} !important;
        }}

        /* --- FIELD GRID: a little more breathing room --- */
        .fields {{
            grid-gap: 10px !important;
            padding: 6px 4px 10px !important;
        }}

        /* --- FLOATING FIELD CARDS (colors stay native) --- */
        .field-container {{
            border-radius: 10px !important;
        }}
        .editor-field {{
            border-radius: 10px !important;
            border: 1px solid var(--border-subtle) !important;
            box-shadow: 0 1px 3px var(--shadow-subtle, rgba(0,0,0,0.08)) !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        .editor-field:focus-within {{
            outline: none !important;
            border-color: var(--hm-accent) !important;
            box-shadow: 0 2px 10px {accent_glow} !important;
        }}

        /* --- FIELD LABELS: small-caps section headers --- */
        .label-name {{
            font-size: 11px !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--fg-subtle) !important;
        }}
        .label-container {{
            padding: 3px 8px 2px !important;
        }}

        /* --- EDITABLE AREA: roomier padding --- */
        .rich-text-input {{
            padding: 10px 12px !important;
        }}

        /* --- CLOZE INDICATOR (class added by JS below) --- */
        .field-container.has-cloze .editor-field {{
            border-left: 3px solid var(--hm-cloze) !important;
        }}
        .field-container.has-cloze .label-container::after {{
            content: "CLOZE";
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 1px;
            color: var(--hm-cloze);
            opacity: 0.7;
            align-self: center;
            pointer-events: none;
        }}

        /* --- LEGACY EDITOR (Anki <2.1.50) --- */
        .field {{
            border-radius: 10px;
            padding: 16px !important;
            margin-bottom: 16px !important;
            transition: border 0.2s ease, box-shadow 0.2s ease;
            position: relative;
        }}
        .field:focus-within {{
            border-color: var(--hm-accent) !important;
            box-shadow: 0 2px 10px {accent_glow} !important;
        }}
        .field.has-cloze {{
            border-left: 3px solid var(--hm-cloze) !important;
        }}
        .fname {{
            font-size: 11px !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600 !important;
            color: var(--fg-subtle, #95a5a6) !important;
        }}
        """

        # JAVASCRIPT: Detects Cloze Syntax as you type and toggles .has-cloze
        # on the field container. The editable lives inside a shadow root in
        # modern Anki, so we resolve the real target via composedPath() and
        # find the container through the shadow host.
        # Note: this must be eval'd directly — <script> tags added via
        # insertAdjacentHTML are never executed by the browser.
        js = """
        (function() {
            function containerFor(editable) {
                var root = editable.getRootNode();
                var base = root.host ? root.host : editable;
                return base.closest('.field-container') || editable.parentElement;
            }
            function checkCloze(editable) {
                var container = containerFor(editable);
                if (!container) return;
                container.classList.toggle('has-cloze', editable.innerHTML.includes('{{c'));
            }
            function scanAll() {
                // Light-DOM editables (legacy editor)
                document.querySelectorAll('.rich-text-editable').forEach(checkCloze);
                // Shadow-DOM editables (modern editor)
                document.querySelectorAll('.rich-text-input, .rich-text-input *').forEach(function(el) {
                    if (el.shadowRoot) {
                        el.shadowRoot.querySelectorAll('.rich-text-editable').forEach(checkCloze);
                    }
                });
            }
            function targetOf(e) {
                var path = e.composedPath ? e.composedPath() : [e.target];
                return path[0];
            }
            document.body.addEventListener('input', function(e) {
                var t = targetOf(e);
                if (t && t.classList && t.classList.contains('rich-text-editable')) {
                    checkCloze(t);
                }
            });
            // Rescan when focus moves (covers note switches in the browser)
            document.body.addEventListener('focusin', function() { setTimeout(scanAll, 50); });
            setTimeout(scanAll, 300);
        })();
        """

        safe_css = css.replace('\n', ' ')

        # Combine CSS and JS injection. The <style> carries a stable id and any
        # previous copy is removed first, so re-injecting on a theme change swaps
        # the colors instead of stacking duplicate style tags. The cloze-detection
        # listeners are only wired up once (guarded by a window flag).
        injection = f"""
        (function() {{
            var old = document.getElementById('hm-editor-theme');
            if (old) old.remove();
            var style = document.createElement('style');
            style.id = 'hm-editor-theme';
            style.innerHTML = `{safe_css}`;
            document.head.appendChild(style);
            if (!window.__hmEditorClozeWired) {{
                window.__hmEditorClozeWired = true;
                {js}
            }}
        }})();
        """

        editor.web.eval(injection)

editor_enhancer = EditorEnhancer()


def _iter_open_editors():
    """Yield every live Editor currently on screen (browser edit pane, Add
    Cards, Edit Current) so their theme CSS can be refreshed in place."""
    seen = set()
    try:
        widgets = list(mw.app.topLevelWidgets())
    except Exception:
        return
    for w in widgets:
        for attr in ("editor",):
            ed = getattr(w, attr, None)
            if ed is not None and id(ed) not in seen and getattr(ed, "web", None) is not None:
                seen.add(id(ed))
                yield ed


def _on_theme_did_change(*args):
    """Re-apply all of the addon's theming when Anki's light/dark mode changes,
    so the user doesn't have to reopen Settings to force an update."""
    try:
        _FSRS_FORECAST_CACHE.clear()
        _REVLOG_AGG_CACHE.clear()
    except Exception:
        pass

    # 1. Deck browser (colors are baked into its HTML, so re-render it)
    try:
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()
    except Exception:
        pass

    # 2. Open browser windows: restyle + rebuild the row delegate for the new mode
    try:
        from aqt.browser import Browser
        for w in mw.app.topLevelWidgets():
            if isinstance(w, Browser):
                enhancer.install_enhancements(w, force=True)
    except Exception:
        traceback.print_exc()

    # 3. Open note editors: re-inject the theme CSS (idempotent via style id)
    for ed in _iter_open_editors():
        try:
            editor_enhancer._apply_editor_theme(ed)
        except Exception:
            pass


try:
    gui_hooks.theme_did_change.remove(_on_theme_did_change)
except Exception:
    pass
gui_hooks.theme_did_change.append(_on_theme_did_change)


# ===== TAG COLOR MANAGER =====
# Allows right-click coloring of tags in the browser sidebar

TAG_COLOR_PRESETS = [
    ("#e74c3c", "Red"),
    ("#e67e22", "Orange"),
    ("#f1c40f", "Yellow"),
    ("#2ecc71", "Green"),
    ("#1abc9c", "Teal"),
    ("#3498db", "Blue"),
    ("#9b59b6", "Purple"),
    ("#e91e63", "Pink"),
    ("#795548", "Brown"),
    ("#607d8b", "Gray"),
]


def _color_icon(color):
    """Create a small color swatch icon"""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor("#555555"))
    painter.drawRoundedRect(2, 2, 12, 12, 3, 3)
    painter.end()
    return QIcon(pixmap)


def _on_browser_sidebar_context_menu(sidebar, menu, item, index):
    """Add tag color options to the sidebar context menu"""
    try:
        from aqt.browser.sidebar import SidebarItemType

        # Only add menu for tags
        if item.item_type != SidebarItemType.TAG:
            return

        tag_name = item.full_name

        # Add separator before our options
        menu.addSeparator()

        # Add color submenu
        color_menu = menu.addMenu("Set Tag Color")

        # Add preset colors
        for color, name in TAG_COLOR_PRESETS:
            action = color_menu.addAction(_color_icon(color), name)
            action.triggered.connect(
                lambda checked, c=color, t=tag_name, s=sidebar: _set_tag_color(t, c, s)
            )

        # Add custom color option
        color_menu.addSeparator()
        custom_action = color_menu.addAction("Custom Color...")
        custom_action.triggered.connect(
            lambda checked, t=tag_name, s=sidebar: _pick_custom_color(t, s)
        )

        # Add clear color option if tag has a color
        cfg = get_config()
        tag_colors = cfg.get("tag_colors", {})
        if tag_name in tag_colors:
            clear_action = menu.addAction("Clear Tag Color")
            clear_action.triggered.connect(
                lambda checked, t=tag_name, s=sidebar: _clear_tag_color(t, s)
            )

    except (ImportError, AttributeError):
        pass


def _set_tag_color(tag_name, color, sidebar):
    """Set color for a tag"""
    cfg = get_config()
    tag_colors = cfg.get("tag_colors", {})
    tag_colors[tag_name] = color
    cfg["tag_colors"] = tag_colors
    write_config(cfg)
    sidebar.viewport().update()


def _pick_custom_color(tag_name, sidebar):
    """Open color picker for custom color"""
    cfg = get_config()
    tag_colors = cfg.get("tag_colors", {})
    current = tag_colors.get(tag_name, "#8e44ad")

    color = QColorDialog.getColor(QColor(current), sidebar, f"Color for tag: {tag_name}")
    if color.isValid():
        _set_tag_color(tag_name, color.name(), sidebar)


def _clear_tag_color(tag_name, sidebar):
    """Remove color from a tag"""
    cfg = get_config()
    tag_colors = cfg.get("tag_colors", {})
    if tag_name in tag_colors:
        del tag_colors[tag_name]
        cfg["tag_colors"] = tag_colors
        write_config(cfg)
        sidebar.viewport().update()


class TagColorDelegate(QStyledItemDelegate):
    """Custom delegate that renders tags with their assigned colors (text and icon)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon_cache = {}  # Cache colorized icons

    def _colorize_icon(self, icon, color):
        """Create a colorized version of the icon"""
        cache_key = (id(icon), color.name())
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        # Get the icon as a pixmap
        sizes = icon.availableSizes()
        size = sizes[0] if sizes else QSize(16, 16)
        pixmap = icon.pixmap(size)

        # Create a colored version
        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(colored_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

        # Draw original pixmap
        painter.drawPixmap(0, 0, pixmap)

        # Apply color overlay using CompositionMode_SourceIn
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), color)

        painter.end()

        colored_icon = QIcon(colored_pixmap)
        self._icon_cache[cache_key] = colored_icon
        return colored_icon

    def initStyleOption(self, option, index):
        """Modify the style option to change text and icon color for colored tags"""
        super().initStyleOption(option, index)

        try:
            from aqt.browser.sidebar import SidebarItemType
            model = index.model()
            item = model.item_for_index(index)

            if item and item.item_type == SidebarItemType.TAG:
                tag_name = item.full_name
                cfg = get_config()
                tag_colors = cfg.get("tag_colors", {})

                if tag_name in tag_colors:
                    color = QColor(tag_colors[tag_name])

                    # Set the text color in the palette
                    option.palette.setColor(option.palette.ColorRole.Text, color)
                    option.palette.setColor(option.palette.ColorRole.HighlightedText, color.lighter(150))

                    # Colorize the icon
                    if not option.icon.isNull():
                        option.icon = self._colorize_icon(option.icon, color)

        except (ImportError, AttributeError):
            pass


class TagColorManager:
    """Manages custom colors for tags in the browser sidebar"""

    def __init__(self):
        self.installed_browsers = set()
        # Hook into browser show to install delegate
        gui_hooks.browser_will_show.append(self.on_browser_show)
        # Hook into sidebar context menu to add our options
        gui_hooks.browser_sidebar_will_show_context_menu.append(_on_browser_sidebar_context_menu)

    def on_browser_show(self, browser):
        if id(browser) in self.installed_browsers:
            return

        # Respect the browser theme setting
        try:
            config = mw.addonManager.getConfig(__name__)
            if not config.get('enable_browser_theme', True):
                return
        except:
            pass

        self.installed_browsers.add(id(browser))

        # Get the sidebar tree widget and install delegate
        sidebar = self._get_sidebar(browser)
        if sidebar:
            self._install_tag_delegate(sidebar)

    def _get_sidebar(self, browser):
        """Get the sidebar tree widget from browser"""
        try:
            if hasattr(browser, 'sidebarTree'):
                return browser.sidebarTree
            elif hasattr(browser, 'sidebar') and hasattr(browser.sidebar, 'tree'):
                return browser.sidebar.tree
        except:
            pass
        return None

    def _install_tag_delegate(self, sidebar):
        """Install a custom delegate that colors tag text"""
        delegate = TagColorDelegate(sidebar)
        sidebar.setItemDelegate(delegate)


# Initialize tag color manager
tag_color_manager = TagColorManager()