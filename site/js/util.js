// Shared helpers. No dependencies, no globals beyond these exports.

export const REPO = "https://github.com/NirmalKumar31/aml-evaluation-harness";

/** Blob URL for a repo-relative artifact path, pinned to the released tag so
 *  a link keeps resolving to the bytes the number came from. */
export function artifactUrl(path, ref = "v0.2.1") {
  return `${REPO}/blob/${ref}/${path}`;
}

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) {
    if (kid === null || kid === undefined) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

export function svgEl(tag, attrs = {}, ...kids) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") n.textContent = v;
    else n.setAttribute(k, String(v));
  }
  for (const kid of kids) if (kid) n.append(kid);
  return n;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/** Fixed-decimal display. Returns an em dash for absent values so a blank
 *  cell is never mistaken for a zero. */
export function fmt(x, places = 5) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return Number(x).toFixed(places).replace(/0+$/, "").replace(/\.$/, "") || "0";
}

export function pct(x, places = 1) {
  if (x === null || x === undefined) return "—";
  return `${(Number(x) * 100).toFixed(places)}%`;
}

export function uniq(values) {
  return [...new Set(values)];
}

/** Sort that puts nulls last and compares numbers numerically. */
export function cmp(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en");
}

export function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
