"""
Time-left estimate, learned from your own review log.

Each remaining card costs what cards like it have cost you:

  • A review's time depends on the card itself (some are always slow), on
    whether you'll fail it (its FSRS retrievability; a fail also brings its
    relearning step), and on your pace.
  • Pace drifts week to week, so it follows a recent average of your past days
    and is then updated with the reviews you've already done today.
  • A new card costs its whole first day of learning steps; a card already in
    learning costs the rest of its steps.

The range combines card-to-card noise with how much your pace wanders within a
day. Backtested on your last 60 days (fit only on the days before each): from 10%
to 60% through a day the expected time is within ~2% on average, typically
14–17% off on a given day, and the 80% range catches the real time ~70–85% of
the time.

Everything here reads the collection through its own read-only sqlite
connection, and the fit (a year of reviews) is meant to run off the main thread.
Where Anki's lock shuts that connection out (always, on Windows), the same
queries run through Anki's own connection instead: see connect.
"""

from __future__ import annotations

import collections
import json
import math
import os
import random
import sqlite3
from array import array
from statistics import NormalDist
from pathlib import Path

HISTORY_DAYS = 365          # reviews the speed model is fit on
POOL_DAYS = 60              # recent window for new-card / relearn / learning costs
CAP = 60.0                  # Anki's per-card time cap (deck option maxTaken)
BUSY_DAY = 50               # days with fewer reviews don't move the pace average
PACE_HALFLIFE = 7           # days
# Extra spread the backtest needed: pace isn't constant within a day.
START_DRIFT_SD = 0.056
MIDDAY_DRIFT_SD = 0.231
DAY_NODES = 15              # quadrature points over today's (uncertain) pace
GRID_LO, GRID_STEP, GRID_N = -3.0, 0.05, 181   # log-seconds grid for the cost table
RESID_SAMPLE = 4000

_ND = NormalDist()
_Z = [_ND.inv_cdf((k + 0.5) / DAY_NODES) for k in range(DAY_NODES)]


# Collections whose read-only connection was refused. Anki holds the collection file
# locked while it's open; on macOS and Linux a second connection in the same process
# still reads, but Windows locks per file handle, so there it never can.
_refused = set()
_anki_db = None             # () -> Anki's col.db (or None), set by use_anki_when_locked


def use_anki_when_locked(get_db) -> None:
    global _anki_db
    _anki_db = get_db


def connect(path: str, fallback: bool = True):
    """A read-only connection of our own, outside Anki's backend. Where Anki's lock
    shuts it out, an AnkiReader over Anki's own connection instead (or, with
    fallback=False, sqlite3.OperationalError)."""
    if path not in _refused:
        # A proper file URI (file:///C:/… on Windows).
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0)
        try:
            conn.execute("PRAGMA query_only=1;")
            conn.execute("SELECT 1 FROM col")       # opening is lazy: a lock shows up here
            return conn
        except sqlite3.OperationalError as e:
            conn.close()
            if "locked" not in str(e):
                raise
            _refused.add(path)
    db = _anki_db() if fallback and _anki_db else None
    if db is None:
        raise sqlite3.OperationalError("database is locked")
    return AnkiReader(db)


class AnkiReader:
    """Just enough of sqlite3.Connection for this module, over Anki's col.db. Only
    statements starting with SELECT: Anki clears its Undo after any other kind. The
    focus log can't be attached here; _log_rows matches it separately (log_path)."""

    def __init__(self, db, log_path: str | None = None):
        self.db, self.log_path, self._rows = db, log_path, iter(())

    def execute(self, sql: str, params=()):
        if sql.lstrip()[:6].lower() != "select" or "flog." in sql:
            raise sqlite3.OperationalError("not available through Anki's connection")
        try:
            self._rows = iter(self.db.all(sql, *params))
        except Exception as e:      # anki.errors.DBError; callers catch sqlite3.Error
            raise sqlite3.OperationalError(str(e)) from e
        return self

    def cursor(self):
        return AnkiReader(self.db, self.log_path)

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self) -> list:
        return list(self._rows)

    def __iter__(self):
        return self._rows

    def close(self) -> None:
        self._rows = iter(())


def _day(rid_ms: int, cutoff: int) -> int:
    """Anki day relative to the model's cutoff: today == -1, yesterday == -2."""
    return math.floor((rid_ms / 1000 - cutoff) / 86400)


def _kind(rtype: int, day: int, firstday: int) -> str:
    if rtype == 0:
        return "new" if day == firstday else "learn"
    return "review" if rtype == 1 else "relearn"


def _moments(values) -> tuple:
    """(mean, second moment) of a pool; (0, 0) if empty."""
    n = len(values)
    if not n:
        return 0.0, 0.0
    return sum(values) / n, sum(v * v for v in values) / n


class Model:
    """Everything the estimate needs, fit once per Anki day."""

    def __init__(self):
        self.cutoff = 0
        self.mu = {}            # (kind, fail) -> mean log-seconds
        self.card_eff = {}      # cid -> shrunken log-speed offset
        self.sigma = 0.7        # per-review noise sd (log-s)
        self.level = 0.0        # recent pace (EWMA of day effects)
        self.innov_sd = 0.15    # how far a day strays from that level
        self.pool_level = 0.0   # pace during the pool window
        self.table1 = []        # E[min(e^(x+noise), CAP)] on the x grid
        self.table2 = []        # second moment of the same
        self.lapse = (0.0, 0.0)         # same-day relearn time after a failed review
        self.learn = (0.0, 0.0)         # remaining same-day time of a learning card
        self.new = {}                   # top-level deck name -> intro-day time moments
        self.new_all = (0.0, 0.0)
        self.wall = 1.0                 # desk time / Anki-recorded time
        self.fail_rate = 0.1            # fallback when a card has no FSRS state
        # Focus score (see lock_stats): the median answer's log-offset from its card's
        # expected time, past days' scores, a typical recent day, and your usual range.
        self.lock_base = 0.0
        self.lock_days = {}             # day (today == -1) -> (score, answers)
        self.lock_typical = None        # lock_stats() of the last POOL_DAYS, pooled
        self.lock_range = (0.6, 0.85)   # 10th / 90th percentile of daily scores
        self.lock_answers = {}          # day -> (answer ids, focus x in SDs; NaN = lookup), for the day view
        self.card_lim = {}              # cid -> that card's cutoff (one of its SDs, log-seconds)
        self.lock_lim0 = math.log(2.0)  # the cutoff for a card with no history
        self.new_lim = math.log(3.0)    # the cutoff for a new card's first view


def fit(path: str, cutoff: int, log_path: str | None = None, away_is_lookup: bool = False,
        reading_counts: bool = False) -> Model:
    """log_path: the focus log's sqlite file (focus_log.path()), for the focus score."""
    conn = connect(path)
    try:
        if log_path and os.path.exists(log_path) and isinstance(conn, AnkiReader):
            conn.log_path = log_path
        elif log_path and os.path.exists(log_path):
            try:
                conn.execute("ATTACH DATABASE ? AS flog", (Path(log_path).resolve().as_uri() + "?mode=ro",))
            except sqlite3.Error:
                pass
        return _fit(conn, cutoff, away_is_lookup, reading_counts)
    finally:
        conn.close()


def _fit(conn, cutoff: int, away_is_lookup: bool = False, reading_counts: bool = False) -> Model:
    m = Model()
    m.cutoff = cutoff
    today_ms = (cutoff - 86400) * 1000
    start_ms = today_ms - HISTORY_DAYS * 86400 * 1000
    tops = {int(d): str(n).split("\x1f")[0] for d, n in conn.execute("SELECT id, name FROM decks")}
    first = dict(conn.execute("SELECT cid, MIN(id) FROM revlog WHERE type < 4 GROUP BY cid"))
    rows = conn.execute(
        "SELECT r.id, r.cid, r.ease, r.time, r.type, c.did FROM revlog r JOIN cards c ON c.id = r.cid "
        "WHERE r.type < 4 AND r.time > 0 AND r.id >= ? AND r.id < ? ORDER BY r.id",
        (start_ms, today_ms),
    ).fetchall()
    if len(rows) < 200:
        return m

    recs = []   # (rid, cid, day, kind, fail, t, logt, top)
    for rid, cid, ease, ms, rtype, did in rows:
        day = _day(rid, cutoff)
        t = ms / 1000.0
        recs.append((rid, cid, day, _kind(rtype, day, _day(first.get(cid, rid), cutoff)),
                     1 if ease == 1 else 0, t, math.log(t), tops.get(did, "")))

    # Speed by kind of review and outcome.
    acc = {}
    for r in recs:
        s = acc.setdefault((r[3], r[4]), [0.0, 0])
        s[0] += r[6]
        s[1] += 1
    m.mu = {k: v[0] / v[1] for k, v in acc.items()}
    res = [r[6] - m.mu[(r[3], r[4])] for r in recs]

    # Day effects, then per-card effects on what's left (empirical-Bayes shrinkage).
    dsum, dn = {}, {}
    for r, e in zip(recs, res):
        dsum[r[2]] = dsum.get(r[2], 0.0) + e
        dn[r[2]] = dn.get(r[2], 0) + 1
    day_eff = {d: dsum[d] / dn[d] for d in dsum}
    res2 = [e - day_eff[r[2]] for r, e in zip(recs, res)]
    cs = {}
    for r, e in zip(recs, res2):
        s = cs.setdefault(r[1], [0.0, 0.0, 0])
        s[0] += e
        s[1] += e * e
        s[2] += 1
    means = {c: s[0] / s[2] for c, s in cs.items()}
    vars_ = [(s[1] - s[0] * s[0] / s[2]) / (s[2] - 1) for s in cs.values() if s[2] > 1]
    sigma2 = sum(vars_) / len(vars_) if vars_ else 0.5
    mm = list(means.values())
    mbar = sum(mm) / len(mm)
    var_m = sum((x - mbar) ** 2 for x in mm) / max(len(mm) - 1, 1)
    tau2 = max(var_m - sum(sigma2 / s[2] for s in cs.values()) / len(cs), 1e-3)
    m.card_eff = {c: means[c] * s[2] / (s[2] + sigma2 / tau2) for c, s in cs.items()}
    resid = [e - m.card_eff[r[1]] for r, e in zip(recs, res2)]
    rbar = sum(resid) / len(resid)
    m.sigma = math.sqrt(sum((x - rbar) ** 2 for x in resid) / len(resid))
    _fit_lock(m, recs, res, res2, cs, sigma2 / tau2, _log_rows(conn, start_ms, today_ms),
              away_is_lookup, reading_counts)

    # Cost table: your real (heavy-tailed) residuals, capped like Anki caps them.
    # Only reviews are costed from this table. Each residual is taken against its card's
    # effect fit without it (leave-one-out): in-sample residuals are tighter than a future
    # answer's, and the table's mean time came out ~10% low. Recent reviews only, when
    # there are enough, so it follows how reviews have felt lately.
    k = sigma2 / tau2
    rev = [(r[2], e - (cs[r[1]][0] - e) / (cs[r[1]][2] - 1 + k))
           for r, e in zip(recs, res2) if r[3] == "review"]
    recent_rev = [e for d, e in rev if d >= recs[-1][2] - POOL_DAYS]
    rev_resid = recent_rev if len(recent_rev) > 1000 else [e for _, e in rev] or resid
    sample = random.Random(0).sample(rev_resid, min(RESID_SAMPLE, len(rev_resid)))
    for i in range(GRID_N):
        x = GRID_LO + i * GRID_STEP
        t = [min(math.exp(x + e), CAP) for e in sample]
        m.table1.append(sum(t) / len(t))
        m.table2.append(sum(v * v for v in t) / len(t))

    # Pace level: EWMA over busy days, and how far a day strays from it.
    # Light reviewers never reach BUSY_DAY; count their fuller days instead.
    busy_min = min(BUSY_DAY, max(10, sorted(dn.values())[len(dn) // 2] / 2))
    busy = sorted(d for d in day_eff if dn[d] > busy_min)
    if len(busy) >= 3:
        a = 1 - math.exp(math.log(0.5) / PACE_HALFLIFE)
        num = den = 0.0
        prev, innov = None, []
        for d in busy:
            x = day_eff[d]
            if prev is not None:
                innov.append(x - prev)
            num = num * (1 - a) + x
            den = den * (1 - a) + 1
            prev = num / den
        m.level = prev
        if len(innov) > 2:
            ib = sum(innov) / len(innov)
            m.innov_sd = math.sqrt(sum((x - ib) ** 2 for x in innov) / (len(innov) - 1))
        last = busy[-1]
        recent = [day_eff[d] for d in busy if d >= last - POOL_DAYS]
        m.pool_level = sum(recent) / len(recent)

    # Recent costs of the things that come in bunches.
    maxday = recs[-1][2]
    pool = [r for r in recs if r[2] >= maxday - POOL_DAYS]
    groups = {}
    for r in pool:
        groups.setdefault((r[1], r[2]), []).append(r)
    lapse, learn, new = [], [], {}
    for g in groups.values():
        after = 0.0
        new_t = 0.0
        for r in reversed(g):
            if r[3] == "review" and r[4]:
                lapse.append(after)
            elif r[3] in ("learn", "relearn"):
                learn.append(after + r[5])
            if r[3] == "new":
                new_t += r[5]
            after += r[5]
        if new_t:
            new.setdefault(g[0][7], []).append(new_t)
    m.lapse, m.learn = _moments(lapse), _moments(learn)
    m.new_all = _moments([v for vs in new.values() for v in vs])
    m.new = {k: _moments(v) for k, v in new.items() if len(v) > 200}

    # Desk time vs recorded time: gaps between answers, breaks over 3 min dropped.
    ratios, gap_sum, t_sum, cur, prev_id = [], 0.0, 0.0, None, None
    for r in pool:
        if r[2] != cur:
            if cur is not None and t_sum:
                ratios.append(gap_sum / t_sum)
            cur, gap_sum, t_sum, prev_id = r[2], 0.0, 0.0, None
        if prev_id is not None:
            g = (r[0] - prev_id) / 1000
            # A break counts as the card's own time, so it's on both sides of the ratio.
            gap_sum += g if g < 180 else r[5]
        t_sum += r[5]
        prev_id = r[0]
    if t_sum:
        ratios.append(gap_sum / t_sum)
    if ratios:
        ratios.sort()
        m.wall = max(1.0, ratios[len(ratios) // 2])

    month = [r for r in recs if r[3] == "review" and r[2] >= maxday - 30]
    if month:
        m.fail_rate = sum(r[4] for r in month) / len(month)
    return m


# ──────────────────────────────────────────────────────────────
# Focus score: how steadily you answered against each card's usual time
# ──────────────────────────────────────────────────────────────
# An answer counts as focused when it took no more than its card's usual time (its kind
# of review, pass/fail and the card's own speed all accounted for) plus one of that
# card's standard deviations. Faster is fine. Each card's SD is blended with your
# overall spread by how many reviews it has (CARD_SD_PRIOR reviews' worth), computed
# with extreme answers capped (one walk-away shouldn't excuse the next), and kept
# between 1.5x and 3x your usual time. On the author's 180 days, cards' cutoffs ran
# 1.7x-2.3x (median 1.9x) and a day's score 71%-86% (median 79%), with odd/even
# reliability 0.93. It doesn't track the pass rate: it measures steadiness, not recall.
LOCK_SD = 1.0               # cutoff, in the card's SDs
LOCK_LIM_MIN, LOCK_LIM_MAX = math.log(1.5), math.log(3.0)
CARD_SD_PRIOR = 4
CLIP_SD = 2.5               # answers capped at this many overall SDs when measuring spread
# A new card's first view is mostly reading it, and how long that takes depends on the
# card, so it gets more room: NEW_SD of the spread of your new-card answers (judged
# against new cards as a whole, since the card has no history yet), up to 4x. On the
# author's 60 days that let 9% of first views count as unfocused (19% at one SD).
NEW_SD = 2.0
NEW_LIM_MAX = math.log(4.0)
LOCK_MIN = 20               # answers before a day gets a score
# From the focus log (focus_log.py), where there is one: a card during which you opened
# the editor or browser was a lookup and is left out. Leaving Anki for LOOKUP_AWAY s or
# more is a lookup only if you say so (away_is_lookup) — it might as well have been a
# video — and otherwise counts like any slow card. With reading_counts (off by
# default: reading the back and staring at it look the same), a card whose question
# side alone took your usual time, with Anki in front throughout, is placed by that.
LOOKUP_AWAY = 2.0
LOG_MATCH_MS = 5000         # a log row belongs to its card's revlog entry within this


def log_row(log: dict, cid: int, rid: int):
    """The focus-log row (t_ms, q, a, away, edit) for revlog entry (cid, rid), or None."""
    best = None
    for row in log.get(cid, ()):
        if abs(row[0] - rid) <= LOG_MATCH_MS and (best is None or abs(row[0] - rid) < abs(best[0] - rid)):
            best = row
    return best


def is_lookup(away: float, edit, away_is_lookup: bool = False) -> bool:
    return bool(edit) or (away_is_lookup and away >= LOOKUP_AWAY)


def _focus_x(x: float, t: float, row, away_is_lookup: bool = False,
             reading_counts: bool = False) -> float | None:
    """An answer's log-offset from usual, after the focus log: None for a lookup; with
    reading_counts, the question side's offset when that is smaller and you stayed in
    Anki (time spent reading the answer)."""
    if row is None:
        return x
    _, q, _, away, edit = row
    if is_lookup(away, edit, away_is_lookup):
        return None
    if reading_counts and away < LOOKUP_AWAY and q > 0 and t > 0:
        return min(x, x - math.log(t) + math.log(max(q, 0.05)))
    return x


LOCK_POINTS = 300           # most answers drawn as dots; more are thinned evenly by rank


def lock_stats(xs: list, points: bool = False) -> dict | None:
    """Score and box-plot numbers for answers given in their cards' SDs from usual
    (0 = the card's usual time, LOCK_SD = its cutoff). Whiskers at the 5th/95th
    percentile, since single answers run from mis-taps to walk-aways. With points,
    also 'points': the answers themselves (at most LOCK_POINTS, evenly spread over the
    sorted answers so the shape holds)."""
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)

    def q(p):
        f = p * (n - 1)
        i = int(f)
        return xs[i] if i + 1 >= n else xs[i] + (xs[i + 1] - xs[i]) * (f - i)

    out = {
        "score": sum(1 for x in xs if x <= LOCK_SD) / n,
        "n": n,
        "box": tuple(q(p) for p in (0.05, 0.25, 0.5, 0.75, 0.95)),
    }
    if points:
        k = min(n, LOCK_POINTS)
        out["points"] = [xs[round(i * (n - 1) / max(k - 1, 1))] for i in range(k)]
    return out


def _card_lims(m: Model, recs: list, res: list, res2: list):
    """Each card's cutoff (one SD of its own answer times, blended toward your overall
    spread, capped extremes) into m.card_lim, and a function giving it for one answer
    with that answer left out (for past days)."""
    srt = sorted(res2)
    med = srt[len(srt) // 2]
    gsd = sorted(abs(v - med) for v in res2)[len(res2) // 2] * 1.4826 or 0.6
    clip = CLIP_SD * gsd
    cw = {}
    for r, e2 in zip(recs, res2):
        c = max(-clip, min(clip, e2))
        s = cw.setdefault(r[1], [0.0, 0.0, 0])
        s[0] += c
        s[1] += c * c
        s[2] += 1
    dof = sum(s[2] - 1 for s in cw.values() if s[2] > 1)
    v0 = sum(s[1] - s[0] * s[0] / s[2] for s in cw.values() if s[2] > 1) / dof if dof else gsd * gsd

    def lim(s0, s1, n):
        ss = s1 - s0 * s0 / n if n > 0 else 0.0
        sd = math.sqrt((CARD_SD_PRIOR * v0 + max(ss, 0.0)) / (CARD_SD_PRIOR + max(n - 1, 0)))
        return min(LOCK_LIM_MAX, max(LOCK_LIM_MIN, sd * LOCK_SD))

    m.card_lim = {cid: lim(*s) for cid, s in cw.items()}
    m.lock_lim0 = min(LOCK_LIM_MAX, max(LOCK_LIM_MIN, math.sqrt(v0) * LOCK_SD))
    new = sorted(e for r, e in zip(recs, res) if r[3] == "new")
    if len(new) >= 50:
        nmed = new[len(new) // 2]
        nsd = sorted(abs(e - nmed) for e in new)[len(new) // 2] * 1.4826
        m.new_lim = min(NEW_LIM_MAX, max(LOCK_LIM_MIN, NEW_SD * nsd))

    def without(cid, e2):
        s = cw[cid]
        c = max(-clip, min(clip, e2))
        return lim(s[0] - c, s[1] - c * c, s[2] - 1)
    return without


def _card_lim(m: Model, cid: int, kind: str = "") -> float:
    if kind == "new":
        return getattr(m, "new_lim", math.log(3.0))
    return m.card_lim.get(cid, getattr(m, "lock_lim0", math.log(2.0)))


def _log_rows(conn, start_ms: int, today_ms: int):
    """(revlog id, q, away, edit) for each of _fit's answers in its order — the focus
    log's row for it, or Nones — streamed from the attached log (see fit), so a year of
    log never sits in memory. None when there's no log attached."""
    if isinstance(conn, AnkiReader):
        return _log_rows_apart(conn, start_ms, today_ms) if conn.log_path else None
    try:
        conn.execute("SELECT 1 FROM flog.log LIMIT 1")
    except sqlite3.Error:
        return None
    # Any log row of the card within LOG_MATCH_MS: a card can't be answered twice that
    # fast, so there's one. (SQLite won't take the outer row in the subquery's ORDER BY.)
    return conn.cursor().execute(
        "SELECT x.id, l.q, l.away, l.edit FROM (SELECT r.id AS id, "
        "(SELECT l2.rowid FROM flog.log l2 WHERE l2.cid = r.cid "
        f"AND l2.t BETWEEN r.id - {LOG_MATCH_MS} AND r.id + {LOG_MATCH_MS} LIMIT 1) AS lrow "
        "FROM revlog r JOIN cards c ON c.id = r.cid "
        "WHERE r.type < 4 AND r.time > 0 AND r.id >= ? AND r.id < ?) x "
        "LEFT JOIN flog.log l ON l.rowid = x.lrow ORDER BY x.id",
        (start_ms, today_ms))


def _log_rows_apart(conn: AnkiReader, start_ms: int, today_ms: int):
    """_log_rows where the log can't be attached (Anki's connection): the same match,
    made here by walking the answers and the log together in time order."""
    try:
        log = sqlite3.connect(Path(conn.log_path).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        answers = conn.execute(
            "SELECT r.id, r.cid FROM revlog r JOIN cards c ON c.id = r.cid "
            "WHERE r.type < 4 AND r.time > 0 AND r.id >= ? AND r.id < ? ORDER BY r.id",
            (start_ms, today_ms)).fetchall()
        # Read it all now and close: an open file in user_files blocks updates on Windows.
        logs = iter(log.execute("SELECT cid, t, q, away, edit FROM log WHERE t >= ? AND t < ? ORDER BY t",
                                (start_ms - LOG_MATCH_MS, today_ms + LOG_MATCH_MS)).fetchall())
    except sqlite3.Error:
        return None
    finally:
        log.close()

    def rows():
        near = collections.deque()      # log rows within LOG_MATCH_MS of the answer
        ahead = next(logs, None)
        for rid, cid in answers:
            while ahead is not None and ahead[1] <= rid + LOG_MATCH_MS:
                near.append(ahead)
                ahead = next(logs, None)
            while near and near[0][1] < rid - LOG_MATCH_MS:
                near.popleft()
            hit = next((l for l in near if l[0] == cid), None)
            yield (rid, hit[2], hit[3], hit[4]) if hit else (rid, None, None, None)
    return rows()


def _fit_lock(m: Model, recs: list, res: list, res2: list, cs: dict, k: float, log_rows=None,
              away_is_lookup: bool = False, reading_counts: bool = False) -> None:
    """Past days' focus scores. Each answer is measured against its card's
    effect fit WITHOUT it (leave-one-out), like today's answers are against a model
    that hasn't seen them; in-sample, past days would look steadier than today."""
    xs = []
    for r, e, e2 in zip(recs, res, res2):
        s = cs[r[1]]
        loo = (s[0] - e2) / (s[2] - 1 + k) if s[2] > 1 else 0.0
        xs.append(e - loo)
    m.lock_base = sorted(xs)[len(xs) // 2]
    lim_without = _card_lims(m, recs, res, res2)
    by_day = {}
    answers = {}
    for r, x, e, e2 in zip(recs, xs, res, res2):
        if r[3] == "new":       # first view: no card history yet, judged against new cards
            x, lim = e, m.new_lim
        else:
            lim = lim_without(r[1], e2)
        row = None
        if log_rows is not None:
            lr = next(log_rows, None)
            if lr is None or lr[0] != r[0]:
                log_rows = None             # out of step with the answers: ignore the log
            elif lr[1] is not None:
                row = (lr[0], lr[1], 0.0, lr[2], lr[3])
        fx = _focus_x(x - m.lock_base, r[5], row, away_is_lookup, reading_counts)
        a = answers.get(r[2])
        if a is None:
            a = answers[r[2]] = (array("q"), array("f"))
        a[0].append(r[0])
        a[1].append(math.nan if fx is None else fx / lim * LOCK_SD)
        if fx is not None:
            by_day.setdefault(r[2], []).append(fx / lim * LOCK_SD)
    m.lock_answers = answers
    days = {}
    for d, v in by_day.items():
        if len(v) >= LOCK_MIN:
            st = lock_stats(v)
            days[d] = (st["score"], st["n"])
    m.lock_days = days
    maxday = recs[-1][2]
    m.lock_typical = lock_stats([x for d, v in by_day.items() if d >= maxday - POOL_DAYS for x in v])
    scores = sorted(sc for d, (sc, _) in days.items() if d >= maxday - POOL_DAYS) or \
        sorted(sc for sc, _ in days.values())
    if scores:
        m.lock_typical["score"] = scores[len(scores) // 2]
    all_scores = sorted(sc for sc, _ in days.values())
    if len(all_scores) >= 10:
        m.lock_range = (all_scores[len(all_scores) // 10], all_scores[(9 * len(all_scores)) // 10])


def lock_in(m: Model, conn, cutoff: int, log: dict | None = None,
            away_is_lookup: bool = False, reading_counts: bool = False) -> dict | None:
    """lock_stats() of today's answers so far (all decks), with 'lookups' (cards the
    focus log left out) and 'away' (cards during which you left Anki, still counted)."""
    xs, lookups, away = [], 0, 0
    for _rid, x, row in today_focus(m, conn, cutoff, log, away_is_lookup, reading_counts):
        if x is None:
            lookups += 1
            continue
        xs.append(x)
        if row is not None and row[3] >= LOOKUP_AWAY:
            away += 1
    st = lock_stats(xs, points=True)
    if st is not None:
        st["lookups"], st["away"] = lookups, away
    return st


def today_focus(m: Model, conn, cutoff: int, log: dict | None = None,
                away_is_lookup: bool = False, reading_counts: bool = False) -> list:
    """[(answer id, focus x in the card's SDs or None for a lookup, focus-log row)]
    for today's answers, in order."""
    out = []
    for rid, t, r, cid, kind in _today(m, conn, cutoff):
        row = log_row(log, cid, rid) if log else None
        fx = _focus_x(r - m.lock_base, t, row, away_is_lookup, reading_counts)
        out.append((rid, None if fx is None else fx / _card_lim(m, cid, kind) * LOCK_SD, row))
    return out


def last_answer(m: Model, conn, cutoff: int, log: dict | None = None,
                away_is_lookup: bool = False, reading_counts: bool = False):
    """(revlog id, 'focus' | 'slow' | 'lookup') for today's latest answer, or None."""
    rows = _today(m, conn, cutoff)
    if not rows:
        return None
    rid, t, r, cid, kind = rows[-1]
    fx = _focus_x(r - m.lock_base, t, log_row(log, cid, rid) if log else None,
                  away_is_lookup, reading_counts)
    if fx is None:
        return rid, "lookup"
    return rid, "focus" if fx <= _card_lim(m, cid, kind) else "slow"


# ──────────────────────────────────────────────────────────────
# Estimating
# ──────────────────────────────────────────────────────────────
def _table(m: Model, x: float) -> tuple:
    f = (x - GRID_LO) / GRID_STEP
    if f <= 0:
        return m.table1[0], m.table2[0]
    if f >= GRID_N - 1:
        return m.table1[-1], m.table2[-1]
    i = int(f)
    w = f - i
    return (m.table1[i] + (m.table1[i + 1] - m.table1[i]) * w,
            m.table2[i] + (m.table2[i + 1] - m.table2[i]) * w)


RECENT_CARDS = 50          # "your recent pace" = today's last this-many answers
RECENT_MIN = 10
RECENT_HALFLIFE = 50       # answers; how fast older answers fade from today's pace


def _today(m: Model, conn, cutoff: int) -> list:
    """[(answer id, seconds, residual, card id, kind)] for today's answers, in order. The
    residual is how much slower (+) or faster (−) than expected the answer was (log-seconds)."""
    rows = conn.execute(
        "SELECT r.id, r.cid, r.ease, r.time, r.type, "
        "(SELECT MIN(f.id) FROM revlog f WHERE f.cid = r.cid AND f.type < 4) "
        "FROM revlog r WHERE r.id >= ? AND r.type < 4 AND r.time > 0 ORDER BY r.id",
        ((cutoff - 86400) * 1000,),
    ).fetchall()
    out = []
    for rid, cid, ease, ms, rtype, fid in rows:
        day = _day(rid, cutoff)
        kind = _kind(rtype, day, _day(fid or rid, cutoff))
        mu = m.mu.get((kind, 1 if ease == 1 else 0))
        if mu is not None:
            out.append((rid, min(ms / 1000.0, CAP), math.log(ms / 1000.0) - mu - m.card_eff.get(cid, 0.0), cid, kind))
    return out


def _today_residuals(m: Model, conn, cutoff: int) -> list:
    """How much slower (+) or faster (−) than expected each of today's answers was
    (log-seconds), in answer order."""
    return [r for _, _, r, _, _ in _today(m, conn, cutoff)]


# A stalled card took STALL_RATIO x its usual time at your usual pace, and at least
# STALL_MIN seconds — the screen sat there. DRIFTING+ of them among the current
# session's last FOCUS_WINDOW answers was rare (14% of the time) and meant the next
# stretch stalled about 3x as often as after a calm one.
STALL_RATIO, STALL_MIN = 3.0, 25.0
FOCUS_WINDOW, DRIFTING = 20, 4
SESSION_BREAK = 600         # seconds without an answer that start a new session


def focus(m: Model, conn, cutoff: int) -> tuple:
    """(stalled cards, answers counted) among the current session's last FOCUS_WINDOW."""
    session, prev = [], None
    for rid, t, r, _, _ in _today(m, conn, cutoff):
        if prev is not None and (rid - prev) / 1000 > SESSION_BREAK:
            session = []
        session.append((t, r))
        prev = rid
    window = session[-FOCUS_WINDOW:]
    stalled = sum(1 for t, r in window if r - m.level > math.log(STALL_RATIO) and t >= STALL_MIN)
    return stalled, len(window)


def drifting(f: tuple) -> bool:
    return f[1] >= FOCUS_WINDOW and f[0] >= DRIFTING


def paces(m: Model, conn, cutoff: int) -> tuple:
    """(today's possible paces — equally likely log offsets — after seeing today's
    reviews, and the pace of your last RECENT_CARDS answers or None)."""
    res = _today_residuals(m, conn, cutoff)
    recent = res[-RECENT_CARDS:]
    return _pace_nodes(m, res), (sum(recent) / len(recent) if len(recent) >= RECENT_MIN else None)


def pace(m: Model, conn, cutoff: int) -> list:
    """Today's possible paces (log offsets), equally likely, after seeing today's reviews."""
    return _pace_nodes(m, _today_residuals(m, conn, cutoff))


def _pace_nodes(m: Model, res: list) -> list:
    """Today's pace leans on your recent answers: each answer's weight halves every
    RECENT_HALFLIFE answers back, so a speed-up late in the day shows, while a single
    slow card barely moves it. Held-out days ran a little closer than with all of
    today's answers weighted alike, most of all near the end of the day."""
    mean, sd = m.level, m.innov_sd
    if res:
        ws = [0.5 ** ((len(res) - 1 - i) / RECENT_HALFLIFE) for i in range(len(res))]
        n_eff = sum(ws) ** 2 / sum(w * w for w in ws)
        avg = sum(w * r for w, r in zip(ws, res)) / sum(ws)
        w = n_eff / (n_eff + m.sigma ** 2 / sd ** 2)
        mean, sd = mean + w * (avg - mean), sd * math.sqrt(1 - w)
    sd = math.hypot(sd, MIDDAY_DRIFT_SD if res else START_DRIFT_SD)
    return [mean + sd * z for z in _Z]


_mem_cache = {}      # card id -> (its data text, (stability, decay, last review) or None)


def _memory(cid: int, data: str):
    """The card's FSRS memory state from its data, parsed once while it stays the same
    (a due card's data only changes when you answer it)."""
    hit = _mem_cache.get(cid)
    if hit is not None and hit[0] == data:
        return hit[1]
    try:
        d = json.loads(data or "{}")
        mem = (float(d["s"]), float(d.get("decay", 0.5) or 0.5), d.get("lrt"))
    except Exception:
        mem = None
    if len(_mem_cache) > 200_000:
        _mem_cache.clear()
    _mem_cache[cid] = (data, mem)
    return mem


def _retrievability(data: str, last_s, now: float, default: float, cid=None) -> float:
    if cid is not None:
        mem = _memory(cid, data)
        if mem is None:
            return default
        s, decay, lrt = mem
    else:
        try:
            d = json.loads(data or "{}")
            s = float(d["s"])
        except Exception:
            return default
        decay = float(d.get("decay", 0.5) or 0.5)
        lrt = d.get("lrt")
    last = lrt or last_s
    if not last or s <= 0:
        return default
    factor = 0.9 ** (-1 / decay) - 1
    return (1 + factor * max(now - float(last), 0) / 86400 / s) ** (-decay)


class Cost:
    """Mean and variance of some work at each possible pace (vectors over DAY_NODES)."""

    __slots__ = ("mean", "var", "n")

    def __init__(self):
        self.mean = [0.0] * DAY_NODES
        self.var = [0.0] * DAY_NODES
        self.n = 0

    def add(self, other, scale: float = 1.0):
        for k in range(DAY_NODES):
            self.mean[k] += other.mean[k] * scale
            self.var[k] += other.var[k] * scale
        self.n += other.n
        return self

    def total(self) -> float:
        return sum(self.mean) / DAY_NODES

    def quantile(self, q: float) -> float:
        """Quantile of the pace-mixture of normals, by bisection."""
        sds = [math.sqrt(max(v, 1e-9)) for v in self.var]
        lo, hi = 0.0, max(mu + 6 * s for mu, s in zip(self.mean, sds)) + 1.0
        for _ in range(50):
            mid = (lo + hi) / 2
            p = sum(_ND.cdf((mid - mu) / s) for mu, s in zip(self.mean, sds)) / DAY_NODES
            lo, hi = (mid, hi) if p < q else (lo, mid)
        return (lo + hi) / 2


def card_costs(m: Model, conn, today: int, cutoff: int, now: float, ds: list, dids=None) -> dict:
    """{did: (reviews Cost, learning Cost)} for due reviews and cards in learning."""
    where = f" AND c.did IN ({','.join(str(int(d)) for d in dids)})" if dids else ""
    reviews = conn.execute(
        "SELECT c.id, c.did, c.data, (SELECT MAX(id) FROM revlog WHERE cid = c.id) / 1000 "
        "FROM cards c WHERE c.queue = 2 AND c.due <= ?" + where, (today,)).fetchall()
    learning = conn.execute(
        "SELECT c.id, c.did FROM cards c WHERE ((c.queue = 1 AND c.due < ?) "
        "OR (c.queue = 3 AND c.due <= ?))" + where, (cutoff, today)).fetchall()

    scale = [math.exp(d - m.pool_level) for d in ds]
    m0, m1 = m.mu.get(("review", 0), 1.9), m.mu.get(("review", 1), 2.3)
    L1, L2 = m.lapse
    t1, t2, top = m.table1, m.table2, GRID_N - 1
    nodes = list(zip(range(len(ds)), ds, scale))
    out = {}
    for cid, did, data, last in reviews:
        p = 1 - _retrievability(data, last, now, 1 - m.fail_rate, cid)
        q = 1 - p
        b = m.card_eff.get(cid, 0.0)
        c = out.setdefault(did, (Cost(), Cost()))[0]
        c.n += 1
        cm, cv = c.mean, c.var
        for k, d, s in nodes:
            # _table(m, x) for the pass and the fail time, inlined: this runs for every
            # due card at every pace node, on each card you answer.
            f = (m0 + b + d - GRID_LO) / GRID_STEP
            if f <= 0:
                e1p, e2p = t1[0], t2[0]
            elif f >= top:
                e1p, e2p = t1[-1], t2[-1]
            else:
                i = int(f); w = f - i
                e1p, e2p = t1[i] + (t1[i + 1] - t1[i]) * w, t2[i] + (t2[i + 1] - t2[i]) * w
            f = (m1 + b + d - GRID_LO) / GRID_STEP
            if f <= 0:
                e1f, e2f = t1[0], t2[0]
            elif f >= top:
                e1f, e2f = t1[-1], t2[-1]
            else:
                i = int(f); w = f - i
                e1f, e2f = t1[i] + (t1[i + 1] - t1[i]) * w, t2[i] + (t2[i + 1] - t2[i]) * w
            sl = s * L1
            mean = q * e1p + p * (e1f + sl)
            m2 = q * e2p + p * (e2f + 2 * e1f * sl + s * s * L2)
            cm[k] += mean
            cv[k] += max(m2 - mean * mean, 0.0)
    X1, X2 = m.learn
    for cid, did in learning:
        f = math.exp(m.card_eff.get(cid, 0.0))
        c = out.setdefault(did, (Cost(), Cost()))[1]
        c.n += 1
        for k in range(DAY_NODES):
            s = scale[k] * f
            c.mean[k] += s * X1
            c.var[k] += s * s * max(X2 - X1 * X1, 0.0)
    return out


def new_cost(m: Model, top: str, count: int, ds: list) -> Cost:
    X1, X2 = m.new.get(top, m.new_all)
    c = Cost()
    c.n = count
    for k, d in enumerate(ds):
        s = math.exp(d - m.pool_level)
        c.mean[k] = count * s * X1
        c.var[k] = count * s * s * max(X2 - X1 * X1, 0.0)
    return c


def summarize(c: Cost, factor: float = 1.0) -> dict:
    """Seconds: expected, and the 80% range."""
    if c.n == 0:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    return {"mean": c.total() * factor, "lo": max(c.quantile(0.10), 0.0) * factor,
            "hi": c.quantile(0.90) * factor, "n": c.n}


def deck_estimate(m: Model, conn, today: int, cutoff: int, now: float, dids: list,
                  counts: tuple, top: str, ds: list, factor: float = 1.0) -> dict:
    """What's left in one deck (+ subdecks), given the scheduler's (new, learn, review) counts."""
    costs = card_costs(m, conn, today, cutoff, now, ds, dids)
    rev, lrn = Cost(), Cost()
    for r, l in costs.values():
        rev.add(r)
        lrn.add(l)
    new, _learn, review = counts
    if rev.n:
        # Daily limits can hold back some due reviews; cost the ones you'll see.
        k = min(1.0, review / rev.n)
        rev = Cost().add(rev, k)
        rev.n = review
    work = Cost().add(rev).add(lrn)
    newc = new_cost(m, top, new, ds)
    return {"reviews": summarize(work, factor), "new": summarize(newc, factor),
            "all": summarize(Cost().add(work).add(newc), factor)}


# ──────────────────────────────────────────────────────────────
# Correction learned from the backtest (accuracy.calibration)
# ──────────────────────────────────────────────────────────────
Z80 = _ND.inv_cdf(0.9)


def log_sd(mean: float, lo: float, hi: float) -> float:
    """The spread a summarize() range implies, in log-seconds."""
    lo = max(lo, mean * 0.05)
    return max((math.log(max(hi, lo)) - math.log(lo)) / (2 * Z80), 1e-3)


def correction_at(table: list, progress: float, left: float) -> tuple:
    """(time multiplier, low and high z of the 80% range) for this share of the day
    done and this much predicted time left in the whole collection (seconds),
    interpolated from accuracy.calibration's table; no change without one."""
    if not table or left <= 0:
        return 1.0, -Z80, Z80
    x = min(max(progress, table[0][0]), table[-1][0])
    row = table[-1][1:]
    for a, b in zip(table, table[1:]):
        if x <= b[0]:
            w = (x - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            row = [u + (v - u) * w for u, v in zip(a[1:], b[1:])]
            break
    level, slope, z0, smear, z_lo, z_hi, zmin, zmax = row
    z = min(max(math.log(left), zmin), zmax)     # don't extrapolate past the days seen
    return math.exp(level + slope * (z - z0)) * smear, z_lo, z_hi


def corrected(s: dict, progress: float, left: float, table: list) -> dict:
    """A summarize() result after the backtest's correction: scaled by how far off the
    estimate has run at this point in your days and on days this size, with the 80%
    range re-sized to catch the real time on 80% of them. `left` is the whole
    collection's predicted time left, so every deck gets the same correction."""
    if not table or not s["n"] or s["mean"] <= 0:
        return s
    c, z_lo, z_hi = correction_at(table, progress, left)
    sd = log_sd(s["mean"], s["lo"], s["hi"])
    mean = s["mean"] * c
    return dict(s, mean=mean, lo=mean * math.exp(z_lo * sd), hi=mean * math.exp(z_hi * sd))


def done_today(conn, cutoff: int, dids=None) -> float:
    """Seconds Anki recorded on today's answers so far (capped like the model's), in
    every deck or only in these deck ids."""
    sql = "SELECT SUM(MIN(r.time, ?)) FROM revlog r WHERE r.id >= ? AND r.type < 4 AND r.time > 0"
    args = [int(CAP * 1000), (cutoff - 86400) * 1000]
    if dids is not None:
        # Look up each of today's answers' deck. A join walks every card in the decks
        # instead and probes its reviews: ~30 ms on AnKing, not ~0.5.
        sql += f" AND (SELECT c.did FROM cards c WHERE c.id = r.cid) IN ({','.join('?' * len(dids))})"
        args += [int(d) for d in dids]
    v = conn.execute(sql, args).fetchone()[0]
    return (v or 0) / 1000.0
