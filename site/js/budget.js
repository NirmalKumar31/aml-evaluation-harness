// The alert-budget simulator.
//
// SYNTHETIC INPUTS ONLY. Nothing here reads the project's data, and the page
// says so beside the controls: these are one-day identities, while the
// project's evaluation is slot-weighted across days of very different size.
// Aggregating N, P and k over a window and feeding them in here does NOT
// reproduce a published number, and presenting it as if it did would be the
// exact pooling error the harness exists to expose.

import { el, svgEl, clear, fmt, pct } from "./util.js";

/** The five identities the explainer teaches. Pure, so the tests can call it
 *  directly. Returns null when the inputs are not a coherent day. */
export function simulate(N, P, k) {
  if (!Number.isFinite(N) || !Number.isFinite(P) || !Number.isFinite(k)) return null;
  if (!Number.isInteger(N) || !Number.isInteger(P) || !Number.isInteger(k)) return null;
  if (N < 1 || k < 1 || P < 0) return null;
  if (P > N) return null;

  const reviewed = Math.min(k, N);           // slots that can actually be used
  const prevalence = P / N;

  // WITH NO POSITIVES, RECALL HAS NO DENOMINATOR.
  //
  // `min(k, N) / N` is the share of the population a random ranker reviews,
  // which is a real quantity -- but it is only recall when there is a
  // positive to recall. At P = 0 both recall and its ceiling are 0/0, and
  // printing 0.05 for "random-ranker recall" on a day with nothing to find
  // states a rate for an empty set. Precision is different: it is 0 out of
  // the reviewed slots, which is defined and correct.
  const noPositives = P === 0;
  return {
    N, P, k,
    reviewed,
    prevalence,
    randomPrecision: prevalence,                             // P / N
    randomRecall: noPositives ? null : reviewed / N,         // min(k, N) / N
    recallCeiling: noPositives ? null : Math.min(P, k) / P,  // min(P, k) / P
    precisionCeiling: Math.min(P, k) / reviewed,
    binds: k < N,
  };
}

/** The message for an input combination the simulator refuses. */
export function validate(N, P, k) {
  if (![N, P, k].every(Number.isFinite)) return "Enter a number in every field.";
  if (![N, P, k].every(Number.isInteger)) return "Counts and budgets are whole numbers.";
  if (N < 1) return "There must be at least one candidate account-day.";
  if (k < 1) return "The review budget must be at least 1.";
  if (P < 0) return "The positive count cannot be negative.";
  if (P > N) return "There cannot be more positives than candidates.";
  return null;
}

function bar(x, y, w, h, cls, title) {
  const r = svgEl("rect", { x, y, width: Math.max(w, 0), height: h, class: cls, rx: 2 });
  if (title) r.append(svgEl("title", { text: title }));
  return r;
}

function drawChart(svg, s) {
  clear(svg);
  const W = 760, rowH = 44, padL = 0, padR = 70, padT = 8;
  // An undefined quantity gets no bar. A zero-length bar would read as
  // "measured, and it is zero".
  const rows = [
    ["Random-ranker precision@k", s.randomPrecision, "bar bar-1"],
    ["Attainable precision ceiling", s.precisionCeiling, "bar"],
    ["Random-ranker recall@k", s.randomRecall, "bar bar-1"],
    ["Attainable recall ceiling", s.recallCeiling, "bar"],
  ].filter(([, v]) => v !== null && v !== undefined);

  // The label sits above its own bar rather than in a left-hand column:
  // four long labels in a gutter would either wrap or force the plot into a
  // sliver on a phone.
  const H = padT + rows.length * rowH + 34;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const plotW = W - padL - padR;
  const axisY = padT + rows.length * rowH;
  svg.append(svgEl("line", { x1: padL, y1: axisY, x2: padL + plotW, y2: axisY,
                             class: "ax" }));
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    const x = padL + t * plotW;
    svg.append(svgEl("line", { x1: x, y1: axisY, x2: x, y2: axisY + 5, class: "tick" }));
    svg.append(svgEl("text", { x, y: axisY + 17, class: "tick-label",
                               "text-anchor": "middle", text: t.toFixed(2) }));
  }

  rows.forEach(([label, value, cls], i) => {
    const y = padT + i * rowH + 18;
    const h = 16;
    svg.append(svgEl("text", { x: padL, y: y - 5, class: "bar-label", text: label }));
    svg.append(bar(padL, y, value * plotW, h, cls, `${label}: ${fmt(value, 4)}`));
    svg.append(svgEl("text", { x: padL + value * plotW + 8, y: y + h - 3,
                               class: "bar-value", text: fmt(value, 4) }));
  });
}

/** An undefined quantity is written out, not printed as a number. */
function setValue(node, value, undefinedText) {
  if (value === null || value === undefined) {
    node.textContent = undefinedText;
    node.classList.add("undefined");
  } else {
    node.textContent = fmt(value, 6);
    node.classList.remove("undefined");
  }
}

export function initBudgetSimulator(root = document) {
  const form = root.querySelector("#sim-form");
  if (!form) return null;
  const inN = root.querySelector("#sim-n");
  const inP = root.querySelector("#sim-p");
  const inK = root.querySelector("#sim-k");
  const err = root.querySelector("#sim-error");
  const svg = root.querySelector("#sim-chart");
  const desc = root.querySelector("#sim-chart-desc");
  const out = {
    prev: root.querySelector("#sim-prev"),
    rprec: root.querySelector("#sim-rprec"),
    rrec: root.querySelector("#sim-rrec"),
    ceil: root.querySelector("#sim-ceil"),
    pceil: root.querySelector("#sim-pceil"),
    binds: root.querySelector("#sim-binds"),
  };

  function render() {
    const N = inN.valueAsNumber, P = inP.valueAsNumber, k = inK.valueAsNumber;
    const problem = validate(N, P, k);
    if (problem) {
      err.textContent = problem;
      for (const n of Object.values(out)) {
        n.textContent = "—";
        n.classList.remove("undefined");
      }
      clear(svg);
      desc.textContent = "";
      return;
    }
    err.textContent = "";
    const s = simulate(N, P, k);
    const undef = "undefined — no positive account-days";
    out.prev.textContent = fmt(s.prevalence, 6);
    out.rprec.textContent = fmt(s.randomPrecision, 6);
    setValue(out.rrec, s.randomRecall, undef);
    setValue(out.ceil, s.recallCeiling, undef);
    out.pceil.textContent = fmt(s.precisionCeiling, 6);

    clear(out.binds);
    out.binds.append(el("span", {
      class: `chip ${s.binds ? "chip-measured" : "chip-not-run"}`,
      text: s.binds ? "yes" : "no — every candidate is alerted",
    }));

    drawChart(svg, s);
    desc.textContent =
      `One day with ${s.N.toLocaleString("en")} candidate account-days, ` +
      `${s.P.toLocaleString("en")} of them positive, and a budget of ` +
      `${s.k.toLocaleString("en")}. A random ranker reaches precision ` +
      `${fmt(s.randomPrecision, 4)}. ` +
      (s.randomRecall === null
        ? "Recall and its ceiling are undefined on a day with no positive " +
          "account-days, so neither is plotted. "
        : `Random-ranker recall is ${fmt(s.randomRecall, 4)} and the attainable ` +
          `recall ceiling is ${fmt(s.recallCeiling, 4)}. `) +
      `The budget ${s.binds ? "binds" : "does not bind, so no ranking is being tested"}.`;
  }

  for (const input of [inN, inP, inK]) {
    input.addEventListener("input", render);
    input.addEventListener("change", render);
  }
  render();
  return { render, simulate, validate };
}
