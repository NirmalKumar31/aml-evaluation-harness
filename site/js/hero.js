// The hero network.
//
// The nodes and edges are rendered into the HTML by the build, from a fixed
// sequence: the same picture on every load, in every browser, for every
// visitor. This module only moves what is already there, on a deterministic
// path derived from each node's index -- so there is no randomness at
// runtime either, and a paused animation is still the built picture.
//
// It does nothing at all under prefers-reduced-motion, and it stops when the
// hero scrolls out of view so no work happens behind the rest of the page.

import { prefersReducedMotion } from "./util.js";

export function initHero(root = document) {
  const svg = root.querySelector(".hero-net");
  if (!svg || prefersReducedMotion()) return null;

  const nodes = [...svg.querySelectorAll(".node")].map((n) => ({
    n,
    x: parseFloat(n.getAttribute("cx")),
    y: parseFloat(n.getAttribute("cy")),
    i: parseInt(n.dataset.i, 10) || 0,
  }));
  const edges = [...svg.querySelectorAll(".edge")].map((e) => ({
    e,
    a: nearest(nodes, parseFloat(e.getAttribute("x1")), parseFloat(e.getAttribute("y1"))),
    b: nearest(nodes, parseFloat(e.getAttribute("x2")), parseFloat(e.getAttribute("y2"))),
  }));
  if (!nodes.length) return null;

  let raf = 0;
  let running = false;

  function frame(t) {
    // Two slow sinusoids per node, phase-shifted by its index. Amplitude is
    // a few pixels: enough to read as alive, not enough to move anything a
    // visitor might be looking at.
    const s = t / 1000;
    for (const nd of nodes) {
      const dx = Math.sin(s * 0.32 + nd.i * 0.7) * 5.5;
      const dy = Math.cos(s * 0.27 + nd.i * 1.1) * 4.5;
      nd.n.setAttribute("cx", (nd.x + dx).toFixed(2));
      nd.n.setAttribute("cy", (nd.y + dy).toFixed(2));
    }
    for (const ed of edges) {
      if (!ed.a || !ed.b) continue;
      ed.e.setAttribute("x1", ed.a.n.getAttribute("cx"));
      ed.e.setAttribute("y1", ed.a.n.getAttribute("cy"));
      ed.e.setAttribute("x2", ed.b.n.getAttribute("cx"));
      ed.e.setAttribute("y2", ed.b.n.getAttribute("cy"));
    }
    raf = requestAnimationFrame(frame);
  }

  function start() {
    if (running) return;
    running = true;
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }

  // NOT UNTIL THE PAGE HAS SETTLED. Motion that begins during first paint
  // keeps the viewport changing while the browser is still laying the page
  // out -- it competes with the text for the reader's attention at exactly
  // the wrong moment, and it is the reason this page measured a slow visual
  // settle while every other metric was already perfect. The picture is in
  // the HTML either way; this only decides when it starts moving.
  let armed = false;
  function arm() {
    if (armed) return;
    armed = true;
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting) start(); else stop();
      }, { threshold: 0 });
      io.observe(svg);
    } else {
      start();
    }
  }
  const settle = () => {
    if ("requestIdleCallback" in window) {
      requestIdleCallback(arm, { timeout: 2500 });
    } else {
      setTimeout(arm, 1200);
    }
  };
  if (document.readyState === "complete") settle();
  else window.addEventListener("load", settle, { once: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop(); else start();
  });

  return { start, stop };
}

function nearest(nodes, x, y) {
  let best = null, bestD = Infinity;
  for (const nd of nodes) {
    const d = (nd.x - x) ** 2 + (nd.y - y) ** 2;
    if (d < bestD) { bestD = d; best = nd; }
  }
  return bestD <= 1 ? best : null;
}
