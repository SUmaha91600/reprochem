/* ReproChem Lens — intent router. Shared by the Lens page (lens.js) and the
 * voice benchmark (voicetest.html), so the benchmark scores the exact code the
 * demo runs. Keyword matching on aliases, most specific concept first, plus a
 * premise check: "BP86 basis set" is caught because BP86 is a functional.
 */
(() => {
  "use strict";
  const C = window.LENS_CONCEPTS;
  const norm = s => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[’']/g, " ");

  function route(text) {
    const t = " " + norm(text) + " ";
    const video = /video|film|animat|en image/.test(t);
    let hit = null;
    for (const [id, c] of Object.entries(C)) {            // concepts.js order: most specific first
      if (c.aliases.some(a => t.includes(a))) { hit = id; break; }
    }
    if (!hit) return { id: null };
    let premise = null;
    const kind = C[hit].kind;
    if (kind === "functional" && /\bbasis\b|\bbase\b/.test(t) && !/functional|fonctionnelle/.test(t))
      premise = `${C[hit].name || C[hit].label} is not a basis set, it is a functional`;
    if (kind === "basis-set" && /functional|fonctionnelle/.test(t))
      premise = `${C[hit].name || C[hit].label} is not a functional, it is a basis set`;
    return { id: hit, video, premise };
  }

  window.LensRouter = { norm, route };
})();
