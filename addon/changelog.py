"""
Release notes, newest first: the What's New window and Settings → Version History
both read these. For a new release, add an entry at the top and set VERSION in
__init__.py to match.
"""

from __future__ import annotations

RELEASES = [
    {"version": '1.9.4', "date": 'November 4, 2026', "notes": [
        ('Pomodoro timer', "A focus timer in the review pill, with breaks in between. Turn it on in Settings → Review Pill."),
        ('Simpler review pill', "Hovering the pill shows one time: time left or your finish time, whichever you chose."),
    ]},
    {"version": '1.9.3', "date": 'November 2, 2026', "notes": [
        ('New name', "Interactive Heatmap is now Elemental."),
        ('Rolling Hills', "New installs start with the Rolling Hills theme. It looks best with Anki's dark mode (Preferences → Appearance → Theme)."),
        ('Your stats', "A stats window for your reviews, study times and topics. Click STATS next to the heatmap's views."),
        ('Reminders', "Short reminders under your decks, like your next exam or cards not synced. Pick them in Settings → Reminders."),
        ('Better day tooltips', "Hover a day to see how it compares to your average."),
        ('Animations', "Small animations when you finish the day, come back to your decks, or reach a streak milestone."),
        ('Help in Settings', "Hover the ? next to a setting to see what it does."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.2', "date": 'October 31, 2026', "notes": [
        ('Day details', "Click a day on the heatmap to see it up close."),
        ('Better forecast', "The forecast is more accurate and can show a likely range."),
        ('Skip a card from focus', "Press X during review to leave a card out of your focus score."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.1', "date": 'October 31, 2026', "notes": [
        ('Focus score', "See how focused you were today, on the review pill and as a heatmap view."),
        ('Themes and background photos', "19 themes, and photos behind your decks and reviews."),
        ('AnKing card styling', "A cleaner layout for AnKing cards."),
        ('New settings window', "A sidebar, search and live previews."),
        ('Send feedback', "Send a bug report or idea from Settings → Feedback."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.0', "date": 'October 29, 2026', "notes": [
        ('Time Left', "See how long today's cards will take."),
        ('Review pill', "Your retention and finish time while you review."),
    ]},
    {"version": '1.7.2', "date": 'July 3, 2026', "notes": [
        ('New and Time views', "Two more ways to color the heatmap."),
        ('Faster loading', ""),
        ('Bug fixes', ""),
    ]},
    {"version": '1.5.1', "date": 'February 24, 2026', "notes": [
        ('60-day graph', "30 days back and 30 days ahead, with an FSRS forecast."),
        ('Rolling averages', ""),
        ('Exam dates on the graph', ""),
    ]},
    {"version": '1.4.0', "date": 'February 6, 2026', "notes": [
        ('Deck filter', "Pick which decks the heatmap covers."),
        ('Heatmap on the overview screen', ""),
    ]},
    {"version": '1.3.4', "date": 'January 30, 2026', "notes": [
        ('Bug fixes', ""),
    ]},
    {"version": '1.3.2', "date": 'January 26, 2026', "notes": [
        ('Browser themes', "Color themes and custom colors for the card browser."),
        ('Browser row spacing', ""),
    ]},
]


def _key(version: str) -> tuple:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return ()


def since(last_seen: str) -> list:
    """Releases newer than last_seen (all you missed), or just the latest on a first install."""
    if not last_seen or not _key(last_seen):
        return RELEASES[:1]
    newer = [r for r in RELEASES if _key(r["version"]) > _key(last_seen)]
    return newer or RELEASES[:1]
