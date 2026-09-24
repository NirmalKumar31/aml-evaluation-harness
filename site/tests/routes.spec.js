// Route-level contracts: the three documents load clean, nothing 404s,
// nothing overflows, and every interactive control can be driven from the
// keyboard.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.resolve(HERE, "..", "_build");
const ROUTES = ["", "explorer/", "engineering/"];

/** Console errors and failed requests, collected for one page. */
function watch(page) {
  const problems = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) =>
    problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
  page.on("response", (r) => {
    if (r.status() >= 400) problems.push(`http ${r.status()}: ${r.url()}`);
  });
  return problems;
}

for (const route of ROUTES) {
  test(`route "/${route}" loads with no console error and no failed request`, async ({ page }) => {
    const problems = watch(page);
    const res = await page.goto(route, { waitUntil: "networkidle" });
    expect(res.status()).toBe(200);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("main#main")).toBeVisible();
    await expect(page.locator("header.site-header")).toBeVisible();
    await expect(page.locator("footer.site-footer")).toBeVisible();
    expect(problems).toEqual([]);
  });

  test(`route "/${route}" has a working skip link`, async ({ page }) => {
    await page.goto(route);
    await page.keyboard.press("Tab");
    const skip = page.locator("a.skip");
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await skip.press("Enter");
    expect(await page.evaluate(() => window.location.hash)).toBe("#main");
  });

  for (const width of [320, 390, 768, 1024, 1440]) {
    test(`route "/${route}" does not overflow horizontally at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route, { waitUntil: "networkidle" });
      // Open every disclosure: a table hidden inside <details> can still
      // widen the document once it is shown.
      await page.evaluate(() => {
        for (const d of document.querySelectorAll("details")) d.open = true;
      });
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1);
    });
  }

  test(`route "/${route}" keeps its headings in order`, async ({ page }) => {
    await page.goto(route);
    const levels = await page.evaluate(() =>
      [...document.querySelectorAll("main h1, main h2, main h3, main h4")]
        .map((h) => Number(h.tagName.slice(1))));
    expect(levels[0]).toBe(1);
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
    }
  });
}

test("the small-screen menu opens, closes with Escape and returns focus @mobile", async ({ page }) => {
  await page.goto("");
  const toggle = page.locator("#nav-toggle");
  const nav = page.locator("#site-nav");
  await expect(toggle).toBeVisible();
  await expect(nav).toBeHidden();
  await toggle.click();
  await expect(nav).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(nav).toBeHidden();
  await expect(toggle).toBeFocused();
});

test("every route is reachable from every other route", async ({ page }) => {
  await page.goto("");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Results explorer" }).click();
  await expect(page).toHaveURL(/explorer\/$/);
  await page.getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Engineering & MLOps" }).click();
  await expect(page).toHaveURL(/engineering\/$/);
  await page.getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Home", exact: true }).click();
  await expect(page).toHaveURL(/_build\/$/);
});

for (const route of ["", "engineering/"]) {
  test(`the architecture dialog on "/${route}" opens, closes with Escape and restores focus`,
    async ({ page }) => {
      await page.goto(route, { waitUntil: "networkidle" });
      const opener = page.locator(".arch-open").first();
      await opener.scrollIntoViewIfNeeded();
      await opener.click();
      const dialog = page.locator("#arch-dialog");
      await expect(dialog).toBeVisible();
      await expect(page.locator("#arch-close")).toBeFocused();
      // Exactly one diagram is shown at a time.
      const visible = await page.locator(".arch-panel:not([hidden])").count();
      expect(visible).toBe(1);

      // A DENSE DIAGRAM NEEDS A WAY OUT OF THE DIALOG. The dialog scales the
      // picture to the viewport, which is not readable on a phone, so the
      // panel links to the asset itself where the browser's zoom works.
      const full = page.locator(".arch-panel:not([hidden]) a.arch-full");
      await expect(full).toHaveCount(1);
      const href = await full.getAttribute("href");
      expect(href).toMatch(/assets\/0\d-[a-z-]+\.svg$/);
      const asset = await page.request.get(new URL(href, page.url()).toString());
      expect(asset.status()).toBe(200);
      // The declared box must be the SVG's own, or the page shifts on load.
      const img = page.locator(".arch-panel:not([hidden]) img");
      const dims = await img.evaluate((n) => ({
        w: n.getAttribute("width"), h: n.getAttribute("height"),
        nw: n.naturalWidth, nh: n.naturalHeight }));
      expect(`${dims.nw}x${dims.nh}`).toBe(`${dims.w}x${dims.h}`);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(opener).toBeFocused();
    });

  test(`the architecture dialog on "/${route}" opens from the keyboard`, async ({ page }) => {
    await page.goto(route, { waitUntil: "networkidle" });
    const opener = page.locator(".arch-open").first();
    await opener.scrollIntoViewIfNeeded();
    await opener.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#arch-dialog")).toBeVisible();
    await page.locator("#arch-close").click();
    await expect(page.locator("#arch-dialog")).toBeHidden();
    await expect(opener).toBeFocused();
  });
}

test("reduced motion stops the hero animation", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto("/_build/", { waitUntil: "networkidle" });
  const read = () => page.evaluate(() =>
    [...document.querySelectorAll(".hero-net .node")]
      .map((n) => `${n.getAttribute("cx")},${n.getAttribute("cy")}`).join("|"));
  const before = await read();
  await page.waitForTimeout(700);
  expect(await read()).toBe(before);
  await ctx.close();
});

test("the hero animates when motion is allowed", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  await page.goto("/_build/", { waitUntil: "networkidle" });
  const read = () => page.evaluate(() =>
    [...document.querySelectorAll(".hero-net .node")]
      .map((n) => `${n.getAttribute("cx")},${n.getAttribute("cy")}`).join("|"));
  const before = await read();
  await page.waitForTimeout(700);
  expect(await read()).not.toBe(before);
  await ctx.close();
});

test("every file in the deployed artifact is served", async ({ request }) => {
  const files = [];
  const walk = (dir, prefix = "") => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) walk(path.join(dir, entry.name), `${prefix}${entry.name}/`);
      else files.push(`${prefix}${entry.name}`);
    }
  };
  walk(BUILD);
  expect(files.length).toBeGreaterThanOrEqual(13);
  for (const f of files) {
    const res = await request.get(f);
    expect(res.status(), `${f} should be served`).toBe(200);
  }
});

test("the site asks for nothing from anywhere else, and stores nothing", async ({ page }) => {
  const external = [];
  page.on("request", (r) => {
    if (!r.url().startsWith("http://127.0.0.1:")) external.push(r.url());
  });
  for (const route of ROUTES) {
    await page.goto(route, { waitUntil: "networkidle" });
  }
  expect(external).toEqual([]);
  const stored = await page.evaluate(() => ({
    cookies: document.cookie,
    local: window.localStorage.length,
    session: window.sessionStorage.length,
  }));
  expect(stored).toEqual({ cookies: "", local: 0, session: 0 });
});


// A phone-width pass over all three routes: the content is there, the
// navigation is reachable, and nothing spills sideways.
for (const route of ROUTES) {
  test(`route "/${route}" is usable at phone width @mobile`, async ({ page }) => {
    const problems = watch(page);
    await page.goto(route, { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.locator("#nav-toggle")).toBeVisible();
    const box = await page.locator("#nav-toggle").boundingBox();
    // A tap target a thumb can actually hit.
    expect(box.height).toBeGreaterThanOrEqual(32);
    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1);
    expect(problems).toEqual([]);
  });
}
