// Seed stability, provenance, window structure and the withdrawal register.
// All rendered from site-data.json; no value is written into this file.

import { el, svgEl, clear, fmt, pct, artifactUrl } from "./util.js";

export function renderStability(data, root = document) {
  const s = data.stability;
  const intro = root.querySelector("#stability-intro");
  if (intro) {
    intro.textContent =
      `Archived sweep on ${s.rung} with ${s.model}: ${s.n_seeds} fits differing in nothing ` +
      `but the random seed. Read from ${s.source.replace("aml-platform/results_archive/", "")}.`;
  }

  const tbody = root.querySelector("#stability-table tbody");
  if (tbody) {
    clear(tbody);
    for (const m of s.metrics) {
      const tr = el("tr");
      tr.append(el("th", { scope: "row" }, el("code", { text: m.metric })));
      for (const k of ["mean", "min", "max", "range"]) {
        tr.append(el("td", { class: "num", text: fmt(m[k], 5) }));
      }
      tr.append(el("td", { class: "num", text: `${fmt(m.spread_pct, 2)}%` }));
      tbody.append(tr);
    }
  }

  const svg = root.querySelector("#stability-chart");
  const desc = root.querySelector("#stab-desc");
  if (!svg) return;
  clear(svg);

  const metrics = s.metrics;
  const rowH = 40, padL = 168, padR = 70, padT = 16, padB = 26, W = 760;
  const H = padT + padB + metrics.length * rowH;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);
  const plotW = W - padL - padR;
  const max = Math.max(...metrics.map(m => m.max), 0.0001);
  const scale = v => (v / max) * plotW;

  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    const x = padL + t * plotW;
    svg.append(svgEl("line", { x1: x, y1: padT, x2: x, y2: H - padB, class: "tick-line" }));
    svg.append(svgEl("text", { x, y: H - 8, class: "tick-text", "text-anchor": "middle",
                               text: fmt(t * max, 2) }));
  }

  metrics.forEach((m, i) => {
    const y = padT + i * rowH + rowH / 2 - 8;
    svg.append(svgEl("text", { x: padL - 10, y: y + 11, class: "axis-text",
                               "text-anchor": "end", text: m.metric }));
    const x0 = padL + scale(m.min), x1 = padL + scale(m.max);
    const band = svgEl("rect", { x: x0, y, width: Math.max(x1 - x0, 2), height: 16,
                                 class: "bar-null", rx: 2 });
    band.append(svgEl("title", { text: `${m.metric}: ${fmt(m.min, 5)} to ${fmt(m.max, 5)}` }));
    svg.append(band);
    const mx = padL + scale(m.mean);
    const mark = svgEl("rect", { x: mx - 1.5, y: y - 3, width: 3, height: 22,
                                 class: "bar-observed" });
    mark.append(svgEl("title", { text: `mean ${fmt(m.mean, 5)}` }));
    svg.append(mark);
    svg.append(svgEl("text", { x: x1 + 6, y: y + 12, class: "bar-label",
                               text: `${fmt(m.spread_pct, 1)}%` }));
  });

  if (desc) {
    const worst = metrics.reduce((a, b) => (b.spread_pct > a.spread_pct ? b : a));
    const best = metrics.reduce((a, b) => (b.spread_pct < a.spread_pct ? b : a));
    desc.textContent =
      `Each grey band spans the observed minimum to maximum across ${s.n_seeds} seeds; ` +
      `the vertical rule is the mean and the figure at the right is the relative spread. ` +
      `${worst.metric} moves most at ${fmt(worst.spread_pct, 2)}% of its mean, ` +
      `${best.metric} least at ${fmt(best.spread_pct, 2)}%.`;
  }
}

export function renderRelease(data, root = document) {
  const box = root.querySelector("#release-facts");
  const r = data.release;
  if (box) {
    clear(box);
    const items = [
      ["Tests collected", r.tests_collected.toLocaleString("en"),
       "Documents quote the collected total, because how many pass or skip depends on which data the machine holds."],
      ["Published values gated", r.published_values_checked.toLocaleString("en"),
       `Checked across ${r.published_documents} documents by the publication gate; ${r.published_values_exempted} carry a written exemption.`],
      ["Archived result sets", r.result_sets.toLocaleString("en"),
       `${r.manifests_archived.toLocaleString("en")} run manifests under results_archive/.`],
      ["Withdrawal patterns", String(r.retraction_patterns),
       "Entries in RETRACTED.json that the gate refuses in any current document."],
      ["Package tree oid", r.package_tree_oid.slice(0, 12) + "…",
       "The content hash of aml-platform/src/aml, recorded by twelve derived artifacts."],
    ];
    for (const [dt, dd, note] of items) {
      box.append(el("div", { class: "fact" },
        el("dl", {}, el("dt", { text: dt }), el("dd", { text: dd })),
        el("p", { text: note })));
    }
  }

  const note = root.querySelector("#replay-note");
  if (note) {
    const rp = r.replay;
    clear(note);
    note.append(document.createTextNode(
      `The ${rp.bundles} row-level replay bundles — ${rp.files} Parquet files, ` +
      `${rp.rows.toLocaleString("en")} rows — are held privately while their CDLA ` +
      `redistribution status is unreviewed. `));
    note.append(el("code", { text: "row_level_data_included" }));
    note.append(document.createTextNode(
      ` is ${String(rp.row_level_data_included)} in the published inventory. ` +
      `Tests that need them skip, by name, with the reason printed. To run the full ` +
      `replay tier you obtain AMLworld from its own source and regenerate the bundles.`));
  }

  const footer = root.querySelector("#footer-build");
  if (footer) {
    footer.textContent =
      `Figures on this page are generated from ${data.release.source.replace("aml-platform/results_archive/", "results_archive/")} ` +
      `and the artifacts it indexes by ${data.generator}.`;
  }
}

export function renderWindows(data, root = document) {
  const tbody = root.querySelector("#window-table tbody");
  if (!tbody) return;
  clear(tbody);
  for (const w of data.windows) {
    for (const b of w.bands) {
      const tr = el("tr");
      tr.append(el("th", { scope: "row", text: w.rung }));
      tr.append(el("td", { class: "num", text: String(w.days) }));
      tr.append(el("td", { class: "num", text: `${w.head_days} / ${w.tail_days}` }));
      tr.append(el("td", { class: "num", text: String(b.budget) }));
      tr.append(el("td", { class: "num", text: `${fmt(b.pooled_low, 5)} – ${fmt(b.pooled_high, 5)}` }));
      tr.append(el("td", { class: "num", text: `${fmt(b.head_low, 5)} – ${fmt(b.head_high, 5)}` }));
      tr.append(el("td", { class: "num", text: `${fmt(b.tail_low, 5)} – ${fmt(b.tail_high, 5)}` }));
      tr.append(el("td", { class: "num", text: String(b.nonbinding_days ?? "—") }));
      tbody.append(tr);
    }
  }
}

export function renderLineages(data, root = document) {
  const box = root.querySelector("#lineage-lists");
  if (!box) return;
  clear(box);
  const reg = data.registry;
  const groups = [
    ["Canonical", reg.canonical, "The result a current document may quote."],
    ["Supporting", reg.supporting, "Archived evidence a canonical result rests on."],
    ["Superseded", reg.superseded, "Real, provenanced and withdrawn. Never shown as current on this site."],
  ];
  for (const [title, entries, note] of groups) {
    const names = Object.keys(entries).sort();
    const b = el("div", { class: "lineage-box" },
      el("h4", { text: `${title} · ${names.length}` }),
      el("p", { class: "note", text: note }));
    const ul = el("ul");
    for (const n of names) ul.append(el("li", {}, el("code", { text: n })));
    b.append(ul);
    box.append(b);
  }
  if (reg.tombstones.length) {
    const b = el("div", { class: "lineage-box" },
      el("h4", { text: `Tombstones · ${reg.tombstones.length}` }),
      el("p", { class: "note",
                text: "Named by an old registry, but no artifact was ever committed. They may not back any published value." }));
    const ul = el("ul");
    for (const n of reg.tombstones) ul.append(el("li", {}, el("code", { text: n })));
    b.append(ul);
    box.append(b);
  }
}

export function renderWithdrawn(data, root = document) {
  const tbody = root.querySelector("#withdrawn-table tbody");
  const summary = root.querySelector("#withdrawn-summary");
  if (summary) {
    summary.textContent = `Show the withdrawal register (${data.withdrawn.count} entries, all withdrawn)`;
  }
  if (!tbody) return;
  clear(tbody);
  for (const e of data.withdrawn.entries) {
    const tr = el("tr");
    tr.append(el("th", { scope: "row" },
      el("span", { class: "pill pill-withdrawn", text: "withdrawn" })));
    tr.append(el("td", { text: e.was }));
    tr.append(el("td", { text: e.now }));
    tr.append(el("td", { text: e.why }));
    tbody.append(tr);
  }
}
