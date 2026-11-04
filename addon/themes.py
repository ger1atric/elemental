"""
Heatmap color themes — one choice that sets every color the heatmap uses: the cells
(volume, the Time and New views, today's border, forecast and empty days), the graph
lines, and the deck list's count pills. Each theme has a light and a dark version and
follows Anki's mode. Retention, speed and focus keep their red-to-green scales, since
those colors mean something.

"custom" (shown as "My colors") uses the colors saved in the config. A theme never
overwrites those: it's laid over them when the config is read (apply), and the saved
ones are put back whenever the config is written (keep_saved_colors), so picking a theme
and coming back to My colors loses nothing.
"""

from __future__ import annotations

# palette field: config key
FIELDS = {
    "base": "base_color",
    "today": "today_color",
    "forecast": "forecast_color",
    "reviews": "graph_reviews_color",
    "time": "graph_time_color",
    "studied": "graph_time_studied_color",
    "retention": "graph_retention_color",
    "fcast": "graph_forecast_color",
    "fsrs": "fsrs_prediction_color",
    "time_view": "custom_time_color",
    "new_view": "custom_newcards_color",
    "new": "pill_new_color",
    "learn": "pill_learn_color",
    "due": "pill_due_color",
    "filtered": "filtered_deck_color",
}
# "empty" is per mode in the config already: light → empty_color, dark → empty_color_night
THEME_KEYS = tuple(FIELDS.values()) + ("empty_color", "empty_color_night")


def _p(base, today, forecast, empty, reviews, time, studied, retention, fcast, fsrs,
       time_view, new_view, new, learn, due, filtered):
    return dict(base=base, today=today, forecast=forecast, empty=empty, reviews=reviews,
                time=time, studied=studied, retention=retention, fcast=fcast, fsrs=fsrs,
                time_view=time_view, new_view=new_view, new=new, learn=learn, due=due,
                filtered=filtered)


#                  base       today      forecast   empty      reviews    time       studied    retention  fcast      fsrs       time view  new view   new        learn      due        filtered
THEMES = {
    # Photo themes: colors taken from a built-in photo (background.BUILTIN), which
    # becomes the background when the theme is picked.
    "highland_mist": {"name": "Highland Mist", "photo": "highland_mist",
        "light": _p("#6b8f3a", "#3f5f74", "#c9cdd3", "#e6e8ea", "#4f6f86", "#b0873a", "#8a6f9e", "#c4a24a", "#a6acb5", "#5f8a7a", "#b0873a", "#4f7f6a", "#2b7bc0", "#cf3f62", "#c69000", "#6a8f8a"),
        "dark":  _p("#9bbf5a", "#a6c4d8", "#3e4642", "#252c27", "#8fb0c8", "#d9b25f", "#b8a0cc", "#e0c46a", "#777a72", "#8fbfae", "#d9b25f", "#8fbfae", "#6db8f2", "#f27a98", "#f5c84a", "#9cc4bf")},
    "forest_trail": {"name": "Forest Trail", "photo": "forest_trail",
        "light": _p("#3f7d3a", "#c08a2e", "#d6d2c2", "#ebe8dc", "#3d6b4f", "#b5651d", "#8a6d3b", "#c9a13b", "#a39e8a", "#5a8f6a", "#b5651d", "#5a8f6a", "#1d86a8", "#d6512a", "#c29200", "#7a9a5a"),
        "dark":  _p("#7fbf5f", "#eac989", "#3a3d30", "#22281f", "#8fc49a", "#e0925a", "#c4a576", "#eac989", "#6e6a55", "#9fd0a8", "#e0925a", "#9fd0a8", "#5cc6e8", "#ff8a5c", "#f2cc4a", "#b5d08a")},
    "rolling_hills": {"name": "Rolling Hills", "photo": "rolling_hills",
        "light": _p("#6aa318", "#3b6e8f", "#cfd8c0", "#e7eedc", "#3b7a2e", "#c7801f", "#4f8a8a", "#b5a21b", "#a7b39a", "#2f7a5a", "#c7801f", "#2f7a5a", "#1f7fd6", "#e0453a", "#c29100", "#4f8a8a"),
        "dark":  _p("#9ed534", "#9cc7e8", "#34402c", "#1c2616", "#a6d98a", "#f0a94a", "#7fc4c4", "#e0d65a", "#6b7a5c", "#6fcf9f", "#f0a94a", "#6fcf9f", "#66b8ff", "#ff7a66", "#ffd23f", "#7fc4c4")},
    "starlight": {"name": "Starlight", "photo": "starlight",
        "light": _p("#b0703f", "#7b68b5", "#d8cfc6", "#ece6df", "#5a6b9e", "#c2783f", "#8e6fb0", "#c9a063", "#a8998c", "#7b68b5", "#c2783f", "#8e6fb0", "#4f63d6", "#d6456a", "#cc8418", "#9a7fb5"),
        "dark":  _p("#d9a06e", "#c6b4f0", "#3b3735", "#211f1d", "#9fb0e0", "#e0a070", "#c6a8e8", "#ecc890", "#70605d", "#b9a6f0", "#e0a070", "#c6a8e8", "#8ea0ff", "#ff7f9f", "#ffc266", "#d8b4e0")},
    "na_pali": {"name": "Nā Pali", "photo": "na_pali",
        "light": _p("#0f8f8f", "#3d7a2a", "#c8d3d3", "#e2ecec", "#1f5fa8", "#d49a4a", "#6b7fbf", "#d4b25a", "#9fb0b0", "#2a9d8f", "#d49a4a", "#3d7a2a", "#0a86c2", "#e4503c", "#c8900f", "#2a9d8f"),
        "dark":  _p("#2ec4c0", "#9ad46a", "#2f4a4c", "#102326", "#6fa8e8", "#f0c27a", "#a6b4f0", "#f0d68a", "#5f7c7a", "#5fd4c4", "#f0c27a", "#9ad46a", "#3cc8f0", "#ff7b63", "#ffcf4d", "#5fd4c4")},
    "wanaka_dusk": {"name": "Wānaka Dusk", "photo": "wanaka_dusk",
        "light": _p("#7b5fc7", "#3f8a5a", "#d6d0e6", "#ebe7f3", "#5a6fd0", "#b5607f", "#b06ad0", "#c7a04f", "#a9a0c0", "#5a9ab0", "#c45f8a", "#5a6fd0", "#4566e0", "#d9437f", "#cf8d1f", "#9a6fd0"),
        "dark":  _p("#b09af0", "#8fd0a0", "#3e3852", "#262236", "#9aa8f5", "#f0a0c0", "#d7a7f2", "#f0d08a", "#6e6888", "#8fc8e0", "#f0a0c0", "#9aa8f5", "#8fa4ff", "#ff7eb3", "#ffcc66", "#d7a7f2")},
    # Color themes
    "classic": {"name": "Classic",
        "light": _p("#8e44ad", "#2ecc71", "#bdc3c7", "#ebedf0", "#3498db", "#e67e22", "#3498db", "#f1c40f", "#95a5a6", "#9b59b6", "#e67e22", "#27ae60", "#2d84e8", "#ec3f36", "#c88f00", "#20b2aa"),
        "dark":  _p("#9b59b6", "#2ecc71", "#4b5260", "#282c34", "#3498db", "#e67e22", "#3498db", "#f1c40f", "#95a5a6", "#b07cc6", "#e67e22", "#27ae60", "#4da3ff", "#ff5c52", "#ffd426", "#20b2aa")},
    "github": {"name": "GitHub",
        "light": _p("#2da44e", "#0969da", "#d0d7de", "#ebedf0", "#0969da", "#bc4c00", "#8250df", "#bf8700", "#8c959f", "#8250df", "#fb8f44", "#54aeff", "#0969da", "#d72a35", "#c48a00", "#1b7c83"),
        "dark":  _p("#39d353", "#58a6ff", "#484f58", "#161b22", "#58a6ff", "#f0883e", "#bc8cff", "#d29922", "#6e7681", "#bc8cff", "#f0883e", "#79c0ff", "#58a6ff", "#ff6b63", "#e3b341", "#39c5cf")},
    "ocean": {"name": "Ocean",
        "light": _p("#1e88e5", "#00a88f", "#b0bec5", "#e3eaf2", "#1565c0", "#ef6c00", "#7e57c2", "#f9a825", "#90a4ae", "#26a69a", "#ff8f00", "#26a69a", "#1a7fe0", "#e63950", "#cf8d00", "#00acc1"),
        "dark":  _p("#4fb3fb", "#1de9b6", "#455a64", "#1c2530", "#64b5f6", "#ffb74d", "#b39ddb", "#ffd54f", "#78909c", "#4db6ac", "#ffb74d", "#4db6ac", "#5ab8ff", "#ff5f6d", "#ffd54f", "#4dd0e1")},
    "catppuccin": {"name": "Catppuccin",
        "light": _p("#8839ef", "#40a02b", "#bcc0cc", "#dce0e8", "#1e66f5", "#fe640b", "#7287fd", "#df8e1d", "#9ca0b0", "#179299", "#fe640b", "#179299", "#1e66f5", "#d20f39", "#d6881c", "#209fb5"),
        "dark":  _p("#cba6f7", "#a6e3a1", "#45475a", "#313244", "#89b4fa", "#fab387", "#b4befe", "#f9e2af", "#6c7086", "#94e2d5", "#fab387", "#94e2d5", "#89b4fa", "#f38ba8", "#fab387", "#74c7ec")},
    "nord": {"name": "Nord",
        "light": _p("#5e81ac", "#7d9b62", "#d8dee9", "#e5e9f0", "#5e81ac", "#d08770", "#b48ead", "#c8a24a", "#a5adbb", "#6a9c9b", "#d08770", "#6a9c9b", "#3b78c4", "#c94f5c", "#c78f20", "#5f9cad"),
        "dark":  _p("#88c0d0", "#a3be8c", "#4c566a", "#3b4252", "#81a1c1", "#d08770", "#b48ead", "#ebcb8b", "#616e88", "#8fbcbb", "#d08770", "#a3be8c", "#8fc7e8", "#f07c86", "#f2cf7a", "#8fbcbb")},
    "dracula": {"name": "Dracula",
        "light": _p("#644ac9", "#14710a", "#cfcbe0", "#e9e5f5", "#036a96", "#a34d14", "#a3144d", "#846e15", "#635d97", "#0e7c86", "#a34d14", "#036a96", "#0277bd", "#d63a2f", "#b88600", "#a3144d"),
        "dark":  _p("#bd93f9", "#50fa7b", "#44475a", "#343746", "#8be9fd", "#ffb86c", "#ff79c6", "#f1fa8c", "#6272a4", "#8be9fd", "#ffb86c", "#50fa7b", "#8be9fd", "#ff5555", "#f1fa8c", "#ff79c6")},
    "tokyo_night": {"name": "Tokyo Night",
        "light": _p("#2e7de9", "#587539", "#c4c8da", "#d5d6db", "#2e7de9", "#b15c00", "#9854f1", "#8c6c3e", "#848cb5", "#118c74", "#b15c00", "#118c74", "#2e7de9", "#f52a65", "#c48a00", "#007197"),
        "dark":  _p("#7aa2f7", "#9ece6a", "#3b4261", "#292e42", "#7aa2f7", "#ff9e64", "#bb9af7", "#e0af68", "#565f89", "#73daca", "#ff9e64", "#73daca", "#7aa2f7", "#ff7a93", "#ffc777", "#7dcfff")},
    "gruvbox": {"name": "Gruvbox",
        "light": _p("#d65d0e", "#79740e", "#d5c4a1", "#ebdbb2", "#076678", "#af3a03", "#8f3f71", "#b57614", "#928374", "#427b58", "#b57614", "#427b58", "#1a6fa8", "#cc241d", "#c88e1f", "#427b58"),
        "dark":  _p("#fe8019", "#b8bb26", "#504945", "#3c3836", "#83a598", "#fe8019", "#d3869b", "#fabd2f", "#928374", "#8ec07c", "#fabd2f", "#8ec07c", "#7fb8d8", "#fb4934", "#fabd2f", "#8ec07c")},
    "rose_pine": {"name": "Rosé Pine",
        "light": _p("#d7827e", "#286983", "#dfdad9", "#f2e9e1", "#286983", "#ea9d34", "#907aa9", "#b4637a", "#9893a5", "#56949f", "#ea9d34", "#56949f", "#2f8aa3", "#c9506f", "#d5891d", "#907aa9"),
        "dark":  _p("#ebbcba", "#9ccfd8", "#403d52", "#26233a", "#9ccfd8", "#f6c177", "#c4a7e7", "#eb6f92", "#6e6a86", "#31748f", "#f6c177", "#9ccfd8", "#9ccfd8", "#eb6f92", "#f6c177", "#c4a7e7")},
    "everforest": {"name": "Everforest",
        "light": _p("#8da101", "#3a94c5", "#e0dcc7", "#efebd4", "#3a94c5", "#f57d26", "#df69ba", "#dfa000", "#939f91", "#35a77c", "#f57d26", "#35a77c", "#3a94c5", "#f85552", "#c89000", "#35a77c"),
        "dark":  _p("#a7c080", "#7fbbb3", "#475258", "#343f44", "#7fbbb3", "#e69875", "#d699b6", "#dbbc7f", "#859289", "#83c092", "#e69875", "#83c092", "#6fc3d8", "#f2777a", "#e8c35a", "#83c092")},
    "solarized": {"name": "Solarized",
        "light": _p("#268bd2", "#859900", "#d9d2bf", "#eee8d5", "#268bd2", "#cb4b16", "#6c71c4", "#b58900", "#93a1a1", "#2aa198", "#cb4b16", "#2aa198", "#268bd2", "#dc322f", "#b58900", "#d33682"),
        "dark":  _p("#268bd2", "#859900", "#586e75", "#073642", "#268bd2", "#cb4b16", "#6c71c4", "#b58900", "#586e75", "#2aa198", "#cb4b16", "#2aa198", "#3a9ee6", "#f04a45", "#d9a300", "#d33682")},
    "sakura": {"name": "Sakura",
        "light": _p("#e0607e", "#5b9a68", "#e8d5da", "#f6e9ec", "#6a7fdb", "#f08a5d", "#b07cd8", "#e0a53a", "#b5a3a8", "#4fa3a5", "#f08a5d", "#4fa3a5", "#4f73e8", "#e8475f", "#c98f18", "#b07cd8"),
        "dark":  _p("#f4a7b9", "#8fcf9b", "#4a3a40", "#33282c", "#9fb0f5", "#f6a57f", "#cfa6ee", "#f3cf7a", "#7d6b71", "#7cc7c9", "#f6a57f", "#7cc7c9", "#94adff", "#ff7088", "#ffd166", "#cfa6ee")},
    "graphite": {"name": "Graphite",
        "light": _p("#4a4a4a", "#e5484d", "#d6d6d6", "#ebebeb", "#4a4a4a", "#e09f3e", "#7a7a7a", "#b0b0b0", "#c2c2c2", "#7a7a7a", "#6b6b6b", "#6b6b6b", "#3f7fc8", "#d9534f", "#c09313", "#7a9e9e"),
        "dark":  _p("#d4d4d4", "#ff6369", "#444444", "#2a2a2a", "#d4d4d4", "#f0b45a", "#9a9a9a", "#6e6e6e", "#555555", "#9a9a9a", "#b5b5b5", "#b5b5b5", "#7fb2f0", "#ff7b7b", "#f0c75e", "#9cc4c4")},
}

CUSTOM = "custom"


def photo(theme: str) -> str | None:
    """The built-in photo a photo theme goes with, else None."""
    return (THEMES.get(theme) or {}).get("photo")


def palette(theme: str, night: bool) -> dict | None:
    t = THEMES.get(theme)
    return None if t is None else t["dark" if night else "light"]


def colors(theme: str, night: bool) -> dict | None:
    """{config key: color} that the theme sets, for the current mode."""
    t = THEMES.get(theme)
    if t is None:
        return None
    out = {key: t["dark" if night else "light"][f] for f, key in FIELDS.items()}
    out["empty_color"] = t["light"]["empty"]
    out["empty_color_night"] = t["dark"]["empty"]
    return out


def apply(conf: dict, night: bool) -> dict:
    """Lay the chosen theme's colors over conf (in place) and return it."""
    over = colors(str(conf.get("heatmap_theme", CUSTOM)), night)
    if over:
        conf.update(over)
    return conf


def keep_saved_colors(conf: dict, saved: dict) -> dict:
    """Before writing: while a theme is chosen, keep the saved colors instead of the
    theme's, so My colors is still there when you switch back."""
    if str(conf.get("heatmap_theme", CUSTOM)) in THEMES:
        for key in THEME_KEYS:
            if key in saved:
                conf[key] = saved[key]
            else:
                conf.pop(key, None)
    return conf


def readable_text(hex_color: str) -> str:
    """White or near-black text, whichever reads better on hex_color."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    except Exception:
        return "#fff"
    return "#1e1e1e" if lum > 0.36 else "#fff"


# ── Glow: a smooth color scale for heatmaps ───────────────────────────────────
# Quiet cells sit close to the background and busy ones move well past the base
# color (toward pale on dark backgrounds, toward deep on light ones), so neighbors
# differ in lightness, not only in how see-through they are. Cells are placed by
# rank (glow_ranker), so the whole range gets used whatever the numbers are.

def _mix_hex(a, b, t):
    try:
        pa = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        pb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return a
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


GLOW_MID = 0.5      # where along the scale the base color itself sits
GLOW_FLOOR = 0.08   # the quietest cell still sits a little off the background


GLOW_CONTRAST = 0.75  # the Glow Contrast setting's default


def glow_stops(base, night, contrast=GLOW_CONTRAST):
    """[low, base, high] for the scale. contrast (0..1) sets how far the two ends
    move away from the base color."""
    c = max(0.0, min(1.0, float(contrast)))
    if night:
        return [_mix_hex(base, "#101214", 0.40 + 0.50 * c), base, _mix_hex(base, "#ffffff", 0.20 + 0.50 * c)]
    return [_mix_hex(base, "#ffffff", 0.46 + 0.48 * c), base, _mix_hex(base, "#000000", 0.15 + 0.40 * c)]


def glow(base, t, night, contrast=GLOW_CONTRAST):
    """The scale's color at t (0 = quietest, 1 = busiest)."""
    lo, mid, hi = glow_stops(base, night, contrast)
    t = GLOW_FLOOR + (1 - GLOW_FLOOR) * max(0.0, min(1.0, t))
    if t <= GLOW_MID:
        return _mix_hex(lo, mid, t / GLOW_MID)
    return _mix_hex(mid, hi, (t - GLOW_MID) / (1 - GLOW_MID))


def glow_ranker(values):
    """A function giving each value its place 0..1 among values (ties share one)."""
    import bisect
    xs = sorted(v for v in values if v > 0)
    n = len(xs)
    if n <= 1:
        return lambda v: 1.0

    def rank(v):
        lo, hi = bisect.bisect_left(xs, v), bisect.bisect_right(xs, v)
        return max(0.0, min(1.0, ((lo + hi - 1) / 2) / (n - 1)))
    return rank
