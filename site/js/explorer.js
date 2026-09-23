// The results explorer: filters, chart and table.
//
// Every number rendered here comes from site-data.json, which is generated
// from the committed artifacts. Nothing is computed from a literal typed into
// this file, and the only arithmetic is the lift the generator already
// carries. A row without a `source` never reaches the browser -- the
// generator refuses to emit one.

import { el, svgEl, clear, fmt, pct, cmp, uniq, artifactUrl } from "./util.js";

const ANY = "__any__";

const FIELDS = [
  { id: "f-rung",    key: "rung",    label: "All rungs" },
  { id: "f-model",   key: "model",   label: "All models" },
  { id: "f-seed",    key: "seed",    label: "All seeds" },
  { id: "f-segment", key: "segment", label: "All segments" },
  { id: "f-metric",  key: "metric",  label: "All metrics" },
  { id: "f-budget",  key: "budget",  label: "All budgets" },
];

const DEFAULTS = { metric: "precision", budget: 50 };

function optionLabel(key, value) {
  if (value === null) return "ensemble / not seeded";
  if (key === "segment") return value === "pooled" ? "Whole evaluated window (pooled)" : value;
  return String(value);
}

function matches(row, state) {
  return FIELDS.every(({ key }) => {
    const want = state[key];
    if (want === ANY) return true;
    return String(row[key]) === String(want);
  });
}

function drawChart(svg, descNode, rows, metricLabel) {
  clear(svg);
  if (!rows.length) {
    svg.setAttribute("viewBox", "0 0 10 10");
    svg.setAttribute("height", 0);
    descNode.textContent = "No rows match the current filters, so there is nothing to plot.";
    return;
  }

  const shown = rows.slice(0, 24);
  const rowH = 30, padL = 208, padR = 84, padT = 16, padB = 26, W = 820;
  const H = padT + padB + shown.length * rowH;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);

  const plotW = W - padL - padR;
  const ceilings = shown.map(r => r.ceiling).filter(v => v !== null);
  const max = Math.max(
    ...shown.map(r => Math.max(r.observed ?? 0, r.null_high ?? 0)),
    ...ceilings, 0.0001);
  const scale = v => (v / max) * plotW;

  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    const x = padL + t * plotW;
    svg.append(svgEl("line", { x1: x, y1: padT, x2: x, y2: H - padB, class: "tick-line" }));
    svg.append(svgEl("text", { x, y: H - 8, class: "tick-text", "text-anchor": "middle",
                               text: fmt(t * max, 3) }));
  }

  shown.forEach((r, i) => {
    const y = padT + i * rowH + 4;
    const h = rowH - 14;
    const name = `${r.model}${r.seed === null ? "" : ` · seed ${r.seed}`} @${r.budget}`;
    svg.append(svgEl("text", { x: padL - 10, y: y + h - 1, class: "axis-text",
                               "text-anchor": "end", text: name }));

    if (r.null_low !== null && r.null_high !== null) {
      const x0 = padL + scale(r.null_low);
      const w = Math.max(scale(r.null_high) - scale(r.null_low), 2);
      const band = svgEl("rect", { x: x0, y: y - 2, width: w, height: h + 4,
                                   class: "bar-null", rx: 2 });
      band.append(svgEl("title", {
        text: `random-ranker band ${fmt(r.null_low, 5)} to ${fmt(r.null_high, 5)}` }));
      svg.append(band);
    }

    const b = svgEl("rect", { x: padL, y, width: Math.max(scale(r.observed), 1), height: h,
                              class: "bar-observed", rx: 2 });
    b.append(svgEl("title", { text: `${r.metric_label} = ${fmt(r.observed, 5)}` }));
    svg.append(b);

    if (r.ceiling !== null && r.ceiling !== undefined) {
      const cx = padL + scale(r.ceiling);
      const line = svgEl("line", { x1: cx, y1: y - 3, x2: cx, y2: y + h + 3,
                                   class: "ceiling-mark" });
      line.append(svgEl("title", { text: `attainable ceiling ${fmt(r.ceiling, 5)}` }));
      svg.append(line);
    }

    svg.append(svgEl("text", { x: padL + scale(r.observed) + 6, y: y + h - 1,
                               class: "bar-label", text: fmt(r.observed, 4) }));
  });

  const withNull = shown.filter(r => r.null_high !== null).length;
  descNode.textContent =
    `${metricLabel} for ${shown.length} run${shown.length === 1 ? "" : "s"}` +
    `${rows.length > shown.length ? ` (first ${shown.length} of ${rows.length})` : ""}. ` +
    `Bars are the observed value; the grey band, where present, is the published ` +
    `random-ranker interval and the dashed rule is the attainable ceiling. ` +
    `${withNull} of ${shown.length} rows have a published band; the rest have none, ` +
    `because a random-ranker band is published for precision and only for the rungs ` +
    `budget_null covers.`;
}

function bindsCell(row) {
  if (row.nonbinding_days === null || row.nonbinding_days === undefined) {
    return el("td", { text: "—" });
  }
  const all = row.nonbinding_days === 0;
  return el("td", {},
    el("span", { class: `pill ${all ? "pill-yes" : "pill-no"}`,
                 text: all ? "binds every day" : `${row.nonbinding_days} non-binding` }));
}

function renderTable(tbody, rows) {
  clear(tbody);
  for (const r of rows.slice(0, 200)) {
    const tr = el("tr");
    tr.append(el("th", { scope: "row", text: r.run }));
    tr.append(el("td", { text: r.seed === null ? "—" : String(r.seed) }));
    tr.append(el("td", { text: r.metric_label }));
    tr.append(el("td", { class: "num", text: String(r.budget) }));
    tr.append(el("td", { class: "num", text: fmt(r.observed, 5) }));
    tr.append(el("td", { class: "num",
      text: r.null_high === null ? "—" : `${fmt(r.null_low, 5)} – ${fmt(r.null_high, 5)}` }));
    tr.append(el("td", { class: "num",
      text: r.lift_vs_null === null ? "—" : `${fmt(r.lift_vs_null, 3)}×` }));
    tr.append(el("td", { class: "num", text: fmt(r.ceiling, 5) }));
    tr.append(el("td", { class: "num", text: fmt(r.efficiency, 5) }));
    tr.append(bindsCell(r));
    tr.append(el("td", {},
      el("span", { class: `pill pill-${r.lineage_status}`, text: r.lineage_status }),
      el("br"),
      el("code", { text: r.lineage })));
    const src = el("td", { class: "wrap-cell" });
    src.append(el("a", { href: artifactUrl(r.source), rel: "noopener",
                         text: r.source.replace("aml-platform/results_archive/", "") }));
    if (r.null_source) {
      src.append(el("br"));
      src.append(el("a", { href: artifactUrl(r.null_source), rel: "noopener",
                           text: "null: derived/budget_null.json" }));
    }
    tr.append(src);
    tbody.append(tr);
  }
}

export function initExplorer(data, root = document) {
  const form = root.querySelector("#explorer-controls");
  if (!form) return null;
  const status = root.querySelector("#explorer-status");
  const svg = root.querySelector("#results-chart");
  const desc = root.querySelector("#chart-desc");
  const tbody = root.querySelector("#results-table tbody");
  const rows = data.results;

  const state = {};
  for (const { key } of FIELDS) state[key] = key in DEFAULTS ? DEFAULTS[key] : ANY;

  const selects = {};
  for (const { id, key, label } of FIELDS) {
    const sel = root.querySelector(`#${id}`);
    selects[key] = sel;
    clear(sel);
    sel.append(el("option", { value: ANY, text: label }));
    const values = uniq(rows.map(r => r[key])).sort(cmp);
    for (const v of values) {
      sel.append(el("option", { value: String(v), text: optionLabel(key, v) }));
    }
    sel.value = String(state[key]);
    sel.addEventListener("change", () => { state[key] = sel.value; render(); });
  }

  function render() {
    const filtered = rows.filter(r => matches(r, state))
      .sort((a, b) => cmp(a.rung, b.rung) || cmp(a.model, b.model) ||
                      cmp(a.seed, b.seed) || cmp(a.budget, b.budget));

    const metricLabel = state.metric === ANY
      ? "Observed values"
      : (data.metrics.find(m => m.key === state.metric) || {}).label || state.metric;

    clear(status);
    if (!filtered.length) {
      status.className = "status is-empty";
      status.append(document.createTextNode(
        "No archived artifact covers that combination. Widen a filter — for example, " +
        "a random-ranker band is published only at k=50 and k=200, and only for HI-Medium " +
        "and HI-Small."));
    } else {
      status.className = "status";
      const srcs = uniq(filtered.map(r => r.source)).length;
      status.append(el("strong", { text: `${filtered.length} row${filtered.length === 1 ? "" : "s"}` }));
      status.append(document.createTextNode(
        ` from ${srcs} source artifact${srcs === 1 ? "" : "s"}. ` +
        `Lineages shown: ${uniq(filtered.map(r => r.lineage)).sort().join(", ")}.`));
    }

    drawChart(svg, desc, filtered, metricLabel);
    renderTable(tbody, filtered);
  }

  root.querySelector("#f-reset").addEventListener("click", () => {
    for (const { key } of FIELDS) {
      state[key] = key in DEFAULTS ? DEFAULTS[key] : ANY;
      selects[key].value = String(state[key]);
    }
    render();
  });

  render();
  return { render, state };
}
