// The architecture dialog.
//
// One <dialog> holds all three diagrams; opening one unhides its panel and
// hides the rest. showModal() gives the focus trap, the inert background and
// Escape-to-close for free -- and where <dialog> is unsupported the button
// falls back to opening the SVG in a new tab, which is still a full-size
// view rather than a dead control.

export function initLightbox(root = document) {
  const dialog = root.querySelector("#arch-dialog");
  const openers = [...root.querySelectorAll(".arch-open")];
  if (!dialog || !openers.length) return null;

  const heading = root.querySelector("#arch-dialog-h");
  const closeBtn = root.querySelector("#arch-close");
  const panels = [...dialog.querySelectorAll(".arch-panel")];
  const supported = typeof dialog.showModal === "function";
  let opener = null;

  function show(id, button) {
    let title = "Architecture diagram";
    for (const p of panels) {
      const mine = p.id === `arch-panel-${id}`;
      p.hidden = !mine;
      if (mine) {
        const strong = p.querySelector("figcaption strong");
        if (strong) title = strong.textContent.trim();
      }
    }
    heading.textContent = title;
    opener = button;
    dialog.showModal();
    closeBtn.focus();
  }

  for (const button of openers) {
    if (!supported) {
      const img = button.querySelector("img");
      button.addEventListener("click", () => { if (img) window.open(img.src, "_blank"); });
      continue;
    }
    button.addEventListener("click", () => show(button.dataset.diagram, button));
  }
  if (!supported) return { supported: false };

  closeBtn.addEventListener("click", () => dialog.close());

  // Clicking the backdrop closes it. The dialog element itself is the click
  // target when the backdrop is hit, because the content sits in children.
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });

  // FOCUS GOES BACK WHERE IT CAME FROM. This fires for Escape too, because
  // Escape closes a modal dialog natively and still emits `close`.
  dialog.addEventListener("close", () => {
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  });

  return { show, supported: true };
}
