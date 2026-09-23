// Engineering. Static content plus the diagram dialog.

import { initNav } from "./nav.js";
import { initReveal } from "./reveal.js";
import { initLightbox } from "./lightbox.js";

function start() {
  initNav(document);
  initLightbox(document);
  initReveal(document);
  document.documentElement.dataset.siteJs = "ready";
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}
