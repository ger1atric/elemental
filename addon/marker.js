/* Retention Tracker marker for Anki's review screen.
 *
 * A small pill (the session sparkline) in one corner. Hover it to open a panel
 * with your retention, the margin to target, and the time left. Only the pill
 * takes the mouse — the panel is click-through — and the grip drags it.
 *
 * It lives in a shadow root, so card templates can't restyle it and it can't
 * restyle them. Python drives it with RTMarker.update(payload).
 */
(function () {
  if (window.RTMarker) return;

  var KEY = "ret-marker-pos";
  var CSS = [
    ":host { all: initial; }",
    ".hud { position: relative; font: 13px/1.3 -apple-system, BlinkMacSystemFont, system-ui, sans-serif;",
    "  color: #e6edf6; -webkit-font-smoothing: antialiased; text-align: left; direction: ltr;",
    "  letter-spacing: normal; word-spacing: normal; text-transform: none; font-style: normal;",
    "  font-weight: 400; text-indent: 0; text-shadow: none; white-space: nowrap; }",
    ".pill { display: flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px;",
    "  border-radius: 15px; box-sizing: border-box; background: rgba(16,21,29,.80);",
    "  border: 1px solid rgba(255,255,255,.08); box-shadow: 0 2px 10px rgba(0,0,0,.18);",
    "  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);",
    "  user-select: none; pointer-events: auto; cursor: default; }",
    ".pill .num { font-variant-numeric: tabular-nums; }",
    ".pill .sep { color: #6f819b; }",
    ".grip { display: flex; align-items: center; margin: 0 -4px 0 -1px; color: #6f819b;",
    "  cursor: grab; opacity: .6; font-size: 13px; }",
    ".grip:hover { opacity: 1; }",
    ".panel { position: absolute; right: 0; top: 38px; width: 224px; padding: 10px 12px 9px;",
    "  box-sizing: border-box; border-radius: 10px; background: rgba(16,21,29,.96);",
    "  border: 1px solid #2b3a52; box-shadow: 0 10px 30px rgba(0,0,0,.35);",
    "  -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);",
    "  opacity: 0; visibility: hidden; transform: translateY(-4px); pointer-events: none;",
    "  transition: opacity .15s, transform .15s, visibility 0s linear .15s; }",
    ".hud.open .panel { opacity: 1; visibility: visible; transform: none;",
    "  transition: opacity .15s .1s, transform .15s .1s, visibility 0s linear .1s; }",
    ".hud.left .panel { right: auto; left: 0; }",
    ".hud.up .panel { top: auto; bottom: 38px; transform: translateY(4px); }",
    ".hud.up.open .panel { transform: none; }",
    ".row { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }",
    ".row + .row { margin-top: 3px; }",
    ".sec + .sec { margin-top: 8px; padding-top: 8px; border-top: 1px solid #243247; }",
    ".label { color: #93a4bd; }",
    ".big { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }",
    ".val { font-weight: 600; font-variant-numeric: tabular-nums; }",
    ".sub { color: #93a4bd; font-size: 11.5px; font-variant-numeric: tabular-nums; }",
    ":host(.light) .hud { color: #1d2733; }",
    ":host(.light) .pill { background: rgba(255,255,255,.82); border-color: rgba(0,0,0,.10); }",
    ":host(.light) .grip { color: #9aa0a6; }",
    ":host(.light) .panel { background: rgba(255,255,255,.98); border-color: #d5dde8;",
    "  box-shadow: 0 10px 30px rgba(0,0,0,.14); }",
    ":host(.light) .sec + .sec { border-color: #e3e9f1; }",
    ":host(.light) .label, :host(.light) .sub { color: #607089; }",
    ".pill.drift { border-color: rgba(255,204,0,.42); }",
    ".ring { position: absolute; pointer-events: none; }",
    ":host(.light) .pill.drift { border-color: rgba(190,148,10,.5); }",
    // This card is left out of the focus score: dashed outline, dimmed contents, pause mark.
    ".pill.paused { border-style: dashed; border-color: rgba(147,164,189,.75); }",
    ":host(.light) .pill.paused { border-color: rgba(96,112,137,.6); }",
    ".pill.paused > :not(.pz):not(.grip) { opacity: .45; }",
    ".pz { display: inline-flex; gap: 2px; margin-right: -1px; }",
    ".pz i { display: block; width: 3px; height: 10px; border-radius: 1px; background: #93a4bd; }",
    ":host(.light) .pz i { background: #607089; }",
    // Pomodoro: a break offered or under way edges the pill in teal; click does something
    ".pill.ready, .pill.brk { border-color: rgba(63,193,169,.55); }",
    ":host(.light) .pill.ready, :host(.light) .pill.brk { border-color: rgba(14,125,110,.5); }",
    ".pill.click { cursor: pointer; }",
    // A panel holding a link (the pomodoro's Stop / Start) takes the mouse, so it can be clicked
    ".hud.open .panel.live { pointer-events: auto; }",
    ".pomo-act { cursor: pointer; font-size: 11.5px; font-weight: 600; }",
    ".pomo-act:hover { text-decoration: underline; }"
  ].join("\n");

  var host = null, hud = null, pill = null, panel = null, base = "", root = null;

  function ensure() {
    if (host && host.isConnected) return;
    host = document.createElement("ret-marker");
    host.id = "ret-marker";
    root = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = CSS;
    hud = document.createElement("div");
    hud.className = "hud";
    pill = document.createElement("div");
    pill.className = "pill";
    panel = document.createElement("div");
    panel.className = "panel";
    hud.appendChild(pill);
    hud.appendChild(panel);
    root.appendChild(style);
    root.appendChild(hud);
    document.body.appendChild(host);
    // Open the panel toward the middle of the window, wherever the pill sits.
    var closing = null;
    pill.addEventListener("mouseenter", function () {
      clearTimeout(closing);
      var r = host.getBoundingClientRect();
      hud.classList.toggle("up", r.top + r.height / 2 > window.innerHeight / 2);
      hud.classList.toggle("left", r.left + r.width / 2 < window.innerWidth / 2);
      if (panel.childNodes.length) hud.classList.add("open");
    });
    // Leaving the pill closes the panel, unless the mouse goes on into a panel with a link
    // to click (it gets a moment to cross the gap between them).
    function close() { hud.classList.remove("open"); }
    pill.addEventListener("mouseleave", function () {
      clearTimeout(closing);
      if (panel.classList.contains("live")) closing = setTimeout(close, 250); else close();
    });
    panel.addEventListener("mouseenter", function () { clearTimeout(closing); });
    panel.addEventListener("mouseleave", function () { clearTimeout(closing); closing = setTimeout(close, 150); });
    panel.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    panel.addEventListener("click", function (ev) {
      var a = ev.target.closest && ev.target.closest(".pomo-act");
      if (a && window.pycmd) pycmd("heatmap:pomo:" + a.getAttribute("data-act"));
    });
    // Never take focus or start a text selection: keys stay with the reviewer.
    pill.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    // The pomodoro's break: start it, or end it early (not from the drag handle)
    pill.addEventListener("click", function (ev) {
      if (!pill.classList.contains("click") || (ev.target.closest && ev.target.closest(".grip"))) return;
      if (window.pycmd) pycmd("heatmap:pomo:click");
    });
  }

  // The pomodoro's countdowns (data-end, ms) tick here once a second, with the ring
  // beside one (data-total, s) emptying as it goes.
  function tickPomo() {
    if (!root || !host || !host.isConnected) return;
    var now = Date.now();
    [].forEach.call(root.querySelectorAll(".pomo-t[data-end]"), function (e) {
      var s = Math.max(0, Math.round((+e.getAttribute("data-end") - now) / 1000));
      e.textContent = Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2);
      var total = +e.getAttribute("data-total"), arc = total && e.parentNode.querySelector(".pomo-arc");
      if (arc) arc.setAttribute("stroke-dasharray", (50.27 * s / total).toFixed(2) + " 50.27");
    });
  }
  setInterval(tickPomo, 1000);

  function applySaved() {
    try {
      var s = localStorage.getItem(KEY);
      if (!s) return;
      var p = JSON.parse(s);
      var mx = Math.max(0, window.innerWidth - host.offsetWidth);
      var my = Math.max(0, window.innerHeight - host.offsetHeight);
      host.style.setProperty("left", Math.max(0, Math.min(mx, p.left)) + "px", "important");
      host.style.setProperty("top", Math.max(0, Math.min(my, p.top)) + "px", "important");
      host.style.setProperty("right", "auto", "important");
      host.style.setProperty("bottom", "auto", "important");
    } catch (_) {}
  }

  function addGrip() {
    var g = document.createElement("div");
    g.className = "grip";
    g.textContent = "⋮";
    g.title = "Drag to move · double-click to reset";
    g.onmousedown = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      hud.classList.remove("open");
      var r = host.getBoundingClientRect(), ox = ev.clientX - r.left, oy = ev.clientY - r.top;
      g.style.cursor = "grabbing";
      function mv(e2) {
        var nx = Math.max(0, Math.min(window.innerWidth - host.offsetWidth, e2.clientX - ox));
        var ny = Math.max(0, Math.min(window.innerHeight - host.offsetHeight, e2.clientY - oy));
        host.style.setProperty("left", nx + "px", "important");
        host.style.setProperty("top", ny + "px", "important");
        host.style.setProperty("right", "auto", "important");
        host.style.setProperty("bottom", "auto", "important");
      }
      function up() {
        document.removeEventListener("mousemove", mv);
        document.removeEventListener("mouseup", up);
        g.style.cursor = "grab";
        try {
          localStorage.setItem(KEY, JSON.stringify({
            left: parseInt(host.style.left) || 0, top: parseInt(host.style.top) || 0 }));
        } catch (_) {}
      }
      document.addEventListener("mousemove", mv);
      document.addEventListener("mouseup", up);
    };
    g.ondblclick = function (ev) {
      ev.stopPropagation();
      try { localStorage.removeItem(KEY); } catch (_) {}
      host.setAttribute("style", base);
    };
    pill.appendChild(g);
  }

  // After each answer: an outline drawn once around the pill — a soft head with a tail
  // that fades continuously, leaving a faint line that then fades. Green when the answer
  // was focused, amber when it wasn't. Style "fade" just fades the outline in and out.
  // The choice is the add-on's setting, not the system's Reduce Motion, which Anki's web
  // view passes through and which would otherwise always turn the drawing off.
  // Drawn on a canvas for its ~0.9 s: the tail is stamped as closely spaced dots whose
  // strength falls off smoothly, so there are no bands between steps. The head doesn't
  // stop at the start: it glides on for OVER of a lap, slowing, and fades evenly over
  // the time that takes, so the end is one motion.
  var DURATION = 950, OVER = 0.75, PAD = 3, TAIL = 0.3;

  function playRing(kind, style) {
    var light = host.classList.contains("light");
    var rgb = kind === "focus" ? "0,204,51" : (light ? "190,148,10" : "255,204,0");
    var old = hud.querySelector("canvas.ring");
    if (old) { if (old.finish) old.finish("replaced"); else old.remove(); }
    var w = pill.offsetWidth + 2 * PAD, h = pill.offsetHeight + 2 * PAD, dpr = window.devicePixelRatio || 1;
    var cv = document.createElement("canvas");
    cv.className = "ring";
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    cv.style.width = w + "px"; cv.style.height = h + "px";
    cv.style.left = (pill.offsetLeft - PAD) + "px";
    cv.style.top = (pill.offsetTop - PAD) + "px";
    hud.appendChild(cv);
    var ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);

    // the outline: a stadium inset by 1 px; perimeter P, measured clockwise from the
    // top-left end of the top edge (where the canvas roundRect path starts too)
    var x0 = 1, y0 = 1, W = w - 2, H = h - 2, r = H / 2, L = W - H, P = 2 * L + Math.PI * H;
    function at(t) {
      if (t < L) return [x0 + r + t, y0];
      t -= L;
      if (t < Math.PI * r) { var a = -Math.PI / 2 + t / r; return [x0 + W - r + r * Math.cos(a), y0 + r + r * Math.sin(a)]; }
      t -= Math.PI * r;
      if (t < L) return [x0 + W - r - t, y0 + H];
      t -= L;
      var b = Math.PI / 2 + t / r;
      return [x0 + r + r * Math.cos(b), y0 + r + r * Math.sin(b)];
    }
    function outlinePath() {
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x0, y0, W, H, r);
      else {
        ctx.moveTo(x0 + r, y0); ctx.lineTo(x0 + W - r, y0); ctx.arc(x0 + W - r, y0 + r, r, -Math.PI / 2, Math.PI / 2);
        ctx.lineTo(x0 + r, y0 + H); ctx.arc(x0 + r, y0 + r, r, Math.PI / 2, Math.PI * 1.5);
      }
    }
    var lineA = light ? .3 : .22, headA = light ? .3 : .24;
    var ease = function (u) { return -(Math.cos(Math.PI * u) - 1) / 2; };    // gentle ease-in-out (sine)
    var t0 = performance.now(), still = style === "fade", end = still ? 1400 : DURATION;

    function draw(t) {
      ctx.clearRect(0, 0, w, h);
      if (still) {
        var k = Math.sin(Math.PI * Math.min(1, t / 1400));
        ctx.strokeStyle = "rgba(" + rgb + "," + (lineA * 1.6 * k) + ")"; ctx.lineWidth = 1.2;
        outlinePath(); ctx.stroke();
        return;
      }
      // 1.75 laps: about half a second to the start point, then a slowing, fading second lap
      var u = Math.min(1, t / DURATION);
      var head = ease(u) * P * (1 + OVER);
      var cross = Math.acos(1 - 2 / (1 + OVER)) / Math.PI;     // when the head passes the start
      var past = Math.min(1, Math.max(0, (u - cross) / (1 - cross)));
      var fade = 0.5 * (1 + Math.cos(Math.PI * past));
      // the line left behind
      ctx.setLineDash([Math.max(0, Math.min(head, P)), P + 10]);
      ctx.strokeStyle = "rgba(" + rgb + "," + (lineA * fade) + ")"; ctx.lineWidth = 1.2;
      outlinePath(); ctx.stroke(); ctx.setLineDash([]);
      // the head and its tail: dots every 0.5 px. Neighbouring dots overlap, so each one is
      // given the share that makes the stack add up to the intended strength (not several
      // times it), and the strength eases off along a cosine: level at the head, no edge
      // where the head ends and the tail begins, and a soft end.
      var tail = TAIL * P, step = 0.5, rad = 0.85, n = Math.max(1, Math.floor(tail / step));
      var share = step / (2 * rad);
      for (var i = n; i >= 0; i--) {
        var d = head - i * step;
        if (d < 0) continue;
        var f = i / n, A = headA * Math.pow(0.5 * (1 + Math.cos(Math.PI * f)), 1.6) * fade;
        if (A < 0.003) continue;
        var pt = at(d % P);
        ctx.fillStyle = "rgba(" + rgb + "," + (1 - Math.pow(1 - A, share)) + ")";
        ctx.beginPath(); ctx.arc(pt[0], pt[1], rad, 0, Math.PI * 2); ctx.fill();
      }
    }

    // Frames come from requestAnimationFrame; if that stalls (Qt's web view can pause it),
    // a 40 ms timer keeps the ring moving, and it's always gone shortly after its end,
    // whatever happens. How each ring went is reported for the diagnostic log.
    var frames = 0, timerFrames = 0, maxGap = 0, lastT = t0, done = false, err = "";
    var rafPending = false, timer = 0;
    function schedule() {
      if (!rafPending) {
        rafPending = true;
        requestAnimationFrame(function () { rafPending = false; tick(false); });
      }
      clearTimeout(timer);
      timer = setTimeout(function () { tick(true); }, 40);
    }
    function tick(viaTimer) {
      if (done) return;
      var now = performance.now();
      if (frames && now - lastT < 12) { schedule(); return; }   // both fired at once: draw once
      if (frames) maxGap = Math.max(maxGap, now - lastT);
      lastT = now;
      frames++;
      if (viaTimer) timerFrames++;
      var t = now - t0;
      try { draw(t); } catch (e) { err = String((e && e.message) || e); t = end; }
      if (t < end) schedule(); else finish("done");
    }
    function finish(why) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearTimeout(hard);
      cv.remove();
      try {
        if (window.pycmd) pycmd("heatmap:ringlog:" + JSON.stringify({ how: why, kind: kind, frames: frames,
          timer: timerFrames, gap: Math.round(maxGap), ms: Math.round(performance.now() - t0), err: err }));
      } catch (_) {}
    }
    cv.finish = finish;
    var hard = setTimeout(function () { finish("timeout"); }, end + 400);
    schedule();
  }

  window.RTMarker = {
    update: function (p) {
      ensure();
      base = "position:fixed !important; z-index:2147482000 !important; margin:0 !important;" +
             "pointer-events:none !important;" + p.corner;
      host.setAttribute("style", base);
      host.classList.toggle("light", !p.night);
      pill.innerHTML = (p.paused ? '<span class="pz"><i></i><i></i></span>' : "") + p.pill;
      pill.classList.toggle("drift", p.focus === "drift");
      pill.classList.toggle("paused", !!p.paused);
      pill.classList.remove("ready", "brk", "click");
      if (p.pomo) p.pomo.split(" ").forEach(function (c) { pill.classList.add(c); });
      pill.title = p.pomo_title || "";
      panel.innerHTML = p.panel;
      panel.classList.toggle("live", !!panel.querySelector(".pomo-act"));
      if (!p.panel) hud.classList.remove("open");
      // The pill redraws more than once per card: play each answer's ring once.
      if (p.ring && window.__rtRingId !== p.ring.id) {
        window.__rtRingId = p.ring.id;
        playRing(p.ring.kind, p.ring.style);
      }
      if (p.draggable) { addGrip(); applySaved(); }
      tickPomo();
    },
    remove: function () {
      if (host && host.parentNode) host.parentNode.removeChild(host);
      host = null;
    }
  };
})();
