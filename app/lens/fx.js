/* ReproChem Lens — visual effects. Purely decorative: no content lives here.
 *
 *   FX.sky()            animated star and particle field behind the stage
 *   FX.deco(g)          slow background atoms with orbiting electrons
 *   FX.burst(g, x, y)   light ring + sparks when a node appears
 *   FX.camera(svg, box) eased viewBox move ("camera") to a region of the diagram
 *   FX.icon(kind)       SVG path for the small glyph drawn inside a node
 */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ star field */
  function sky() {
    const c = document.getElementById("sky");
    if (!c) return;
    const ctx = c.getContext("2d");
    let W, H, stars = [], mx = 0, my = 0;
    const palette = ["#ffffff", "#bfe9ff", "#d9ccff", "#2ee6d6", "#8b5cf6"];
    function resize() {
      W = c.width = innerWidth * devicePixelRatio; H = c.height = innerHeight * devicePixelRatio;
      c.style.width = innerWidth + "px"; c.style.height = innerHeight + "px";
      stars = Array.from({ length: 170 }, (_, i) => ({
        x: Math.random() * W, y: Math.random() * H,
        r: (Math.random() ** 3 * 1.8 + 0.3) * devicePixelRatio,
        z: Math.random() * 0.8 + 0.2,
        tw: Math.random() * Math.PI * 2,
        col: i < 150 ? palette[i % 3] : palette[3 + (i % 2)],
        big: i >= 150,
      }));
    }
    addEventListener("resize", resize);
    addEventListener("mousemove", e => { mx = (e.clientX / innerWidth - 0.5); my = (e.clientY / innerHeight - 0.5); });
    resize();
    let t = 0;
    (function frame() {
      t += 0.016;
      ctx.clearRect(0, 0, W, H);
      for (const s of stars) {
        if (!calm) { s.y -= s.z * 0.12 * devicePixelRatio; if (s.y < -10) { s.y = H + 10; s.x = Math.random() * W; } }
        const px = s.x + mx * 30 * s.z * devicePixelRatio, py = s.y + my * 20 * s.z * devicePixelRatio;
        const a = 0.35 + 0.65 * Math.abs(Math.sin(t * (0.6 + s.z) + s.tw));
        ctx.globalAlpha = s.big ? 0.5 * a : a;
        if (s.big) {
          const g = ctx.createRadialGradient(px, py, 0, px, py, s.r * 9);
          g.addColorStop(0, s.col); g.addColorStop(1, "transparent");
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, s.r * 9, 0, 7); ctx.fill();
        }
        ctx.fillStyle = s.col; ctx.beginPath(); ctx.arc(px, py, s.r, 0, 7); ctx.fill();
      }
      ctx.globalAlpha = 1;
      requestAnimationFrame(frame);
    })();
  }

  /* ---------------------------------------------- background atoms (decor) */
  function deco(g) {
    g.innerHTML = "";
    const atoms = [[905, 520, 1], [70, 540, 0.7], [960, 70, 0.6]];
    atoms.forEach(([cx, cy, s], k) => {
      const a = document.createElementNS(NS, "g");
      a.setAttribute("transform", `translate(${cx} ${cy}) scale(${s})`);
      a.innerHTML = `<circle class="nuc" r="9"/>` + [0, 60, -60].map((rot, i) => {
        const id = `orb${k}${i}`;
        return `<g transform="rotate(${rot})"><ellipse class="orb" rx="46" ry="16"/>
          <path id="${id}" d="M-46,0 a46,16 0 1,0 92,0 a46,16 0 1,0 -92,0" fill="none"/>
          <circle class="el" r="3.2">${calm ? "" : `<animateMotion dur="${3 + i}s" repeatCount="indefinite"><mpath href="#${id}"/></animateMotion>`}</circle></g>`;
      }).join("");
      g.appendChild(a);
    });
  }

  /* --------------------------------------------------- burst on appearance */
  function burst(g, x, y, color) {
    if (calm || !g || !("animate" in Element.prototype)) return;
    const ring = document.createElementNS(NS, "circle");
    ring.setAttribute("cx", x); ring.setAttribute("cy", y); ring.setAttribute("r", 18);
    ring.setAttribute("class", "burst"); ring.style.stroke = color;
    ring.style.transformBox = "fill-box"; ring.style.transformOrigin = "center";
    g.appendChild(ring);
    ring.animate([{ transform: "scale(.4)", opacity: .95 }, { transform: "scale(4.2)", opacity: 0 }], { duration: 900, easing: "cubic-bezier(.2,.7,.3,1)" })
      .onfinish = () => ring.remove();
    for (let i = 0; i < 9; i++) {
      const s = document.createElementNS(NS, "circle");
      s.setAttribute("cx", x); s.setAttribute("cy", y); s.setAttribute("r", 1.6 + Math.random() * 1.6);
      s.setAttribute("class", "spark"); s.style.fill = i % 3 ? "#fff" : color;
      g.appendChild(s);
      const ang = (i / 9) * Math.PI * 2 + Math.random() * 0.5, d = 50 + Math.random() * 60;
      s.animate([{ transform: "translate(0,0)", opacity: 1 }, { transform: `translate(${Math.cos(ang) * d}px,${Math.sin(ang) * d}px)`, opacity: 0 }],
        { duration: 700 + Math.random() * 400, easing: "cubic-bezier(.1,.8,.3,1)" }).onfinish = () => s.remove();
    }
  }

  /* -------------------------------------------------------- camera moves */
  let vb = [0, 0, 1000, 580], camRaf = 0;
  function fit(box) {
    if (!box) return [0, 0, 1000, 580];
    let [x, y, w, h] = box;
    const pad = 70, R = 1000 / 580;
    x -= pad; y -= pad; w += 2 * pad; h += 2 * pad;
    if (w / h < R) { const nw = h * R; x -= (nw - w) / 2; w = nw; } else { const nh = w / R; y -= (nh - h) / 2; h = nh; }
    if (w < 560) { const k = 560 / w; x -= (w * k - w) / 2; y -= (h * k - h) / 2; w *= k; h *= k; }
    if (w > 1000) return [0, 0, 1000, 580];
    x = Math.max(-300, Math.min(x, 1300 - w)); y = Math.max(-300, Math.min(y, 880 - h));
    return [x, y, w, h];
  }
  function camera(svg, box, ms = 1400) {
    const to = fit(box), from = vb.slice();
    cancelAnimationFrame(camRaf);
    if (calm) { vb = to; svg.setAttribute("viewBox", to.join(" ")); return; }
    const t0 = performance.now();
    const ease = u => (u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
    (function step(now) {
      const u = Math.min(1, (now - t0) / ms), e = ease(u);
      vb = from.map((v, i) => v + (to[i] - v) * e);
      svg.setAttribute("viewBox", vb.join(" "));
      if (u < 1) camRaf = requestAnimationFrame(step);
    })(t0);
  }
  function resetCamera(svg) { cancelAnimationFrame(camRaf); vb = [0, 0, 1000, 580]; svg.setAttribute("viewBox", vb.join(" ")); }

  /* ---------------------------------------------------------- node glyphs */
  const ICONS = {
    core: "M-10,0 a10,4 0 1,0 20,0 a10,4 0 1,0 -20,0 M-5,-8.7 a10,4 60 1,0 10,17.4 a10,4 60 1,0 -10,-17.4 M5,-8.7 a10,4 -60 1,0 -10,17.4 a10,4 -60 1,0 10,-17.4",
    step: "M-7,0 H7 M2,-5 L7,0 L2,5",
    risk: "M0,-8 L8.5,7 H-8.5 Z M0,-2 V2.5 M0,5 V5.2",
    fix: "M-7,0.5 L-2.5,5 L7,-5.5",
    result: "M0,-8.5 L2.5,-2.8 8.5,-2.6 3.8,1.2 5.4,7.4 0,3.9 -5.4,7.4 -3.8,1.2 -8.5,-2.6 -2.5,-2.8Z",
    warn: "M0,-7 V2 M0,6 V6.2",
    next: "M-6,6 L6,-6 M-1,-6 H6 V1",
  };
  const icon = kind => ICONS[kind] || ICONS.step;

  window.FX = { sky, deco, burst, camera, resetCamera, icon };
})();
