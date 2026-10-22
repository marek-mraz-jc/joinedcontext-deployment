// T-5122: a dataset page with many charts starts their frames one at a time and only near the
// screen, so a phone downloads each renderer once. jc-viz.js runs as the CKAN theme ships it.
//   npm i --no-save --no-package-lock @playwright/test@1.63.0 (chromium 1243, as the Portal pins)
//   PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright test -c components/viz/tests frames
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const queue = readFileSync(path.join(here, "../../../charts/ckan/files/jc_theme/public__jc-viz.js"), "utf8");
const VIZ = "viz.dev.joinedcontext.com";
const CATALOGUE = "opendata.dev.joinedcontext.com";

test("charts near the screen start one after another, a chart far below waits for the scroll", async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const frame = (n, gap) => `<div style="height:${gap}px"></div><iframe id="f${n}" class="jc-viz-frame" loading="lazy"
    title="Chart ${n}" data-src="https://${VIZ}/c${n}/#chart-${n}&inline" data-jc-viz="https://${VIZ}" style="height:200px"></iframe>`;
  let active = 0;
  let most = 0;
  const started = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === CATALOGUE) {
      // Two charts on screen, one just below it, one 4 000 px down; the template's tag twice.
      const body = `<!doctype html><title>dataset</title>${frame(1, 0)}${frame(2, 0)}${frame(3, 300)}${frame(4, 4000)}
        <script>${queue}</script><script>${queue}</script>`;
      return route.fulfill({ status: 200, contentType: "text/html", body });
    }
    if (url.hostname === VIZ) {
      started.push(`chart-${url.pathname.slice(2, -1)}`);
      active += 1;
      most = Math.max(most, active);
      await new Promise((resolve) => setTimeout(resolve, 300));
      active -= 1;
      return route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><p>chart</p>" });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  await page.goto(`https://${CATALOGUE}/dataset/charts`);
  await expect.poll(() => started.length).toBe(3);
  await page.waitForTimeout(1000);
  expect(started).toEqual(["chart-1", "chart-2", "chart-3"]);
  expect(most).toBe(1);
  await expect(page.locator("#f4")).not.toHaveAttribute("src");
  await page.locator("#f4").scrollIntoViewIfNeeded();
  await expect.poll(() => started).toEqual(["chart-1", "chart-2", "chart-3", "chart-4"]);
  await expect(page.locator("#f4")).toHaveAttribute("src", `https://${VIZ}/c4/#chart-4&inline`);
});
