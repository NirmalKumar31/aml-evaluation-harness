// The explorer's contract: nothing offered is empty, nothing is ambiguous,
// and the simulator refuses what it cannot compute.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.resolve(HERE, "..", "_build");
const core = JSON.parse(fs.readFileSync(path.join(BUILD, "data/site-data.json"), "utf8"));
const rows = JSON.parse(fs.readFileSync(path.join(BUILD, "data/results.json"), "utf8")).results;

/** Choose an experiment the way a visitor does: by its card.
 *
 * The radio itself is visually hidden -- it is the accessible control, and
 * the card is its label -- so clicking the card is both what a person does
 * and what a keyboard user's Space key does. */
async function pick(page, id) {
  await page.locator(`label[for="exp-${id}"]`).click();
  await expect(page.locator(`#exp-${id}`)).toBeChecked();
}

async function open(page) {
  await page.goto("explorer/", { waitUntil: "networkidle" });
  await expect(page.locator("html")).toHaveAttribute("data-site-data", "loaded");
}

const opts = (page, id) =>
  page.locator(`#${id} option`).evaluateAll((os) => os.map((o) => o.value));

test("choosing an experiment offers only what that experiment contains", async ({ page }) => {
  await open(page);
  for (const e of core.experiments) {
    await pick(page, e.id);
    expect(await opts(page, "f-metric")).toEqual(e.metrics);
    const metric = await page.locator("#f-metric").inputValue();
    expect(await opts(page, "f-budget"))
      .toEqual(e.budgets_by_metric[metric].map(String));
  }
});

// THE WHOLE PRODUCT IS CHECKED IN THE PYTHON SUITE, over the same three maps
// the controls are built from, where it costs milliseconds. What has to be
// checked in a browser is different: that driving the controls really does
// walk those maps and never lands on an empty view. So every experiment,
// every metric and every budget is driven here, and the seed list is
// exercised at its ends.
test("no selectable combination returns zero rows", async ({ page }) => {
  test.slow();
  await open(page);
  const status = page.locator("#explorer-status");
  for (const e of core.experiments) {
    await pick(page, e.id);
    for (const metric of await opts(page, "f-metric")) {
      await page.locator("#f-metric").selectOption(metric);
      for (const budget of await opts(page, "f-budget")) {
        await page.locator("#f-budget").selectOption(budget);
        const seeds = await opts(page, "f-seed");
        expect(seeds.length, `${e.id} ${metric}@${budget} offers no seed`)
          .toBeGreaterThan(0);
        for (const seed of [seeds[0], seeds[seeds.length - 1]]) {
          await page.locator("#f-seed").selectOption(seed);
          await expect(status).not.toHaveClass(/is-empty/);
          await expect(status).toContainText(/^[1-9]\d* rows?/);
          const bars = await page.locator("#rc-svg g.run rect.bar").count();
          expect(bars, `${e.id} ${metric}@${budget} seed=${seed}`).toBeGreaterThan(0);
        }
      }
    }
  }
});

test("an invalid dependent choice resolves itself when the experiment changes",
  async ({ page }) => {
    await open(page);
    // HI-Medium offers ring_recall at k=1000; HI-Small's sweep offers
    // ring_recall only at k=200 and no other metric there at all.
    await pick(page, "medium-sweep");
    await page.locator("#f-metric").selectOption("ring_recall");
    await page.locator("#f-budget").selectOption("1000");
    await pick(page, "small-sweep");
    expect(await page.locator("#f-metric").inputValue()).toBe("ring_recall");
    expect(await page.locator("#f-budget").inputValue()).toBe("200");
    await expect(page.locator("#explorer-status")).not.toHaveClass(/is-empty/);

    // A metric the new experiment does not carry falls back to its first.
    await pick(page, "medium-sweep");
    await page.locator("#f-metric").selectOption("recall_efficiency");
    await page.locator("#f-budget").selectOption("1000");
    await pick(page, "small-sweep");
    expect(await opts(page, "f-metric")).toContain(
      await page.locator("#f-metric").inputValue());
    await expect(page.locator("#explorer-status")).not.toHaveClass(/is-empty/);
  });

test("reset returns the view to the experiment's first metric and budget",
  async ({ page }) => {
    await open(page);
    await pick(page, "medium-sweep");
    await page.locator("#f-metric").selectOption("ring_recall");
    await page.locator("#f-budget").selectOption("1000");
    await page.locator("#f-seed").selectOption("4");
    await page.locator("#f-reset").click();
    const e = core.experiments.find((x) => x.id === "medium-sweep");
    expect(await page.locator("#f-metric").inputValue()).toBe(e.metrics[0]);
    expect(await page.locator("#f-budget").inputValue())
      .toBe(String(e.budgets_by_metric[e.metrics[0]][0]));
    expect(await page.locator("#f-seed").inputValue()).toBe("");
  });

test("chart labels are unique in every view", async ({ page }) => {
  await open(page);
  for (const e of core.experiments) {
    await pick(page, e.id);
    for (const metric of await opts(page, "f-metric")) {
      await page.locator("#f-metric").selectOption(metric);
      const labels = await page.locator("#rc-svg g.run text.bar-label")
        .evaluateAll((ts) => ts.map((t) => t.textContent));
      expect(labels.length).toBeGreaterThan(0);
      expect(new Set(labels).size, `${e.id} ${metric}: ${labels}`).toBe(labels.length);
    }
  }
});

test("switching experiments keeps one bar per run and no stale bars", async ({ page }) => {
  await open(page);
  for (const id of ["medium-sweep", "large-cloud", "medium-baseline", "small-sweep"]) {
    await pick(page, id);
    const metric = await page.locator("#f-metric").inputValue();
    const budget = Number(await page.locator("#f-budget").inputValue());
    const expected = rows.filter((r) =>
      r.experiment === id && r.metric === metric && r.budget === budget).length;
    await expect(page.locator("#rc-svg g.run")).toHaveCount(expected);
  }
});

test("the row table paginates and never shows more than a page", async ({ page }) => {
  await open(page);
  await pick(page, "medium-sweep");
  await page.locator("#rows-block").evaluate((d) => { d.open = true; });
  const body = page.locator("#rows-body tr");
  expect(await body.count()).toBeLessThanOrEqual(12);
  expect(await body.count()).toBeGreaterThanOrEqual(10);
  await expect(page.locator("#rows-prev")).toBeDisabled();
  const first = await body.first().textContent();
  await page.locator("#rows-next").click();
  await expect(page.locator("#rows-state")).toContainText("Page 2 of");
  expect(await body.first().textContent()).not.toBe(first);
  await page.locator("#rows-prev").click();
  await expect(page.locator("#rows-state")).toContainText("Page 1 of");
});

test("every displayed value carries a link to the artifact it came from",
  async ({ page }) => {
    await open(page);
    await page.locator("#rows-block").evaluate((d) => { d.open = true; });
    const hrefs = await page.locator("#rows-body a.artifact")
      .evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    expect(hrefs.length).toBeGreaterThan(0);
    for (const h of hrefs) {
      expect(h).toMatch(
        /^https:\/\/github\.com\/NirmalKumar31\/aml-evaluation-harness\/blob\/v0\.2\.1\//);
    }
    const prov = await page.locator("#rc-prov a.artifact").count();
    expect(prov).toBeGreaterThan(0);
  });

test("the simulator computes the five identities and refuses impossible days",
  async ({ page }) => {
    await open(page);
    await page.locator("#sim-n").fill("5000");
    await page.locator("#sim-p").fill("40");
    await page.locator("#sim-k").fill("50");
    await expect(page.locator("#sim-error")).toHaveText("");
    await expect(page.locator("#sim-prev")).toHaveText("0.008");
    await expect(page.locator("#sim-rprec")).toHaveText("0.008");
    await expect(page.locator("#sim-rrec")).toHaveText("0.01");
    await expect(page.locator("#sim-ceil")).toHaveText("1");
    await expect(page.locator("#sim-pceil")).toHaveText("0.8");
    await expect(page.locator("#sim-binds")).toContainText("yes");

    // k >= N: the budget stops binding and nothing is being ranked.
    await page.locator("#sim-k").fill("5000");
    await expect(page.locator("#sim-binds")).toContainText("no");

    // More positives than candidates is not a day.
    await page.locator("#sim-p").fill("6000");
    await expect(page.locator("#sim-error"))
      .toHaveText("There cannot be more positives than candidates.");
    await expect(page.locator("#sim-prev")).toHaveText("—");
  });

test("with no positives, recall is undefined rather than zero", async ({ page }) => {
  await open(page);
  await page.locator("#sim-n").fill("5000");
  await page.locator("#sim-p").fill("0");
  await page.locator("#sim-k").fill("50");
  await expect(page.locator("#sim-error")).toHaveText("");
  await expect(page.locator("#sim-rprec")).toHaveText("0");
  await expect(page.locator("#sim-pceil")).toHaveText("0");
  await expect(page.locator("#sim-rrec")).toHaveText("undefined — no positive account-days");
  await expect(page.locator("#sim-ceil")).toHaveText("undefined — no positive account-days");
  // No bar may be drawn for an undefined quantity.
  const labels = await page.locator("#sim-chart text.bar-label")
    .evaluateAll((ts) => ts.map((t) => t.textContent));
  expect(labels).toEqual(["Random-ranker precision@k", "Attainable precision ceiling"]);
});

test("the coverage matrix says the same thing the data does", async ({ page }) => {
  await open(page);
  for (const row of core.coverage.rungs) {
    for (const cell of row.cells) {
      const td = page.locator(
        `.matrix tbody tr:has(th:text-is("${row.rung}")) td`)
        .nth(core.coverage.families.findIndex((f) => f.id === cell.family));
      await expect(td.locator(".chip")).toHaveText(
        { measured: "measured", diagnostic: "diagnostic only", "not-run": "not run" }[cell.state]);
      await expect(td.locator(".cell-note")).toContainText(cell.short);
    }
  }
});

test("the budget switcher on the homepage works without JavaScript", async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto("/_build/");
  await expect(page.locator("#nullband-50-svg")).toBeVisible();
  await expect(page.locator("#nullband-200-svg")).toBeHidden();
  await page.locator('label[for="nb-200"]').click();
  await expect(page.locator("#nullband-200-svg")).toBeVisible();
  await expect(page.locator("#nullband-50-svg")).toBeHidden();
  // The three findings are in the HTML, not fetched.
  await expect(page.locator("#story-seed-spread svg")).toBeVisible();
  await expect(page.locator("#story-scaling svg")).toBeVisible();
  await ctx.close();
});
