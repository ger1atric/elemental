"""
Forecast extras for the FSRS forecast:

- New cards on chosen weekdays. Anki's simulator only takes one new-card count for every
  day, so the forecast simulates your existing cards with no new cards, then runs the
  simulator once on a batch of new cards alone. That gives the reviews one day's new cards
  cause on each following day (learning, lapses and all), which is added for each day you
  add cards on.
- A confidence band around the forecast, as standard deviations from your own data:
  how much your new cards per weekday have varied over the last few weeks, and how far
  past forecasts were from what you actually reviewed, as a share of the forecast, so the
  band grows with the forecast and with how far ahead it is. Until enough forecasts are
  saved (a small log in user_files/forecast_log.json), the past forecasts are rebuilt from
  your review history: what the schedule expected each day versus when you reviewed.
"""

from __future__ import annotations

import datetime
import json
import math
import os
from datetime import timedelta

WEEKDAYS = ("M", "T", "W", "Th", "F", "Sa", "Su")   # date.weekday() order
ALL_DAYS = list(range(7))
BAND_WEEKS = 6          # weeks of new-card history behind the band
MATCH_WEEKS = 4         # weeks behind "Match my last 4 weeks"
BATCH = 1000            # new cards in the one-day batch run (more = smoother curve)
LOG_DAYS = 30           # horizons kept per logged forecast
LOG_KEEP = 120          # days of forecasts kept
LOG_SCOPES = 8
MIN_SAMPLES = 14        # past forecasts needed before a horizon's error is used
BACKTEST_DAYS = 60      # days of rebuilt schedules behind the band until then
# horizons grouped so each group gathers enough past forecasts
HORIZON_GROUPS = ((1, 1), (2, 3), (4, 7), (8, 14), (15, 30))

LOG_PATH = os.path.join(os.path.dirname(__file__), "user_files", "forecast_log.json")
_SCHEDULE_CACHE = {}
_LEARNING_CACHE = {}
_BACKLOG_CACHE = {}
LEARN_DAYS = 3          # learning answers after a card's first day are counted on day 0, 1, 2+


def clean_days(value) -> list:
    """The configured weekdays as a sorted list of 0 (Mon) … 6 (Sun); all days if unset."""
    try:
        days = sorted({int(d) for d in value if 0 <= int(d) <= 6})
    except (TypeError, ValueError):
        return list(ALL_DAYS)
    return days


def days_label(days) -> str:
    days = clean_days(days)
    if len(days) == 7:
        return "every day"
    return ", ".join(WEEKDAYS[d] for d in days) or "no days"


# ──────────────────────────────────────────────────────────────
# Your new cards per weekday
# ──────────────────────────────────────────────────────────────
def scope_dids(col, deck_ids):
    """Deck ids with their subdecks (what a "deck:Name" search covers), or None for all."""
    if not deck_ids:
        return None
    out = set()
    for did in deck_ids:
        try:
            out.update(col.decks.deck_and_child_ids(did))
        except Exception:
            out.add(int(did))
    return sorted(out)


def _day_bounds(today, rollover, days_back):
    """(start ms, end ms) for the days_back days before today (today excluded)."""
    start = datetime.datetime.combine(today - timedelta(days=days_back), datetime.time(rollover % 24))
    end = datetime.datetime.combine(today, datetime.time(rollover % 24))
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _day_of(ms, rollover):
    return datetime.datetime.fromtimestamp(ms / 1000 - rollover * 3600).date()


def new_cards_by_day(col, dids, today, rollover, days_back) -> dict:
    """{date: cards studied for the first time} over the days_back days before today
    (the same first-review rule as the heatmap's New view)."""
    lo, hi = _day_bounds(today, rollover, days_back)
    join = "JOIN cards c ON r.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    ids = col.db.list(f"""
        SELECT r.id FROM revlog r {join}
        WHERE r.type = 0 AND r.id >= {lo} AND r.id < {hi} {where}
        AND NOT EXISTS (SELECT 1 FROM revlog r2 WHERE r2.cid = r.cid AND r2.id < r.id AND r2.type < 4)
    """)
    out = {}
    for ms in ids:
        d = _day_of(ms, rollover)
        out[d] = out.get(d, 0) + 1
    return out


def weekday_counts(col, dids, today, rollover, weeks) -> dict:
    """{weekday: [new cards on that weekday in each of the last `weeks` weeks]}."""
    by_day = new_cards_by_day(col, dids, today, rollover, weeks * 7)
    out = {w: [] for w in ALL_DAYS}
    for back in range(1, weeks * 7 + 1):
        d = today - timedelta(days=back)
        out[d.weekday()].append(by_day.get(d, 0))
    return out


def _median(values) -> float:
    v = sorted(values)
    if not v:
        return 0.0
    mid = len(v) // 2
    return float(v[mid]) if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def match(counts: dict) -> tuple[int, list]:
    """(cards per day, weekdays) that fit your recent weeks. The days are the ones you
    usually add new cards on (by the typical week, so a single big day doesn't count), and
    your average weekly total is spread over them, so the forecast keeps the same volume."""
    weekly = sum(sum(v) / len(v) for v in counts.values() if v)
    if weekly < 1:
        return 0, list(ALL_DAYS)
    medians = {w: _median(counts.get(w, [])) for w in ALL_DAYS}
    top = max(medians.values())
    days = [w for w in ALL_DAYS if medians[w] >= max(1.0, 0.25 * top)] if top >= 1 else list(ALL_DAYS)
    return max(1, int(round(weekly / len(days)))), days


# ──────────────────────────────────────────────────────────────
# New cards on chosen days
# ──────────────────────────────────────────────────────────────
def learning_profile(col, dids, today, rollover, fallback_steps, weeks=8) -> list:
    """Learning answers per new card on the day it's introduced, the next day, and later
    (Anki's simulator leaves learning steps out of its review counts). From the cards you
    started in the last `weeks` weeks (the most recent week left out, so their steps are
    finished); fallback_steps on the first day if you haven't started any."""
    key = (tuple(dids) if dids else None, today, rollover)
    if key in _LEARNING_CACHE:
        return _LEARNING_CACHE[key]
    lo = _day_bounds(today, rollover, weeks * 7)[0]
    hi = _day_bounds(today - timedelta(days=7), rollover, 1)[1]
    join = "JOIN cards c ON fr.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    # Cards first answered in [lo, hi): answered in the window and never before it (the
    # same cards as grouping the whole revlog by card, about 3x faster on a big one)
    rows = col.db.all(f"""
        SELECT r.cid, r.id, f.fid FROM revlog r JOIN (
            SELECT fr.cid AS cid, MIN(fr.id) AS fid FROM revlog fr {join}
            WHERE fr.type < 4 AND fr.id >= {lo} AND fr.id < {hi} {where}
              AND NOT EXISTS (SELECT 1 FROM revlog x WHERE x.cid = fr.cid AND x.type < 4 AND x.id < {lo})
            GROUP BY fr.cid
        ) f ON r.cid = f.cid
        WHERE r.type = 0
    """)
    cards, per_day = set(), [0] * LEARN_DAYS
    for cid, rid, fid in rows:
        cards.add(cid)
        off = (_day_of(rid, rollover) - _day_of(fid, rollover)).days
        per_day[min(max(off, 0), LEARN_DAYS - 1)] += 1
    if len(cards) >= 20:
        out = [n / len(cards) for n in per_day]
    else:
        out = [float(fallback_steps)] + [0.0] * (LEARN_DAYS - 1)
    if len(_LEARNING_CACHE) >= 8:      # a few scopes (Settings' preview, the forecast deck)
        _LEARNING_CACHE.clear()
    _LEARNING_CACHE[key] = out
    return out


def backlog_rate(col, dids, today, rollover, weeks=8) -> float:
    """The share of an overdue backlog you review each day, from your last `weeks` weeks:
    each review done late counts as one card cleared after the days it sat overdue. 1.0
    (everything done the day it's due) if you haven't reviewed anything late."""
    key = (tuple(dids) if dids else None, today, rollover)
    if key in _BACKLOG_CACHE:
        return _BACKLOG_CACHE[key]
    lo, hi = _day_bounds(today, rollover, weeks * 7)
    join = "JOIN cards c ON r.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    rows = col.db.all(f"""
        SELECT r.id, r.lastIvl,
               (SELECT MAX(p.id) FROM revlog p WHERE p.cid = r.cid AND p.id < r.id AND p.type < 4)
        FROM revlog r {join}
        WHERE r.type = 1 AND r.lastIvl > 0 AND r.id >= {lo} AND r.id < {hi} {where}
    """)
    late = days = 0
    for rid, last_ivl, prev in rows:
        if prev is None:
            continue
        delay = (_day_of(rid, rollover) - _day_of(prev, rollover)).days - last_ivl
        if delay >= 1:
            late += 1
            days += delay
    rate = min(1.0, late / days) if days else 1.0
    _BACKLOG_CACHE.clear()
    _BACKLOG_CACHE[key] = rate
    return rate


def spread_backlog(counts, backlog, rate) -> list:
    """The simulator puts every overdue card on today; you clear a backlog at `rate` a day.
    Moves the part you won't get to today onto the following days (same total)."""
    if backlog <= 0 or rate >= 1 or not counts:
        return counts
    out = list(counts)
    out[0] -= backlog * (1 - rate)
    left = backlog * (1 - rate)
    for d in range(1, len(out)):
        out[d] += left * rate
        left *= 1 - rate
    return out


def started_recently(col, dids, today, rollover) -> list:
    """New cards started [the day before yesterday, yesterday, so far today]."""
    by_day = new_cards_by_day(col, dids, today + timedelta(days=1), rollover, 3)
    return [by_day.get(today - timedelta(days=b), 0) for b in (2, 1, 0)]


def learning_done_today(col, dids, today, rollover) -> int:
    lo = _day_bounds(today + timedelta(days=1), rollover, 1)[0]
    join = "JOIN cards c ON r.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    return col.db.scalar(f"SELECT COUNT(*) FROM revlog r {join} WHERE r.type = 0 AND r.id >= {lo} {where}") or 0


def add_learning(intro, profile) -> list:
    """Learning answers on each day from the new cards introduced (profile from
    learning_profile)."""
    return [sum(intro[d - j] * profile[j] for j in range(len(profile)) if d - j >= 0)
            for d in range(len(intro))]


def batch_curve(run_sim, days_to_simulate) -> list:
    """Reviews per new card on each day after it's introduced on day 0, from Anki's
    simulator. run_sim(search, deck_size, new_limit) -> daily review counts."""
    counts = run_sim("cid:1", BATCH, BATCH)      # matches no card: the batch alone
    curve = [c / BATCH for c in counts[:days_to_simulate]]
    return curve + [0.0] * (days_to_simulate - len(curve))


def intro_schedule(today, n_days, per_day, days) -> list:
    """New cards introduced on each day offset (0 = today)."""
    days = set(clean_days(days))
    return [per_day if (today + timedelta(days=i)).weekday() in days else 0 for i in range(n_days)]


def add_new_cards(base, curve, intro) -> list:
    """base reviews plus the reviews of the new cards introduced on each day."""
    out = []
    for d in range(len(base)):
        out.append(base[d] + sum(intro[i] * curve[d - i] for i in range(d + 1) if intro[i]))
    return out


def habit_spread(curve, today, n_days, per_day, days, counts) -> tuple[list, list]:
    """(above, below): how far each day's answers could land above and below the forecast
    because your new cards differ from the plan (per_day on `days`, none on the others),
    from how they differed on each weekday in recent weeks. Kept apart because a big batch
    on an "off" day adds far more than a light day takes away. Each day's new cards are
    treated as independent."""
    days = set(clean_days(days))
    up_w, down_w = {}, {}
    for w in ALL_DAYS:
        plan = per_day if w in days else 0
        hist = counts.get(w) or [plan]
        up_w[w] = sum(max(n - plan, 0) ** 2 for n in hist) / len(hist)
        down_w[w] = sum(max(plan - n, 0) ** 2 for n in hist) / len(hist)
    wd = [(today + timedelta(days=i)).weekday() for i in range(n_days)]

    def spread(var_w):
        var_i = [var_w[w] for w in wd]
        return [math.sqrt(sum(var_i[i] * curve[d - i] ** 2 for i in range(d + 1) if var_i[i]))
                for d in range(n_days)]
    return spread(up_w), spread(down_w)


# ──────────────────────────────────────────────────────────────
# Past forecasts vs what happened
# ──────────────────────────────────────────────────────────────
def scope_key(deck_ids) -> str:
    return ",".join(str(int(d)) for d in sorted(deck_ids)) if deck_ids else "all"


def _load_log() -> dict:
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("scopes"), dict) else {"scopes": {}}
    except Exception:
        return {"scopes": {}}


def log_forecast(scope, today, values) -> None:
    """Keep the day's first forecast (horizons 1…LOG_DAYS) for this scope."""
    data = _load_log()
    scopes = data["scopes"]
    entries = scopes.setdefault(scope, {})
    key = today.isoformat()
    if key in entries:
        return
    entries[key] = [int(round(v)) for v in values[1:LOG_DAYS + 1]]
    oldest = (today - timedelta(days=LOG_KEEP)).isoformat()
    for k in [k for k in entries if k < oldest]:
        del entries[k]
    if len(scopes) > LOG_SCOPES:
        for s in sorted(scopes, key=lambda s: max(scopes[s] or [""]))[:len(scopes) - LOG_SCOPES]:
            del scopes[s]
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        tmp = LOG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, LOG_PATH)
    except OSError:
        pass


def actual_reviews(col, dids, today, rollover, days_back, every_answer) -> dict:
    """{date: reviews} counted the way the forecast counts them: every answer (as the
    heatmap does) when the forecast counts learning and relearning steps, otherwise each
    card in review once a day (the simulator's own count)."""
    lo, hi = _day_bounds(today, rollover, days_back)
    join = "JOIN cards c ON r.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    day = f"strftime('%Y-%m-%d', (r.id - {int(rollover * 3600 * 1000)}) / 1000, 'unixepoch', 'localtime')"
    rows = col.db.all(f"""
        SELECT {day}, COUNT(DISTINCT CASE WHEN r.type = 1 THEN r.cid END), COUNT(*)
        FROM revlog r {join}
        WHERE r.id >= {lo} AND r.id < {hi} AND r.type < 4 {where}
        GROUP BY 1
    """)
    return {d: (every if every_answer else rev or 0) for d, rev, every in rows}


def schedule_errors(col, dids, today, rollover) -> dict:
    """{horizon group: relative error} from your history, until enough forecasts are saved.

    Each review records the interval it set, so for every day of the last BACKTEST_DAYS days
    this rebuilds how many cards the schedule expected 1…30 days later and compares it with
    when you actually reviewed them next (cards done late, early or skipped). The spread of
    that difference, as a share of the expected count, is the error for each horizon. Kept
    for the day, since it reads every review of the deck."""
    key = (tuple(dids) if dids else None, today, rollover)
    if key in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[key]
    H = HORIZON_GROUPS[-1][1]
    first = (today - timedelta(days=BACKTEST_DAYS)).toordinal()
    last = (today - timedelta(days=2)).toordinal()
    t = today.toordinal()
    join = "JOIN cards c ON r.cid = c.id" if dids else ""
    where = f"AND c.did IN ({','.join(map(str, dids))})" if dids else ""
    rows = col.db.all(f"SELECT r.cid, r.id, r.ivl FROM revlog r {join} WHERE r.type < 4 {where} ORDER BY r.cid, r.id")
    expected, actual = {}, {}

    def card(revs):
        for j, (d, ivl) in enumerate(revs):
            nd = revs[j + 1][0] if j + 1 < len(revs) else None
            if ivl <= 0:            # still learning: no day scheduled
                continue
            due = d + ivl
            for m in range(max(d, first), min(nd - 1 if nd else last, last) + 1):
                if 1 <= due - m <= H:
                    expected[(m, due - m)] = expected.get((m, due - m), 0) + 1
                if nd is not None and 1 <= nd - m <= H:
                    actual[(m, nd - m)] = actual.get((m, nd - m), 0) + 1

    cur, revs = None, []
    for cid, rid, ivl in rows:
        if cid != cur:
            if revs:
                card(revs)
            cur, revs = cid, []
        revs.append((_day_of(rid, rollover).toordinal(), ivl))
    if revs:
        card(revs)

    out = {}
    for g in HORIZON_GROUPS:
        res, exp = [], []
        for m in range(first, last + 1):
            for h in range(g[0], g[1] + 1):
                if m + h >= t:
                    break
                e = expected.get((m, h), 0)
                res.append(actual.get((m, h), 0) - e)
                exp.append(e)
        if len(res) < MIN_SAMPLES or sum(exp) / len(exp) < 5:
            continue
        mean = sum(res) / len(res)
        sd = math.sqrt(sum((r - mean) ** 2 for r in res) / (len(res) - 1))
        out[g] = (sd / (sum(exp) / len(exp)), len(res))
    _SCHEDULE_CACHE.clear()
    _SCHEDULE_CACHE[key] = out
    return out


def forecast_errors(col, scope, dids, today, rollover, every_answer) -> dict:
    """{horizon group: (relative error, samples)}: the root-mean-square difference between past
    forecasts and what you reviewed, as a share of the forecast, for horizon groups with at
    least MIN_SAMPLES past days."""
    entries = _load_log()["scopes"].get(scope) or {}
    if not entries:
        return {}
    actual = None
    errs = {g: [] for g in HORIZON_GROUPS}
    for made, values in entries.items():
        try:
            m = datetime.date.fromisoformat(made)
        except ValueError:
            continue
        for h, v in enumerate(values, start=1):
            target = m + timedelta(days=h)
            if target >= today:
                break
            if actual is None:
                actual = actual_reviews(col, dids, today, rollover, LOG_KEEP + LOG_DAYS, every_answer)
            for g in HORIZON_GROUPS:
                if g[0] <= h <= g[1]:
                    errs[g].append((actual.get(target.isoformat(), 0) - v, v))
                    break
    out = {}
    for g, v in errs.items():
        mean_f = sum(f for _, f in v) / len(v) if v else 0
        if len(v) >= MIN_SAMPLES and mean_f > 0:
            out[g] = (math.sqrt(sum(e * e for e, _ in v) / len(v)) / mean_f, len(v))
    return out


def error_rel(errors, horizon) -> float:
    """The relative error for a day this far ahead (0 when there isn't enough data)."""
    h = min(max(1, horizon), HORIZON_GROUPS[-1][1])
    for g in HORIZON_GROUPS:
        if g[0] <= h <= g[1]:
            hit = errors.get(g)
            return hit[0] if hit else 0.0
    return 0.0
