"""
Day view: click a day on the heatmap to see it in detail. Totals against your usual
day, the focus box plot, a timeline of your sessions, your weakest topics, and every
card you answered (click one to open it in the Browser).

Read-only: everything goes through estimator.connect (SELECTs only, so Undo is
untouched). Focus needs Time Left on: past days use the model's per-answer focus
(estimator._fit_lock, the same numbers as the heatmap's FOCUS view), today uses
estimator.today_focus like the review pill.

Topics come from the "day_topic_tag" setting (a tag folder, grouped "day_topic_level"
levels below it); without one, AnKing's ^Systems tags, else subdecks.
"""

from __future__ import annotations

import datetime
import html
import json
import math
import re
import statistics

from aqt import mw
from aqt.qt import QDialog, QVBoxLayout

try:
    from aqt.webview import AnkiWebView
except ImportError:         # very old Anki: no bridge for clicks, so no day view
    AnkiWebView = None

from . import estimator as E
from .icons import icon

TOPIC_MIN_REVIEWS = 10      # topics with this many reviews rank first; smaller ones fill the rest
TOPICS_FILL_MIN = 3         # then topics with at least this many, then any
USUAL_DAYS = 30             # "usual" = the median of your study days in this window before the day
TOPICS_SHOWN = 5
REPEATED = 3                # a card answered this many times in a day is "repeated"
TEXT_MAX = 180
FOCUS_SESSION_MIN = 5       # answers before a session gets its own focus color

_get_config = lambda: {}
_edit_note = lambda date_str: False
_win = None


def setup(get_config, edit_note) -> None:
    """edit_note(date_str) opens the note dialog and returns True when it saved."""
    global _get_config, _edit_note
    _get_config, _edit_note = get_config, edit_note
    from aqt import gui_hooks
    gui_hooks.profile_will_close.append(close)


def available() -> bool:
    return AnkiWebView is not None


# ──────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────
def _rollover() -> int:
    try:
        return int(mw.col.get_config("rollover", 4))
    except Exception:
        return 4


def _day_start(d: datetime.date, ro: int) -> int:
    return int(datetime.datetime(d.year, d.month, d.day, ro).timestamp())


def _today(ro: int) -> datetime.date:
    return (datetime.datetime.now() - datetime.timedelta(hours=ro)).date()


def _deck_sql(deck_ids, alias="c") -> str:
    if not deck_ids:
        return ""
    return f" AND {alias}.did IN ({','.join(str(int(d)) for d in deck_ids)})"


def _firsts(conn, cids) -> dict:
    """{card id: id of its first-ever answer}."""
    out = {}
    cids = list(cids)
    for i in range(0, len(cids), 900):
        part = ",".join(str(int(c)) for c in cids[i:i + 900])
        # One index probe per card (about 3x faster here than GROUP BY over the IN list)
        out.update((cid, first) for cid, first in conn.execute(
            "SELECT c.id, (SELECT MIN(x.id) FROM revlog x WHERE x.cid = c.id AND x.type < 4) "
            f"FROM cards c WHERE c.id IN ({part})") if first is not None)
    return out


def _totals(rows, firsts, ro, exclude_new) -> dict:
    """{date: [answers, ms, retention rows, passed, new]} with the heatmap's retention:
    every answer but a card's first view (with exclude_new, none of a new card's
    answers on the day you met it)."""
    days = {}
    # A day changes only at (local) midnight, which is always on a 15-minute mark, so
    # look each 15-minute stretch's date up once rather than once per answer.
    shift, when = ro * 3600, {}

    def day_of(ms_id):
        k = (ms_id // 1000 - shift) // 900
        d = when.get(k)
        if d is None:
            d = when[k] = datetime.date.fromtimestamp(k * 900)
        return d

    for rid, cid, ease, ms, rtype in rows:
        d = day_of(rid)
        t = days.setdefault(d, [0, 0, 0, 0, 0])
        t[0] += 1
        t[1] += ms
        fid = firsts.get(cid, rid)
        first_view = rid == fid and rtype == 0
        if first_view:
            t[4] += 1
        if first_view or (exclude_new and day_of(fid) == d):
            continue
        t[2] += 1
        t[3] += ease > 1
    return days


_usual_cache = {}       # (collection, day start, decks, rollover, exclude_new, cards) -> _usual()


def _usual(conn, start: int, deck_ids, ro, exclude_new) -> dict | None:
    """Medians of your study days in the USUAL_DAYS before the day. They only look at
    days before it, which don't change, so each is worked out once a session (stepping
    between days, or opening one again, is quick)."""
    try:
        key = (mw.col.path, start, tuple(sorted(int(d) for d in deck_ids)) if deck_ids else None, ro,
               bool(exclude_new), conn.execute("SELECT count() FROM cards").fetchone()[0])
    except Exception:
        key = None
    if key is not None and key in _usual_cache:
        hit = _usual_cache[key]
        return dict(hit) if hit else hit
    out = _usual_calc(conn, start, deck_ids, ro, exclude_new)
    if key is not None:
        if len(_usual_cache) > 120:
            _usual_cache.clear()
        _usual_cache[key] = out
    return out


def _usual_calc(conn, start: int, deck_ids, ro, exclude_new) -> dict | None:
    lo = (start - USUAL_DAYS * 86400) * 1000
    rows = conn.execute(f"SELECT r.id, r.cid, r.ease, r.time, r.type FROM revlog r JOIN cards c ON c.id = r.cid "
                        f"WHERE r.id >= ? AND r.id < ? AND r.type < 4{_deck_sql(deck_ids)}",
                        (lo, start * 1000)).fetchall()
    if not rows:
        return None
    days = _totals(rows, _firsts(conn, {r[1] for r in rows}), ro, exclude_new).values()
    return {
        "n": statistics.median(t[0] for t in days),
        "sec": statistics.median(t[1] for t in days) / 1000,
        "ret": statistics.median(t[3] / t[2] for t in days if t[2]) if any(t[2] for t in days) else None,
        "new": statistics.median(t[4] for t in days),
    }


_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.S)


def _card_text(sfld, flds) -> str:
    """The card's sort field (else first non-empty field) as safe HTML, cloze answers
    in <b>, cut to TEXT_MAX characters."""
    raw = str(sfld or "") or next((f for f in str(flds or "").split("\x1f") if f.strip()), "")
    raw = re.sub(r"<br\s*/?>|<div>|</div>|<li>", " ", raw, flags=re.I)
    raw = html.unescape(re.sub(r"<[^>]+>", "", raw))
    raw = re.sub(r"\S+\.(?:png|jpe?g|gif|svg|webp|bmp|tiff?)\b", " ", raw, flags=re.I)   # image file names
    raw = re.sub(r"\?(?=[A-Za-z{])", "? ", raw)        # fields joined without a space
    out, used, pos = [], 0, 0
    for m in list(_CLOZE.finditer(raw)) + [None]:
        plain = raw[pos:m.start()] if m else raw[pos:]
        for text, bold in ((plain, False), ((m.group(1) if m else ""), True)):
            text = re.sub(r"\s+", " ", text)
            if not text or used >= TEXT_MAX:
                continue
            piece = text[:TEXT_MAX - used]
            used += len(piece)
            esc = html.escape(piece)
            out.append(f"<b>{esc}</b>" if bold else esc)
        if m is None:
            break
        pos = m.end()
    s = "".join(out).strip()
    if used >= TEXT_MAX:
        s += "…"
    return s or "<i>(no text)</i>"


def _tidy(part: str) -> str:
    s = re.sub(r"^[#^]+", "", part)
    s = re.sub(r"^\d+[\s._-]+(?=\D)", "", s)
    s = s.replace("_", " ").replace("-", " ").replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()


_ANKING_SYSTEM = re.compile(r"^#AK_Step\d+_v\d+::\^Systems::([^:]+)", re.I)


def _topic_keys(ans: list, cfg: dict, decks: dict):
    """(mode, [{key: (label, sub)} per answer]); mode is "tag", "anking" or "deck"."""
    prefix = [p.lower() for p in str(cfg.get("day_topic_tag", "") or "").strip().strip(":").split("::") if p]
    level = max(1, int(cfg.get("day_topic_level", 1) or 1))
    if prefix:
        n = len(prefix)
        out = []
        for a in ans:
            ks = {}
            for t in a["tags"]:
                parts = t.split("::")
                if len(parts) >= n + level and [p.lower() for p in parts[:n]] == prefix:
                    sub = parts[n:n + level]
                    ks[tuple(p.lower() for p in sub)] = (_tidy(sub[-1]), _tidy(sub[-2]) if level > 1 else "")
            out.append(ks)
        return "tag", out
    systems = []
    for a in ans:
        ks = {}
        for t in a["tags"]:
            m = _ANKING_SYSTEM.match(t)
            if m:
                ks[m.group(1).lower()] = (_tidy(m.group(1)), "")
        systems.append(ks)
    if any(systems):
        return "anking", systems
    out = []
    for a in ans:
        parts = decks.get(a["did"], "").split("::")
        out.append({parts[1].lower(): (parts[1], parts[0])} if len(parts) > 1 else {parts[0].lower(): (parts[0], "")})
    return "deck", out


def _topics(ans: list, cfg: dict, decks: dict) -> dict | None:
    mode, keys = _topic_keys(ans, cfg, decks)
    groups = {}
    for a, ks in zip(ans, keys):
        for k, (label, sub) in ks.items():
            g = groups.setdefault(k, {"label": label, "sub": sub, "n": 0, "rev": 0, "pass": 0, "new": 0})
            g["n"] += 1
            if a["type"] == 1:
                g["rev"] += 1
                g["pass"] += a["ease"] > 1
            if a["kind"] == "new":
                g["new"] += 1
    # Always TOPICS_SHOWN when you reviewed that many topics: the lowest retention among
    # well-reviewed topics first, then smaller topics fill the rest (a topic missed on its
    # only review would otherwise top every list).
    tier = lambda g: 0 if g["rev"] >= TOPIC_MIN_REVIEWS else 1 if g["rev"] >= TOPICS_FILL_MIN else 2
    weak = sorted((g for g in groups.values() if g["rev"]),
                  key=lambda g: (tier(g), g["pass"] / g["rev"], -g["rev"]))[:TOPICS_SHOWN]
    new_from = sorted((g for g in groups.values() if g["new"]), key=lambda g: -g["new"])[:3]
    if not weak and not new_from:
        return None
    if mode == "deck" and len(groups) < 2:
        return None
    new_total = sum(a["kind"] == "new" for a in ans)
    new_tagged = sum(1 for a, ks in zip(ans, keys) if a["kind"] == "new" and ks)
    return {"mode": mode, "weak": weak, "new_from": new_from,
            "covered": sum(1 for ks in keys if ks), "untagged_new": new_total - new_tagged}


def _focus_lookup(m, d: datetime.date, ro: int, conn, cfg) -> dict:
    """{answer id: focus x (None = lookup)} for the day, from the Time Left model."""
    from . import focus_log
    model_today = datetime.date.fromtimestamp(m.cutoff - 86400)
    if d >= model_today:
        if d != model_today:
            return {}
        rows = E.today_focus(m, conn, m.cutoff, focus_log.today_index(),
                             bool(cfg.get("focus_away_is_lookup")), bool(cfg.get("focus_reading_counts")))
        return {rid: x for rid, x, _ in rows}
    out = {}
    k = (d - model_today).days - 1                 # the model's day number (today == -1)
    for day in (k - 1, k, k + 1):                  # a day either side, for clock changes
        rids, xs = m.lock_answers.get(day, ((), ()))
        for rid, x in zip(rids, xs):
            out[rid] = None if math.isnan(x) else x
    return out


def collect(d: datetime.date, deck_ids=None) -> dict:
    """Everything the page shows for day d (in the heatmap's deck scope)."""
    from . import time_left
    cfg = _get_config()
    ro = _rollover()
    start = _day_start(d, ro)
    end = _day_start(d + datetime.timedelta(days=1), ro)
    exclude_new = bool(cfg.get("exclude_new_cards_from_retention", False))
    m = time_left._get_model() if time_left.enabled() else None
    if m is not None and not m.mu:
        m = None
    conn = E.connect(mw.col.path)
    try:
        rows = conn.execute(
            "SELECT r.id, r.cid, r.ease, r.time, r.type, r.lastIvl, c.did, n.sfld, n.flds, n.tags "
            "FROM revlog r JOIN cards c ON c.id = r.cid JOIN notes n ON n.id = c.nid "
            f"WHERE r.id >= ? AND r.id < ? AND r.type < 4{_deck_sql(deck_ids)} ORDER BY r.id",
            (start * 1000, end * 1000)).fetchall()
        decks = {int(i): str(n).replace("\x1f", "::") for i, n in conn.execute("SELECT id, name FROM decks")}
        firsts = _firsts(conn, {r[1] for r in rows}) if rows else {}
        usual = _usual(conn, start, deck_ids, ro, exclude_new)
        focus = _focus_lookup(m, d, ro, conn, cfg) if m is not None and rows else {}
    finally:
        conn.close()

    ans = []
    for rid, cid, ease, ms, rtype, last_ivl, did, sfld, flds, tags in rows:
        fid = firsts.get(cid, rid)
        intro_day = fid >= start * 1000
        if rtype == 0:
            kind = "new" if rid == fid else "learn"
        else:
            kind = "relearn" if rtype == 2 else "review"
        usual_t = None
        if m is not None:
            mkind = "new" if rtype == 0 and intro_day else ("learn" if rtype == 0 else kind)
            mu = m.mu.get((mkind, 1 if ease == 1 else 0))
            if mu is not None:
                usual_t = min(math.exp(mu + m.card_eff.get(cid, 0.0)), E.CAP)
        ans.append({"rid": rid, "cid": cid, "ease": ease, "ms": ms, "type": rtype, "kind": kind,
                    "last_ivl": last_ivl, "did": did, "tags": str(tags).split(),
                    "text": _card_text(sfld, flds), "usual": usual_t,
                    "x": focus.get(rid) if rid in focus else (math.nan if m is None else None)})
    totals = _totals([(a["rid"], a["cid"], a["ease"], a["ms"], a["type"]) for a in ans], firsts, ro,
                     exclude_new).get(d, [0, 0, 0, 0, 0])
    sessions, prev = [], None
    for a in ans:
        t = a["rid"] / 1000
        if prev is None or t - prev > E.SESSION_BREAK:
            sessions.append([])
        sessions[-1].append(a)
        prev = t
    reviews = [a for a in ans if a["type"] == 1]
    return {"date": d, "start": start, "end": end, "answers": ans, "totals": totals, "usual": usual,
            "sessions": sessions, "model": m, "decks": decks, "cfg": cfg,
            "review_ret": (sum(a["ease"] > 1 for a in reviews) / len(reviews)) if reviews else None,
            "topics": _topics(ans, cfg, decks) if ans else None}


# ──────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────
def _dur(sec: float) -> str:
    mins = int(round(sec / 60))
    if mins < 1:
        return "<1m"
    return f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"


def _clock(ts: float) -> str:
    t = datetime.datetime.fromtimestamp(ts)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _secs(a: dict) -> str:
    ms = a["ms"]
    s = f"{ms / 1000:.0f}s+" if ms >= 60000 and ms % 1000 == 0 else f"{ms / 1000:.1f}s"
    return s


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def _focus_of(xs: list) -> float | None:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    return sum(1 for x in xs if x <= E.LOCK_SD) / len(xs) if xs else None


_EASE = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}


def _ease_colors(night: bool) -> dict:
    if night:
        return {1: "#e5534b", 2: "#d29922", 3: "#57ab5a", 4: "#539bf5"}
    return {1: "#d1383d", 2: "#bf8700", 3: "#2f8f3a", 4: "#2f7fe0"}


def _timeline(data: dict, ink: dict, colors) -> str:
    w, h = 640.0, 52.0
    start = data["start"]
    span = data["end"] - start

    def x(ts):
        return 22 + max(0.0, min(1.0, (ts - start) / span)) * (w - 44)

    svg = (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" width="100%" style="display:block">'
           f'<line x1="22" y1="22" x2="{w - 22:.0f}" y2="22" class="grid"/>')
    for k in range(7):
        ts = start + k * span / 6
        svg += (f'<line x1="{x(ts):.1f}" y1="15" x2="{x(ts):.1f}" y2="29" class="grid"/>'
                f'<text x="{x(ts):.1f}" y="47" class="tk" text-anchor="middle">'
                f'{_clock(ts).replace(":00", "")}</text>')
    for s in data["sessions"]:
        t0, t1 = s[0]["rid"] / 1000, s[-1]["rid"] / 1000
        x0, x1 = x(t0), max(x(t1), x(t0) + 4)
        bh = min(26.0, 8 + math.sqrt(len(s)) * 0.9)
        f = _focus_of([a["x"] for a in s])
        fill = colors(f) if f is not None and len(s) >= FOCUS_SESSION_MIN else ink["short"]
        revs = [a for a in s if a["type"] == 1]
        tip = (f"<b>{_clock(t0)} – {_clock(t1)}</b><br>{len(s)} card{'s' if len(s) != 1 else ''} in "
               f"{_dur(sum(a['ms'] for a in s) / 1000)}")
        if f is not None:
            tip += f"<br>Focus {round(100 * f)}%"
        if revs:
            tip += f"<br>Retention {round(100 * sum(a['ease'] > 1 for a in revs) / len(revs))}%"
        svg += (f'<rect x="{x0:.1f}" y="{22 - bh / 2:.1f}" width="{x1 - x0:.1f}" height="{bh:.1f}" rx="3" '
                f'fill="{fill}" fill-opacity=".85" data-tip="{html.escape(tip)}"/>')
    return svg + "</svg>"


def _box_svg(review_pill, st: dict, typical, night: bool) -> str:
    """The review pill's focus box plot, drawn about twice its size here, so its
    labels are shrunk to stay at the page's text size."""
    return review_pill._lock_box(st["box"], typical, night, st.get("points")).replace(
        'font-size="8.5"', 'font-size="5.5"')


def _tiles(data: dict, focus_html: str) -> str:
    n, ms, ret_n, ret_p, new = data["totals"]
    u = data["usual"] or {}

    def tile(cap, val, sub):
        return f'<div class="stat"><div class="cap">{cap}</div><div class="big">{val}</div><div class="was">{sub}</div></div>'

    ret = f"{100 * ret_p / ret_n:.1f}%" if ret_n else "–"
    parts = [
        tile("Cards", f"{n:,}", f"usual {round(u['n']):,}" if u else ""),
        tile("Time", _dur(ms / 1000), f"usual {_dur(u['sec'])}" if u else ""),
        tile("Retention", ret, f"usual {100 * u['ret']:.1f}%" if u.get("ret") is not None else ""),
    ]
    if focus_html:
        parts.append(focus_html)
    parts.append(tile("New", f"{new:,}", f"usual {round(u['new'])}" if u else ""))
    return f'<div class="glass stats" style="grid-template-columns:repeat({len(parts)},1fr)">{"".join(parts)}</div>'


_TOPIC_FOOT = "<!--topic-foot-->"


def _topics_html(t: dict, review_ret, accent: str) -> str:
    if not t:
        return ""
    rows = ""
    line = 100 * review_ret if review_ret is not None else None
    # Bars start at 60%, or lower when a topic is below that (small topics can be).
    lo = min([60.0] + [10 * math.floor(10 * g["pass"] / g["rev"]) for g in t["weak"]])
    for g in t["weak"]:
        r = 100 * g["pass"] / g["rev"]
        bar = max(2.0, (r - lo) / (100 - lo) * 100)
        mark = (f'<div class="mark" style="left:{(line - lo) / (100 - lo) * 100:.1f}%"></div>'
                if line is not None and line > lo else "")
        sub = f'{html.escape(g["sub"])} · ' if g["sub"] else ""
        rows += (f'<div class="topic"><div class="tname">{html.escape(g["label"])}'
                 f'<div class="was">{sub}{g["rev"]} review{"s" if g["rev"] != 1 else ""}</div></div>'
                 f'<div class="track"><div class="fill" style="width:{bar:.1f}%"></div>{mark}</div>'
                 f'<div class="tpct">{r:.0f}%</div></div>')
    out = ""
    if t["weak"]:
        out += f'<div class="title">Weakest topics</div>{rows}{_TOPIC_FOOT}'
    if t["new_from"]:
        chips = "".join(f'<span class="chip">{html.escape(g["label"])} · {g["new"]}</span>' for g in t["new_from"])
        if t["mode"] != "deck" and t["untagged_new"]:
            chips += f'<span class="was" style="padding:3px 2px">+{t["untagged_new"]} untagged</span>'
        out += f'<div class="title" style="margin-top:12px">New cards from</div><div class="chips">{chips}</div>'
    return f'<div class="glass">{out}</div>'


def _lists(data: dict, has_focus: bool) -> tuple:
    """(answers JSON-ready, {tab: [[index, label], ...]}, tab order)."""
    ans = data["answers"]
    rows = []
    for a in ans:
        ivl = a["last_ivl"]
        rows.append([_clock(a["rid"] / 1000), a["text"], a["ease"], _secs(a),
                     None if a["usual"] is None else f"{a['usual']:.0f}s", a["cid"], _ivl(ivl),
                     f"{ivl} day{'s' if ivl != 1 else ''}" if ivl > 0 else ""])

    def default(a):
        return {"new": "new", "learn": "learning", "relearn": "relearning"}.get(a["kind"], "")

    tabs = {"all": [[i, default(a)] for i, a in enumerate(ans)]}
    again = [i for i, a in enumerate(ans) if a["ease"] == 1]
    # Forgotten reviews first, longest interval first.
    again.sort(key=lambda i: (-(ans[i]["last_ivl"] if ans[i]["kind"] == "review" else -1), i))
    tabs["again"] = [[i, default(ans[i])] for i in again]
    if has_focus:
        slow = [i for i, a in enumerate(ans) if a["x"] is not None and not math.isnan(a["x"]) and a["x"] > E.LOCK_SD]
        slow.sort(key=lambda i: -ans[i]["x"])
        tabs["slow"] = [[i, default(ans[i])] for i in slow]
    seen = {}
    for i, a in enumerate(ans):
        seen.setdefault(a["cid"], []).append(i)
    rep = sorted((v for v in seen.values() if len(v) >= REPEATED), key=lambda v: (-len(v), v[0]))
    tabs["rep"] = [[v[0], f"{len(v)} times"] for v in rep]
    return rows, tabs


def _ivl(ivl: int) -> str:
    """The card's interval before this answer (revlog lastIvl: days, or −seconds for a
    learning step): '12d', '7 wk', '5 mo', '1.5 yr', '10m'; '–' for a new card."""
    if ivl < 0:
        sec = -ivl
        return f"{max(1, round(sec / 60))}m" if sec < 3600 else f"{round(sec / 3600)}h"
    if ivl == 0:
        return "–"
    if ivl < 14:
        return f"{ivl}d"
    if ivl < 60:
        return f"{round(ivl / 7)} wk"
    if ivl < 365:
        return f"{round(ivl / 30.4)} mo"
    return f"{round(ivl / 365.25, 1):g} yr"


_JS = """
var D = %DATA%, cur = D.start;
var tip = document.getElementById('tip');
document.addEventListener('mousemove', function (e) {
  var t = e.target.getAttribute && e.target.getAttribute('data-tip');
  if (!t) { tip.style.display = 'none'; return; }
  tip.innerHTML = t; tip.style.display = 'block';
  var w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(e.clientX + 12, innerWidth - w - 8) + 'px';
  tip.style.top = Math.max(8, e.clientY - h - 12) + 'px';
});
function show(k) {
  cur = k;
  document.querySelectorAll('.tabs button').forEach(function (b) { b.classList.toggle('on', b.dataset.k === k); });
  var out = [];
  D.tabs[k].forEach(function (p) {
    var a = D.rows[p[0]];
    out.push('<div class="crow" data-cid="' + a[5] + '"><span class="was">' + a[0] + '</span><span class="ctext">' +
      a[1] + (p[1] ? ' <span class="was">· ' + p[1] + '</span>' : '') +
      '</span><span class="ivl"' + (a[7] ? ' data-tip="' + a[7] + '"' : '') + '>' + a[6] + '</span><span class="ease e' + a[2] + '">' +
      D.ease[a[2]] + '</span><span class="secs">' + a[3] + (a[4] ? ' <span class="was">/ ' + a[4] + '</span>' : '') +
      '</span></div>');
  });
  document.getElementById('cards').innerHTML = out.join('') ||
    '<div class="was" style="padding:14px 0;text-align:center">None on this day.</div>';
}
document.querySelectorAll('.tabs button').forEach(function (b) { b.onclick = function () { show(b.dataset.k); }; });
document.getElementById('cards').addEventListener('click', function (e) {
  var r = e.target.closest('.crow');
  if (r) pycmd('day:browse:' + r.dataset.cid);
});
var ob = document.getElementById('open');
if (ob) ob.onclick = function () {
  var seen = {}, ids = [];
  D.tabs[cur].forEach(function (p) { var c = D.rows[p[0]][5]; if (!seen[c]) { seen[c] = 1; ids.push(c); } });
  if (ids.length) pycmd('day:browse:' + ids.join(','));
};
document.addEventListener('keydown', function (e) {
  if (e.key === 'ArrowLeft') pycmd('day:go:-1');
  else if (e.key === 'ArrowRight') pycmd('day:go:1');
  else if (e.key === 'Escape') pycmd('day:close');
});
if (D.start) show(D.start);
"""


def theme(night: bool, accent: str, backdrop: dict | None = None, glass: float = 0.45) -> tuple:
    """(ink, panel css, photo css): the colors and glass panels the main screen uses,
    shared with the stats window."""
    lo_glass = max(0.0, glass - 0.2)
    if night:
        ink = {"fg": "rgba(255,255,255,.92)", "sub": "rgba(255,255,255,.58)", "base": "#1f1f1f",
               "line": "255,255,255", "accent": accent, "short": "#8a8f98"}
        panel = (f"background:linear-gradient(135deg,rgba(30,30,30,{glass}) 0%,rgba(10,10,10,{lo_glass}) 100%);"
                 "border:1px solid rgba(255,255,255,.08);"
                 "box-shadow:0 8px 32px 0 rgba(0,0,0,.4),inset 0 0 0 1px rgba(255,255,255,.02);")
    else:
        ink = {"fg": "#1d2733", "sub": "rgba(29,39,51,.62)", "base": "#ffffff", "line": "29,39,51",
               "accent": accent, "short": "#9aa0a8"}
        panel = (f"background:linear-gradient(135deg,rgba(255,255,255,{glass}) 0%,"
                 f"rgba(255,255,255,{lo_glass}) 100%);border:1px solid rgba(255,255,255,.18);"
                 "box-shadow:0 8px 32px 0 rgba(0,0,0,.1),inset 0 0 0 1px rgba(255,255,255,.05);")
    if not backdrop:
        panel += f"background:rgba({ink['line']},.035);border:1px solid rgba({ink['line']},.08);box-shadow:none;"
    photo = ""
    if backdrop:
        photo = (f'body::before{{content:"";position:fixed;inset:0;z-index:-1;'
                 f'background:url("{backdrop["url"]}") {backdrop.get("position", "center")}/'
                 f'{backdrop.get("size", "cover")} no-repeat;opacity:{backdrop.get("opacity", 1)}}}')
    return ink, panel, photo


def page(data: dict, night: bool, accent: str, backdrop: dict | None = None, glass: float = 0.45,
         note: str = "", exam: list | None = None, scope: str = "", is_today: bool = False) -> str:
    from . import review_pill
    ink, panel, photo = theme(night, accent, backdrop, glass)
    ec = _ease_colors(night)
    css = (f"html,body{{margin:0;min-height:100%}}body{{padding:14px 18px 18px;background:{ink['base']};"
           f"color:{ink['fg']};font:13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
           "-webkit-font-smoothing:antialiased;box-sizing:border-box}" + photo +
           f".glass{{{panel}border-radius:16px;padding:12px 14px;margin-bottom:12px;"
           "backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}"
           ".head{display:flex;align-items:center;gap:10px;margin:0 2px 12px}"
           ".head h1{font-size:18px;font-weight:600;margin:0}"
           f".nav{{all:unset;cursor:pointer;width:26px;height:26px;border-radius:8px;text-align:center;"
           f"line-height:26px;font-size:16px;color:{ink['fg']};background:rgba({ink['line']},.07)}}"
           f".nav:hover{{background:rgba({ink['line']},.14)}}.nav.off{{opacity:.3;pointer-events:none}}"
           f".btn{{all:unset;cursor:pointer;font-size:12px;padding:4px 11px;border-radius:8px;"
           f"background:rgba({ink['line']},.07)}}.btn:hover{{background:rgba({ink['line']},.14)}}"
           ".stats{display:grid;padding:12px 4px}"
           f".stat{{padding:0 12px}}.stat+.stat{{border-left:1px solid rgba({ink['line']},.12)}}"
           f".cap{{font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:{ink['sub']}}}"
           ".big{font-size:21px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:3px}"
           f".was{{font-size:11px;color:{ink['sub']}}}"
           ".two{display:grid;grid-template-columns:1.3fr 1fr;gap:12px}.two>.glass{margin-bottom:12px}"
           ".title{font-size:13px;font-weight:600;margin:0 0 8px}"
           f".tk{{fill:{ink['sub']};font-size:10px;font-weight:600}}"
           f".grid{{stroke:rgba({ink['line']},.14);stroke-width:1}}"
           ".bar{display:flex;height:12px;border-radius:4px;overflow:hidden;margin:2px 0 6px}"
           ".keys{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11.5px}"
           ".keys i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}"
           ".keys .grad{display:inline-block;width:72px;height:8px;border-radius:4px;margin:0 6px;"
           "vertical-align:-1px}"
           ".kinds{display:grid;grid-template-columns:1fr auto;gap:3px 0;margin-top:10px;font-size:12px}"
           ".boxsvg svg{width:100%!important;height:auto!important}"
           ".topic{display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr) 38px;gap:10px;"
           "align-items:center;margin:6px 0}.tname{font-size:12.5px;line-height:1.3}"
           f".track{{height:8px;border-radius:4px;background:rgba({ink['line']},.08);position:relative}}"
           f".fill{{height:100%;border-radius:4px;background:{ec[1]};opacity:.75}}"
           f".mark{{position:absolute;top:-3px;bottom:-3px;border-left:1.5px dashed {ink['sub']}}}"
           ".tpct{text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums}"
           ".chips{display:flex;flex-wrap:wrap;gap:6px}"
           f".chip{{font-size:12px;padding:3px 10px;border-radius:999px;background:{accent}2e;"
           f"border:1px solid {accent}66}}"
           ".chead{display:flex;align-items:center;gap:8px;margin-bottom:4px}"
           f".tabs{{display:flex;gap:3px}}.tabs button{{all:unset;cursor:pointer;font-size:9.5px;font-weight:700;"
           f"letter-spacing:.5px;text-transform:uppercase;padding:4px 9px;border-radius:8px;color:{ink['sub']}}}"
           f".tabs button i{{font-style:normal;font-weight:600;opacity:.75;margin-left:4px}}"
           f".tabs button.on{{background:{accent};color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.2)}}"
           f".crow{{display:grid;grid-template-columns:62px minmax(0,1fr) 46px 50px 78px;gap:8px;align-items:center;"
           f"font-size:12.5px;padding:7px 4px;border-top:1px solid rgba({ink['line']},.09);cursor:pointer;"
           f"border-radius:6px}}.crow:hover{{background:rgba({ink['line']},.06)}}"
           f".ctext{{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}"
           f".ctext b{{color:{accent};font-weight:600}}"
           ".ease{font-size:10.5px;font-weight:600;padding:1px 0;border-radius:999px;text-align:center}"
           + "".join(f".e{k}{{color:{c};background:{c}24;border:1px solid {c}55}}" for k, c in ec.items()) +
           ".secs{text-align:right;font-variant-numeric:tabular-nums}"
           f".ivl{{text-align:right;font-variant-numeric:tabular-nums;color:{ink['sub']}}}"
           f".chdr{{cursor:default;border-top:0;padding-top:2px;padding-bottom:2px;font-size:9px;font-weight:700;"
           f"letter-spacing:.5px;text-transform:uppercase;color:{ink['sub']}}}.chdr:hover{{background:none}}"
           ".chdr span:nth-child(n+3){text-align:right}.chdr span:nth-child(4){text-align:center}"
           # A thin see-through scrollbar instead of the white system one
           "::-webkit-scrollbar{width:12px;height:12px;background:transparent}"
           "::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}"
           f"::-webkit-scrollbar-thumb{{background:rgba({ink['line']},.28);border-radius:8px;"
           "border:3px solid transparent;background-clip:padding-box}"
           f"::-webkit-scrollbar-thumb:hover{{background:rgba({ink['line']},.45);background-clip:padding-box}}"
           ".note{font-size:13.5px;line-height:1.5;white-space:pre-wrap}"
           f".empty{{text-align:center;color:{ink['sub']};padding:48px 0}}"
           "#tip{position:fixed;display:none;background:rgba(0,0,0,.92);color:#fff;padding:7px 10px;"
           "border-radius:6px;font-size:11px;line-height:1.45;pointer-events:none;z-index:9;"
           "box-shadow:0 4px 10px rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);max-width:260px}")
    d = data["date"]
    ans = data["answers"]
    title = f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}" + (f", {d.year}" if d.year != _today(_rollover()).year else "")
    sub = [html.escape(scope)] if scope else []
    if data["sessions"]:
        sub.append(f"{len(data['sessions'])} session{'s' if len(data['sessions']) != 1 else ''}")
        sub.append(f"{_clock(ans[0]['rid'] / 1000)} – {_clock(ans[-1]['rid'] / 1000)}")
    exam_html = ""
    for e in exam or []:        # a day can have more than one exam
        c = e.get("color", "#e74c3c")
        exam_html += (f'<span class="chip" style="background:{c}2e;border-color:{c}66">'
                      f'{html.escape(str(e.get("label", "Exam")))}</span> ')
    head = (f'<div class="head"><button class="nav" onclick="pycmd(\'day:go:-1\')" title="Previous day">{icon("left")}</button>'
            f'<div style="flex:1"><h1>{title} {exam_html}</h1><div class="was">{" · ".join(sub)}</div></div>'
            f'<button class="btn" onclick="pycmd(\'day:note\')">{"Edit note" if note or exam else "Add note"}</button>'
            f'<button class="nav{" off" if is_today else ""}" onclick="pycmd(\'day:go:1\')" title="Next day">{icon("right")}</button></div>')
    note_html = (f'<div class="glass"><div class="cap" style="margin-bottom:4px">Personal note</div>'
                 f'<div class="note">{html.escape(note)}</div></div>') if note else ""
    doc = (f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>{head}")
    if not ans:
        msg = "No reviews yet today." if is_today else "No reviews on this day."
        return doc + note_html + (f'<div class="glass empty">{msg}</div><div id="tip"></div>'
                      f'<script>{_JS.replace("%DATA%", json.dumps({"start": ""}))}</script></body></html>')

    m = data["model"]
    xs = [a["x"] for a in ans if a["x"] is not None and not math.isnan(a["x"])]
    st = E.lock_stats(xs, points=True) if m is not None and len(xs) >= E.LOCK_MIN else None
    lo, hi = m.lock_range if m is not None else (0.6, 0.85)
    colors = lambda f: _hex(review_pill._gradient_rgb(f, lo, hi))
    focus_tile, box = "", ""
    if st is not None:
        focus_tile = (f'<div class="stat"><div class="cap">Focus</div><div class="big" style="color:{colors(st["score"])}">'
                      f'{round(100 * st["score"])}%</div><div class="was">usual {round(100 * lo)}–{round(100 * hi)}%</div></div>')
        typical = m.lock_typical["box"] if m.lock_typical else None
        box = (f'<div class="glass"><div class="title">Answer speed</div>'
               f'<div class="boxsvg">{_box_svg(review_pill, st, typical, night)}</div>'
               f'<div class="was" style="display:flex;justify-content:space-between;gap:8px">'
               f'<span>Faint: a typical day</span><span>Past the dashed line: slow</span></div></div>')
    elif m is not None:
        focus_tile = ('<div class="stat"><div class="cap">Focus</div><div class="big">–</div>'
                      '<div class="was">not enough data</div></div>')
    counts = {k: sum(1 for a in ans if a["ease"] == k) for k in (1, 2, 3, 4)}
    n = len(ans)
    bar = "".join(f'<div style="width:{100 * c / n:.2f}%;background:{ec[k]}"></div>' for k, c in counts.items() if c)
    keys = "".join(f'<span><i style="background:{ec[k]}"></i>{_EASE[k]} {c:,}</span>' for k, c in counts.items())
    kinds = {"review": "Reviews", "learn": "Learning", "new": "New", "relearn": "Relearning"}
    kind_rows = "".join(f'<span class="was" style="font-size:12px">{label}</span>'
                        f'<span>{sum(1 for a in ans if a["kind"] == k):,}</span>' for k, label in kinds.items())
    answers = (f'<div class="glass"><div class="title">Answers</div><div class="bar">{bar}</div>'
               f'<div class="keys">{keys}</div><div class="kinds">{kind_rows}</div></div>')
    mid = f'<div class="two">{box}{answers}</div>' if box else answers
    if m is not None:
        dot = lambda c: f'<i style="background:{c}"></i>'
        grad = f"linear-gradient(90deg,{colors(lo)},{colors((lo + hi) / 2)},{colors(hi)})"
        key = (f'<div class="keys was" style="margin-top:2px;align-items:center"><span>Focus:</span>'
               f'<span>Low<b class="grad" style="background:{grad}"></b>High</span>'
               f'<span>{dot(ink["short"])}Not enough data</span></div>')
    else:
        key = ""
    timeline = (f'<div class="glass"><div class="title">Your day</div>{_timeline(data, ink, colors)}'
                f'{key}</div>')
    t = data["topics"]
    topics = _topics_html(t, data["review_ret"], accent)
    if t:
        foot = (f'<div class="was" style="margin:4px 0 2px">Dashed line: your {100 * data["review_ret"]:.0f}% overall</div>'
                if data["review_ret"] is not None and t["weak"] else "")
        topics = topics.replace(_TOPIC_FOOT, foot)
    rows, tabs = _lists(data, st is not None)
    names = [("all", "All"), ("again", "Again"), ("slow", "Slow"), ("rep", "Repeated")]
    tab_html = "".join(f'<button data-k="{k}">{label}<i>{len(tabs[k]):,}</i></button>' for k, label in names if k in tabs)
    first = "again" if tabs["again"] else "all"
    cards = (f'<div class="glass"><div class="chead"><span class="title" style="margin:0">Cards</span>'
             f'<div class="tabs">{tab_html}</div><span style="flex:1"></span>'
             f'<button class="btn" id="open">Open in Browser</button></div>'
             f'<div class="crow chdr"><span></span><span></span><span>Interval</span><span>Answer</span>'
             f'<span>Time</span></div><div id="cards"></div></div>')
    blob = json.dumps({"rows": rows, "tabs": tabs, "start": first, "ease": _EASE}).replace("</", "<\\/")
    return (doc + _tiles(data, focus_tile) + note_html + mid + timeline + topics + cards +
            f'<div id="tip"></div><script>{_JS.replace("%DATA%", blob)}</script></body></html>')


# ──────────────────────────────────────────────────────────────
# Window
# ──────────────────────────────────────────────────────────────
class DayWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        from . import time_left
        self.setWindowTitle("Day Details")
        self.setStyleSheet(f"QDialog {{ background: {'#1f1f1f' if time_left._is_night() else '#ffffff'}; }}")
        self.resize(800, 880)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.web = AnkiWebView(self, title="day details")
        self.web.set_bridge_command(self._on_cmd, self)
        lay.addWidget(self.web)
        self.date, self.deck_ids, self.scope = None, None, ""

    def load(self, d: datetime.date, deck_ids, scope: str) -> None:
        from . import time_left
        self.date, self.deck_ids, self.scope = d, deck_ids, scope
        cfg = _get_config()
        ds = d.isoformat()
        exams = cfg.get("exam_days", {})
        exam = ([{"label": "Exam", "color": "#e74c3c"}] if ds in exams else None) if isinstance(exams, list) \
            else exams.get(ds)
        if isinstance(exam, dict):      # one exam saved as a dict, several as a list
            exam = [exam]
        exam = [e for e in exam or [] if isinstance(e, dict)] or None
        try:
            html_ = page(collect(d, deck_ids), time_left._is_night(), time_left._new_color(),
                         time_left._backdrop(), time_left._glass_opacity(),
                         note=cfg.get("daily_notes", {}).get(ds, ""), exam=exam, scope=scope,
                         is_today=d >= _today(_rollover()))
        except Exception as e:      # show what went wrong rather than a blank window
            import traceback
            html_ = (f"<body style='font:13px -apple-system,sans-serif;padding:20px;color:#999'>"
                     f"This day couldn't be shown: {html.escape(str(e))}"
                     f"<pre style='font-size:11px'>{html.escape(traceback.format_exc())}</pre></body>")
        from . import lowpower
        self.web.setHtml(lowpower.into(html_))

    def _on_cmd(self, cmd: str):
        if cmd.startswith("day:go:"):
            d = self.date + datetime.timedelta(days=int(cmd.split(":")[2]))
            if d <= _today(_rollover()):
                self.load(d, self.deck_ids, self.scope)
        elif cmd == "day:note":
            if _edit_note(self.date.isoformat()):
                self.load(self.date, self.deck_ids, self.scope)
        elif cmd.startswith("day:browse:"):
            ids = [c for c in cmd.split(":")[2].split(",") if c.isdigit()]
            if ids:
                from aqt import dialogs
                browser = dialogs.open("Browser", mw)
                browser.search_for(f"cid:{','.join(ids)}")
        elif cmd == "day:close":
            self.close()
        return None


def _alive(w) -> bool:
    try:
        w.isVisible()
        return True
    except (RuntimeError, AttributeError):
        return False


def show(date_str: str, deck_ids=None, scope: str = "") -> None:
    """Open (or move) the day window to date_str. Its own window, never inside a modal
    exec(): see time_left.show_accuracy."""
    global _win
    if mw.col is None or AnkiWebView is None:
        return
    if _win is None or not _alive(_win):
        _win = DayWindow(mw)
    _win.load(datetime.date.fromisoformat(date_str), deck_ids, scope)
    first = not _win.isVisible()
    _win.show()
    if first:
        _fit_on_screen(_win)
    _win.raise_()
    _win.activateWindow()


def _fit_on_screen(w) -> None:
    """Shrink and move the window so all of it, title bar included, is below the menu
    bar: centered on Anki's window it could start above the top of the screen."""
    try:
        screen = (mw.screen() if hasattr(mw, "screen") else None) or w.screen()
        avail = screen.availableGeometry()
        frame = w.frameGeometry()
        bar = frame.height() - w.height()           # the title bar
        width = min(w.width(), avail.width() - 40)
        height = min(w.height(), avail.height() - bar - 40)
        if (width, height) != (w.width(), w.height()):
            w.resize(width, height)
        frame = w.frameGeometry()
        x = min(max(frame.x(), avail.left() + 20), avail.right() - frame.width() - 20)
        y = min(max(frame.y(), avail.top() + 20), avail.bottom() - frame.height() - 20)
        if (x, y) != (frame.x(), frame.y()):
            w.move(x, y)
    except Exception:
        pass


def close() -> None:
    global _win
    if _win is not None and _alive(_win):
        _win.close()
    _win = None
