/* ReproChem Lens — demo engine.
 *
 *   voice (Web Speech API) → intent router → concept (concepts.js)
 *   → SVG diagram revealed act by act → narration (system text-to-speech)
 *
 * Diagrams are never drawn by a model: each concept is a specification written
 * and checked by hand (nodes, links, sources, five acts). The engine only
 * displays it and keeps it in sync with the voice; fx.js adds the visual
 * effects (camera, bursts, star field) and carries no content.
 */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const C = window.LENS_CONCEPTS;
  const ACT_NAMES = ["Question", "Problem", "Elements", "Answer", "Going further"];
  const FILL = { core: "url(#gCore)", step: "url(#gStep)", risk: "url(#gRisk)", fix: "url(#gFix)", result: "url(#gResult)", warn: "url(#gWarn)", next: "none", seg: "url(#gSeg)" };
  const GLOW = { core: "#2ee6d6", step: "#8b5cf6", risk: "#ff6b6b", fix: "#7ae582", result: "#ffd23f", warn: "#ff9f1c", next: "#8b5cf6", seg: "#2ee6d6" };

  /* ---------------------------------------------------------------- state */
  let current = null;        // concept on screen
  let byId = {};             // node specs of the current concept
  let run = 0;               // token: any running video stops when run changes
  let paused = false;
  let captions = false;
  let tcStart = 0, tcTimer = 0;

  /* -------------------------------------------------------- SVG rendering */
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const center = n => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });

  function anchors(a, b, force) {
    const ca = center(a), cb = center(b);
    const dx = cb.x - ca.x, dy = cb.y - ca.y;
    const horiz = force ? force === "h" : Math.abs(dx) * 0.55 > Math.abs(dy);
    if (horiz) {
      const s = dx >= 0 ? 1 : -1;
      return { horiz, p: [ca.x + s * a.w / 2, ca.y, cb.x - s * (b.w / 2 + 8), cb.y] };
    }
    const s = dy >= 0 ? 1 : -1;
    return { horiz, p: [ca.x, ca.y + s * a.h / 2, cb.x, cb.y - s * (b.h / 2 + 8)] };
  }

  function curve({ horiz, p: [x1, y1, x2, y2] }) {
    if (horiz) { const m = (x2 - x1) / 2; return `M${x1},${y1} C${x1 + m},${y1} ${x2 - m},${y2} ${x2},${y2}`; }
    const m = (y2 - y1) / 2; return `M${x1},${y1} C${x1},${y1 + m} ${x2},${y2 - m} ${x2},${y2}`;
  }

  function render(concept) {
    const gN = $("nodes"), gE = $("edges");
    gN.innerHTML = ""; gE.innerHTML = ""; $("fx").innerHTML = "";
    byId = {};
    concept.nodes.forEach(n => { byId[n.id] = n; });
    (concept.edges || []).forEach(([a, b, label, force]) => {
      const A = byId[a], B = byId[b];
      if (!A || !B) { console.warn("unknown link", a, b); return; }
      const geo = anchors(A, B, force), d = curve(geo);
      el("path", { d, class: "edge", "data-a": a, "data-b": b }, gE);
      el("path", { d, class: "flow", "data-a": a, "data-b": b }, gE);
      el("circle", { cx: geo.p[2], cy: geo.p[3], r: 4.5, class: "tip", "data-a": a, "data-b": b }, gE);
      if (label) {
        const [x1, y1, x2, y2] = geo.p;
        const t = el("text", { x: (x1 + x2) / 2 + (geo.horiz ? 0 : 10), y: (y1 + y2) / 2 - 8, "text-anchor": geo.horiz ? "middle" : "start", class: "elab", "data-a": a, "data-b": b }, gE);
        t.textContent = label;
      }
    });
    concept.nodes.forEach(n => drawNode(gN, n));
    $("sources").textContent = concept.sources ? "Sources · " + concept.sources.join(" · ") : "";
  }

  function drawNode(parent, n) {
    const k = n.k || "step";
    const g = el("g", { class: `node k-${k}${n.goto ? " click" : ""}`, "data-id": n.id }, parent);
    const rx = Math.min(24, n.h / 2.4);
    const clip = el("clipPath", { id: `cl-${n.id}` }, g);
    el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx }, clip);
    if (k !== "next") el("rect", { x: n.x, y: n.y + 7, width: n.w, height: n.h, rx, class: "shadow" }, g);
    el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx, class: "body", fill: FILL[k] }, g);
    if (k !== "next" && k !== "seg") el("rect", { x: n.x + 8, y: n.y + 4, width: n.w - 16, height: n.h * 0.38, rx: rx * 0.8, class: "gloss" }, g);
    el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx, class: "rim" }, g);
    const sweepBox = el("g", { "clip-path": `url(#cl-${n.id})` }, g);   // clip outside, animate inside
    const sw = el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, class: "sweep" }, sweepBox);
    sw.style.transformBox = "fill-box";

    const withIcon = k !== "seg" && n.w >= 200 && n.h >= 52;
    let cx = n.x + n.w / 2;
    if (withIcon) {
      const ix = n.x + 32, iy = n.y + n.h / 2;
      const ic = el("g", { class: "ico", transform: `translate(${ix} ${iy})` }, g);
      el("circle", { r: 17, class: "disc" }, ic);
      el("path", { d: FX.icon(k), class: "g" }, ic);
      cx = n.x + 58 + (n.w - 66) / 2;
    }
    const lines = n.s ? n.s.split("\n") : [];
    const big = k === "seg";
    const titleLines = n.t.split("\n");
    const lh = 17, tl = big ? 36 : 20;
    const total = titleLines.length * tl + lines.length * lh + (lines.length ? 4 : 0);
    let y = n.y + n.h / 2 - total / 2 + (big ? 30 : 15);
    titleLines.forEach((tt, i) => {
      const t = el("text", { x: cx, y: y + i * tl, "text-anchor": "middle", class: "t" }, g);
      t.textContent = tt;
    });
    y += (titleLines.length - 1) * tl + (big ? 8 : 4);
    lines.forEach(line => {
      y += lh;
      const s = el("text", { x: cx, y, "text-anchor": "middle", class: "s" }, g);
      s.textContent = line;
    });
    if (n.goto) g.addEventListener("click", () => open(n.goto, { video: videoMode() }));
  }

  function reveal(ids) {
    ids.forEach((id, i) => {
      const g = document.querySelector(`.node[data-id="${id}"]`);
      if (!g || g.classList.contains("in")) return;
      setTimeout(() => {
        g.classList.add("in");
        const n = byId[id];
        if (n) FX.burst($("fx"), n.x + n.w / 2, n.y + n.h / 2, GLOW[n.k || "step"]);
        linkEdges();
      }, i * 140);
    });
  }

  function linkEdges() {
    const shown = new Set([...document.querySelectorAll(".node.in")].map(g => g.dataset.id));
    document.querySelectorAll(".edge, .flow, .tip, .elab").forEach(e => {
      if (shown.has(e.dataset.a) && shown.has(e.dataset.b)) e.classList.add("in");
    });
  }

  function focus(ids) {
    document.querySelectorAll(".node").forEach(g => g.classList.toggle("focus", ids.includes(g.dataset.id)));
    document.querySelectorAll(".flow").forEach(e => e.classList.toggle("hot", ids.includes(e.dataset.b)));
  }

  function bbox(ids) {
    const ns = ids.map(id => byId[id]).filter(Boolean);
    if (!ns.length) return null;
    const x0 = Math.min(...ns.map(n => n.x)), y0 = Math.min(...ns.map(n => n.y));
    const x1 = Math.max(...ns.map(n => n.x + n.w)), y1 = Math.max(...ns.map(n => n.y + n.h));
    return [x0, y0, x1 - x0, y1 - y0];
  }

  function setAct(i) {
    document.querySelectorAll("#acts li").forEach((li, k) => {
      li.classList.toggle("on", k === i);
      li.classList.toggle("done", i >= 0 && k < i);
    });
  }

  function flag(i) {
    const f = $("actflag");
    f.classList.remove("show");
    if (i < 0) return;
    setTimeout(() => { f.textContent = `0${i + 1} · ${ACT_NAMES[i]}`; f.classList.add("show"); }, 120);
  }

  function titleCard(show, title, kicker) {
    const c = $("titleCard");
    if (show) { $("cardTitle").textContent = title; $("kicker").textContent = kicker || "ReproChem Lens · explainer"; }
    c.classList.toggle("show", !!show);
    $("canvas").style.transition = "opacity .8s";
    $("canvas").style.opacity = show ? 0.15 : 1;
  }

  function timecode(on) {
    clearInterval(tcTimer);
    if (!on) { $("tc").textContent = "00:00"; return; }
    tcStart = Date.now();
    tcTimer = setInterval(() => {
      const s = Math.floor((Date.now() - tcStart) / 1000);
      $("tc").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }, 500);
  }

  /* ---------------------------------------------------------- voice (TTS) */
  let voice = null;
  function pickVoice() {
    if (!("speechSynthesis" in window)) return;
    const vs = speechSynthesis.getVoices().filter(v => /^en/i.test(v.lang));
    const pref = ["Samantha", "Daniel", "Alex", "Karen", "Google US English", "Google UK English Female"];
    voice = pref.map(p => vs.find(v => v.name.includes(p))).find(Boolean) || vs.find(v => /en-US/i.test(v.lang)) || vs[0] || null;
  }
  if ("speechSynthesis" in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }

  function wait(ms, token) {
    return new Promise(res => {
      const t0 = Date.now();
      const tick = () => {
        if (token !== run) return res(false);
        if (paused) return setTimeout(tick, 150);
        if (Date.now() - t0 >= ms) return res(true);
        setTimeout(tick, 100);
      };
      tick();
    });
  }

  function say(text, token) {
    showCaption(text);
    document.body.classList.add("speaking");
    const done = ok => { document.body.classList.remove("speaking"); return ok; };
    if (!("speechSynthesis" in window) || !voice) return wait(Math.max(2500, text.length * 62), token).then(done);
    return new Promise(res => {
      const u = new SpeechSynthesisUtterance(text);
      u.voice = voice; u.lang = voice.lang; u.rate = 1.0; u.pitch = 1;
      let finished = false;
      const finish = ok => { if (!finished) { finished = true; res(done(ok)); } };
      u.onend = () => finish(token === run);
      u.onerror = () => finish(token === run);
      speechSynthesis.speak(u);
      // safety net: some browsers never fire onend
      const guard = setInterval(() => {
        if (token !== run) { clearInterval(guard); finish(false); }
        else if (!speechSynthesis.speaking && !paused) { clearInterval(guard); finish(true); }
      }, 400);
    });
  }

  function showCaption(text) {
    const c = $("caption");
    c.textContent = text || "";
    c.hidden = !captions || !text;
  }

  function stopAll() {
    run++;
    paused = false;
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    document.body.classList.remove("speaking");
    $("pauseBtn").textContent = "❚❚";
    showCaption("");
    titleCard(false);
    flag(-1);
    timecode(false);
  }

  /* ---------------------------------------------------- playing a concept */
  function videoMode() { return document.body.dataset.mode === "video"; }

  async function open(id, { video = false, premise = null } = {}) {
    const concept = C[id];
    if (!concept) return unknown();
    stopAll();
    const token = run;
    current = concept;
    document.body.dataset.mode = video ? "video" : "diagram";
    FX.resetCamera($("canvas"));
    render(concept);
    const q = $("question");
    q.innerHTML = "";
    if (premise) {
      const s = document.createElement("span"); s.className = "fix"; s.textContent = "⚠ " + premise + " — ";
      q.appendChild(s);
    }
    q.appendChild(document.createTextNode(concept.question));
    setAct(video ? 0 : -1);

    if (!video) {                                    // diagram only: everything builds up, no text
      for (const act of concept.acts) {
        reveal(act.show || []);
        focus(act.focus || act.show || []);
        if (!(await wait(1000, token))) return;
      }
      focus([]);
      return;
    }

    timecode(true);
    const seen = [];
    for (let i = 0; i < concept.acts.length; i++) {  // video: five narrated acts
      const act = concept.acts[i];
      setAct(i);
      flag(i);
      if (i === 0) titleCard(true, concept.question, premise ? "⚠ " + premise : null);
      else titleCard(false);
      seen.push(...(act.show || []));
      const last = i === concept.acts.length - 1;
      const box = last ? null : i >= 3 ? bbox(seen) : bbox(act.show || []);
      if (i > 0) FX.camera($("canvas"), box);
      if (i > 0) setTimeout(() => { if (token === run) { reveal(act.show || []); focus(act.focus || act.show || []); } }, 500);
      const text = (i === 0 && premise ? `A quick correction first: ${premise}. ` : "") + act.say;
      if (!(await say(text, token))) return;
      if (!(await wait(600, token))) return;
    }
    focus(concept.acts.at(-1).show || []);
    setAct(5); flag(-1); timecode(false);
    showCaption("");
  }

  function unknown() {
    stopAll();
    $("question").textContent = "This concept is not in the verified base yet. Available concepts are listed below.";
    $("nodes").innerHTML = ""; $("edges").innerHTML = ""; $("sources").textContent = "";
    setAct(-1);
  }

  /* --------------------------------------------------------------- router */
  const { norm, route } = window.LensRouter;   // router.js, shared with voicetest.html

  function handle(text) {
    $("heard").textContent = "“" + text + "”";
    const t = norm(text);
    if (/\b(stop|arrete|quiet)\b/.test(t)) return stopAll();
    if (/\bpause\b/.test(t)) return togglePause();
    const r = route(text);
    if (!r.id) return unknown();
    open(r.id, r);
  }

  /* --------------------------------------------------- microphone (ASR) */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, listening = false;
  if (SR) {
    rec = new SR();
    rec.lang = "en-US"; rec.interimResults = true; rec.continuous = false;
    rec.onresult = e => {
      let txt = "", final = false;
      for (const r of e.results) { txt += r[0].transcript; final = final || r.isFinal; }
      $("heard").textContent = "“" + txt + "”";
      if (final) handle(txt);
    };
    rec.onend = () => { listening = false; $("micBtn").classList.remove("live"); $("micLabel").textContent = "Talk"; };
    rec.onerror = e => { $("heard").textContent = "mic: " + e.error; };
  } else {
    $("micLabel").textContent = "Mic unavailable";
    $("micBtn").disabled = true;
  }

  function listen() {
    if (!rec || listening) return;
    stopAll();                                     // barge-in: the user interrupts the system
    listening = true;
    $("micBtn").classList.add("live"); $("micLabel").textContent = "Listening…";
    try { rec.start(); } catch (_) { /* already started */ }
  }
  function unlisten() { if (rec && listening) rec.stop(); }

  $("micBtn").addEventListener("click", () => (listening ? unlisten() : listen()));
  document.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space" && !e.repeat) { e.preventDefault(); listen(); }
    if (e.key === "p" || e.key === "P") togglePause();
    if (e.key === "Escape") stopAll();
  });
  document.addEventListener("keyup", e => { if (e.code === "Space" && e.target.tagName !== "INPUT") unlisten(); });

  $("typed").addEventListener("submit", e => {
    e.preventDefault();
    const v = $("typedIn").value.trim();
    if (v) handle(v);
    $("typedIn").value = "";
  });

  function togglePause() {
    paused = !paused;
    if ("speechSynthesis" in window) paused ? speechSynthesis.pause() : speechSynthesis.resume();
    $("pauseBtn").textContent = paused ? "▶" : "❚❚";
  }
  $("pauseBtn").addEventListener("click", togglePause);
  $("ccBtn").addEventListener("click", () => {
    captions = !captions;
    $("ccBtn").setAttribute("aria-pressed", String(captions));
    if (!captions) $("caption").hidden = true;
  });

  /* ---------------------------------------------------------------- shelf */
  const shelf = $("shelf");
  Object.entries(C).forEach(([id, c]) => {
    const b = document.createElement("button");
    b.textContent = c.label;
    b.title = "Click: diagram · Shift+click: video";
    b.addEventListener("click", e => open(id, { video: e.shiftKey }));
    shelf.appendChild(b);
  });

  $("fine").textContent = "Demo: browser speech recognition and system text-to-speech (synthetic voice, labelled as such). "
    + "Target version: local Whisper and local TTS. Diagrams written and checked by hand, sources under each diagram. "
    + "Space = talk · P = pause · Esc = stop · Shift+click = video.";

  FX.sky();
  FX.deco($("deco"));
  window.LENS = { open, handle, route };            // for tests
})();
