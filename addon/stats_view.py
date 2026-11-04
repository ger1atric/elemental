"""
Stats window: your reviews over a month, three months, a year or all time. Totals,
each day/week/month (what you were adding, answers by kind; retention, focus and speed on hover),
when you study, how well you remember after each gap, how your cards grew, your topics,
and the cards you forgot most.

Read-only like the day view: one pass over the revlog through estimator.connect, in the
background. Colors come from the heatmap's theme (get_config is themed), and the panels
and photo from day_view.theme, so it sits on the same background as the main screen.
Topics use the Day Details setting (day_topic_tag), grouped "stats_topic_level" levels
down (0 = auto: the Day Details level, at most 2); a level named like an exam ("Exam 2",
"Final", "OSPE 3 …") folds into its parent.
"""

from __future__ import annotations

import bisect
import collections
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
except ImportError:
    AnkiWebView = None

from . import day_view
from . import themes
from . import estimator as E

RANGES = {"month": "30 days", "quarter": "3 months", "year": "Year", "all": "All time"}
TAIL_DAYS = {"month": 7, "quarter": 28, "year": 28, "all": 90}     # the "last …" under the totals
MATURE = 21
TOPICS_SHOWN = 7
HARD_SHOWN = 8                              # Forgot most: shown at first
HARD_MAX = 40                               # ... and after Show all
MEM_BANDS = (14, 30, 60, 120, 240, 480)     # days since first studied, for "around the same time"
MEM_MIN = 20                                # review cards a topic needs for its stability
MEM_CLIP = 1.6                              # a card counts at most ×5 (e^1.6) above or below
MEM_SELF = 0.6                              # topic is this much of its own comparison: no number
GAPS = [(0, 1.5, "1d", "1 day"), (1.5, 3.5, "2–3d", "2–3 days"), (3.5, 7.5, "4–7d", "4–7 days"),
        (7.5, 14.5, "1–2 wk", "1–2 weeks"), (14.5, 30.5, "2–4 wk", "2–4 weeks"),
        (30.5, 90.5, "1–3 mo", "1–3 months"), (90.5, 1e9, "3 mo +", "3+ months")]
GAP_MIN = 30                # reviews before a gap gets a dot
_ASSESS = re.compile(r"^(exam|final|midterm|quiz|test|ospe|shelf|nbme)\b", re.I)
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_get_config = lambda: {}
_win = None
_range = "year"


def setup(get_config) -> None:
    global _get_config
    _get_config = get_config
    from aqt import gui_hooks
    gui_hooks.profile_will_close.append(close)


def available() -> bool:
    return AnkiWebView is not None


# ──────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────
def _step(rng: str, today: datetime.date, first: datetime.date) -> int:
    """Days per bar: daily for 30 days, every 2 days for 3 months, weekly for a year;
    0 = calendar months for all time."""
    return {"month": 1, "quarter": 2, "year": 7}.get(rng, 0)


def _span(s: datetime.date, e: datetime.date) -> str:
    if s == e:
        return f"{s.strftime('%a')}, {_MON[s.month - 1]} {s.day}"
    if s.month == e.month:
        return f"{_MON[s.month - 1]} {s.day} – {e.day}"
    return f"{_MON[s.month - 1]} {s.day} – {_MON[e.month - 1]} {e.day}"


def _buckets(rng: str, today: datetime.date, first: datetime.date) -> tuple:
    """([(start, end, name, tick)] oldest first, days per bar)."""
    step = _step(rng, today, first)
    out = []
    if step:
        count = {"month": 30, "quarter": 46, "year": 52}[rng]
        prev = None
        for k in range(count - 1, -1, -1):
            e = today - datetime.timedelta(days=step * k)
            s = e - datetime.timedelta(days=step - 1)
            if step < 7:            # a date every 7 bars: weekly for daily bars, fortnightly for 2-day ones
                tick = f"{_MON[e.month - 1]} {e.day}" if k % 7 == 0 and k < count - 1 else ""
            else:
                tick = "" if prev is None or e.month == prev else _MON[e.month - 1]
                prev = e.month
            out.append((s, e, _span(s, e), tick))
        return out, step
    y, m = first.year, first.month
    months = (today.year - y) * 12 + today.month - m + 1
    for _ in range(months):
        s = datetime.date(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        e = min(today, datetime.date(ny, nm, 1) - datetime.timedelta(days=1))
        tick = str(y) if m == 1 else ""
        out.append((s, e, f"{_MON[m - 1]} {y}", tick if out else ""))
        y, m = ny, nm
    return out, 0


def _grouper(cfg: dict, decks: dict, all_tags: dict):
    """(mode, fn(tags, did) -> (key, label, sub, rest) | None); mode is "tag", "anking" or "deck".
    all_tags is {tags: reviews} over the cards in scope.
    rest is the path below the topic (raw tag parts or subdeck names), for expanding its row."""
    prefix = [p.lower() for p in str(cfg.get("day_topic_tag", "") or "").strip().strip(":").split("::") if p]
    if prefix:
        n = len(prefix)
        level = int(cfg.get("stats_topic_level", 0) or 0) or min(2, max(1, int(cfg.get("day_topic_level", 1) or 1)))

        def by_tag(tags, did):
            for t in sorted(tags.split()):
                parts = t.split("::")
                if len(parts) <= n or [p.lower() for p in parts[:n]] != prefix:
                    continue
                sub = parts[n:n + level]
                if not sub[0][:1].isalnum():
                    continue                    # "(✏️)-Tagged-by-…" and such
                if len(sub) > 1 and _ASSESS.match(day_view._tidy(sub[-1])):
                    sub = sub[:-1]
                return (tuple(p.lower() for p in sub), day_view._tidy(sub[-1]),
                        day_view._tidy(sub[-2]) if len(sub) > 1 else "", tuple(parts[n + len(sub):]))
            return None
        return "tag", by_tag
    # AnKing systems only when cards carrying them get most of your reviews; a few AnKing
    # cards in your own decks shouldn't stand in for all of them
    with_ak = sum(n for tags, n in all_tags.items() if any(day_view._ANKING_SYSTEM.match(t) for t in tags.split()))
    if with_ak and 2 * with_ak >= sum(all_tags.values()):
        def by_system(tags, did):
            for t in tags.split():
                m = day_view._ANKING_SYSTEM.match(t)
                if m:
                    return (m.group(1).lower(), day_view._tidy(m.group(1)), "", tuple(t.split("::")[3:]))
            return None
        return "anking", by_system

    def by_deck(tags, did):
        parts = decks.get(did, "").split("::")
        if len(parts) > 1:
            return (parts[1].lower(), parts[1], parts[0], tuple(parts[2:]))
        return (parts[0].lower(), parts[0], "", ()) if parts[0] else None
    return "deck", by_deck


def _focus(xs: list) -> float | None:
    return sum(1 for x in xs if x <= E.LOCK_SD) / len(xs) if len(xs) >= E.LOCK_MIN else None


def collect(rng: str, deck_ids, cfg: dict, m, path: str, ro: int) -> dict:
    """Everything the page shows. Runs in the background: no mw.col here."""
    today = (datetime.datetime.now() - datetime.timedelta(hours=ro)).date()
    exclude_new = bool(cfg.get("exclude_new_cards_from_retention", False))
    dsql = day_view._deck_sql(deck_ids)
    conn = E.connect(path)
    try:
        rows = conn.execute("SELECT r.id, r.cid, r.ease, r.time, r.type, r.ivl FROM revlog r "
                            f"JOIN cards c ON c.id = r.cid WHERE r.type < 4{dsql} ORDER BY r.cid, r.id").fetchall()
        cards = conn.execute(f"SELECT c.id, n.tags, c.did, c.ivl, c.type, c.queue, c.data FROM cards c JOIN notes n ON n.id = c.nid "
                             f"WHERE 1{dsql}").fetchall()
        decks = {int(i): str(n).replace("\x1f", "::") for i, n in conn.execute("SELECT id, name FROM decks")}
    finally:
        conn.close()
    if not rows:
        return {"empty": True, "rng": rng}

    day_of = lambda rid: datetime.date.fromtimestamp(rid / 1000 - ro * 3600)
    first_day = day_of(min(r[0] for r in rows))
    B, step = _buckets(rng, today, first_day)
    nb = len(B)
    lo_day = B[0][0]
    starts = [b[0] for b in B]
    span = (today - lo_day).days + 1
    tail_lo = today - datetime.timedelta(days=TAIL_DAYS[rng] - 1)

    revs = collections.Counter(r[1] for r in rows)
    tag_revs = collections.Counter()
    for c in cards:
        tag_revs[c[1]] += revs[c[0]]
    mode, group_of = _grouper(cfg, decks, tag_revs)
    gcache, card_group, card_ivl, card_mem, card_nodes = {}, {}, {}, {}, {}
    for cid, tags, did, ivl, ctype, queue, cdata in cards:
        k = (tags, did)
        if k not in gcache:
            g = group_of(tags, did)
            below = []                      # (node key, label) for each level below the topic
            if g is not None:
                for i, part in enumerate(g[3]):
                    label = day_view._tidy(part)
                    if not label:
                        break
                    below.append(((g[0],) + tuple(q.lower() for q in g[3][:i + 1]), label))
            gcache[k] = (g, below)
        card_group[cid], card_nodes[cid] = gcache[k]
        card_ivl[cid] = ivl
        if ctype == 2 and queue >= 0 and ivl > 0:
            try:
                stab = float(json.loads(cdata).get("s") or 0) if cdata else 0.0
            except (ValueError, TypeError, AttributeError):
                stab = 0.0
            card_mem[cid] = (stab, ivl)

    def bucket(d):
        return bisect.bisect_right(starts, d) - 1

    kinds = [[0, 0, 0] for _ in range(nb)]          # review, new + learning, relearn
    firsts = [0] * nb                               # first views, grouped or not
    ms_b = [0] * nb
    times_b = [[] for _ in range(nb)]
    ret_b = [[0, 0] for _ in range(nb)]
    days_seen = set()
    punch = [[[0, 0, 0, 0] for _ in range(24)] for _ in range(7)]   # answers, retention rows, passed, ms
    gaps = [[0, 0] for _ in GAPS]
    growth_diff = [[0, 0, 0] for _ in range(nb)]     # learning, young, mature: changes in each bucket
    groups, nodes = {}, {}
    again, seen = {}, {}
    rid_bucket = {}
    tot = {"n": 0, "ms": 0, "rn": 0, "rp": 0, "new": 0}
    tail = {"rn": 0, "rp": 0}

    first_seen = {}
    prev_cid, fid, fday, prev_rid, state = None, 0, None, 0, -1
    for rid, cid, ease, ms, rtype, ivl in rows:
        d = day_of(rid)
        if cid != prev_cid:
            prev_cid, fid, fday, prev_rid, state = cid, rid, d, 0, -1
            first_seen[cid] = d
        new_state = 2 if ivl >= MATURE else (1 if ivl > 0 else 0)
        if new_state != state and d <= today:
            k = max(0, bucket(d))
            if state >= 0:
                growth_diff[k][state] -= 1
            growth_diff[k][new_state] += 1
            state = new_state
        if d >= lo_day:
            k = bucket(d)
            first_view = rid == fid and rtype == 0
            firsts[k] += first_view
            kinds[k][0 if rtype in (1, 3) else (2 if rtype == 2 else 1)] += 1
            ms = min(ms, 60000)
            ms_b[k] += ms
            times_b[k].append(ms)
            days_seen.add(d)
            tot["n"] += 1
            tot["ms"] += ms
            tot["new"] += first_view
            rid_bucket[rid] = k
            t = datetime.datetime.fromtimestamp(rid / 1000)
            cell = punch[d.weekday()][t.hour]
            cell[0] += 1
            cell[3] += ms
            g = card_group.get(cid)
            if g is not None:
                gr = groups.get(g[0])
                if gr is None:
                    gr = groups[g[0]] = {"label": g[1], "sub": g[2], "n": 0, "ms": 0, "rn": 0, "rp": 0,
                                         "vol": [0] * nb, "nw": [0] * nb}
                gr["n"] += 1
                gr["ms"] += ms
                gr["vol"][k] += 1
                gr["nw"][k] += first_view
                nds = []
                for nk, label in card_nodes[cid]:
                    nd = nodes.get(nk)
                    if nd is None:
                        nd = nodes[nk] = {"label": label, "n": 0, "ms": 0, "rn": 0, "rp": 0, "vol": [0] * nb}
                    nd["n"] += 1
                    nd["ms"] += ms
                    nd["vol"][k] += 1
                    nds.append(nd)
            counted = not (first_view or (exclude_new and fday == d))
            if counted:
                ok = ease > 1
                ret_b[k][0] += 1
                ret_b[k][1] += ok
                tot["rn"] += 1
                tot["rp"] += ok
                cell[1] += 1
                cell[2] += ok
                if d >= tail_lo:
                    tail["rn"] += 1
                    tail["rp"] += ok
                if g is not None:
                    gr["rn"] += 1
                    gr["rp"] += ok
                    for nd in nds:
                        nd["rn"] += 1
                        nd["rp"] += ok
                seen[cid] = seen.get(cid, 0) + 1
                if not ok:
                    again[cid] = again.get(cid, 0) + 1
            if rtype == 1 and prev_rid:
                el = (rid - prev_rid) / 86400000
                for j, (g_lo, g_hi, _, _) in enumerate(GAPS):
                    if g_lo <= el < g_hi:
                        gaps[j][0] += 1
                        gaps[j][1] += ease > 1
                        break
        prev_rid = rid

    # Focus: the model's per-answer numbers (its last HISTORY_DAYS; today isn't in them)
    focus_b = [[] for _ in range(nb)]
    all_x, tail_x = [], []
    if m is not None:
        for _day, (rids, xs) in m.lock_answers.items():
            for rid, x in zip(rids, xs):
                k = rid_bucket.get(rid)
                if k is None or math.isnan(x):
                    continue
                focus_b[k].append(x)
                all_x.append(x)
                if day_of(rid) >= tail_lo:
                    tail_x.append(x)

    run = best = 0
    d = lo_day
    while d <= today:
        run = run + 1 if d in days_seen else 0
        best = max(best, run)
        d += datetime.timedelta(days=1)

    growth, cum = [], [0, 0, 0]
    for k in range(nb):
        cum = [c + g for c, g in zip(cum, growth_diff[k])]
        growth.append({"learning": cum[0], "young": cum[1], "mature": cum[2]})

    sizes = {}
    for cid, cg in card_group.items():
        if cg is not None:
            mature = card_ivl[cid] >= MATURE
            for key in [cg[0]] + [nk for nk, _ in card_nodes[cid] if nk in nodes]:
                sz = sizes.setdefault(key, [0, 0])
                sz[0] += 1
                sz[1] += mature
    # Stability by topic: each review card's FSRS stability (its interval without FSRS) against
    # your cards first studied around the same time, so a newer topic isn't low just for being
    # new. A topic's number averages its cards on a log scale (capped, centered on the average
    # card that age), so the cards you forgot count: a median misses them in young topics, where
    # most cards have the same few Good answers and so the same stability.
    use_s = len(card_mem) > 0 and 2 * sum(1 for st, _ in card_mem.values() if st > 0) >= len(card_mem)
    pool = []
    for cid, (st, ivl) in card_mem.items():
        v, f = (st if use_s else ivl), first_seen.get(cid)
        if v > 0 and f is not None:
            pool.append((cid, bisect.bisect_left(MEM_BANDS, (today - f).days), v))
    by_band = {}
    for _, b, v in pool:
        by_band.setdefault(b, []).append(v)
    band_med = {b: statistics.median(vs) for b, vs in by_band.items()}
    clip = lambda x: max(-MEM_CLIP, min(MEM_CLIP, x))
    band_mid = {b: statistics.fmean(clip(math.log(v / band_med[b])) for v in vs) for b, vs in by_band.items()}
    mem = {}
    for cid, b, v in pool:
        g = card_group.get(cid)
        if g is not None:
            x = clip(math.log(v / band_med[b])) - band_mid[b]
            for key in [g[0]] + [nk for nk, _ in card_nodes[cid] if nk in nodes]:
                mem.setdefault(key, []).append((x, v, b))

    def stability(mm):
        """(ratio vs same-age cards, median days, compared mostly with itself)"""
        if len(mm) < MEM_MIN:
            return None, None, False
        mine = {}
        for _, _, b in mm:
            mine[b] = mine.get(b, 0) + 1
        self_share = sum(n * n / len(by_band[b]) for b, n in mine.items()) / len(mm)
        if self_share > MEM_SELF:
            return None, statistics.median(v for _, v, _ in mm), True
        return math.exp(statistics.fmean(x for x, _, _ in mm)), statistics.median(v for _, v, _ in mm), False

    def row(key, g):
        n_cards, mature = sizes.get(key, (0, 0))
        rel, days, alone = stability(mem.get(key, []))
        return {"label": g["label"], "n": g["n"], "hours": g["ms"] / 3.6e6,
                "ret": g["rp"] / g["rn"] if g["rn"] else None, "cards": n_cards,
                "mature": mature / n_cards if n_cards else None, "vol": g["vol"],
                "mem": rel, "mem_days": days, "mem_alone": alone}

    kids_of = {}
    for nk in nodes:
        kids_of.setdefault(nk[:-1], []).append(nk)

    def kids(parent):
        out = []
        for nk in sorted(kids_of.get(parent, []), key=lambda c: -nodes[c]["n"]):
            r = row(nk, nodes[nk])
            r["kids"] = kids(nk)
            out.append(r)
        # a lone child ("Lecture › Class Content") adds nothing to open: skip that level
        return out[0]["kids"] if len(out) == 1 else out

    topics = []
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"]):
        t = row(key, g)
        t.update(sub=g["sub"], nw=g["nw"], kids=kids((key,)))
        topics.append(t)
    # one deck, no tags (or one group with nearly everything): topics say nothing, so leave them out
    solo = not topics or topics[0]["n"] >= 0.9 * sum(t["n"] for t in topics)
    if solo:
        topics = []

    hard = []
    top = sorted(again.items(), key=lambda kv: (-kv[1], -seen.get(kv[0], 0)))[:HARD_MAX]
    if top:
        conn = E.connect(path)
        try:
            text = {cid: day_view._card_text(sfld, flds) for cid, sfld, flds in conn.execute(
                "SELECT c.id, n.sfld, n.flds FROM cards c JOIN notes n ON n.id = c.nid "
                f"WHERE c.id IN ({','.join(str(int(c)) for c, _ in top)})")}
        finally:
            conn.close()
        for cid, k in top:
            g = card_group.get(cid)
            hard.append({"cid": cid, "again": k, "seen": seen.get(cid, 0), "text": text.get(cid, ""),
                         "ivl": card_ivl.get(cid, 0), "topic": g[1] if g else ""})

    lo, hi = m.lock_range if m is not None else (0.6, 0.85)
    return {
        "rng": rng, "step": step, "bridge": {1: 3, 2: 2}.get(step, 1), "mode": mode, "lo": lo_day.isoformat(), "hi": today.isoformat(),
        "has_focus": m is not None,
        "tiles": {"n": tot["n"], "hours": tot["ms"] / 3.6e6, "span": span, "days": len(days_seen),
                  "streak": best, "new": tot["new"],
                  "ret": tot["rp"] / tot["rn"] if tot["rn"] else None,
                  "tail_ret": tail["rp"] / tail["rn"] if tail["rn"] else None,
                  "focus": _focus(all_x), "tail_focus": _focus(tail_x), "tail_days": TAIL_DAYS[rng],
                  "focus_lo": lo, "focus_hi": hi},
        "buckets": [{"name": B[k][2], "tick": B[k][3], "rev": kinds[k][0], "new": kinds[k][1], "bad": kinds[k][2],
                     "ret": ret_b[k][1] / ret_b[k][0] if ret_b[k][0] >= 20 else None,
                     "focus": _focus(focus_b[k]),
                     "spc": statistics.median(times_b[k]) / 1000 if times_b[k] else None,
                     "hours": ms_b[k] / 3.6e6, "nw": firsts[k]} for k in range(nb)],
        "punch": punch, "ro": ro,
        "gaps": [{"short": s, "long": l, "n": n, "ret": p / n if n >= GAP_MIN else None}
                 for (_, _, s, l), (n, p) in zip(GAPS, gaps)],
        "growth": growth, "topics": topics, "solo": solo, "mem_kind": "Stability" if use_s else "Interval", "hard": hard,
    }


# ──────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────
_JS = r"""
var D = %DATA%, C = D.colors, B = D.buckets, N = B.length;
var tip = document.getElementById('tip');
function showTip(e, h) { tip.innerHTML = h; tip.style.display = 'block';
  var w = tip.offsetWidth, ht = tip.offsetHeight, x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14; if (y + ht > innerHeight - 8) y = e.clientY - ht - 14;
  tip.style.left = x + 'px'; tip.style.top = y + 'px'; }
function hideTip() { tip.style.display = 'none'; }
function hover(svg, sel, fn, leave) {
  svg.querySelectorAll(sel).forEach(function (el) {
    el.addEventListener('mousemove', function (e) { fn(el, e); });
    el.addEventListener('mouseleave', function () { hideTip(); if (leave) leave(); });
  });
}
var f0 = function (n) { return Math.round(n).toLocaleString('en-US'); };
var pct = function (v, d) { return v == null ? '–' : (v * 100).toFixed(d || 0) + '%'; };
var dot = function (c, o) { return '<i style="background:' + c + (o ? ';opacity:' + o : '') + '"></i>'; };
var shortName = function (t) { return t.label.replace(/\s+block$/i, ''); };
function tick(x, y, t, right) {        // a date under the chart, kept inside its right edge
  var end = x + t.length * 6 > right;
  return '<text x="' + (end ? right : x) + '" y="' + y + '" class="tk"' + (end ? ' text-anchor="end"' : '') + '>' + t + '</text>';
}
function nice(lo, hi, steps, most) {    // at most `most` (3) gridlines inside [lo, hi]
  for (var i = 0; i < steps.length; i++) {
    var s = steps[i], a = Math.ceil(lo / s) * s, out = [];
    for (var v = a; v <= hi + 1e-9; v += s) out.push(+v.toFixed(4));
    if (out.length <= (most || 3)) return out;
  }
  return [lo, hi];
}

// ---- each day / week / month
(function () {
  var VW = 840, L = 46, R = 8, PW = VW - L - R, bw = PW / N, x = function (i) { return L + i * bw; };
  var s = '', y0 = 4;
  // what you were adding: every topic with a real share of new cards, packed into lanes
  var tot = B.map(function (b) { return b.nw; });        // all new cards, tagged or not
  var win = function (a, i) { return (a[i - 1] || 0) + a[i] + (a[i + 1] || 0); };
  var busy = tot.filter(function (v) { return v; }).sort(function (p, q) { return p - q; });
  var typical = busy[Math.floor(busy.length / 2)] || 0, runs = [];
  D.topics.forEach(function (t) {
    var on = t.nw.map(function (_, i) { var v = win(t.nw, i); return v > 0 && v >= 0.2 * win(tot, i) && v >= 0.25 * typical; });
    var bridge = D.bridge;                            // fill short gaps inside a run
    for (var i = 1; i < N; i++) if (!on[i] && on[i - 1]) {
      var j = i; while (j < N && !on[j] && j - i < bridge) j++;
      if (j < N && on[j]) for (var q = i; q < j; q++) on[q] = true;
    }
    var st = -1;
    for (var i = 0; i <= N; i++) {
      if (i < N && on[i]) { if (st < 0) st = i; }
      else if (st >= 0) {
        if (i - st >= 2) runs.push({t: t, start: st, end: i - 1, n: t.nw.slice(st, i).reduce(function (p, q) { return p + q; }, 0)});
        st = -1;
      }
    }
  });
  runs.sort(function (p, q) { return p.start - q.start || q.n - p.n; });
  // Each topic is a tag over exactly the weeks you added cards from it, its name inside;
  // a name too long for its tag is cut short with "…" (hover shows it whole). Rows are
  // packed so tags never overlap, up to 4 rows.
  var LH = 15, LG = 3, CW = 5.9, lanes = [];
  var free = function (k, a, b) { return (lanes[k] || []).every(function (o) { return b + 2 <= o[0] || a >= o[1] + 2; }); };
  runs.forEach(function (r) {
    var x0 = x(r.start) + 1, w = Math.max(4, (r.end - r.start + 1) * bw - 2);
    for (var k = 0; k < 4; k++) {
      if (free(k, x0, x0 + w)) { (lanes[k] = lanes[k] || []).push([x0, x0 + w]); r.lane = k; r.x0 = x0; r.w = w; break; }
    }
  });
  var fitName = function (t, w) {
    var n = Math.floor((w - 10) / CW);
    if (t.length <= n) return t;
    return n >= 3 ? t.slice(0, n - 1).replace(/[\s&]+$/, '') + '…' : '';
  };
  if (lanes.length) s += '<text x="' + (L - 8) + '" y="' + (y0 + 11) + '" class="lab" text-anchor="end">NEW</text>';
  runs.forEach(function (r, ri) {
    if (r.lane == null) return;
    var ly = y0 + r.lane * (LH + LG), label = fitName(shortName(r.t), r.w);
    s += '<g data-run="' + ri + '"><rect x="' + r.x0 + '" y="' + ly + '" width="' + r.w + '" height="' + LH + '" rx="5" class="lane"/>' +
         (label ? '<text x="' + (r.x0 + r.w / 2) + '" y="' + (ly + 10.8) + '" text-anchor="middle" class="lanet">' + label + '</text>' : '') + '</g>';
  });
  var yy = y0 + lanes.length * (LH + LG);
  if (lanes.length) y0 = yy - LG + 8;
  var RB = y0 - 6;
  // answers, stacked
  var BH = 150, max = Math.max.apply(null, B.map(function (b) { return b.rev + b.new + b.bad; })) || 1;
  var step = nice(0, max, [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]);
  var top = Math.max(max, step[step.length - 1]);
  var by = function (v) { return y0 + BH - v / top * BH; };
  var lab = function (v) { return v >= 1000 ? (v / 1000) + 'k' : v; };
  step.forEach(function (v) {
    s += '<line x1="' + L + '" x2="' + (VW - R) + '" y1="' + by(v) + '" y2="' + by(v) + '" class="grid"/>' +
         '<text x="' + (L - 8) + '" y="' + (by(v) + 3.5) + '" class="tk" text-anchor="end">' + lab(v) + '</text>';
  });
  var gap = bw > 6 ? 1.5 : 0.5;
  B.forEach(function (b, i) {
    var segs = [[b.rev, C.reviews], [b.new, C.new], [b.bad, C.forgot]], acc = 0, bx = x(i) + gap, ww = bw - 2 * gap;
    segs.forEach(function (sg, j) {
      var v = sg[0]; if (!v) return;
      var h = v / top * BH, yy = by(acc + v), isTop = segs.slice(j + 1).every(function (q) { return !q[0]; });
      var g = acc ? 1 : 0, rr = Math.min(3, ww / 2, h);
      s += isTop ? '<path d="M' + bx + ',' + (yy + h - g) + ' V' + (yy + rr) + ' q0,-' + rr + ' ' + rr + ',-' + rr + ' h' + (ww - 2 * rr) +
                   ' q' + rr + ',0 ' + rr + ',' + rr + ' V' + (yy + h - g) + ' Z" fill="' + sg[1] + '"/>'
                 : '<rect x="' + bx + '" y="' + (yy + 1) + '" width="' + ww + '" height="' + Math.max(0, h - 1 - g) + '" fill="' + sg[1] + '"/>';
      acc += v;
    });
  });
  y0 += BH + 22;
  B.forEach(function (b, i) { if (b.tick) s += tick(x(i), y0 - 4, b.tick, VW - R); });
  var H = y0;
  s += '<line id="xh" y1="' + RB + '" y2="' + (H - 14) + '" class="xh" style="display:none"/>';
  B.forEach(function (b, i) { s += '<rect x="' + x(i) + '" y="' + RB + '" width="' + bw + '" height="' + (H - 12 - RB) + '" fill="transparent" data-i="' + i + '"/>'; });
  var svg = document.getElementById('buckets');
  svg.setAttribute('viewBox', '0 0 ' + VW + ' ' + H); svg.innerHTML = s;
  var xh = svg.querySelector('#xh');
  hover(svg, '[data-run]', function (el, e) {
    var r = runs[+el.dataset.run];
    showTip(e, '<b>' + r.t.label + '</b>' + (r.t.sub ? ' · ' + r.t.sub : '') + '<br>' + B[r.start].name.split(' – ')[0] +
      ' – ' + (B[r.end].name.split(' – ')[1] || B[r.end].name) + '<br>' + f0(r.n) + ' new cards');
  });
  hover(svg, 'rect[data-i]', function (el, e) {
    var i = +el.dataset.i, b = B[i], cx = x(i) + bw / 2;
    xh.setAttribute('x1', cx); xh.setAttribute('x2', cx); xh.style.display = '';
    var h = '<b>' + b.name + '</b><br>' + dot(C.reviews) + 'Reviews ' + f0(b.rev) + '<br>' + dot(C.new) + 'New &amp; learning ' +
      f0(b.new) + '<br>' + dot(C.forgot) + 'Forgot ' + f0(b.bad) + '<br>Retention ' + pct(b.ret, 1);
    if (D.has_focus) h += ' · Focus ' + pct(b.focus);
    if (b.spc != null) h += '<br>' + b.spc.toFixed(1) + ' s a card · ' + (b.hours < 1 ? Math.round(b.hours * 60) + ' min' : b.hours.toFixed(1) + ' h');
    showTip(e, h);
  }, function () { xh.style.display = 'none'; });
})();

// ---- when you study (weekday x hour, from the day's start)
(function () {
  var P = D.punch, DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var VW = 470, L = 30, cw = (VW - L - 4) / 24, ch = 17, top = 4, s = '';
  var hours = []; for (var j = 0; j < 24; j++) hours.push((j + D.ro) % 24);
  // Smooth dark-to-bright scale, placed by rank so every shade gets used (see themes.glow)
  var xs = []; P.forEach(function (row) { row.forEach(function (c) { if (c[0] > 0) xs.push(c[0]); }); });
  xs.sort(function (a, b) { return a - b; });
  var rankOf = function (v) {
    if (xs.length < 2) return 1;
    var lo = 0, hi = xs.length; while (lo < hi) { var m = (lo + hi) >> 1; if (xs[m] < v) lo = m + 1; else hi = m; }
    var a = lo; hi = xs.length; while (lo < hi) { var m2 = (lo + hi) >> 1; if (xs[m2] <= v) lo = m2 + 1; else hi = m2; }
    return ((a + lo - 1) / 2) / (xs.length - 1);
  };
  var hex = function (c) { return [1, 3, 5].map(function (i) { return parseInt(c.substr(i, 2), 16); }); };
  var G = C.glow.map(hex), mixc = function (a, b, t) {
    return 'rgb(' + a.map(function (x, i) { return Math.round(x + (b[i] - x) * t); }).join(',') + ')';
  };
  var glowAt = function (t) {
    t = C.glow_floor + (1 - C.glow_floor) * t;
    return t <= C.glow_mid ? mixc(G[0], G[1], t / C.glow_mid) : mixc(G[1], G[2], (t - C.glow_mid) / (1 - C.glow_mid));
  };
  DAYS.forEach(function (dn, r) {
    s += '<text x="' + (L - 6) + '" y="' + (top + r * ch + ch / 2 + 3.5) + '" class="tk" text-anchor="end">' + dn[0] + '</text>';
    hours.forEach(function (h, j) {
      var c = P[r][h];
      s += '<rect x="' + (L + j * cw + 1) + '" y="' + (top + r * ch + 1) + '" width="' + (cw - 2) + '" height="' + (ch - 2) +
           '" rx="3" fill="' + (c[0] ? glowAt(rankOf(c[0])) : C.empty) + '" data-r="' + r + '" data-h="' + h + '"/>';
    });
  });
  var lab = function (h) { return h === 0 ? '12a' : h === 12 ? '12p' : h < 12 ? h + 'a' : (h - 12) + 'p'; };
  [0, 4, 8, 12, 16, 20].forEach(function (j) { s += '<text x="' + (L + j * cw) + '" y="' + (top + 7 * ch + 13) + '" class="tk">' + lab(hours[j]) + '</text>'; });
  var svg = document.getElementById('punch');
  svg.setAttribute('viewBox', '0 0 ' + VW + ' ' + (top + 7 * ch + 18)); svg.innerHTML = s;
  hover(svg, 'rect[data-r]', function (el, e) {
    var r = +el.dataset.r, h = +el.dataset.h, c = P[r][h];
    showTip(e, '<b>' + DAYS[r] + ' ' + lab(h) + '–' + lab((h + 1) % 24) + '</b><br>' + f0(c[0]) + ' cards' +
      (c[0] ? '<br>Retention ' + pct(c[1] ? c[2] / c[1] : null) + ' · ' + (c[3] / c[0] / 1000).toFixed(1) + ' s a card' : ''));
  });
  var best = 0, bh = 0, tot = 0;
  for (var h = 0; h < 24; h++) {
    var n = 0; P.forEach(function (row) { n += row[h][0] + row[(h + 1) % 24][0]; tot += row[h][0]; });
    if (n > best) { best = n; bh = h; }
  }
  if (tot) document.getElementById('punchnote').textContent = 'Busiest: ' + lab(bh) + '–' + lab((bh + 2) % 24) + ' · ' + pct(best / tot) + ' of cards';
})();

// ---- remembered, by time since last seen
(function () {
  var M = D.gaps, VW = 330, L = 34, R = 10, top = 12, PH = 120;
  var vals = M.filter(function (m) { return m.ret != null; }).map(function (m) { return m.ret; });
  var svg = document.getElementById('gaps');
  if (!vals.length) { svg.parentNode.style.display = 'none'; return; }
  var lo = Math.min(0.8, Math.floor(Math.min.apply(null, vals) * 10) / 10), hi = 1;
  var xw = (VW - L - R) / M.length, y = function (v) { return top + PH - (v - lo) / (hi - lo) * PH; }, s = '';
  var ticks = [lo, (lo + hi) / 2, hi];
  ticks.forEach(function (t) {
    s += '<line x1="' + L + '" x2="' + (VW - R) + '" y1="' + y(t) + '" y2="' + y(t) + '" class="grid"/>' +
         '<text x="' + (L - 6) + '" y="' + (y(t) + 3.5) + '" class="tk" text-anchor="end">' + pct(t) + '</text>';
  });
  if (D.tiles.ret != null) s += '<line x1="' + L + '" x2="' + (VW - R) + '" y1="' + y(D.tiles.ret) + '" y2="' + y(D.tiles.ret) + '" class="ref"/>';
  M.forEach(function (m, i) {
    var cx = L + xw * i + xw / 2;
    s += '<text x="' + cx + '" y="' + (top + PH + 15) + '" class="tk" text-anchor="middle">' + m.short + '</text>';
    s += '<rect x="' + (L + xw * i) + '" y="0" width="' + xw + '" height="' + (top + PH + 20) + '" fill="transparent" data-i="' + i + '"/>';
    if (m.ret == null) return;
    s += '<line x1="' + cx + '" x2="' + cx + '" y1="' + y(lo) + '" y2="' + y(m.ret) + '" stroke="' + C.reviews + '" stroke-opacity=".35" stroke-width="2"/>' +
         '<circle cx="' + cx + '" cy="' + y(m.ret) + '" r="5" fill="' + C.reviews + '" stroke="' + C.page + '" stroke-width="2"/>' +
         '<text x="' + cx + '" y="' + (y(m.ret) - 10) + '" class="val" text-anchor="middle">' + Math.round(m.ret * 100) + '</text>';
  });
  svg.setAttribute('viewBox', '0 0 ' + VW + ' ' + (top + PH + 22)); svg.innerHTML = s;
  hover(svg, 'rect[data-i]', function (el, e) {
    var m = M[+el.dataset.i];
    showTip(e, '<b>Last seen ' + m.long + ' before</b><br>' + (m.ret != null ? 'Remembered ' + pct(m.ret, 1) + '<br>' : '') + f0(m.n) + ' reviews');
  });
})();

// ---- your cards
(function () {
  var G = D.growth, VW = 840, L = 46, R = 8, top = 6, PH = 110, bw = (VW - L - R) / N;
  var x = function (i) { return L + i * bw + bw / 2; };
  var tot = function (g) { return g.mature + g.young + g.learning; };
  var max = Math.max.apply(null, G.map(tot)) || 1;
  var step = nice(0, max, [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]);
  var top2 = Math.max(max, step[step.length - 1]), y = function (v) { return top + PH - v / top2 * PH; }, s = '';
  step.forEach(function (v) {
    s += '<line x1="' + L + '" x2="' + (VW - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" class="grid"/><text x="' + (L - 8) + '" y="' +
         (y(v) + 3.5) + '" class="tk" text-anchor="end">' + (v >= 1000 ? (v / 1000) + 'k' : v) + '</text>';
  });
  var pts = function (f) { return G.map(function (g, i) { return x(i).toFixed(1) + ',' + y(f(g)).toFixed(1); }); };
  var area = function (fa, fb) { return 'M' + pts(fa).join('L') + 'L' + pts(fb).reverse().join('L') + 'Z'; };
  s += '<path d="' + area(function (g) { return g.mature; }, function () { return 0; }) + '" fill="' + C.base + '"/>';
  s += '<path d="' + area(tot, function (g) { return g.mature; }) + '" fill="' + C.base + '" fill-opacity=".38"/>';
  s += '<path d="M' + pts(function (g) { return g.mature; }).join('L') + '" fill="none" stroke="' + C.page + '" stroke-width="2"/>';
  B.forEach(function (b, i) { if (b.tick) s += tick(L + i * bw, top + PH + 15, b.tick, VW - R); });
  s += '<line id="xh2" y1="' + top + '" y2="' + (top + PH) + '" class="xh" style="display:none"/>';
  G.forEach(function (g, i) { s += '<rect x="' + (L + i * bw) + '" y="0" width="' + bw + '" height="' + (top + PH) + '" fill="transparent" data-i="' + i + '"/>'; });
  var svg = document.getElementById('growth');
  svg.setAttribute('viewBox', '0 0 ' + VW + ' ' + (top + PH + 20)); svg.innerHTML = s;
  var xh = svg.querySelector('#xh2');
  hover(svg, 'rect[data-i]', function (el, e) {
    var i = +el.dataset.i, g = G[i];
    xh.setAttribute('x1', x(i)); xh.setAttribute('x2', x(i)); xh.style.display = '';
    showTip(e, '<b>' + B[i].name + '</b><br>' + dot(C.base) + 'Mature ' + f0(g.mature) + '<br>' + dot(C.base, .45) + 'Young ' + f0(g.young + g.learning));
  }, function () { xh.style.display = 'none'; });
  var g = G[N - 1], g0 = G[0];
  document.getElementById('growthnote').textContent = f0(g.mature) + ' mature · ' + (g.mature >= g0.mature ? '+' : '−') +
    f0(Math.abs(g.mature - g0.mature)) + ' in this range';
})();

// ---- stability chips
var rel = function (v) { if (v == null) return '–'; var p = Math.round((v - 1) * 100); return (p > 0 ? '+' : p < 0 ? '−' : '') + Math.abs(p) + '%'; };
// a tinted chip once a topic is 10% or more off cards started around the same time
var memChip = function (v) {
  if (v == null) return '<div class="memc"><span class="chip">–</span></div>';
  var p = Math.round((v - 1) * 100), on = Math.abs(p) >= 10;
  var st = !on ? '' : ' style="background:' + (p < 0 ? C.weak_bg + ';color:' + C.weak_text : C.strong_bg + ';color:' + C.strong_text) + '"';
  return '<div class="memc"><span class="chip' + (on ? ' on' : '') + '"' + st + '>' + rel(v) + '</span></div>';
};

// ---- topics
(function () {
  var T = D.topics, el = document.getElementById('topics');
  if (!T.length) { el.parentNode.style.display = 'none'; return; }
  var peak = function (rows) { return Math.max.apply(null, rows.map(function (t) { return Math.max.apply(null, t.vol); })) || 1; };
  function spark(t, vmax) {
    var w = 150, h = 22, bw = w / N, s = '';
    t.vol.forEach(function (v, i) { if (!v) return; var bh = Math.max(1.5, Math.sqrt(v / vmax) * h);
      s += '<rect x="' + (i * bw).toFixed(1) + '" y="' + (h - bh).toFixed(1) + '" width="' + Math.max(0.8, bw - 1).toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1" fill="' + C.base + '"/>'; });
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '" style="display:block">' + s + '</svg>';
  }
  // Rows open in place to show the tags (or subdecks) below them; siblings share a spark scale.
  // Click a header to sort every level by it, again to flip. It starts on Reviews, most first.
  var byId = {}, open = {}, more = {}, KIDS = 8;
  var FIRST = {label: 1, n: -1, hours: -1, mem: 1, mature: 1};    // first click: A–Z, most, weakest, least mature
  var sortKey = 'n', sortDir = -1;
  var CHEV = '<svg width="9" height="9" viewBox="0 0 9 9" style="display:block"><path d="M3 1.5 L6 4.5 L3 7.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  (function tag(list, pre) { list.forEach(function (t, i) { t.id = pre + i; t.ord = i; byId[t.id] = t; tag(t.kids, t.id + '.'); }); })(T, '');
  var order = function (list) {
    var k = sortKey, d = sortDir;
    return list.slice().sort(function (p, q) {
      var a = p[k], b = q[k];
      if (a == null || b == null) return (a == null) - (b == null) || p.ord - q.ord;     // no number: last
      return d * (k === 'label' ? String(a).localeCompare(String(b)) : a - b) || p.ord - q.ord;
    });
  };
  var head = function (k, text, cls) {
    var on = sortKey === k;
    return '<span class="' + cls + ' sort' + (on ? ' on' : '') + '" data-sort="' + k + '"><span class="lbl">' + text +
      (on ? '<span class="arr">' + (sortDir > 0 ? '↑' : '↓') + '</span>' : '') + '</span></span>';
  };
  var row = function (t, depth, vmax) {
    var m = t.mature || 0, has = t.kids.length > 0;
    return '<div class="row' + (depth ? ' kid' : '') + (has ? ' has' : '') + (open[t.id] ? ' open' : '') + '" data-id="' + t.id + '">' +
      '<div class="tname" style="padding-left:' + depth * 16 + 'px"><span class="chev">' + (has ? CHEV : '') + '</span><div class="clip">' +
      '<div class="clip">' + t.label + '</div>' + (t.sub && !depth ? '<div class="was">' + t.sub + '</div>' : '') + '</div></div><div>' + spark(t, vmax) + '</div>' +
      '<div class="num">' + f0(t.n) + '</div><div class="num">' + (t.hours < 1 ? Math.round(t.hours * 60) + 'm' : f0(t.hours) + 'h') + '</div>' + memChip(t.mem) +
      '<div class="mbar"><div class="track"><div class="mfill" style="width:' + (m * 100).toFixed(0) + '%"></div></div><span class="num" style="width:30px">' + pct(t.mature) + '</span></div></div>' +
      (open[t.id] ? rows(t.kids, t.id, depth + 1) : '');
  };
  var rows = function (list, pid, depth) {
    list = order(list);
    var vmax = peak(list), cut = depth && !more[pid] && list.length > KIDS + 2 ? KIDS : list.length;
    return list.slice(0, cut).map(function (t) { return row(t, depth, vmax); }).join('') +
      (cut < list.length ? '<div class="row kid" data-more="' + pid + '"><div class="tname" style="padding-left:' + depth * 16 + 'px">' +
        '<span class="chev"></span><span class="lnk">+ ' + (list.length - cut) + ' more</span></div></div>' : '');
  };
  var hdr = function () {
    return '<div class="row hdr">' + head('label', D.topic_word, '') + '<span>Reviews over time</span>' + head('n', 'Reviews', 'num') +
      head('hours', 'Time', 'num') + head('mem', D.mem_kind, 'mid') + head('mature', 'Mature', '') + '</div>';
  };
  var btn = document.getElementById('moret'), all = false;
  var draw = function () {
    var top = order(T);
    el.innerHTML = hdr() + rows(top.slice(0, all ? T.length : D.topics_shown), '', 0);
    btn.textContent = all ? 'Show fewer' : 'Show all ' + T.length; btn.style.display = T.length > D.topics_shown ? '' : 'none'; };
  btn.onclick = function () { all = !all; draw(); }; draw();
  el.addEventListener('click', function (e) {
    var sh = e.target.closest('[data-sort]');
    if (sh) { var k = sh.dataset.sort; if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = FIRST[k]; } draw(); return; }
    var mr = e.target.closest('[data-more]'); if (mr) { more[mr.dataset.more] = true; draw(); return; }
    var r = e.target.closest('.row.has'); if (!r) return;
    open[r.dataset.id] = !open[r.dataset.id]; hideTip(); draw();
  });
  el.addEventListener('mousemove', function (e) {
    var r = e.target.closest('.row[data-id]'); if (!r) { hideTip(); return; }
    var t = byId[r.dataset.id], k = D.mem_kind.toLowerCase();
    showTip(e, '<b>' + t.label + '</b><br>Retention ' + pct(t.ret) +
      (t.mem != null ? '<br>' + D.mem_kind + ' ' + rel(t.mem) + ' vs cards you started around the same time' :
       t.mem_alone ? '<br>Little else started around the same time to compare' : '') +
      (t.mem_days != null ? '<br>Median ' + k + ' ' + f0(t.mem_days) + ' d' : ''));
  });
  el.addEventListener('mouseleave', hideTip);
})();

// ---- forgot most
(function () {
  var H = D.hard, el = document.getElementById('hard');
  if (!H.length) { el.parentNode.style.display = 'none'; return; }
  var cls = D.solo ? 'crow solo' : 'crow', btn = document.getElementById('morehard'), all = false;
  var shown = function () { return all ? H : H.slice(0, D.hard_shown); };
  var draw = function () {
    el.innerHTML = '<div class="' + cls + ' hdr"><span>Card</span>' + (D.solo ? '' : '<span>' + D.topic_one + '</span>') + '<span class="num">Forgot</span><span class="num">Interval</span></div>' +
      shown().map(function (h) {
        return '<div class="' + cls + '" data-cid="' + h.cid + '"><div class="ctext">' + h.text + '</div>' + (D.solo ? '' : '<div class="was clip">' + (h.topic || '–') + '</div>') +
          '<div class="forgot">' + h.again + ' <span class="was">of ' + h.seen + '</span></div><div class="num was">' + h.ivl_s + '</div></div>';
      }).join('');
    btn.textContent = all ? 'Show fewer' : 'Show all ' + H.length; btn.style.display = H.length > D.hard_shown ? '' : 'none';
  };
  btn.onclick = function () { all = !all; draw(); }; draw();
  el.addEventListener('click', function (e) { var r = e.target.closest('.crow[data-cid]'); if (r) pycmd('stats:browse:' + r.dataset.cid); });
  document.getElementById('openhard').onclick = function () { pycmd('stats:browse:' + shown().map(function (h) { return h.cid; }).join(',')); };
})();

document.querySelectorAll('.seg button').forEach(function (b) { b.onclick = function () { pycmd('stats:range:' + b.dataset.r); }; });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') pycmd('stats:close'); });
"""


def _css(night: bool, cfg: dict, backdrop, glass) -> tuple:
    from . import themes
    accent = cfg.get("pill_new_color", "#4a90e2")
    ink, panel, photo = day_view.theme(night, accent, backdrop, glass)
    base = cfg.get("base_color", "#4fb3fb")
    line = ink["line"]
    css = (f"html,body{{margin:0;min-height:100%}}body{{padding:14px 18px 18px;background:{ink['base']};"
           f"color:{ink['fg']};font:13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
           "-webkit-font-smoothing:antialiased;box-sizing:border-box}" + photo +
           f".glass{{{panel}border-radius:16px;padding:12px 14px;margin-bottom:12px;"
           "backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}"
           ".head{display:flex;align-items:center;gap:10px;margin:0 2px 12px}"
           ".head h1{font-size:18px;font-weight:600;margin:0}"
           f".seg{{display:flex;gap:2px;background:rgba({line},.07);border-radius:9px;padding:2px;margin-left:auto}}"
           f".seg button{{all:unset;cursor:pointer;font-size:12px;padding:3px 11px;border-radius:7px;color:{ink['sub']}}}"
           f".seg button:hover{{color:{ink['fg']}}}"
           f".seg button.on{{background:{base};color:{themes.readable_text(base)};box-shadow:0 1px 4px rgba(0,0,0,.2)}}"
           f".btn{{all:unset;cursor:pointer;font-size:12px;padding:4px 11px;border-radius:8px;"
           f"background:rgba({line},.07)}}.btn:hover{{background:rgba({line},.14)}}"
           ".stats{display:grid;padding:12px 4px}"
           f".stat{{padding:0 12px}}.stat+.stat{{border-left:1px solid rgba({line},.12)}}"
           f".cap{{font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:{ink['sub']}}}"
           ".big{font-size:21px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:3px}"
           f".was{{font-size:11px;color:{ink['sub']}}}"
           ".title{font-size:13px;font-weight:600;margin:0 0 8px;display:flex;align-items:baseline;gap:12px}"
           ".title .r{margin-left:auto;font-weight:400}"
           ".keys{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11.5px;font-weight:400}"
           ".keys i,#tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}"
           ".two{display:grid;grid-template-columns:1.25fr 1fr;gap:12px}.two>.glass{margin-bottom:12px}"
           f".tk{{fill:{ink['sub']};font-size:10px;font-weight:600}}"
           f".lab{{fill:{ink['sub']};font-size:9px;font-weight:700;letter-spacing:.5px}}"
           f".val{{fill:{ink['fg']};font-size:10.5px;font-weight:600}}"
           f".grid{{stroke:rgba({line},.1);stroke-width:1}}"
           f".ref{{stroke:rgba({line},.4);stroke-width:1;stroke-dasharray:3 3}}"
           f".xh{{stroke:rgba({line},.4);stroke-width:1}}"
           f".lane{{fill:rgba({line},.09)}}.lanet{{font-size:10px;fill:{ink['fg']};opacity:.8;pointer-events:none}}"
           ".row{display:grid;grid-template-columns:minmax(0,1.5fr) 150px 64px 48px 78px 92px;gap:10px;"
           f"align-items:center;padding:6px 4px;border-top:1px solid rgba({line},.09);font-size:12.5px;border-radius:6px}}"
           f".row:hover{{background:rgba({line},.05)}}"
           ".row.has{cursor:pointer}.row.kid{border-top:0;padding:4px;font-size:12px}"
           f".row.kid .tname{{color:{ink['sub']}}}.row.kid .num{{opacity:.85}}"
           ".tname{display:flex;align-items:center;min-width:0}"
           f".chev{{flex:none;width:14px;color:{ink['sub']}}}.chev svg{{transition:transform .15s}}"
           f".lnk{{color:{accent};cursor:pointer}}"
           ".memc{display:flex;justify-content:center}.mid{text-align:center}"
           ".sort .lbl{position:relative}.sort .arr{position:absolute;left:100%;padding-left:4px}"
           ".num.sort .arr{left:auto;right:100%;padding:0 4px 0 0}"
           f".chip{{font-variant-numeric:tabular-nums;font-size:12px;padding:1px 8px;border-radius:999px;color:{ink['sub']}}}"
           ".chip.on{font-weight:600}"
           f".sort{{cursor:pointer}}.sort:hover,.sort.on{{color:{ink['fg']}}}"
           ".row.open>.tname .chev svg{transform:rotate(90deg)}"
           ".row.hdr,.crow.hdr{border-top:0;padding:2px 4px;font-size:9px;font-weight:700;letter-spacing:.5px;"
           f"text-transform:uppercase;color:{ink['sub']};cursor:default}}.row.hdr:hover,.crow.hdr:hover{{background:none}}"
           ".num{text-align:right;font-variant-numeric:tabular-nums}"
           ".mbar{display:flex;align-items:center;gap:6px}"
           f".track{{flex:1;height:6px;border-radius:3px;background:rgba({line},.09)}}"
           f".mfill{{height:100%;border-radius:3px;background:{base}}}"
           f".more{{all:unset;cursor:pointer;font-size:12px;color:{accent};margin:8px 4px 0;display:inline-block}}"
           ".crow{display:grid;grid-template-columns:minmax(0,1fr) 160px 70px 58px;gap:10px;align-items:center;"
           f"font-size:12.5px;padding:7px 4px;border-top:1px solid rgba({line},.09);cursor:pointer;border-radius:6px}}"
           ".crow.solo{grid-template-columns:minmax(0,1fr) 70px 58px}"
           f".crow:hover{{background:rgba({line},.06)}}"
           ".clip{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}"
           ".ctext{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}"
           f".ctext b{{color:{accent};font-weight:600}}"
           f".forgot{{color:{cfg.get('pill_learn_color', '#e74c3c')};font-variant-numeric:tabular-nums;text-align:right}}"
           f".empty{{text-align:center;color:{ink['sub']};padding:48px 0}}"
           "::-webkit-scrollbar{width:12px;height:12px;background:transparent}"
           "::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}"
           f"::-webkit-scrollbar-thumb{{background:rgba({line},.28);border-radius:8px;"
           "border:3px solid transparent;background-clip:padding-box}"
           f"::-webkit-scrollbar-thumb:hover{{background:rgba({line},.45);background-clip:padding-box}}"
           "#tip{position:fixed;display:none;background:rgba(0,0,0,.92);color:#fff;padding:7px 10px;"
           "border-radius:6px;font-size:11px;line-height:1.5;pointer-events:none;z-index:9;"
           "box-shadow:0 4px 10px rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);max-width:260px}"
           "#tip b{font-weight:600}")
    return ink, css


def _head(rng: str, sub: str, cfg: dict = None, night: bool = False) -> str:
    from . import brand
    seg = "".join(f'<button data-r="{k}"{" class=on" if k == rng else ""}>{v}</button>' for k, v in RANGES.items())
    logo = brand.svg((cfg or {}).get("base_color", "#8e44ad"), night, 22, style="margin-right:-1px")
    return (f'<div class="head">{logo}<h1>Your stats</h1><span class="was">{sub}</span>'
            f'<div class="seg">{seg}</div></div>')


def loading_page(rng: str, night: bool, cfg: dict, backdrop, glass, scope: str) -> str:
    from . import brand
    _, css = _css(night, cfg, backdrop, glass)
    still = brand.still_js(cfg.get("animations", "system"))
    spin = brand.svg(cfg.get("base_color", "#8e44ad"), night, 40, style="margin:0 auto 10px")
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>"
            f"{_head(rng, html.escape(scope), cfg, night)}<div class='glass empty' id='hm-load'>{spin}Loading…</div>"
            f"<script>{brand.SCRIPT}window.hmLogo(document.querySelector('#hm-load svg'),true,{still});</script>"
            f"</body></html>")


def _date(s: str) -> str:
    d = datetime.date.fromisoformat(s)
    return f"{_MON[d.month - 1]} {d.day}, {d.year}"


def _mix(a: str, b: str, t: float) -> str:
    """a moved a share t of the way toward b."""
    try:
        pa = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        pb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return a
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def page(data: dict, night: bool, cfg: dict, backdrop=None, glass: float = 0.45, scope: str = "") -> str:
    from . import review_pill
    ink, css = _css(night, cfg, backdrop, glass)
    rng = data["rng"]
    if data.get("empty"):
        return (f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>"
                f"{_head(rng, html.escape(scope), cfg, night)}<div class='glass empty'>No reviews yet.</div>"
                f"<script>document.querySelectorAll('.seg button').forEach(function(b){{b.onclick=function()"
                f"{{pycmd('stats:range:'+b.dataset.r)}}}})</script></body></html>")
    t = data["tiles"]
    sub = f"{_date(data['lo'])} – {_date(data['hi'])}" + (f" · {html.escape(scope)}" if scope else "")
    last = f"last {t['tail_days']} days" if t["tail_days"] < 28 else (
        "last 4 wk" if t["tail_days"] == 28 else "last 3 mo")

    def tile(cap, big, small, color=""):
        st = f' style="color:{color}"' if color else ""
        return f'<div class="stat"><div class="cap">{cap}</div><div class="big"{st}>{big}</div><div class="was">{small}</div></div>'

    pc = lambda v, d=0: "–" if v is None else f"{100 * v:.{d}f}%"
    tiles = [tile("Reviews", f"{t['n']:,}", f"{round(t['n'] / t['span']):,} a day"),
             tile("Time", f"{t['hours']:,.0f} h" if t["hours"] >= 10 else f"{t['hours']:.1f} h",
                  f"{t['hours'] / max(1, t['days']):.1f} h a day"),
             tile("Retention", pc(t["ret"], 1), f"{last} {pc(t['tail_ret'], 1)}")]
    if data["has_focus"]:
        col = ("#%02x%02x%02x" % tuple(int(v) for v in review_pill._gradient_rgb(t["focus"], t["focus_lo"], t["focus_hi"]))
               if t["focus"] is not None else "")
        tiles.append(tile("Focus", pc(t["focus"]), f"{last} {pc(t['tail_focus'])}" if t["focus"] is not None
                          else "not enough data", col))
    tiles.append(tile("New cards", f"{t['new']:,}", f"{round(t['new'] / t['span']):,} a day"))
    tiles.append(tile("Days studied", f"{t['days']:,} / {t['span']:,}", f"streak {t['streak']:,}"))
    tiles_html = f'<div class="glass stats" style="grid-template-columns:repeat({len(tiles)},1fr)">{"".join(tiles)}</div>'

    base = cfg.get("base_color", "#4fb3fb")
    # Bars in the heatmap's own color: reviews solid, new cards a softer tint of it (like
    # Young under Your cards), forgotten cards the theme's learning color, toned down.
    colors = {"reviews": base, "new": _mix(base, ink["base"], 0.45 if night else 0.55),
              "forgot": _mix(cfg.get("pill_learn_color", "#e74c3c"), ink["base"], 0.3), "base": base,
              "empty": cfg.get("empty_color_night" if night else "empty_color", "#282c34" if night else "#ebedf0"),
              "glow": themes.glow_stops(base, night, cfg.get("glow_contrast", themes.GLOW_CONTRAST)), "glow_mid": themes.GLOW_MID, "glow_floor": themes.GLOW_FLOOR,
              "fg": ink["fg"], "page": ink["base"]}
    # stability chips: a tint of the forgot / base color, its text pulled toward white or black to read
    for k, c in (("weak", colors["forgot"]), ("strong", base)):
        colors[k + "_bg"] = c + ("40" if night else "30") if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "transparent"
        colors[k + "_text"] = _mix(c, "#ffffff", 0.45) if night else _mix(c, "#1a1a1a", 0.4)
    word = {1: "Each day", 2: "Every 2 days", 7: "Each week", 0: "Each month"}[data["step"]]
    key = (f'<span class="keys r"><span><i style="background:{colors["reviews"]}"></i>Reviews</span>'
           f'<span><i style="background:{colors["new"]}"></i>New &amp; learning</span>'
           f'<span><i style="background:{colors["forgot"]}"></i>Forgot</span></span>')
    topic_word = {"tag": "Topic", "anking": "System", "deck": "Deck"}[data["mode"]]
    shown = sum(t["n"] for t in data["topics"]) / data["tiles"]["n"] if data["tiles"]["n"] else 1
    cover = f'<span class="was r">{max(1, round(shown * 100))}% of your reviews</span>' if data["topics"] and shown < 0.5 else ""
    body = (tiles_html +
            f'<div class="glass"><div class="title">{word}{key}</div><svg id="buckets" width="100%" style="display:block"></svg></div>'
            '<div class="two">'
            '<div class="glass"><div class="title">When you study<span class="was r" id="punchnote"></span></div>'
            '<svg id="punch" width="100%" style="display:block"></svg></div>'
            '<div class="glass"><div class="title">Remembered, by time since last seen</div>'
            '<svg id="gaps" width="100%" style="display:block"></svg></div></div>'
            f'<div class="glass"><div class="title">Your cards<span class="keys"><span><i style="background:{colors["base"]}"></i>Mature</span>'
            f'<span><i style="background:{colors["base"]};opacity:.45"></i>Young</span></span>'
            '<span class="was r" id="growthnote"></span></div><svg id="growth" width="100%" style="display:block"></svg></div>'
            f'<div class="glass"><div class="title">{topic_word}s{cover}</div><div id="topics"></div>'
            '<button class="more" id="moret"></button></div>'
            '<div class="glass"><div class="title">Forgot most<span class="r"><button class="btn" id="openhard">'
            'Open in Browser</button></span></div><div id="hard"></div><button class="more" id="morehard"></button></div>')
    for h in data["hard"]:
        h["ivl_s"] = day_view._ivl(h["ivl"]) if h["ivl"] > 0 else "–"
    blob = dict(data, colors=colors, topic_word=topic_word, topic_one=topic_word, topics_shown=TOPICS_SHOWN, hard_shown=HARD_SHOWN)
    def esc(rows):
        for tp in rows:
            tp["label"], tp["sub"] = html.escape(tp["label"]), html.escape(tp.get("sub", ""))
            esc(tp["kids"])
    esc(blob["topics"])
    for h in blob["hard"]:
        h["topic"] = html.escape(h["topic"])
    js = _JS.replace("%DATA%", json.dumps(blob).replace("</", "<\\/"))
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>"
            f"{_head(rng, sub, cfg, night)}{body}<div id='tip'></div><script>{js}</script></body></html>")


# ──────────────────────────────────────────────────────────────
# Window
# ──────────────────────────────────────────────────────────────
class StatsWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        from . import time_left
        self.setWindowTitle("Your Stats")
        try:
            from . import brand
            self.setWindowIcon(brand.icon((mw.addonManager.getConfig(__name__.rsplit(".", 1)[0]) or {})
                                          .get("base_color", "#8e44ad"), time_left._is_night()))
        except Exception:
            pass
        self.setStyleSheet(f"QDialog {{ background: {'#1f1f1f' if time_left._is_night() else '#ffffff'}; }}")
        self.resize(920, 900)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.web = AnkiWebView(self, title="your stats")
        self.web.set_bridge_command(self._on_cmd, self)
        lay.addWidget(self.web)
        self.deck_ids, self.scope, self._req = None, "", 0

    def load(self, rng: str, deck_ids, scope: str) -> None:
        from . import time_left
        global _range
        _range = rng
        self.deck_ids, self.scope = deck_ids, scope
        self._req += 1
        req = self._req
        cfg = _get_config()
        night, backdrop, glass = time_left._is_night(), time_left._backdrop(), time_left._glass_opacity()
        self.web.setHtml(loading_page(rng, night, cfg, backdrop, glass, scope))
        m = time_left._get_model() if time_left.enabled() else None
        if m is not None and not m.mu:
            m = None
        path, ro = mw.col.path, day_view._rollover()

        def done(fut) -> None:
            if req != self._req or not _alive(self):
                return
            try:
                html_ = page(fut.result(), night, cfg, backdrop, glass, scope)
            except Exception as e:      # show what went wrong rather than a blank window
                import traceback
                html_ = (f"<body style='font:13px -apple-system,sans-serif;padding:20px;color:#999'>"
                         f"Stats couldn't be shown: {html.escape(str(e))}"
                         f"<pre style='font-size:11px'>{html.escape(traceback.format_exc())}</pre></body>")
            self.web.setHtml(html_)

        mw.taskman.run_in_background(lambda: collect(rng, deck_ids, cfg, m, path, ro), done)

    def _on_cmd(self, cmd: str):
        if cmd.startswith("stats:range:"):
            rng = cmd.split(":")[2]
            if rng in RANGES:
                self.load(rng, self.deck_ids, self.scope)
        elif cmd.startswith("stats:browse:"):
            ids = [c for c in cmd.split(":")[2].split(",") if c.isdigit()]
            if ids:
                from aqt import dialogs
                browser = dialogs.open("Browser", mw)
                browser.search_for(f"cid:{','.join(ids)}")
        elif cmd == "stats:close":
            self.close()
        return None


def _alive(w) -> bool:
    return day_view._alive(w)


def show(deck_ids=None, scope: str = "") -> None:
    """Open the stats window (its own window, like the day view)."""
    global _win
    if mw.col is None or AnkiWebView is None:
        return
    if _win is None or not _alive(_win):
        _win = StatsWindow(mw)
    _win.load(_range, deck_ids, scope)
    first = not _win.isVisible()
    _win.show()
    if first:
        day_view._fit_on_screen(_win)
    _win.raise_()
    _win.activateWindow()


def close() -> None:
    global _win
    if _win is not None and _alive(_win):
        _win.close()
    _win = None
