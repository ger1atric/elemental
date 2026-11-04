"""
Small animations on the deck list:

- the 30-day graph's lines draw on, left to right, each time you come back to the deck list
  from another screen (not when it's just redrawn in place);
- when you finish the day (nothing left to study, some cards done), today's heatmap cell
  blooms once and the Done for today chip (time_left) rises in;
- deck counts that went down since the last deck list tick down to their new value;
- the first deck list after you've reviewed today, the streak in the stats bar rolls up
  from yesterday's number to today's, once a day, and on a milestone (every 5, 10, 25, 50,
  100, 365 or 500 days, the biggest that fits) something more plays: at 50 and 100 the streak's
  days on the heatmap light up first (and at 100 confetti bursts from the heatmap's border); at a
  year and 500 the heatmap puts on a light show (chevrons and diamond bursts) that ends in a
  border flash and confetti. These wait for a sign
  you're looking (the mouse moving, a key) and only count as played once they have. On a
  milestone day the number stays gold with a flame, and clicking it plays the milestone again.

They wait until the page is on screen and settled (Anki can take a moment between screens,
and a page drawn behind another is never seen), then start together. The bloom plays once a day: the page reports back when it's started,
and only then is it marked played (user_files/moments.json), so a page nobody saw doesn't
use it up. Once they've run, the page settles (html.hm-done), so a later in-place redraw of
the heatmap doesn't play them again. The animations
setting: "system" plays them unless the computer asks for reduced motion, "on" always,
"off" never.
"""

from __future__ import annotations

import json
import os

from .icons import icon

_STATE = os.path.join(os.path.dirname(__file__), "user_files", "moments.json")
_state = None
_back_home = True       # the next deck list is a return from another screen (or the first)


def came_home() -> None:
    global _back_home
    _back_home = True


def _load() -> dict:
    global _state
    if _state is None:
        try:
            with open(_STATE, encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            _state = {}
    return _state


def played(key: str, day: str) -> bool:
    return _load().get(key) == day


def mark(key: str, day: str) -> None:
    st = _load()
    if st.get(key) == day:
        return
    st[key] = day
    try:
        os.makedirs(os.path.dirname(_STATE), exist_ok=True)
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


# Until the page starts them (html.hm-go), the pieces that are about to animate sit at their
# first frame, so nothing shows in full and then jumps back.
_DRAW = """
@keyframes hmDraw { from { stroke-dashoffset: 1 } to { stroke-dashoffset: 0 } }
@keyframes hmFade { from { opacity: 0 } to { opacity: 1 } }
#heatmap-graph-container .hm-line { stroke-dasharray: 1; stroke-dashoffset: 1 }
#heatmap-graph-container .hm-fill { opacity: 0 }
.hm-go #heatmap-graph-container .hm-line { animation: hmDraw .9s cubic-bezier(.3,.6,.25,1) both }
.hm-go #heatmap-graph-container .hm-fill { animation: hmFade .9s ease-out both }
.hm-done #heatmap-graph-container .hm-line { animation: none; stroke-dasharray: none; stroke-dashoffset: 0 }
.hm-done #heatmap-graph-container .hm-fill { animation: none; opacity: 1 }
"""

_DONE = """
@keyframes hmBloom {
  0% { transform: scale(1); box-shadow: 0 0 0 0 COLOR }
  45% { transform: scale(1.45); box-shadow: 0 0 0 5px transparent }
  100% { transform: scale(1); box-shadow: 0 0 0 0 transparent }
}
@keyframes hmRise { from { opacity: 0; transform: translateY(4px) } to { opacity: 1; transform: none } }
#rt-today { opacity: 0 }
.hm-go #hm-today { animation: hmBloom .9s cubic-bezier(.2,.7,.3,1) .1s both; position: relative; z-index: 1 }
.hm-go #rt-today { animation: hmRise .45s ease-out .5s both }
.hm-done #hm-today { animation: none }
.hm-done #rt-today { animation: none; opacity: 1 }
"""

# ── Streak milestones ─────────────────────────────────────────────────────────
# The biggest tier the streak is a multiple of: a year beats 500, 500 beats 100, and so on.
TIERS = (("year", 365), ("500", 500), ("100", 100), ("50", 50), ("25", 25), ("10", 10), ("5", 5))


def milestone(n: int):
    """The tier name for an n-day streak, or None."""
    for name, k in TIERS:
        if n > 0 and n % k == 0:
            return name
    return None


def milestone_label(n: int) -> str:
    """How a milestone is said in a reminder or the heatmap's tooltip."""
    if n % 365 == 0:
        y = n // 365
        return f"{y}-year streak" if y > 1 else "1-year streak"
    return f"{n}-day streak"


# Gold that stays for the day on a milestone, readable on light and dark.
_STREAK_CSS = """
#hm-streak.hm-gold { color: #c48f17 !important }
.night_mode #hm-streak.hm-gold, .nightMode #hm-streak.hm-gold { color: #f0c35a !important }
.hm-streak-lbl { position: relative }
.hm-streak-flame { position: absolute; right: 100%; top: 50%; transform: translateY(-50%); margin-right: 3px;
  display: inline-flex; color: #d9a52c }
#hm-streak { position: relative }
"""

# The streak's script. The roll (yesterday's number above today's in a one-line window) is
# set up before the page first shows, only when it will move. It and the milestone play on
# the first sign you're looking; until then nothing moves, and after two minutes without one
# it settles where it ends, unplayed, so the next deck list tries again. Effects draw in an
# overlay laid over the number, so they sit on it wherever the page puts it.
_STREAK_JS = """<script>(function(){
  var S = CONF, FLAME = FLAME_SVG;
  var still = function () { return !!(window.hmStill && window.hmStill()); };
  var el, inner, h, busy = false, NS = 'http://www.w3.org/2000/svg';
  function tween(ms, f, done) {
    var t0 = null;
    function step(t) { if (t0 === null) t0 = t; var p = Math.min(1, (t - t0) / ms); f(p); if (p < 1) requestAnimationFrame(step); else if (done) done(); }
    requestAnimationFrame(step);
  }
  var ease = function (p) { return 1 - Math.pow(1 - p, 3); };
  function overlay() {
    var r = el.getBoundingClientRect(), d = document.createElement('div');
    d.style.cssText = 'position:absolute;pointer-events:none;z-index:60;left:' + (r.left + scrollX) + 'px;top:' +
      (r.top + scrollY) + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
    d.innerHTML = '<svg width="100%" height="100%" style="overflow:visible;display:block"></svg>';
    document.body.appendChild(d);
    return { svg: d.firstChild, w: r.width, h: r.height, done: function () { d.remove(); } };
  }
  function ring(o, col, scale) {
    var c = document.createElementNS(NS, 'rect'), w0 = o.w + 26 * (scale || 1), h0 = o.h + 14 * (scale || 1);
    c.setAttribute('fill', 'none'); c.setAttribute('stroke', col); c.setAttribute('stroke-width', '1.5'); c.setAttribute('rx', '10');
    o.svg.appendChild(c);
    tween(950, function (p) {
      var e = ease(p), w = w0 * (0.8 + 0.6 * e), hh = h0 * (0.8 + 0.6 * e);
      c.setAttribute('x', o.w / 2 - w / 2); c.setAttribute('y', o.h / 2 - hh / 2);
      c.setAttribute('width', w); c.setAttribute('height', hh); c.setAttribute('opacity', (0.9 * (1 - p)).toFixed(3));
    }, function () { c.remove(); });
  }
  function sparks(o, n, spread, col, dist) {
    for (var i = 0; i < n; i++) (function (i) {
      var d = document.createElementNS(NS, 'circle');
      d.setAttribute('r', (1.2 + Math.random() * 1.4).toFixed(1)); d.setAttribute('fill', col); d.setAttribute('opacity', 0);
      o.svg.appendChild(d);
      var ang = -Math.PI / 2 + (Math.random() - 0.5) * spread, len = dist * (0.7 + 0.6 * Math.random()),
          x0 = o.w / 2 + (Math.random() - 0.5) * o.w * 0.6, y0 = o.h / 2 - 4;
      setTimeout(function () {
        tween(900 + Math.random() * 400, function (p) {
          var e = ease(p);
          d.setAttribute('cx', x0 + Math.cos(ang) * len * e); d.setAttribute('cy', y0 + Math.sin(ang) * len * e);
          d.setAttribute('opacity', (1 - p).toFixed(3));
        }, function () { d.remove(); });
      }, i * 40);
    })(i);
  }
  function rgbOf(c) { var m = c.match(/[\\d.]+/g); return m ? m.slice(0, 3).map(Number) : [0, 0, 0]; }
  function alphaOf(c) { var m = c.match(/[\\d.]+/g); return m && m.length > 3 ? +m[3] : (c === 'transparent' ? 0 : 1); }
  function mix(a, b, t) { return a.map(function (v, i) { return Math.round(v + (b[i] - v) * t); }); }
  function flare(ms) {
    var base = rgbOf(getComputedStyle(el).color), gold = [244, 200, 90];
    tween(ms, function (p) {
      var a = p < 0.2 ? p / 0.2 : Math.max(0, 1 - (p - 0.2) / 0.8);
      el.style.textShadow = '0 0 ' + (10 * a) + 'px rgba(244,200,90,' + (0.55 * a) + ')';
      el.style.setProperty('color', 'rgb(' + mix(base, gold, a).join(',') + ')', 'important');
    }, function () { el.style.textShadow = ''; el.style.removeProperty('color'); });
  }
  // The streak's days dim, then light back up one by one in date order, each with a brief
  // glow as it comes on, ending on today. Their colors are read as it starts (never mid-way:
  // a replay waits for the last one to finish, busy) and put back after.
  var DIM = 220, EACH = 300;
  function streakCells() {
    var cells = [].slice.call(document.querySelectorAll('#heatmap-root .cell')), i = cells.indexOf(document.getElementById('hm-today'));
    return i < 0 ? [] : cells.slice(Math.max(0, i - S.to + 1), i + 1).map(function (c) {
      return { c: c, css: c.style.background, rgb: rgbOf(getComputedStyle(c).backgroundColor) };
    });
  }
  function sweep(glow, span) {
    var r = streakCells(), n = r.length;
    if (!n) return 0;
    var dark = [22, 26, 20];
    r.forEach(function (x) { x.dim = mix(x.rgb, dark, 0.8); x.peak = mix(x.rgb, glow, 0.5); });
    tween(DIM, function (p) { r.forEach(function (x) { x.c.style.background = 'rgb(' + mix(x.rgb, x.dim, p).join(',') + ')'; }); }, function () {
      tween(span, function (p) {
        var t = p * span;
        r.forEach(function (x, j) {
          var q = Math.max(0, Math.min(1, (t - j / n * (span - EACH)) / EACH)), col;
          col = q < 0.45 ? mix(x.dim, x.peak, ease(q / 0.45)) : mix(x.peak, x.rgb, (q - 0.45) / 0.55);
          x.c.style.background = 'rgb(' + col.join(',') + ')';
        });
      }, function () { r.forEach(function (x) { x.c.style.background = x.css; }); });
    });
    return DIM + span;
  }
  // ── The heatmap box: confetti from its glass border, and the light show ──────────────
  function hudBox() {
    var hud = document.querySelector('#heatmap-root .hud');
    if (!hud) return null;
    var r = hud.getBoundingClientRect(), d = document.createElement('div');
    d.style.cssText = 'position:absolute;pointer-events:none;z-index:60;left:' + (r.left + scrollX) + 'px;top:' +
      (r.top + scrollY) + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
    d.innerHTML = '<svg width="100%" height="100%" style="overflow:visible;display:block"></svg>';
    document.body.appendChild(d);
    return { hud: hud, svg: d.firstChild, w: r.width, h: r.height, rx: parseFloat(getComputedStyle(hud).borderTopLeftRadius) || 14,
             done: function () { d.remove(); } };
  }
  // pieces burst out from all around the border, tumble and fall, fading out
  function confetti(n) {
    var b = hudBox();
    if (!b) return;
    var COLS = ['#f4c85a', '#a6d84a', '#d6ecaa', '#ffffff', '#6aa318', '#f0a85a'], per = 2 * (b.w + b.h), left = n;
    for (var i = 0; i < n; i++) (function () {
      var d = Math.random() * per, x, y, nx, ny;
      if (d < b.w) { x = d; y = 0; nx = 0; ny = -1; }
      else if (d < b.w + b.h) { x = b.w; y = d - b.w; nx = 1; ny = 0; }
      else if (d < 2 * b.w + b.h) { x = b.w - (d - b.w - b.h); y = b.h; nx = 0; ny = 1; }
      else { x = 0; y = b.h - (d - 2 * b.w - b.h); nx = -1; ny = 0; }
      var p = document.createElementNS(NS, 'rect');
      p.setAttribute('width', 3 + Math.random() * 3); p.setAttribute('height', 5 + Math.random() * 5); p.setAttribute('rx', 1);
      p.setAttribute('fill', COLS[Math.floor(Math.random() * COLS.length)]);
      b.svg.appendChild(p);
      var sp = 90 + Math.random() * 120, vx = nx * sp + (Math.random() - 0.5) * 80, vy = ny * sp - 60 - Math.random() * 90,
          spin = (Math.random() - 0.5) * 900, life = 1600 + Math.random() * 900;
      setTimeout(function () {
        tween(life, function (q) {
          var t = q * life / 1000;
          p.setAttribute('transform', 'translate(' + (x + vx * t) + ',' + (y + vy * t + 260 * t * t) + ') rotate(' + (spin * t) + ')');
          p.setAttribute('opacity', (q < 0.75 ? 1 : 1 - (q - 0.75) / 0.25).toFixed(2));
        }, function () { p.remove(); if (--left === 0) b.done(); });
      }, Math.random() * 180);
    })();
  }
  // the border glows gold out and in (the 100-day glow is softer than the light show's finale)
  function borderFlash(b, ms, strength) {
    var hud = b.hud, sh = hud.style.boxShadow, bc = hud.style.borderColor;
    var e = document.createElementNS(NS, 'rect');
    e.setAttribute('x', 0.5); e.setAttribute('y', 0.5); e.setAttribute('width', b.w - 1); e.setAttribute('height', b.h - 1);
    e.setAttribute('rx', b.rx); e.setAttribute('fill', 'none'); e.setAttribute('stroke', '#f4c85a'); e.setAttribute('stroke-width', 2.5);
    b.svg.appendChild(e);
    tween(ms, function (q) {
      var a = (q < 0.3 ? q / 0.3 : Math.max(0, 1 - (q - 0.3) / 0.7)) * strength;
      e.setAttribute('opacity', a.toFixed(3));
      hud.style.boxShadow = '0 0 ' + (34 * a) + 'px ' + (4 * a) + 'px rgba(244,200,90,' + (0.45 * a).toFixed(3) + '), inset 0 0 ' +
        (22 * a) + 'px rgba(244,200,90,' + (0.18 * a).toFixed(3) + ')';
    }, function () { e.remove(); hud.style.boxShadow = sh; hud.style.borderColor = bc; });
  }
  // 1 year / 500: the light show. The heatmap dims (house lights down) while a light runs round
  // its border. Mirror-image gold chevrons, > from the left and < from the right, fly in and
  // straight through each other; each time a pair crosses in the middle, a diamond bursts
  // there. 500 adds an encore: mirrored diamond bursts working in from both edges, and five
  // explosions of mixed sizes, one at a time, each in its own part of the heatmap. A big
  // diamond from the middle closes it, then the finale: the whole border flashes gold, the
  // squares take one gold breath, and confetti bursts out. Returns ms until the finale (when
  // the number rolls). Everything is mirrored about the middle, so nothing drifts to one side.
  var FIN = 1100, EXPLODE = [[0.62, 1, 1.0], [0.18, 5, 0.7], [0.84, 4, 1.3], [0.33, 1, 1.1], [0.70, 5, 0.8]];
  function lightShow() {
    var big2 = S.tier === '500', b = hudBox();
    var cells = [].slice.call(document.querySelectorAll('#heatmap-root .cell')), ti = cells.indexOf(document.getElementById('hm-today'));
    if (!b || ti < 0) { if (b) b.done(); return 0; }
    var W = Math.ceil(cells.length / 7), MC = (W - 1) / 2, MR = 3, K = 1.15, GOLD = [244, 200, 90], WHITE = [255, 248, 226], DARK = [16, 19, 14];
    var base = cells.map(function (c) { var bg = getComputedStyle(c).backgroundColor; return { css: c.style.background, rgb: rgbOf(bg), a: alphaOf(bg) }; });
    // dim: how far the squares are dimmed; v: gold; fl: white on top (crossings, burst centres)
    function paint(c, k, v, fl, dim) {
      var x = base[k];
      if (v <= 0.002 && fl <= 0.002 && dim <= 0.002) { c.style.background = x.css; return; }
      var col = mix(x.a < 0.05 ? x.rgb : mix(x.rgb, DARK, dim), GOLD, Math.min(1, v));
      if (fl > 0) col = mix(col, WHITE, Math.min(1, fl));
      c.style.background = 'rgba(' + col.join(',') + ',' + (x.a + (1 - x.a) * Math.min(1, v + fl) * 0.6).toFixed(3) + ')';
    }
    function band(x, w) { x = Math.abs(x); return x < w ? Math.pow(Math.cos(Math.PI / 2 * x / w), 2) : 0; }
    var PAIRS = big2 ? 5 : 3, EVERY = 170, TRAVEL = 850, SPAN = W - 1 + 8, chevEnd = (PAIRS - 1) * EVERY + TRAVEL, bursts = [], i;
    for (i = 0; i < PAIRS; i++) bursts.push({ c: MC, r: MR, t: i * EVERY + TRAVEL * 0.5, sp: 0.03, life: 620, w: 1.3, amp: 0.85 });
    var t2 = chevEnd - 150;
    if (big2) {
      [[0.08, 2], [0.24, 4], [0.38, 3]].forEach(function (m, j) {
        bursts.push({ c: m[0] * (W - 1), r: m[1], t: t2 + j * 300, sp: 0.03, life: 600, w: 1.3, amp: 1 });
        bursts.push({ c: (1 - m[0]) * (W - 1), r: m[1], t: t2 + j * 300, sp: 0.03, life: 600, w: 1.3, amp: 1 });
      });
      EXPLODE.forEach(function (z, m) {
        bursts.push({ c: z[0] * (W - 1), r: z[1], t: t2 + 130 + m * 260, sp: 0.022 + 0.018 * z[2], life: 420 + 320 * z[2],
                      w: 0.9 + 0.5 * z[2], amp: 0.75 + 0.2 * z[2], spark: 1 });
      });
      t2 += 3 * 300 + 250;
    }
    var bigT = t2 - 60, D = bigT + 620;
    bursts.push({ c: MC, r: MR, t: bigT, sp: 0.06, life: 720, w: 1.4, amp: 1 });
    var per = 2 * (b.w + b.h), seg = document.createElementNS(NS, 'rect');
    seg.setAttribute('x', 0.5); seg.setAttribute('y', 0.5); seg.setAttribute('width', b.w - 1); seg.setAttribute('height', b.h - 1);
    seg.setAttribute('rx', b.rx); seg.setAttribute('fill', 'none'); seg.setAttribute('stroke', '#f4c85a'); seg.setAttribute('stroke-width', 2);
    seg.setAttribute('stroke-dasharray', (per * 0.12) + ' ' + (per * 0.38));
    b.svg.appendChild(seg);
    tween(D, function (q) {
      var t = q * D, dim = 0.58 * Math.min(1, t / 220);
      seg.setAttribute('stroke-dashoffset', (-per * q * 2.6).toFixed(1));
      seg.setAttribute('opacity', (q < 0.1 ? q / 0.1 : q > 0.9 ? (1 - q) / 0.1 : 1).toFixed(2));
      cells.forEach(function (c, k) {
        var col = Math.floor(k / 7), row = k % 7, v = 0, fl = 0, arm = Math.abs(row - MR) * K, j, p, age;
        for (j = 0; j < PAIRS; j++) {
          age = t - j * EVERY;
          if (age < 0 || age > TRAVEL) continue;
          var tip = -4 + (age / TRAVEL) * SPAN, fade = age > TRAVEL * 0.85 ? (TRAVEL - age) / (TRAVEL * 0.15) : 1;
          var a = band(col - (tip - arm), 1.15) * fade, bb = band((W - 1 - col) - (tip - arm), 1.15) * fade;
          v = Math.max(v, a, bb);
          fl = Math.max(fl, Math.pow(a * bb, 0.75) * 0.8);     // white rises and falls with the overlap
        }
        for (j = 0; j < bursts.length; j++) {
          p = bursts[j]; age = t - p.t;
          if (age < 0 || age > p.life) continue;
          var d = Math.abs(col - p.c) + Math.abs(row - p.r);
          v = Math.max(v, band(d - age * p.sp, p.w) * (1 - age / p.life) * p.amp);
          fl = Math.max(fl, Math.max(0, 1 - d / 1.4) * Math.sin(Math.PI * Math.min(1, age / 260)) * (p.spark ? 0.9 : 0.6));
        }
        paint(c, k, v, fl, dim);
      });
    }, function () {
      seg.remove();
      borderFlash(b, FIN, 1);
      confetti(110);
      tween(FIN, function (q) {
        var v = Math.sin(Math.PI * q) * 0.6, dim = 0.58 * Math.max(0, 1 - q / 0.35);
        cells.forEach(function (c, k) { paint(c, k, v, 0, dim); });
      }, function () { cells.forEach(function (c, k) { c.style.background = base[k].css; }); setTimeout(b.done, 50); });
    });
    return D;
  }

  // The label briefly reads 500 DAYS or 1 YEAR: the words float centered over it, and the
  // label itself keeps its width, so the stats bar doesn't shift.
  var label0 = null;
  function relabel(text) {
    var lbl = el.parentNode.querySelector('.stat-lbl');
    if (!lbl) return;
    if (label0 === null) label0 = lbl.innerHTML;
    lbl.classList.add('hm-streak-lbl');
    lbl.innerHTML = '<span>' + label0 + '</span><span style="position:absolute;left:50%;top:0;transform:translateX(-50%);' +
      'white-space:nowrap;color:#e2b03f;opacity:0">' + text + '</span>';
    var a = lbl.firstChild, b = lbl.lastChild;
    tween(300, function (p) { a.style.opacity = 1 - p; b.style.opacity = p; });
    setTimeout(function () {
      tween(300, function (p) { a.style.opacity = p; b.style.opacity = 1 - p; }, function () { lbl.innerHTML = label0; });
    }, 2400);
  }
  // First, on the heatmap: at 50 and 100 the streak's days light up; at a year and 500 the
  // whole heatmap puts on its light show. ms until the number should roll.
  function wave() {
    if (still()) return 0;
    if (S.tier === '500' || S.tier === 'year') return lightShow();
    if (S.tier === '50' || S.tier === '100') return Math.max(0, sweep([214, 236, 170], 1000) - 250);
    return 0;
  }
  function effect(done, waved) {
    var t = S.tier;
    if (!t || still()) return done && done();
    busy = true;
    var big = t === '500' || t === 'year', lead = waved ? 0 : wave();
    setTimeout(function () {
      var o = overlay(), G = '#f4c85a';
      if (t === '5') ring(o, '#cfe99a');
      if (t === '10') { flare(1400); ring(o, G); }
      if (t === '25') { flare(1500); sparks(o, 7, 1.6, G, 34); }
      if (t === '50') { flare(1600); ring(o, G); sparks(o, 9, 1.8, G, 38); }
      if (t === '100') {
        flare(1800); ring(o, G, 1.3); sparks(o, 10, 2, G, 40); confetti(110);
        var hb = hudBox(); if (hb) { borderFlash(hb, 900, 0.6); setTimeout(hb.done, 950); }
      }
      if (big) {
        flare(2600); ring(o, G, 1.6); sparks(o, 14, 2.4, G, 48);
        relabel(S.big_label);
      }
      setTimeout(function () { o.done(); if (done) done(); }, big ? 2000 : 1500);
      setTimeout(function () { busy = false; }, big ? 3300 : t === '100' ? 2800 : 1700);
    }, lead);
  }
  function settle() {
    if (inner) inner.style.transform = 'translateY(' + (-h) + 'px)';
    if (S.gold) {
      el.classList.add('hm-gold');
      var lbl = el.parentNode.querySelector('.stat-lbl');
      if (lbl && !lbl.querySelector('.hm-streak-flame')) {
        lbl.classList.add('hm-streak-lbl');      // the flame hangs off its left, so nothing shifts
        lbl.insertAdjacentHTML('afterbegin', '<span class="hm-streak-flame">' + FLAME + '</span>');
        label0 = lbl.innerHTML;
      }
    }
  }
  // The wave runs first; the number rolls as it reaches today, then turns gold and sparkles
  function play() {
    try { pycmd('heatmap:moment:streak'); } catch (e) {}
    busy = true;
    var lead = wave();
    if (!inner) { setTimeout(function () { settle(); effect(null, true); }, lead); return; }
    setTimeout(function () {
      tween(550, function (p) { inner.style.transform = 'translateY(' + (-h * ease(p)) + 'px)'; }, function () {
        settle(); effect(null, true);
      });
    }, lead || 150);
  }
  function setup() {
    el = document.getElementById('hm-streak');
    if (!el || el.dataset.ms) return;
    el.dataset.ms = '1';
    if (S.title) el.title = S.title;
    if (S.play && !still()) {
      h = el.getBoundingClientRect().height;
      if (h) {
        el.innerHTML = '<span style="display:inline-block;vertical-align:top;overflow:hidden;height:' + h + 'px;line-height:' + h +
          'px"><span style="display:block;text-align:center">' + S.from + '<br>' + S.to + '</span></span>';
        inner = el.firstChild.firstChild;
      }
    } else { settle(); }
    // clicking the number plays the milestone again (once the one playing has finished)
    if (S.tier) {
      el.style.cursor = 'pointer';
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!busy && el.dataset.ready) effect();
      });
    }
    (window.hmWhenShown || function (f) { f(); })(function () {
      if (!S.play || still()) { el.dataset.ready = '1'; return; }
      var gone = false, quiet;
      var go = function () {
        if (gone) return; gone = true; clearTimeout(quiet);
        ['mousemove', 'mousedown', 'keydown', 'wheel'].forEach(function (k) { removeEventListener(k, go, true); });
        play(); setTimeout(function () { el.dataset.ready = '1'; }, 2500);
      };
      ['mousemove', 'mousedown', 'keydown', 'wheel'].forEach(function (k) { addEventListener(k, go, true); });
      quiet = setTimeout(function () { if (gone) return; gone = true; settle(); el.dataset.ready = '1'; }, 120000);
    });
  }
  (window.hmAfterGlass = window.hmAfterGlass || []).push(setup);
})();</script>"""


def _streak(day: str, streak: int, longest: int) -> tuple:
    """(css, script) for the stats bar's streak on a day it counts today."""
    tier = milestone(streak)
    play = not played("streak", day)
    title = (f"{milestone_label(streak) if tier else f'{streak} days in a row'} · "
             + ("your longest yet" if streak >= longest else f"your longest is {longest}"))
    big = (f"{streak // 365} YEAR{'S' if streak >= 730 else ''}" if tier == "year" else f"{streak} DAYS")
    conf = {"from": streak - 1, "to": streak, "tier": tier, "play": play, "title": title,
            "gold": tier is not None and tier != "5", "big_label": big}
    js = (_STREAK_JS.replace("CONF", json.dumps(conf))
          .replace("FLAME_SVG", json.dumps(icon("flame", "9px", 2.4))))
    return _STREAK_CSS, js


# Starts everything once the page is visible and the deck list's glass box is built (or
# after a short wait without one), two frames in so the first paint is done. A last-resort
# timer starts it anyway, so nothing is ever left at its first frame, but doesn't count that
# as played: the page may not have been seen.
_GATE = """<script>(function(){
  var go = false, waiting = [], t0 = Date.now();
  window.hmWhenShown = function (f) { go ? f() : waiting.push(f); };
  window.hmStill = function () {
    return MODE === 'off' || (MODE === 'system' && !!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  };
  function start(seen) {
    if (go) return;
    go = true;
    document.documentElement.classList.add('hm-go');
    if (seen && !window.hmStill()) { PLAYED }
    waiting.forEach(function (f) { try { f(); } catch (e) {} });
    waiting = [];
    setTimeout(function () { document.documentElement.classList.add('hm-done'); }, 1600);
  }
  function ready() {
    return document.visibilityState === 'visible' &&
      (document.querySelector('.glass-deck-container') || Date.now() - t0 > 800);
  }
  (function wait() {
    if (go) return;
    if (ready()) requestAnimationFrame(function () { requestAnimationFrame(function () { setTimeout(function () { start(true); }, 120); }); });
    else setTimeout(wait, 50);
  })();
  setTimeout(function () { start(false); }, 4000);
})();</script>"""


def deck_browser(day: str, done: bool, color: str, mode: str = "system", streak: int = 0,
                 longest: int = 0) -> str:
    """Style and script for this deck list's animations. Call it only for a deck list that
    shows final numbers, not the dimmed one drawn while the background job runs. streak:
    the stats bar's streak, when it counts today (you've reviewed today) and is showing;
    longest: your longest streak, for its tooltip."""
    if mode not in ("system", "on", "off"):
        mode = "system"
    gate = _GATE.replace("MODE", json.dumps(mode))
    streak_css, streak_js = _streak(day, streak, max(longest, streak)) if streak >= 2 else ("", "")
    if mode == "off":
        return (f"<style>{streak_css}</style>" if streak_css else "") + gate.replace("PLAYED", "") + streak_js
    global _back_home
    css, keys = "", []
    if _back_home:
        css += _DRAW
        _back_home = False
    if done and not played("done", day):
        css += _DONE.replace("COLOR", color)
        keys.append("done")
    report = "".join(f"pycmd('heatmap:moment:{k}');" for k in keys)
    if not css:
        style = ""
    elif mode == "on":
        style = f"<style>{css}</style>"
    else:
        style = f"<style>@media (prefers-reduced-motion: no-preference) {{{css}}}</style>"
    # the streak's gold is still (no motion), so it isn't behind the reduced-motion query
    return style + (f"<style>{streak_css}</style>" if streak_css else "") + gate.replace("PLAYED", report) + streak_js
