// Scroll reveal, applied only where it cannot do harm.
//
// AN ELEMENT IS ONLY HIDDEN IF IT IS ALREADY BELOW THE FOLD. Hiding content
// that is on screen at load would cost a repaint of the largest element and
// would leave the page blank if this module ever failed to run. So the first
// screen is never touched, and if the observer is unavailable nothing is
// hidden at all.

import { prefersReducedMotion } from "./util.js";

export function initReveal(root = document) {
  const targets = [...root.querySelectorAll(".reveal")];
  if (!targets.length) return null;
  if (prefersReducedMotion() || !("IntersectionObserver" in window)) return null;

  const fold = window.innerHeight;
  const pending = targets.filter((t) => t.getBoundingClientRect().top > fold * 1.05);
  for (const t of pending) t.classList.add("pending");

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.remove("pending");
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
  for (const t of pending) io.observe(t);

  return { pending: pending.length };
}
