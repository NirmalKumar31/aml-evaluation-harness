// The results explorer: experiment first, then only what that experiment has.
//
// THE CONTROLS ARE BUILT FROM THE DATA, NOT FROM A FIXED LIST. The archive is
// not a grid. HI-Small's sweep carries three metrics at k=50 and one at
// k=200; HI-Medium carries four metrics at seven budgets. A single flat
// budget list would offer six combinations on HI-Small that return nothing,
// which is the defect this design exists to remove. So the metric list comes
// from the chosen experiment, the budget list from the chosen metric, and the
// seed list from the chosen metric and budget -- and every option therefore
// has at least one row behind it.
//
// When a choice survives a change of experiment it is kept; when it does not,
// it moves to that experiment's nearest available value rather than emptying.

import { el, svgEl, clear, fmt, artifactUrl } from "./util.js";

const PAGE_SIZE = 12;

export function initExplorer(data, rows, root = document) {
  const form = root.querySelector("#explorer-controls");
  if (!form) return null;

  const byId = new Map(data.experiments.map((e) => [e.id, e]));
  const radios = [...form.querySelectorAll(".exp-radio")];
  const selMetric = root.querySelector("#f-metric");
  const selBudget = root.querySelector("#f-budget");
  const selSeed = root.querySelector("#f-seed");
  const reset = root.querySelector("#f-reset");
  const status = root.querySelector("#explorer-status");
  const metricLabel = new Map(data.metrics.map((m) => [m.key, m.label]));

  const state = {
    experiment: (radios.find((r) => r.checked) || radios[0]).value,
    metric: null, budget: null, seed: "", page: 0,
  };

  const chart = makeChart(root.querySelector("#rc-svg"));

  function experiment() { return byId.get(state.experiment); }

  function seedKey() { return `${state.metric}@${state.budget}`; }

  /** Rebuild the dependent controls, keeping any choice that still exists. */
  function syncControls() {
    const e = experiment();
    const metrics = e.metrics;
    if (!metrics.includes(state.metric)) state.metric = metrics[0];
    fill(selMetric, metrics.map((m) => [m, metricLabel.get(m) || m]), state.metric);

    const budgets = e.budgets_by_metric[state.metric] || [];
    if (!budgets.includes(state.budget)) state.budget = budgets[0];
    fill(selBudget, budgets.map((b) => [String(b), `k = ${b}`]), String(state.budget));

    // With a single seed there is one option and it is the honest one: a
    // control offering "all" and "seed 0" as separate choices that select
    // the same rows is a control that lies about what it does.
    const seeds = e.seeds_by_metric_budget[seedKey()] || [];
    const seedName = (s) => (s === null ? "pooled (no seed)" : `seed ${s}`);
    const seedOpts = seeds.length > 1
      ? [["", `All ${seeds.length} seeds`], ...seeds.map((s) => [String(s), seedName(s)])]
      : [["", seedName(seeds[0])]];
    if (!seedOpts.some(([v]) => v === state.seed)) state.seed = "";
    fill(selSeed, seedOpts, state.seed);
  }

  function selected() {
    return rows.filter((r) =>
      r.experiment === state.experiment &&
      r.metric === state.metric &&
      r.budget === Number(state.budget) &&
      (state.seed === "" || String(r.seed) === state.seed));
  }

  /** Every row of the chosen experiment at the chosen metric, all budgets. */
  function tableRows() {
    return rows
      .filter((r) => r.experiment === state.experiment && r.metric === state.metric)
      .sort((a, b) => a.budget - b.budget ||
                      a.run_label.localeCompare(b.run_label, "en"));
  }

  function render() {
    syncControls();
    const sel = selected();
    const e = experiment();

    // A selection with no rows is a bug in this file, not a state a visitor
    // can reach: it is reported rather than rendered as an empty chart.
    if (!sel.length) {
      status.className = "status is-empty";
      status.textContent =
        `No rows for ${state.metric}@${state.budget} in ${e.title}. This ` +
        `combination should not have been selectable; the archive index is ` +
        `in aml-platform/results_archive/.`;
      chart.clearAll();
      return;
    }
    status.className = "status";
    status.textContent =
      `${sel.length} row${sel.length === 1 ? "" : "s"} · ` +
      `${metricLabel.get(state.metric) || state.metric} at k = ${state.budget} · ` +
      `${e.rung} · ${e.title}`;

    chart.update(sel, state, metricLabel);
    renderReads(root, sel, e, state, metricLabel);
    renderProv(root, sel);
    renderTable(root, tableRows(), state);
  }

  for (const r of radios) {
    r.addEventListener("change", () => {
      if (!r.checked) return;
      state.experiment = r.value;
      state.page = 0;
      render();
    });
  }
  selMetric.addEventListener("change", () => {
    state.metric = selMetric.value; state.page = 0; render();
  });
  selBudget.addEventListener("change", () => {
    state.budget = Number(selBudget.value); state.page = 0; render();
  });
  selSeed.addEventListener("change", () => {
    state.seed = selSeed.value; state.page = 0; render();
  });
  if (reset) {
    reset.addEventListener("click", () => {
      const e = experiment();
      state.metric = e.metrics[0];
      state.budget = e.budgets_by_metric[state.metric][0];
      state.seed = "";
      state.page = 0;
      render();
    });
  }

  const prev = root.querySelector("#rows-prev");
  const next = root.querySelector("#rows-next");
  if (prev && next) {
    prev.addEventListener("click", () => {
      state.page = Math.max(0, state.page - 1);
      renderTable(root, tableRows(), state);
    });
    next.addEventListener("click", () => {
      const last = Math.max(0, Math.ceil(tableRows().length / PAGE_SIZE) - 1);
      state.page = Math.min(last, state.page + 1);
      renderTable(root, tableRows(), state);
    });
  }

  render();
  return { state, render, selected, tableRows };
}

function fill(select, options, value) {
  clear(select);
  for (const [v, label] of options) {
    select.append(el("option", { value: v, text: label, selected: v === String(value) }));
  }
  select.value = String(value);
}

/* ---------------------------------------------------------------- chart */

/** A keyed chart: a run that survives an update keeps its bar, so the bar
 *  moves to its new length instead of being destroyed and replaced. That is
 *  what makes the transition readable rather than a flicker. */
function makeChart(svg) {
  if (!svg) return { update() {}, clearAll() {} };
  const groups = new Map();
  let band = null, edge = null, ceiling = null, ceilingText = null, axisG = null;

  function clearAll() {
    clear(svg);
    groups.clear();
    band = edge = ceiling = ceilingText = axisG = null;
  }

  function update(sel, state, metricLabel) {
    const runs = [...sel].sort((a, b) => (b.observed ?? 0) - (a.observed ?? 0));
    const x0 = 20, x1 = 620, top = 34, rowH = 56;
    const height = top + runs.length * rowH + 56;
    svg.setAttribute("viewBox", `0 0 760 ${height}`);
    const sx = (v) => x0 + Math.max(0, Math.min(1, v)) * (x1 - x0);

    const first = runs[0];
    // The band belongs to the split and is identical for every run here, so
    // it is drawn once, behind everything.
    if (first.null_low !== null && first.null_low !== undefined) {
      if (!band) {
        band = svgEl("rect", { class: "null-band", y: top - 12 });
        edge = svgEl("line", { class: "null-edge" });
        svg.prepend(edge);
        svg.prepend(band);
      }
      band.setAttribute("x", sx(first.null_low).toFixed(2));
      band.setAttribute("width", Math.max(2, sx(first.null_high) - sx(first.null_low)).toFixed(2));
      band.setAttribute("height", String(runs.length * rowH));
      edge.setAttribute("x1", sx(first.null_high).toFixed(2));
      edge.setAttribute("x2", sx(first.null_high).toFixed(2));
      edge.setAttribute("y1", String(top - 12));
      edge.setAttribute("y2", String(top - 12 + runs.length * rowH));
    } else if (band) {
      band.remove(); edge.remove(); band = edge = null;
    }

    if (first.ceiling !== null && first.ceiling !== undefined) {
      if (!ceiling) {
        ceiling = svgEl("line", { class: "ceiling-line" });
        ceilingText = svgEl("text", { class: "ceiling-label", "text-anchor": "middle" });
        svg.append(ceiling, ceilingText);
      }
      const cx = sx(first.ceiling);
      ceiling.setAttribute("x1", cx.toFixed(2));
      ceiling.setAttribute("x2", cx.toFixed(2));
      ceiling.setAttribute("y1", String(top - 16));
      ceiling.setAttribute("y2", String(top - 12 + runs.length * rowH));
      ceilingText.setAttribute("x", cx.toFixed(2));
      ceilingText.setAttribute("y", String(top - 22));
      ceilingText.textContent = `attainable ceiling ${fmt(first.ceiling, 4)}`;
    } else if (ceiling) {
      ceiling.remove(); ceilingText.remove(); ceiling = ceilingText = null;
    }

    const keep = new Set();
    runs.forEach((r, i) => {
      keep.add(r.run);
      const y = top + i * rowH;
      let g = groups.get(r.run);
      if (!g) {
        const rect = svgEl("rect", { class: "bar", x: x0, height: 22, rx: 3 });
        const title = svgEl("title");
        rect.append(title);
        const label = svgEl("text", { class: "bar-label", x: x0 });
        const value = svgEl("text", { class: "bar-value" });
        g = { g: svgEl("g", { class: "run" }, rect, label, value), rect, title, label, value };
        g.g.dataset.run = r.run;
        svg.append(g.g);
        groups.set(r.run, g);
      }
      g.rect.setAttribute("y", String(y));
      g.rect.setAttribute("width", (sx(r.observed) - x0).toFixed(2));
      g.title.textContent =
        `${r.run_label}: ${metricLabel.get(r.metric) || r.metric} at k=${r.budget} ` +
        `is ${fmt(r.observed)}`;
      g.label.setAttribute("y", String(y - 6));
      g.label.textContent = r.run_label;
      g.value.setAttribute("x", (sx(r.observed) + 8).toFixed(2));
      g.value.setAttribute("y", String(y + 16));
      g.value.textContent = r.lift_vs_null
        ? `${fmt(r.observed)} (${fmt(r.lift_vs_null, 4)}× the top of the band)`
        : fmt(r.observed);
    });
    for (const [run, g] of groups) {
      if (!keep.has(run)) { g.g.remove(); groups.delete(run); }
    }

    if (axisG) axisG.remove();
    axisG = svgEl("g", { class: "axis" });
    const ay = top + runs.length * rowH + 8;
    axisG.append(svgEl("line", { class: "ax", x1: x0, y1: ay, x2: x1, y2: ay }));
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      const x = sx(t);
      axisG.append(svgEl("line", { class: "tick", x1: x, y1: ay, x2: x, y2: ay + 5 }));
      axisG.append(svgEl("text", { class: "tick-label", x, y: ay + 17,
                                   "text-anchor": "middle", text: t.toFixed(2) }));
    }
    axisG.append(svgEl("text", {
      class: "axis-title", x: (x0 + x1) / 2, y: ay + 38, "text-anchor": "middle",
      text: `${metricLabel.get(state.metric) || state.metric} at k = ${state.budget} ` +
            `(${first.unit})`,
    }));
    svg.append(axisG);
  }

  return { update, clearAll };
}

/* ------------------------------------------------------- interpretation */

function renderReads(root, sel, e, state, metricLabel) {
  const box = root.querySelector("#rc-reads");
  const title = root.querySelector("#rc-title");
  const desc = root.querySelector("#rc-desc");
  const cap = root.querySelector("#rc-caption");
  if (!box) return;
  clear(box);

  const label = metricLabel.get(state.metric) || state.metric;
  const vals = sel.map((r) => r.observed).filter((v) => v !== null);
  const min = Math.min(...vals), max = Math.max(...vals);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const first = sel[0];

  if (title) title.textContent = `${label} at k = ${state.budget} — ${e.title}`;
  if (desc) {
    desc.textContent =
      `One bar per run, longest first. ${sel.length} run` +
      `${sel.length === 1 ? "" : "s"} on ${e.rung}, ` +
      (first.null_low !== null
        ? `with the random-ranker band for this split shaded behind them.`
        : `with no random-ranker band published for this rung and budget.`);
  }
  if (cap) {
    cap.textContent =
      `Unit: ${first.unit}. Segment: ${first.segment}. Lineage: ` +
      `${first.lineage} (${first.lineage_status}).`;
  }

  box.append(el("h3", { class: "chart-title", text: "How to read this" }));
  box.append(el("p", {
    text: vals.length === 1
      ? `The single archived value is ${fmt(min)}.`
      : `Across ${vals.length} runs, ${label} at k = ${state.budget} runs from ` +
        `${fmt(min)} to ${fmt(max)}, with a mean of ${fmt(mean)}.`,
  }));

  if (first.null_low !== null && first.null_low !== undefined) {
    const lifts = sel.map((r) => r.lift_vs_null).filter((v) => v !== null);
    box.append(el("p", {
      text: `A uniformly random ranker on this split reaches ${fmt(first.null_low)} ` +
            `to ${fmt(first.null_high)} at the same budget` +
            (lifts.length
              ? `, so the observed values are ${fmt(Math.min(...lifts), 4)}× to ` +
                `${fmt(Math.max(...lifts), 4)}× the top of that band.`
              : `.`) +
            ` The band is a property of the window, not of any model.`,
    }));
  } else if (first.null_status) {
    box.append(el("p", { text: `Random-ranker null: ${first.null_status}.` }));
  }

  box.append(el("p", { text: `Attainable ceiling: ${first.ceiling_kind}.` }));

  if (first.nonbinding_days) {
    box.append(el("p", {
      text: `On ${first.nonbinding_days} day(s) in this window the budget did not ` +
            `bind — every candidate account-day could be reviewed — which is ` +
            `${(first.nonbinding_day_share * 100).toFixed(2)}% of the alert slots. ` +
            `Nothing is being ranked on those days.`,
    }));
  }
}

function renderProv(root, sel) {
  const box = root.querySelector("#rc-prov");
  if (!box) return;
  clear(box);
  box.append(el("h3", { class: "prov-h", text: "Read from" }));
  const list = el("ul", { class: "prov-list plain" });
  const seen = new Set();
  for (const r of sel) {
    for (const p of [r.source, r.null_source]) {
      if (!p || seen.has(p)) continue;
      seen.add(p);
      const parts = p.split("/");
      list.append(el("li", {},
        el("a", { class: "artifact", href: artifactUrl(p), rel: "noopener" },
          el("code", { text: parts.slice(-2).join("/") }))));
    }
  }
  box.append(list);
}

/* -------------------------------------------------------------- table */

function renderTable(root, all, state) {
  const body = root.querySelector("#rows-body");
  const cap = root.querySelector("#rows-cap");
  const stateLine = root.querySelector("#rows-state");
  const prev = root.querySelector("#rows-prev");
  const next = root.querySelector("#rows-next");
  if (!body) return;

  const pages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
  if (state.page > pages - 1) state.page = pages - 1;
  const start = state.page * PAGE_SIZE;
  const page = all.slice(start, start + PAGE_SIZE);

  clear(body);
  for (const r of page) {
    const current = r.budget === Number(state.budget) &&
                    (state.seed === "" || String(r.seed) === state.seed);
    const tr = el("tr", { class: current ? "is-current" : null });
    // The marker is a word, not a colour: the row highlight is decoration.
    tr.append(el("td", {}, r.run_label,
      current ? el("span", { class: "chip chip-measured", text: "selected" }) : null));
    tr.append(el("td", { text: r.metric_label }));
    tr.append(el("td", { text: String(r.budget) }));
    tr.append(el("td", { text: fmt(r.observed) }));
    tr.append(el("td", {
      text: r.null_low === null ? "not published" :
            `${fmt(r.null_low)} – ${fmt(r.null_high)}`,
    }));
    tr.append(el("td", { text: r.ceiling === null ? "—" : fmt(r.ceiling) }));
    tr.append(el("td", {}, el("code", { text: r.lineage })));
    const td = el("td", {});
    td.append(el("a", { class: "artifact", href: artifactUrl(r.source), rel: "noopener" },
      el("code", { text: r.source.split("/").slice(-2).join("/") })));
    tr.append(td);
    body.append(tr);
  }

  if (cap) {
    cap.textContent =
      `Every archived row for this experiment at ${page.length ? page[0].metric_label : ""}` +
      `, across all budgets — ${all.length} rows. The rows matching the chart ` +
      `above are marked “selected”.`;
  }
  if (stateLine) {
    stateLine.textContent =
      `Page ${state.page + 1} of ${pages} · rows ${all.length ? start + 1 : 0}–` +
      `${Math.min(start + PAGE_SIZE, all.length)} of ${all.length}`;
  }
  if (prev) prev.disabled = state.page === 0;
  if (next) next.disabled = state.page >= pages - 1;
}
