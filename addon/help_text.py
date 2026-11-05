"""
The ? marks in Settings: what each setting does, in plain words. Each key names the
settings window's control (an attribute, or "dict.key" for one kept in a dict), and
attach() puts a small ? after that control that shows the text when you hover it.
"""

from __future__ import annotations

from aqt.qt import (QAbstractButton, QBoxLayout, QEvent, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QObject,
                    QPoint, QToolTip, QWidget, Qt)

# Only the settings whose name doesn't already say what they do.
HELP = {
    # General
    "avg_combo": ("Your daily average is worked out over this stretch of time. When you hover a day, "
                  "it's compared against this average."),
    "time_scale_spin": "How many minutes it takes for a day to show up in full color. At Auto, your longest day sets the top.",
    "nc_scale_spin": "How many new cards it takes for a day to show up in full color. At Auto, your biggest day sets the top.",
    "chk_show_focus_mode": ("Adds a Focus view, where each day is colored by how focused you were. A card counts "
                            "as focused if you answered it in about the time it normally takes you. "
                            "This needs Time Left turned on."),

    # Theme
    "chk_glass": "Makes the box around the heatmap look like frosted glass, so the background softly shows through.",
    "chk_low_power": "For slower computers. Turns off the frosted-glass blur and all animations, here and in the review pill.",
    "animations_combo": ("Little touches like the graph drawing itself in, or today's square glowing when you "
                         "finish. Follow system turns them off if your computer is set to reduce motion, and "
                         "Always plays them regardless."),
    "opacity_slider": "How see-through the glass box is. Lower it to let more of the background show.",
    "intensity_slider": ("Makes light days easier to see. Turn it up if days with only a few reviews blend in "
                         "with days you didn't study."),
    "min_opacity_slider": "How faint a studied day is allowed to get, so even a day with a single review doesn't disappear.",
    "gradient_mode_combo": ("Changes how a day's color builds up as you do more reviews. Glow lines your days up "
                            "from quietest to busiest and spreads them over the whole range, from dark to bright, so "
                            "neighboring days are easy to tell apart. With Opacity, busy days get more solid. With "
                            "Shade they get brighter, and Shade inverted makes them darker."),
    "glow_slider": ("How far apart your quietest and busiest days look in Glow. Turn it up for bolder "
                    "differences, or down for a softer look that stays closer to your theme color. "
                    "It changes the Stats window's grid too."),
    "shade_slider": "For the Shade modes, how dark your lightest days start out. At 0%, they start from black.",
    "color_scale_max_spin": ("How many reviews it takes for a day to show up in full color. At 0, your busiest "
                             "day sets the top. Picking a number keeps the colors steady, so one huge day won't "
                             "make the rest look washed out. Glow doesn't use this."),
    "chk_monochrome": "Shows the stats bar numbers in your normal text color instead of green, yellow and red.",
    "bg_main": "How strongly the photo comes through. Keeping it lower makes text easier to read.",

    # Deck List
    "chk_modern": "Gives the deck list a fresh look, with rounded rows and colored badges for your New, Learning and Due counts.",
    "chk_deck_glass": "Puts your deck list in the same frosted-glass box as the heatmap.",
    "chk_ratio": "Adds a little ring next to each deck that fills in as you get through today's cards.",
    "chk_count_pills": "Shows New, Learning and Due as colored pills. Turn it off for Anki's plain numbers.",
    "chk_replace": ("Hides Anki's own \"Studied 120 cards in 25 minutes today\" line, since the heatmap "
                    "already tells you that."),

    # Reminders
    "chk_time_pill": "Shows when you'll be done with today's cards. You'll need Time Left turned on for this one.",
    "notice_more.notice_milestone": ("On the day your streak reaches a milestone (every 5, 10, 25, 50 or 100 days, "
                                     "a year, or 500 days), a short note says so. It stays all day, in case you "
                                     "missed the animation."),
    "chk_exam_countdown": "Counts down to your next exam. To add one, click a day on the heatmap and choose Add note.",
    "chk_notice_backlog": "Lets you know how many review cards are overdue, but only once there are 20 or more.",
    "notice_more.notice_learning": ("Reminds you about learning cards that are coming back later today, "
                                    "once there's nothing else left to do."),
    "chk_notice_tomorrow": "Gives you a heads-up on tomorrow's reviews in the evening, or as soon as you're done for the day.",
    "notice_more.notice_this_week": ("Starting Wednesday, lets you know if this week is running well ahead of "
                                     "or behind last week, by 15% or more."),

    # Data
    "ret_min_input": ("Sets the color range for the Retention view. Days at or below the first number get the "
                      "lowest color, days at or above the second get the highest, and everything in between blends."),
    "chk_exclude_new_retention": ("Leaves new cards out of your retention on the day you first learn them, since "
                                  "missing them then is normal. They count as usual from the next day."),
    "speed_min_input": ("Sets the color range for the Speed view, in seconds per card. Anything faster than the "
                        "first number gets the best color, and anything slower than the second gets the worst."),
    "chk_exclude_idle": ("If you walk away in the middle of a card, the time it sat there can throw off your "
                         "stats. Cards that took longer than this are left out of your study time and seconds "
                         "per card. Your review count and retention don't change."),
    "chk_show_overview": "Also shows the heatmap on the screen you see after clicking a deck, the one with the Study Now button.",
    "chk_retention_scope": ("Works out retention from just the decks you pick below, while everything else still "
                            "counts all your decks. Handy when one deck, like a language deck, would pull your "
                            "retention up or down."),

    # Forecast
    "chk_fsrs_enabled": ("Uses FSRS, the memory model built into Anki, to predict your upcoming reviews. It "
                         "accounts for cards you'll forget and new cards you'll add. With it off, the forecast "
                         "just counts cards that are already scheduled. FSRS has to be turned on in Anki for "
                         "this to work."),
    "fsrs_ret_slider": ("The retention you're aiming for. Aiming higher means more reviews. It's best to match "
                        "what's set in your deck options."),
    "fsrs_new_cards_spin": ("How many new cards you plan to start on each of the days you pick. Set it to 0 to "
                            "only forecast cards you've already started."),
    "chk_fsrs_band": ("Shades in the range your reviews will probably fall in, based on how much your days "
                      "usually vary. It can't know about breaks or exam weeks ahead of time."),
    "fsrs_band_combo": ("How wide the shaded range is. The narrower one catches about 2 out of 3 days, and the "
                        "wider one about 6 out of 7."),
    "chk_fsrs_overhead": ("Counts every answer, including the extra steps for new and forgotten cards, so the "
                          "forecast lines up with the heatmap. With it off, only reviews of cards you've already "
                          "learned are counted, the same as Anki's own simulator."),
    "chk_custom_weights": ("Lets you type in your own FSRS parameters instead of using the ones from your deck "
                           "options. Most people won't need this."),
    "fsrs_deck_combo": "Picks which deck's FSRS settings the forecast uses. Most recent uses whichever deck you studied last.",

    # Day Details
    "day_topic_tag": ("When you click a day, your cards are grouped into topics by these tags. Leave it blank "
                      "to use AnKing's systems if you have them, or your subdecks if you don't."),
    "day_topic_level": ("How far down under that tag to go. At 1, cards are grouped by the tags right under it, "
                        "and 2 goes one level further."),
    "stats_topic_level": "How far down the topics go in the Stats window. Auto matches the setting above, up to 2.",

    # Time Left & Focus
    "chk_time_enabled": ("Estimates how long the rest of today's cards will take, based on how long your cards "
                         "have taken you in the past. It gets more accurate the more you review."),
    "chk_time_desk": "Includes the few seconds between cards, so the estimate matches what the clock actually says.",
    "chk_away_lookup": ("Your focus score already skips cards where you opened the editor or browser. Turn this "
                        "on to also skip cards where you switched to another app, if you only ever do that to "
                        "look things up."),
    "chk_reading_counts": ("Judges each card only by how long you spent on the question, so taking your time "
                           "with the answer won't hurt your focus score. It's off by default, because carefully "
                           "reading the back and zoning out look the same from the outside."),
    "focus_lookup_key": ("Press this during a review to leave that card out of your focus score, like when you "
                         "stop to look something up."),

    # Review Pill
    "rp_style": ("Graph shows a small line of how your recent answers went. Numbers shows your percentage and "
                 "how many you can still miss. Only when I hover keeps the pill quiet until you hover over it."),
    "rp_target": ("The retention you're aiming for. The pill tells you how many more cards you can miss, or "
                  "how many you need to get right, to stay there."),
    "rp_window": "Whether your retention counts just today's reviews, or every review you've done in this deck.",
    "chk_rp_focus": ("The pill turns amber when several recent cards took you a lot longer than usual. That can "
                     "be a sign your mind is wandering."),
    "rp_ring": ("A quick ring around the pill after each answer. It's green if the card took about as long as "
                "usual, and amber if it took longer. Cards you looked something up for don't get one."),
    "chk_rp_pomo": ("A countdown at the end of the pill. When a block ends, the break starts by itself, and "
                    "the next block starts when it's over. After the long break, a new set begins. Click the pill "
                    "to pause a block or end a break early. Hover it to end the session, or start a new one."),
    "chk_rp_pomo_pause": "The block only counts time on the review screen, so stepping away doesn't use it up.",
    "chk_rp_pomo_drift": ("When several cards in a row take much longer than usual, the pill offers a break "
                          "early. Needs Time Left turned on."),
    "chk_rp_pomo_notify": "A notification when a break ends, if you've switched away from Anki.",

    # Feedback
    "fb_diag": ("Sends along the add-on, Anki and system versions, which features you use, and your list of "
                "add-ons, so problems are easier to track down. It never includes your cards, decks or reviews."),
}


_TIP_DROP = 16


class HelpMark(QLabel):
    """A small ? that shows its text right away on hover."""

    def __init__(self, text, parent=None):
        super().__init__("?", parent)
        self.setObjectName("hmHelp")
        self.help = text
        self.setFixedSize(15, 15)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)

    def _tip(self):
        # Long ones wrap at a comfortable width; short ones stay one line.
        if len(self.help) <= 60:
            return f"<p style='white-space:pre'>{self.help}</p>"
        return f'<table width="280" cellpadding="0" cellspacing="0"><tr><td>{self.help}</td></tr></table>'

    def enterEvent(self, e):
        # Qt drops a tooltip about 16px below the point it's given (to clear the
        # pointer), so aim above it: the tip opens beside the ?, level with it.
        QToolTip.showText(self.mapToGlobal(QPoint(self.width() + 6, -2 - _TIP_DROP)),
                          self._tip(), self, self.rect())
        super().enterEvent(e)

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:     # already showing, from enterEvent
            return True
        return super().event(e)


class _Follow(QObject):
    """Hides a ? along with its setting when the page hides that setting."""

    def __init__(self, mark, parent):
        super().__init__(parent)
        self.mark = mark

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Hide:
            self.mark.hide()
        elif e.type() == QEvent.Type.Show:
            self.mark.show()
        return False


def _resolve(dlg, key):
    name, _, item = key.partition(".")
    w = getattr(dlg, name, None)
    if item and isinstance(w, dict):
        w = w.get(item)
    return w if isinstance(w, QWidget) else None


def _holder(layout, w):
    """The layout directly holding w, searched from layout down."""
    if layout is None:
        return None
    if layout.indexOf(w) >= 0:
        return layout
    for i in range(layout.count()):
        sub = layout.itemAt(i).layout()
        found = _holder(sub, w) if sub is not None else None
        if found is not None:
            return found
    return None


def _wrap(w, mark):
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(w)
    row.addWidget(mark)
    row.addStretch()
    return row


def _place(w, mark):
    """Put mark just after w, keeping w where it was. False if it can't."""
    parent = w.parentWidget()
    lay = None
    while parent is not None and lay is None:
        lay = _holder(parent.layout(), w)
        parent = parent.parentWidget() if lay is None else parent
    if lay is None:
        return False
    if isinstance(lay, QFormLayout):
        row, role = lay.getWidgetPosition(w)
        lay.removeWidget(w)
        box = QWidget()
        box.setLayout(_wrap(w, mark))
        lay.setWidget(row, role, box)
        return True
    if isinstance(lay, QGridLayout):
        idx = lay.indexOf(w)
        r, c, rs, cs = lay.getItemPosition(idx)
        lay.removeWidget(w)
        box = QWidget()
        box.setLayout(_wrap(w, mark))
        lay.addWidget(box, r, c, rs, cs)
        return True
    if isinstance(lay, QBoxLayout):
        idx = lay.indexOf(w)
        if lay.direction() in (QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.RightToLeft):
            # A row: after the setting and the boxes that go with it (a number, a value
            # label), stopping at a gap or the next checkbox or button
            end = idx + 1
            while end < lay.count():
                nxt = lay.itemAt(end).widget()
                if nxt is None or isinstance(nxt, QAbstractButton):
                    break
                end += 1
            lay.insertWidget(end, mark, 0, Qt.AlignmentFlag.AlignVCenter)
            return True
        lay.removeWidget(w)
        lay.insertLayout(idx, _wrap(w, mark))
        return True
    return False


def attach(dlg):
    """Add a ? after each setting in HELP that the settings window has."""
    for key, text in HELP.items():
        w = _resolve(dlg, key)
        if w is None:
            continue
        mark = HelpMark(text)
        if not _place(w, mark):
            mark.deleteLater()
            continue
        w.setToolTip(text)
        mark.setVisible(not w.isHidden())
        w.installEventFilter(_Follow(mark, w))
