"""
Release notes, newest first: the What's New window and Settings → Version History
both read these. For a new release, add an entry at the top and set VERSION in
__init__.py to match.
"""

from __future__ import annotations

RELEASES = [
    {"version": '1.9.6', "date": 'November 9, 2026', "notes": [
        ('Forecast shading', "In Volume view, future days get darker the more cards are due. Turn it off in Settings → General."),
        ('Smoother reviews', "Cards show up right away, before Live Stats updates."),
        ('Bug fixes', "Fixes Anki's memory use growing on the deck screen."),
    ]},
    {"version": '1.9.5', "date": 'November 8, 2026', "notes": [
        ('Heatmap improvements', "Adds more heatmap display settings, like separating months, and lets you scroll back through more of your history."),
        ('Performance improvements', ""),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.4', "date": 'November 4, 2026', "notes": [
        ('Pomodoro timer', "Adds a pomodoro timer to your daily reviews, in Live Stats. Turn it on in Settings → Live Stats."),
        ('Bug fixes and improvements', ""),
    ]},
    {"version": '1.9.3', "date": 'November 2, 2026', "notes": [
        ('New name', "Interactive Heatmap is now Elemental."),
        ('More stats', "Look back on your reviews, when you study and how each of your topics is going. Click STATS next to the heatmap's views."),
        ('Reminders', "Short reminders under your decks, like your next exam or cards not synced. Pick them in Settings → Reminders."),
        ('Better heatmap tooltips', "Hover a day to see how it compares to your average."),
        ('Animations', "Small animations when you finish the day, come back to your decks, or reach a streak milestone."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.2', "date": 'October 31, 2026', "notes": [
        ('Day details', "Click a day on the heatmap to see it up close."),
        ('Better forecast', "The forecast is more accurate and can show confidence intervals."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.1', "date": 'October 31, 2026', "notes": [
        ('Focus score', "See how focused you were today, in Live Stats and as a heatmap view."),
        ('Themes and background photos', "19 themes, and photos behind your decks and reviews."),
        ('AnKing card styling', "A cleaner layout for AnKing cards."),
        ('New settings window', "A sidebar, search and live previews."),
        ('Send feedback', "Send a bug report or idea from Settings → Feedback."),
        ('Bug fixes', ""),
    ]},
    {"version": '1.9.0', "date": 'October 29, 2026', "notes": [
        ('Time Left', "See how long today's cards will take."),
        ('Live Stats', "Your retention and finish time while you review."),
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
