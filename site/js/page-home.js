// Home. Everything readable here is already in the HTML; this adds the hero
// motion, the diagram dialog and the scroll reveal, and nothing else.

import { initNav } from "./nav.js";
import { initHero } from "./hero.js";
import { initReveal } from "./reveal.js";
import { initLightbox } from "./lightbox.js";

function start() {
  initNav(document);
  initHero(document);
  initLightbox(document);
  initReveal(document);
  document.documentElement.dataset.siteJs = "ready";
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}
