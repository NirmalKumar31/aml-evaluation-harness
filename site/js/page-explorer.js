// The explorer.
//
// Two fetches, both relative so the page works at any base path: the shared
// facts, and the rows. The rows are the large file and only this route pays
// for them.
//
// If either fetch fails the page says so and shows nothing, rather than
// rendering an empty chart that would read as a measured zero.

import { initNav } from "./nav.js";
import { initReveal } from "./reveal.js";
import { initExplorer } from "./explorer.js";
import { initBudgetSimulator } from "./budget.js";

function failVisibly(err) {
  const status = document.querySelector("#explorer-status");
  if (status) {
    status.className = "status is-empty";
    status.textContent =
      "The results data could not be loaded, so nothing is shown rather than " +
      "something unverified. The same numbers are in the repository under " +
      "aml-platform/results_archive/.";
  }
  document.documentElement.dataset.siteData = "failed";
  console.error("site data could not be loaded:", err);
}

async function start() {
  // The simulator reads no project data, so it works whatever the fetches do.
  initNav(document);
  initBudgetSimulator(document);
  initReveal(document);
  document.documentElement.dataset.siteJs = "ready";

  try {
    const [core, rows] = await Promise.all([
      fetch("../data/site-data.json", { cache: "no-cache" }),
      fetch("../data/results.json", { cache: "no-cache" }),
    ]);
    if (!core.ok) throw new Error(`site-data.json: HTTP ${core.status}`);
    if (!rows.ok) throw new Error(`results.json: HTTP ${rows.status}`);
    const data = await core.json();
    const results = (await rows.json()).results;
    initExplorer(data, results, document);
    document.documentElement.dataset.siteData = "loaded";
  } catch (err) {
    failVisibly(err);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}
