// Entry point. Loads the generated data once and hands it to each section.
//
// The fetch is relative, so the page works at any base path -- including
// /aml-evaluation-harness/ on GitHub Pages and / on a local preview server.

import { initNav } from "./nav.js";
import { initExplorer } from "./explorer.js";
import { initBudgetSimulator } from "./budget.js";
import { renderStability, renderRelease, renderWindows, renderLineages, renderWithdrawn }
  from "./sections.js";
import { el } from "./util.js";

function failVisibly(err) {
  const status = document.querySelector("#explorer-status");
  if (status) {
    status.className = "status is-empty";
    status.textContent =
      "The results data could not be loaded, so nothing is shown rather than " +
      "something unverified. The same numbers are in the repository under " +
      "aml-platform/results_archive/.";
  }
  console.error("site-data could not be loaded:", err);
}

async function main() {
  // The simulator is self-contained, so it works even if the data fetch
  // fails. Navigation likewise.
  initNav(document);
  initBudgetSimulator(document);

  try {
    const res = await fetch("./data/site-data.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    initExplorer(data, document);
    renderStability(data, document);
    renderRelease(data, document);
    renderWindows(data, document);
    renderLineages(data, document);
    renderWithdrawn(data, document);
    document.documentElement.dataset.siteData = "loaded";
  } catch (err) {
    failVisibly(err);
    document.documentElement.dataset.siteData = "failed";
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", main, { once: true });
} else {
  main();
}
