// Navigation: the small-screen disclosure and the current-section marker.

export function initNav(root = document) {
  const toggle = root.querySelector("#nav-toggle");
  const nav = root.querySelector("#site-nav");
  if (!toggle || !nav) return null;

  function setOpen(open) {
    nav.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
  }

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  // Choosing a destination on a phone should close the menu, and Escape
  // should return focus to the control that opened it.
  nav.addEventListener("click", (e) => {
    if (e.target.closest("a")) setOpen(false);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });

  // Reopening at a wider width must not leave the disclosure state stale.
  const wide = window.matchMedia("(min-width: 60rem)");
  const sync = () => { if (wide.matches) setOpen(false); };
  wide.addEventListener ? wide.addEventListener("change", sync) : wide.addListener(sync);

  const links = [...nav.querySelectorAll('a[href^="#"]')];
  const sections = links
    .map(a => root.getElementById(a.getAttribute("href").slice(1)))
    .filter(Boolean);

  function mark(id) {
    for (const a of links) {
      const isCurrent = a.getAttribute("href") === `#${id}`;
      if (isCurrent) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    }
  }

  if ("IntersectionObserver" in window && sections.length) {
    const seen = new Map();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(e.target.id, e.intersectionRatio);
      let best = null, bestRatio = 0;
      for (const [id, ratio] of seen) {
        if (ratio > bestRatio) { best = id; bestRatio = ratio; }
      }
      if (best) mark(best);
    }, { rootMargin: "-20% 0px -70% 0px", threshold: [0, 0.25, 0.5, 1] });
    for (const s of sections) io.observe(s);
  }

  return { setOpen, mark };
}
