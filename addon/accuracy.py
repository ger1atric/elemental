"""
How good is the time-left estimate? A backtest on your own recent days.

For each of the last BACKTEST_DAYS days, the model is fit only on reviews from
before that day. Then, at 0%, 10%, … 90% of that day's answers, it predicts the
time the rest took, the way the hover panel would have, and compares.

Per point it reports:
  • bias      mean of (actual − predicted) / predicted   (+ = took longer)
  • miss      median of |actual − predicted| / predicted
  • caught    share of days whose actual time fell in the 80% range

Pure Python and read-only (estimator.connect), so it can run off the main
thread. Fitting a model per day takes about a minute in all; `pause` lets the
caller hold it while you review.

One simplification: the revlog doesn't keep each card's past FSRS recall
probability, so every review is costed at your recent fail rate. The live
estimate uses each card's own, which should do at least as well.
"""

from __future__ import annotations

import math
import statistics
import time

try:
    from . import estimator as E
except ImportError:         # run as a script
    import estimator as E

BACKTEST_DAYS = 60
MIN_ANSWERS = 20            # days lighter than this (or a fifth of your usual day) aren't scored
MIN_DAYS = 10
MIN_LEFT = 60.0             # seconds; points with less left are too noisy to score
FRACS = [i / 10 for i in range(10)]
# Extra checkpoints that only train the correction: you speed up and drop follow-ups
# near the end of a day, which the tenths above can't see.
END_FRACS = [0.85, 0.925, 0.95, 0.975]


def _rest_cost(m, rest, seen, ds):
    """Cost of the answers still to come, built the way card_costs builds it."""
    p = m.fail_rate
    m0, m1 = m.mu.get(("review", 0), 1.9), m.mu.get(("review", 1), 2.3)
    L1, L2 = m.lapse
    X1, X2 = m.learn
    scale = [math.exp(d - m.pool_level) for d in ds]
    work, new, done = E.Cost(), {}, set()
    for a in rest:
        cid = a["cid"]
        if cid in done:
            continue
        done.add(cid)
        kind = "learn" if cid in seen else a["kind"]
        b = m.card_eff.get(cid, 0.0)
        if kind == "review":
            work.n += 1
            for k, d in enumerate(ds):
                e1p, e2p = E._table(m, m0 + b + d)
                e1f, e2f = E._table(m, m1 + b + d)
                s = scale[k]
                mean = (1 - p) * e1p + p * (e1f + s * L1)
                m2 = (1 - p) * e2p + p * (e2f + 2 * e1f * s * L1 + s * s * L2)
                work.mean[k] += mean
                work.var[k] += max(m2 - mean * mean, 0.0)
        elif kind == "new":
            new[a["top"]] = new.get(a["top"], 0) + 1
        else:
            f = math.exp(b)
            work.n += 1
            for k in range(E.DAY_NODES):
                s = scale[k] * f
                work.mean[k] += s * X1
                work.var[k] += s * s * max(X2 - X1 * X1, 0.0)
    for top, n in new.items():
        work.add(E.new_cost(m, top, n, ds))
    return work


def run(path: str, cutoff: int, desk: bool = True, pause=None) -> dict | None:
    """Backtest the days before `cutoff`. None if there aren't enough of them."""
    conn = E.connect(path)
    try:
        tops = {int(d): str(n).split("\x1f")[0] for d, n in conn.execute("SELECT id, name FROM decks")}
        first = dict(conn.execute("SELECT cid, MIN(id) FROM revlog WHERE type < 4 GROUP BY cid"))
        points, dates = [], []
        # A day counts if it's at least a fifth of your usual day (and MIN_ANSWERS):
        # tiny days of a heavy reviewer would only add noise; light reviewers keep theirs.
        counts = [conn.execute("SELECT COUNT(*) FROM revlog WHERE type < 4 AND time > 0 AND id >= ? AND id < ?",
                               ((cutoff - (b + 1) * 86400) * 1000, (cutoff - b * 86400) * 1000)).fetchone()[0]
                  for b in range(1, BACKTEST_DAYS + 1)]
        active = sorted(c for c in counts if c)
        min_answers = max(MIN_ANSWERS, active[len(active) // 2] / 5) if active else MIN_ANSWERS
        for back in range(1, BACKTEST_DAYS + 1):
            while pause and pause():
                time.sleep(5)
            cut = cutoff - back * 86400
            rows = conn.execute(
                "SELECT r.id, r.cid, r.ease, r.time, r.type, c.did FROM revlog r "
                "JOIN cards c ON c.id = r.cid WHERE r.type < 4 AND r.time > 0 "
                "AND r.id >= ? AND r.id < ? ORDER BY r.id", ((cut - 86400) * 1000, cut * 1000)).fetchall()
            if len(rows) < min_answers:
                continue
            m = E._fit(conn, cut)
            if not m.mu:
                continue
            factor = m.wall if desk else 1.0
            ans, prev = [], None
            for rid, cid, ease, ms, rtype, did in rows:
                t = min(ms / 1000, E.CAP)
                gap = (rid - prev) / 1000 if prev else t
                kind = E._kind(rtype, E._day(rid, cut), E._day(first.get(cid, rid), cut))
                mu = m.mu.get((kind, int(ease == 1)))
                ans.append({"cid": cid, "kind": kind, "top": tops.get(did, ""), "t": t,
                            "left": (gap if gap < 180 else t) if desk else t,
                            "res": None if mu is None else math.log(t) - mu - m.card_eff.get(cid, 0.0)})
                prev = rid
            for f in FRACS + END_FRACS:
                n0 = int(f * len(ans))
                done, rest = ans[:n0], ans[n0:]
                actual = sum(a["left"] for a in rest)
                if actual < MIN_LEFT:
                    continue
                ds = E._pace_nodes(m, [a["res"] for a in done if a["res"] is not None])
                s = E.summarize(_rest_cost(m, rest, {a["cid"] for a in done}, ds), factor)
                if s["mean"] > 0:
                    points.append({"day": len(dates), "date": cut - 86400, "f": f,
                                   "pred": s["mean"], "lo": s["lo"],
                                   "hi": s["hi"], "act": actual,
                                   "done": sum(a["t"] for a in done) * factor})
            dates.append(cut - 86400)
            time.sleep(0.05)    # breathe between fits
    finally:
        conn.close()

    if len(dates) < MIN_DAYS:
        return None
    return {"raw": score(points), "fixed": score(points, held_out=True), "days_list": scatter(points),
            "calib": calibration(points), "points": points, "days": len(dates),
            "first": min(dates), "last": max(dates), "desk": desk, "computed": time.time()}


# ──────────────────────────────────────────────────────────────
# The correction: how far off the estimate has run, by share of the day done
# ──────────────────────────────────────────────────────────────
SCATTER = (0.0, 0.5, 0.9)    # points in the day the window's scatterplot shows
BANDWIDTH = 0.05            # share-of-day smoothing; picked by the held-out test
GRID = [i / 20 for i in range(21)]


def _progress(q: dict) -> float:
    """Share of the day's time already done when this prediction was made — what the
    live estimate can also compute (time so far vs. predicted time left)."""
    return q["done"] / (q["done"] + q["pred"])


def _wquantile(vals: list, weights: list, p: float) -> float:
    pairs = sorted(zip(vals, weights))
    target, acc = p * sum(weights), 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def calibration(points: list) -> list:
    """[[progress, level, slope, z0, smear, z low, z high, z min, z max], …] over GRID.
    At each point in the day (kernel-weighted nearby predictions): a line through the
    log of actual/predicted against the log of the predicted time left, since big
    days ran long and small days short; no mean correction (smear 1) for the leftover
    error, so the estimate lands on your typical day rather than your average one,
    which rare long days pull late; and that error's 10th/90th percentile in units of
    each prediction's own spread, so the range catches 80%. z min/max bound the day
    sizes it was fit on."""
    pts = [(_progress(q), math.log(q["pred"]), math.log(q["act"] / q["pred"]),
            E.log_sd(q["pred"], q["lo"], q["hi"])) for q in points]
    table = []
    for x in GRID:
        ws = [math.exp(-0.5 * ((f - x) / BANDWIDTH) ** 2) for f, _, _, _ in pts]
        tot = sum(ws)
        if tot < 5:             # too little nearby to say anything
            continue
        z0 = sum(w * z for w, (_, z, _, _) in zip(ws, pts)) / tot
        y0 = sum(w * y for w, (_, _, y, _) in zip(ws, pts)) / tot
        sxx = sum(w * (z - z0) ** 2 for w, (_, z, _, _) in zip(ws, pts))
        sxy = sum(w * (z - z0) * (y - y0) for w, (_, z, y, _) in zip(ws, pts))
        slope = max(-1.0, min(1.0, sxy / sxx)) if sxx > 0 else 0.0
        res = [y - y0 - slope * (z - z0) for _, z, y, _ in pts]
        smear = 1.0
        zs = [r / sd for r, (_, _, _, sd) in zip(res, pts)]
        sizes = [z for _, z, _, _ in pts]
        table.append([x, y0, slope, z0, smear, _wquantile(zs, ws, 0.1), _wquantile(zs, ws, 0.9),
                      _wquantile(sizes, ws, 0.05), _wquantile(sizes, ws, 0.95)])
    return table


def _wilson(k: int, n: int) -> tuple:
    z = 1.96
    p = k / n
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return mid - half, mid + half


def _pct(vals: list, p: float) -> float:
    v = sorted(vals)
    i = p * (len(v) - 1)
    lo = int(i)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (i - lo)


def _estimates(points: list, held_out: bool, only=None) -> list:
    """[(point, the estimate it gave)]: as predicted, or held_out = corrected with a
    table made from the other days only (what the live correction does for today)."""
    tables, out = {}, []
    for q in points:
        if only is not None and q["f"] not in only:
            continue
        s = {"mean": q["pred"], "lo": q["lo"], "hi": q["hi"], "n": 1}
        if held_out:
            d = q["day"]
            if d not in tables:
                tables[d] = calibration([p for p in points if p["day"] != d])
            s = E.corrected(s, _progress(q), q["pred"], tables[d])
        out.append((q, s))
    return out


def scatter(points: list) -> dict:
    """{share done: [[date, estimate min, actual min, inside the range], …]} for the
    points the window plots, with the correction applied as for today."""
    out = {}
    for q, s in _estimates(points, True, SCATTER):
        out.setdefault(str(q["f"]), []).append(
            [q.get("date", 0), s["mean"] / 60, q["act"] / 60, s["lo"] <= q["act"] <= s["hi"]])
    return out


def score(points: list, held_out: bool = False) -> list:
    """Per share of the day done: bias (with its 95% CI and the middle 80% of days),
    typical miss, how often the 80% range caught the real time (with a 95% CI), and
    the misses in minutes.
    held_out scores the corrected estimate, each day corrected only from the others."""
    est = _estimates(points, held_out)
    rows = []
    for f in FRACS:
        err, mins, left, hit = [], [], [], []
        for q, s in est:
            if q["f"] != f:
                continue
            err.append((q["act"] - s["mean"]) / s["mean"])
            mins.append((q["act"] - s["mean"]) / 60)
            left.append(q["act"] / 60)
            hit.append(s["lo"] <= q["act"] <= s["hi"])
        n = len(err)
        if n < MIN_DAYS:
            continue
        mean = statistics.mean(err)
        se = statistics.stdev(err) / math.sqrt(n)
        rows.append({"f": f, "n": n, "bias": mean, "bias_ci": [mean - 1.96 * se, mean + 1.96 * se],
                     "band": [_pct(err, 0.1), _pct(err, 0.9)],
                     "miss": statistics.median(abs(e) for e in err),
                     "caught": sum(hit) / n, "caught_ci": list(_wilson(sum(hit), n)),
                     # the same, in minutes (+ = took longer)
                     "left": statistics.median(left), "avg_min": statistics.mean(mins),
                     "miss_min": statistics.median(abs(e) for e in mins),
                     "spread_min": [_pct(mins, 0.1), _pct(mins, 0.9)],
                     "early": sum(e < 0 for e in mins) / n})
    return rows


# ──────────────────────────────────────────────────────────────
# The window's page — glass panels like the Interactive Heatmap's, over the
# Custom Background photo when there is one
# ──────────────────────────────────────────────────────────────
W, H = 300, 176                  # chart size (viewBox)
PL, PR, PT, PB = 50, 10, 10, 26  # plot padding
_WHEN = {0.0: "Start", 0.5: "Halfway", 0.9: "Near the end"}


def _mins(v: float) -> str:
    v = round(v)
    if v < 60:
        return f"{v} min"
    return f"{v // 60}h" if v % 60 == 0 else f"{v // 60}h {v % 60:02d}m"


def _early_late(v: float) -> str:
    """'12 min late' / '5 min early' / 'on time'."""
    if round(abs(v)) == 0:
        return "on time"
    return f"{_mins(abs(v))} {'late' if v > 0 else 'early'}"


def _frame(lo, hi, ticks, fmt, ink) -> tuple:
    """Gridlines, y labels, x labels; returns (svg parts, x(), y(), bar width)."""
    pw, ph = W - PL - PR, H - PT - PB
    step = pw / len(FRACS)
    x = lambda f: PL + (round(f * 10) + 0.5) * step
    y = lambda v: PT + (hi - max(lo, min(hi, v))) / (hi - lo) * ph
    g = []
    for t in ticks:
        g.append(f'<line x1="{PL}" x2="{W - PR}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                 f'<text x="{PL - 6}" y="{y(t) + 3.5:.1f}" text-anchor="end" class="tk">{fmt(t)}</text>')
    for f, name in _WHEN.items():
        anchor = "start" if f == 0 else "end" if f == 0.9 else "middle"
        dx = -step / 2 + 2 if f == 0 else step / 2 - 2 if f == 0.9 else 0
        g.append(f'<text x="{x(f) + dx:.1f}" y="{H - 8}" text-anchor="{anchor}" class="tk">{name}</text>')
    return g, x, y, step * 0.56


def _minutes_chart(rows, raw, ink, accent) -> str:
    """Where most days finished vs. the estimate (bars) and the average (dots)."""
    worst = max(max(abs(r["spread_min"][0]), abs(r["spread_min"][1])) for r in rows)
    step = 10 if worst <= 30 else 20 if worst <= 60 else 30
    top = max(step, math.ceil(worst / step) * step)
    ticks = list(range(-top, top + 1, step))
    g, x, y, bw = _frame(-top, top, ticks,
                         lambda t: "on time" if t == 0 else f"{abs(t)} {'late' if t > 0 else 'early'}", ink)
    g.append(f'<line x1="{PL}" x2="{W - PR}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="ref"/>')
    before = {r["f"]: r for r in raw}
    for r in rows:
        cx, (a, b) = x(r["f"]), r["spread_min"]
        when = _WHEN.get(r["f"], f"{r['f']:.0%} of the way through")
        b4 = before.get(r["f"])
        tip = (f"<b>{when}</b> · about {_mins(r['left'])} left<br>"
               f"Most days finished between {_early_late(a)} and {_early_late(b)}<br>"
               f"On average: {_early_late(r['avg_min'])}"
               + (f"<br>Before the correction: {_early_late(b4['avg_min'])} on average" if b4 else ""))
        g.append(f'<rect x="{cx - bw / 2:.1f}" y="{y(b):.1f}" width="{bw:.1f}" height="{max(y(a) - y(b), 2):.1f}" '
                 f'rx="4" fill="{accent}" fill-opacity=".32" stroke="{accent}" stroke-opacity=".55"/>'
                 f'<circle cx="{cx:.1f}" cy="{y(r["avg_min"]):.1f}" r="3.6" fill="{accent}" '
                 f'stroke="{ink["ring"]}" stroke-width="1.5"/>'
                 f'<rect x="{cx - bw:.1f}" y="{PT}" width="{bw * 2:.1f}" height="{H - PT - PB}" '
                 f'fill="transparent" data-tip="{tip}"/>')
    return f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">{"".join(g)}</svg>'


SW, SH = 300, 190                    # scatterplot size (viewBox)
SL, SR, ST, SB = 50, 14, 8, 30


def _scatter_svg(pts: list, when: str, ink: dict, accent: str) -> str:
    """One dot per day: the estimate at this point in the day vs. what it took."""
    top = max(max(p[1] for p in pts), max(p[2] for p in pts)) * 1.05
    step = next((s for s in (5, 10, 15, 30, 60, 120, 180) if top / s <= 4), 240)
    top = math.ceil(top / step) * step
    pw, ph = SW - SL - SR, SH - ST - SB
    x = lambda v: SL + v / top * pw
    y = lambda v: ST + (1 - v / top) * ph
    g = []
    for t in range(0, int(top) + 1, step):
        g.append(f'<line x1="{SL}" x2="{SW - SR}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                 f'<text x="{SL - 6}" y="{y(t) + 3.5:.1f}" text-anchor="end" class="tk">{_mins(t) if t else "0"}</text>'
                 f'<text x="{x(t):.1f}" y="{SH - SB + 14}" text-anchor="middle" class="tk">{_mins(t) if t else "0"}</text>')
    g.append(f'<text x="{SL + pw / 2:.1f}" y="{SH - 2}" text-anchor="middle" class="tk">Estimate</text>'
             f'<text x="8" y="{ST + ph / 2:.1f}" text-anchor="middle" class="tk" '
             f'transform="rotate(-90 8 {ST + ph / 2:.1f})">What it took</text>'
             f'<line x1="{x(0):.1f}" y1="{y(0):.1f}" x2="{x(top):.1f}" y2="{y(top):.1f}" class="ref"/>'
             f'<text x="{SL + 8}" y="{ST + 14}" class="tk">took longer ↑</text>'
             f'<text x="{SW - SR - 8}" y="{SH - SB - 8}" text-anchor="end" class="tk">↓ finished early</text>')
    for date, est, act, inside in sorted(pts, key=lambda p: p[0]):
        lt = time.localtime(date)
        day = f'{time.strftime("%a, %b", lt)} {lt.tm_mday}' if date else "A day"
        tip = (f"<b>{day}</b> · {when}<br>Estimate {_mins(est)}, took {_mins(act)}<br>"
               f"{_early_late(act - est).capitalize()}, "
               f"{'inside' if inside else 'outside'} the range shown")
        fill = f'fill="{accent}"' if inside else f'fill="{ink["ring"]}" fill-opacity=".35"'
        g.append(f'<circle cx="{x(est):.1f}" cy="{y(act):.1f}" r="4" {fill} stroke="{accent}" stroke-width="1.5"/>'
                 f'<circle cx="{x(est):.1f}" cy="{y(act):.1f}" r="9" fill="transparent" data-tip="{tip}"/>')
    return f'<svg viewBox="0 0 {SW} {SH}" width="100%" role="img">{"".join(g)}</svg>'


_TIP_JS = """
var tip = document.getElementById('tip');
document.addEventListener('mousemove', function (e) {
  var t = e.target.getAttribute && e.target.getAttribute('data-tip');
  if (!t) { tip.style.display = 'none'; return; }
  tip.innerHTML = t; tip.style.display = 'block';
  var w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(e.clientX + 12, innerWidth - w - 8) + 'px';
  tip.style.top = Math.max(8, e.clientY - h - 12) + 'px';
});
document.querySelectorAll('.seg button').forEach(function (b) {
  b.onclick = function () {
    document.querySelectorAll('.seg button').forEach(function (o) { o.classList.toggle('on', o === b); });
    document.querySelectorAll('.sc').forEach(function (s) { s.style.display = s.id === b.dataset.f ? '' : 'none'; });
  };
});
"""


def _scatter_panel(days: dict, ink: dict, accent: str) -> str:
    shown = [(f, name) for f, name in _WHEN.items() if days.get(str(f))]
    if not shown:
        return ""
    short = {"Near the end": "End"}
    seg = "".join(f'<button data-f="sc{i}" class="{"on" if i == 0 else ""}">{short.get(name, name)}</button>'
                  for i, (_, name) in enumerate(shown))
    charts = "".join(f'<div class="sc" id="sc{i}" style="{"" if i == 0 else "display:none"}">'
                     f'{_scatter_svg(days[str(f)], name.lower(), ink, accent)}</div>'
                     for i, (f, name) in enumerate(shown))
    key = (f'<span><svg width="10" height="10"><circle cx="5" cy="5" r="3.6" fill="{accent}" stroke="{accent}"/>'
           f'</svg>Finished inside the range</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="3.6" '
           f'fill="none" stroke="{accent}" stroke-width="1.5"/></svg>Outside it</span>')
    return (f'<div class="glass"><div class="head"><div class="title">Estimate vs. what it took</div>'
            f'<div class="seg">{seg}</div></div><div class="how">One dot per day, estimated at the point you '
            f'pick. On the dashed line = spot on.</div>{charts}<div class="key">{key}</div></div>')


def page(res: dict | None, night: bool, accent: str, status: str = "",
         backdrop: dict | None = None, glass: float = 0.45) -> str:
    """The window's HTML. backdrop = {"url", "opacity", "size", "position"} of the
    Custom Background photo; glass = the heatmap's glass_opacity."""
    lo_glass = max(0.0, glass - 0.2)
    if night:
        ink = {"fg": "rgba(255,255,255,.92)", "sub": "rgba(255,255,255,.58)", "ring": "#1c1c1c",
               "base": "#1f1f1f", "line": "255,255,255", "fgs": "#ffffff"}
        panel = (f"background:linear-gradient(135deg,rgba(30,30,30,{glass}) 0%,rgba(10,10,10,{lo_glass}) 100%);"
                 "border:1px solid rgba(255,255,255,.08);"
                 "box-shadow:0 8px 32px 0 rgba(0,0,0,.4),inset 0 0 0 1px rgba(255,255,255,.02);")
    else:
        ink = {"fg": "#1d2733", "sub": "rgba(29,39,51,.62)", "ring": "#ffffff", "base": "#ffffff",
               "line": "29,39,51", "fgs": "#1d2733"}
        panel = (f"background:linear-gradient(135deg,rgba(255,255,255,{glass}) 0%,"
                 f"rgba(255,255,255,{lo_glass}) 100%);border:1px solid rgba(255,255,255,.18);"
                 "box-shadow:0 8px 32px 0 rgba(0,0,0,.1),inset 0 0 0 1px rgba(255,255,255,.05);")
    photo = ""
    if backdrop:
        photo = (f'body::before{{content:"";position:fixed;inset:0;z-index:-1;'
                 f'background:url("{backdrop["url"]}") {backdrop.get("position", "center")}/'
                 f'{backdrop.get("size", "cover")} no-repeat;opacity:{backdrop.get("opacity", 1)}}}')
    css = (f"html,body{{margin:0;min-height:100%}}body{{padding:16px 18px;background:{ink['base']};color:{ink['fg']};"
           "font:13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
           "-webkit-font-smoothing:antialiased;box-sizing:border-box}" + photo +
           f".glass{{{panel}border-radius:16px;padding:12px 14px;"
           "backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}"
           ".stats{display:grid;grid-template-columns:repeat(3,1fr);margin-bottom:12px;padding:12px 4px}"
           f".stat{{padding:0 14px}}.stat+.stat{{border-left:1px solid rgba({ink['line']},.12)}}"
           f".cap{{font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:{ink['sub']}}}"
           ".big{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:3px}"
           f".was{{font-size:11px;color:{ink['sub']}}}"
           ".charts{display:grid;grid-template-columns:1fr 1fr;gap:12px}"
           ".title{font-size:13px;font-weight:600;margin:0 0 2px 2px}"
           f".how{{font-size:11px;color:{ink['sub']};margin:0 0 6px 2px;min-height:30px}}"
           f".tk{{fill:{ink['sub']};font-size:9.5px;font-weight:600}}"
           f".grid{{stroke:rgba({ink['line']},.10);stroke-width:1}}"
           f".ref{{stroke:rgba({ink['line']},.5);stroke-width:1;stroke-dasharray:3 3}}"
           f".key{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:10.5px;color:{ink['sub']};margin:4px 2px 0}}"
           ".key span{display:inline-flex;align-items:center;gap:6px}"
           f".foot{{display:table;margin:10px auto 0;padding:5px 14px;border-radius:12px;font-size:10.5px;"
           f"color:{ink['sub']}}}"
           f".empty{{text-align:center;color:{ink['sub']};padding:56px 0}}"
           ".head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:2px}"
           ".head .title{margin:0 0 0 2px}"
           ".seg{display:flex;gap:3px;flex:none}"
           f".seg button{{all:unset;cursor:pointer;font-size:9px;font-weight:700;letter-spacing:.5px;"
           f"text-transform:uppercase;padding:4px 9px;border-radius:8px;color:{ink['sub']}}}"
           f".seg button.on{{background:{accent};color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.2)}}"
           "#tip{position:fixed;display:none;background:rgba(0,0,0,.92);color:#fff;padding:7px 10px;"
           "border-radius:6px;font-size:10.5px;line-height:1.45;pointer-events:none;z-index:9;"
           "box-shadow:0 4px 10px rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);max-width:250px}")
    head = (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content=width=device-width>"
            f"<style>{css}</style></head><body>")
    if not res or not res.get("fixed") or "miss_min" not in res["fixed"][0]:
        msg = status or "Not enough review history yet."
        return head + f'<div class="glass empty">{msg}</div></body></html>'

    rows, raw = res["fixed"], res.get("raw") or []
    mid = min(rows, key=lambda r: abs(r["f"] - 0.5))
    lean = mid["avg_min"]
    stats = "".join(
        f'<div class="stat"><div class="cap">{cap}</div><div class="big">{val}</div>'
        f'<div class="was">{sub}</div></div>' for cap, val, sub in (
            ("Usually off by", _mins(mid["miss_min"]),
             f"at the halfway point (~{_mins(mid['left'])} left)"),
            ("Finish inside the range", f"{mid['caught'] * 10:.0f} in 10 days", "the goal is 8 in 10"),
            ("Early or late?", "On time" if abs(lean) < 2 else _early_late(lean).capitalize(),
             "on average, at the halfway point"),
        ))
    key1 = (f'<span><svg width="12" height="12"><rect width="12" height="12" rx="3" fill="{accent}" '
            f'fill-opacity=".32" stroke="{accent}" stroke-opacity=".55"/></svg>Where most days finished</span>'
            f'<span><svg width="10" height="10"><circle cx="5" cy="5" r="3.6" fill="{accent}"/></svg>Average</span>')
    lt = time.localtime(res["computed"])
    when = (f'{time.strftime("%b", lt)} {lt.tm_mday}, {lt.tm_hour % 12 or 12}:{lt.tm_min:02d} '
            f'{"AM" if lt.tm_hour < 12 else "PM"}')
    foot = f'Based on your last {res["days"]} days · updated {when}' + (f" · {status}" if status else "")
    body = (f'<div class="glass stats">{stats}</div><div class="charts">'
            f'<div class="glass"><div class="title">How early or late you finished</div>'
            f'<div class="how">Compared with the estimate at each point in the day. '
            f'Bars closer to “on time” are better.</div>{_minutes_chart(rows, raw, ink, accent)}'
            f'<div class="key">{key1}</div></div>'
            f'{_scatter_panel(res.get("days_list") or {}, ink, accent)}</div>'
            f'<div class="glass foot">{foot}</div><div id="tip"></div><script>{_TIP_JS}</script>')
    return head + body + "</body></html>"
