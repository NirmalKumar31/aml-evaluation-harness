// The homepage's narrative contract.
//
// The page has one job: make a stranger understand the project and want to
// open one of the other two routes. These check the parts of that job a
// static read of the markup cannot — that the calls to action go where they
// say, that the story sections are present and in order, that the detail a
// reader did not ask for stays folded away, and that all of it survives with
// JavaScript switched off.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.resolve(HERE, "..", "_build");
const core = JSON.parse(fs.readFileSync(path.join(BUILD, "data/site-data.json"), "utf8"));

test("the hero states the constraint and offers two ways in", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  const h1 = page.locator("h1");
  await expect(h1).toHaveCount(1);
  await expect(h1).toContainText("rank millions of transactions");
  await expect(h1).toContainText("review only a few alerts");

  const primary = page.getByRole("link", { name: "Explore the findings" });
  const secondary = page.getByRole("link", { name: "See how it was engineered" });
  await expect(primary).toBeVisible();
  await expect(secondary).toBeVisible();
  await expect(primary).toBeInViewport();

  // The repository is a tertiary link, not a third button competing with them.
  const tertiary = page.locator(".hero-tertiary a");
  await expect(tertiary).toHaveAttribute(
    "href", "https://github.com/NirmalKumar31/aml-evaluation-harness");

  // The proof strip says what was measured without implying a full grid.
  const proof = page.locator(".hero-proof > div");
  await expect(proof).toHaveCount(4);
  await expect(page.locator(".hero-proof")).toContainText(
    core.scale.transactions_display);
});

test("each call to action lands on the route it names", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  await page.getByRole("link", { name: "Explore the findings" }).click();
  await expect(page).toHaveURL(/explorer\/$/);
  await expect(page.locator("h1")).toContainText("Canonical model evaluations");

  await page.goBack();
  await page.getByRole("link", { name: "See how it was engineered" }).click();
  await expect(page).toHaveURL(/engineering\/$/);

  await page.goBack();
  await page.getByRole("link", { name: "Open the results explorer" }).click();
  await expect(page).toHaveURL(/explorer\/$/);
});

test("the story sections appear once each, in order", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  const ids = ["hero-h", "problem-h", "solution-h", "findings-h", "useful-h",
               "who-h", "methods-h", "lim-h", "next-h"];
  const tops = [];
  for (const id of ids) {
    const el = page.locator(`#${id}`);
    await expect(el).toHaveCount(1);
    const box = await el.boundingBox();
    expect(box, `${id} has no box`).not.toBeNull();
    tops.push(box.y);
  }
  const sorted = [...tops].sort((a, b) => a - b);
  expect(tops).toEqual(sorted);
});

test("three findings, each with a conclusion, a boundary and a link", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  const cards = page.locator("#findings-h ~ * article.story, article.story");
  await expect(cards).toHaveCount(3);
  await expect(page.locator(".finding-says")).toHaveCount(3);
  await expect(page.locator(".reads-no")).toHaveCount(3);

  // Every chart is in the markup, not fetched.
  for (const id of ["split-sensitivity-svg", "seed-spread-svg", "scaling-svg"]) {
    await expect(page.locator(`#${id}`)).toBeVisible();
  }

  // The numbers on the page are the numbers in the data.
  const split = core.stories.find((s) => s.id === "split-sensitivity");
  await expect(page.locator("#story-split-sensitivity")).toContainText(
    `${split.pairs[0].pct}% higher`);
  const seeds = core.stories.find((s) => s.id === "seed-spread");
  await expect(page.locator("#story-seed-spread")).toContainText(
    String(seeds.spread_pct));
});

test("provenance is folded away until a reader asks for it", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  const provs = page.locator("details.prov");
  await expect(provs).toHaveCount(3);
  const first = provs.first();
  await expect(first.locator("ul")).toBeHidden();
  await first.locator("summary").click();
  await expect(first.locator("ul")).toBeVisible();
  const href = await first.locator("a.artifact").first().getAttribute("href");
  expect(href).toMatch(
    /^https:\/\/github\.com\/NirmalKumar31\/aml-evaluation-harness\/blob\/v0\.2\.1\//);
});

test("coverage is summarised here and detailed on the explorer", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator(".matrix")).toHaveCount(0);
  const rungs = page.locator(".rung-list li");
  await expect(rungs).toHaveCount(core.coverage.rungs.length);
  for (const row of core.coverage.rungs) {
    await expect(page.locator(".rung-list")).toContainText(row.rung);
  }
  await page.locator('a[href="explorer/#coverage"]').click();
  await expect(page).toHaveURL(/explorer\/#coverage$/);
  await expect(page.locator(".matrix")).toBeVisible();
});

test("one architecture preview here, the rest on the engineering page", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  await expect(page.locator(".arch-open")).toHaveCount(1);
  const opener = page.locator(".arch-open").first();
  await opener.scrollIntoViewIfNeeded();
  await opener.click();
  await expect(page.locator("#arch-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#arch-dialog")).toBeHidden();
  await expect(opener).toBeFocused();

  await page.getByRole("link", { name: /cloud-execution and delivery diagrams/ }).click();
  await expect(page).toHaveURL(/engineering\/$/);
  await expect(page.locator(".arch-open")).toHaveCount(3);
});

test("the five-stage method is readable without JavaScript", async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto("/_build/");
  await expect(page.locator(".pipeline .stage")).toHaveCount(5);
  await expect(page.locator("#funnel-svg")).toBeVisible();
  await expect(page.locator("#split-sensitivity-svg")).toBeVisible();
  await expect(page.locator(".finding-says")).toHaveCount(3);
  await expect(page.locator(".rung-list li")).toHaveCount(3);
  await expect(page.getByRole("link", { name: "Explore the findings" })).toBeVisible();
  await ctx.close();
});

test("the homepage claims no outcome it did not measure", async ({ page }) => {
  await page.goto("", { waitUntil: "networkidle" });
  const text = await page.locator("main").innerText();
  for (const claim of [/used by (banks?|investigators?)/i,
                       /prevents? (financial crime|money laundering)/i,
                       /reduces? losses/i,
                       /outperform/i,
                       /state-of-the-art/i]) {
    expect(text, `the page makes a claim it cannot support: ${claim}`)
      .not.toMatch(claim);
  }
  // And it does say where it does not fit.
  expect(text).toMatch(/not a live monitoring service/i);
  expect(text).toMatch(/no investigator ever worked one of these alerts/i);
});
