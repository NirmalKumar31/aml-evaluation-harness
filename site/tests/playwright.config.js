// Browser tests for the built site.
//
// THE SERVER ROOT IS NOT THE SITE ROOT. The site is served at `/_build/`
// rather than `/`, because GitHub Pages serves this project under
// `/aml-evaluation-harness/`. Any absolute path that crept into a page would
// resolve to the wrong place here and the tests would see it.
//
// The browser is the one already installed on the machine: `channel: chrome`
// with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD set in CI, so no unpinned binary is
// fetched at test time.
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.SITE_TEST_PORT || 4173);
const BASE = `http://127.0.0.1:${PORT}/_build/`;

export default defineConfig({
  testDir: ".",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    channel: "chrome",
    trace: "off",
    screenshot: "off",
  },
  // TWO PROJECTS, NOT TWO COPIES. Every test that cares about a width sets
  // that width itself, so running the whole file twice would only buy the
  // same assertions again at twice the cost. The mobile project therefore
  // runs the tests tagged @mobile, and the desktop project runs the rest.
  projects: [
    {
      name: "desktop",
      grepInvert: /@mobile/,
      use: { ...devices["Desktop Chrome"], channel: "chrome",
             viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      grep: /@mobile/,
      use: { ...devices["Desktop Chrome"], channel: "chrome",
             viewport: { width: 390, height: 844 }, hasTouch: true },
    },
  ],
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory ..`,
    url: `${BASE}index.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
