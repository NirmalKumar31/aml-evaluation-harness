// The small-screen navigation disclosure.
//
// The current page is marked with aria-current in the generated HTML, so
// there is no scroll-spy here and nothing to keep in sync: three documents,
// three static markers.

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

  // Choosing a destination closes the menu; Escape closes it and returns
  // focus to the control that opened it, so keyboard users are never left
  // pointing at something that is no longer on screen.
  nav.addEventListener("click", (e) => {
    if (e.target.closest("a")) setOpen(false);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });

  // Widening the window must not leave a stale open state behind.
  const wide = window.matchMedia("(min-width: 60rem)");
  const sync = () => { if (wide.matches) setOpen(false); };
  if (wide.addEventListener) wide.addEventListener("change", sync);
  else wide.addListener(sync);

  return { setOpen };
}
