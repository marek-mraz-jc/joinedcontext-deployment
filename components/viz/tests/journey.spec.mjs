// T-4641: the chart renderer in a browser. The three hosts are routed to this repository's files
// (viz.{domain}, with the headers nginx.conf sets) and to answers shaped like dev's (CKAN's
// resource_view_show, the Endpoint's OData, NGSI-LD and temporal answers of 2026-10-18), so the
// journey runs anywhere: the good specs draw, the hostile ones draw nothing and ask no other host,
// and the renderer frame cannot read a cookie.
//   npm i --no-save --no-package-lock @playwright/test@1.62.1
//   PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright test -c components/viz/tests
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const chart = path.join(here, "../charts/renderer");
const vendor = path.join(here, "../../../images/viz/vendor");
const DOMAIN = "dev.joinedcontext.com";
const VIZ = `viz.${DOMAIN}`;
const SLUG = "3iasem46w7d7pxxypwdfdzheyaodv3qn";
const OURS = new Set([VIZ, `api.${DOMAIN}`, `data.${DOMAIN}`, `tiles.${DOMAIN}`, `assistant.${DOMAIN}`]);

// The CSP of each page, read from nginx.conf as the chart renders it.
const conf = readFileSync(path.join(chart, "files/nginx.conf"), "utf8").replaceAll("__HOST__", VIZ).replaceAll("__DOMAIN__", DOMAIN);
const csp = (location) => {
  const block = conf.slice(conf.indexOf(`location = ${location} {`));
  return /Content-Security-Policy "([^"]+)"/.exec(block)[1];
};

const STATIONS = {
  "urn:ngsi-ld:WeatherObserved:banskabystrica.sk:banskabystrica-verejne:shmu-11894": "Stanica SHMÚ Donovaly",
  "urn:ngsi-ld:WeatherObserved:banskabystrica.sk:banskabystrica-verejne:shmu-11898": "Stanica SHMÚ Banská Bystrica - Zelená"
};
const hours = (start, values) => values.map((v, i) => {
  const from = new Date(Date.parse(start) + i * 3600e3).toISOString().replace(".000", "");
  const to = new Date(Date.parse(start) + (i + 1) * 3600e3).toISOString().replace(".000", "");
  return [v, from, to];
});
const TEMPORAL = Object.keys(STATIONS).map((id, n) => ({
  id, type: "WeatherObserved",
  temperature: { type: "Property", avg: hours("2026-10-17T16:02:33Z", [9.02, 8.6, 9.2, 8.5, 7.2, 7.1, 7.7, 8.3, 7.8, 7.1, 6.5, 6.6].map((v) => v + n * 3)) }
}));
const ODATA = {
  value: [
    { id: Object.keys(STATIONS)[0], dateObserved: "2026-10-18T15:40:00Z", name: null, temperature: 11.5 },
    { id: Object.keys(STATIONS)[1], dateObserved: "2026-10-18T15:43:00Z", name: null, temperature: 13.4 }
  ]
};
const NAMES = Object.entries(STATIONS).map(([id, name]) => ({ id, name }));

const VL = "https://vega.github.io/schema/vega-lite/v5.json";
const temporal = { source: "temporal", type: "WeatherObserved", attrs: ["temperature"], last: "PT24H", aggrMethod: "avg", aggrPeriod: "PT1H" };
const odata = { source: "odata", entitySet: "WeatherObserved", $select: "name,temperature,dateObserved", $orderby: "temperature desc" };
const SPECS = {
  // The example of docs Architecture/04 §3a: temperature per station over 24 hours.
  line: [temporal, {
    $schema: VL, data: { name: "source" },
    params: [{ name: "station", select: { type: "point", fields: ["name"] }, bind: "legend" }],
    mark: { type: "line", point: true },
    encoding: {
      x: { field: "observedAt", type: "temporal", title: null },
      y: { field: "temperature", type: "quantitative", title: "°C", scale: { zero: false } },
      color: { field: "name", type: "nominal", title: null },
      opacity: { condition: { param: "station", value: 1 }, value: 0.2 }
    }
  }],
  bar: [odata, {
    $schema: VL, data: { name: "source" }, mark: "bar",
    encoding: { y: { field: "name", type: "nominal", sort: "-x", title: null }, x: { field: "temperature", type: "quantitative", title: "°C" } }
  }],
  // Two linked views: a time brush on the line filters the bar of the mean per station.
  brush: [temporal, {
    $schema: VL, data: { name: "source" },
    vconcat: [
      {
        params: [{ name: "time", select: { type: "interval", encodings: ["x"] } }],
        mark: "line",
        encoding: { x: { field: "observedAt", type: "temporal" }, y: { field: "temperature", type: "quantitative" }, color: { field: "name", type: "nominal" } }
      },
      {
        transform: [{ filter: { param: "time" } }],
        mark: "bar",
        encoding: { x: { aggregate: "mean", field: "temperature", type: "quantitative" }, y: { field: "name", type: "nominal" } }
      }
    ]
  }],
  dataUrl: [odata, { $schema: VL, data: { url: "https://evil.example/rows.csv" }, mark: "bar" }],
  javascriptHref: [odata, { $schema: VL, data: { name: "source" }, mark: "bar", encoding: { href: { value: "javascript:alert(1)" } } }],
  windowExpr: [odata, { $schema: VL, data: { name: "source" }, transform: [{ calculate: "window.location.href", as: "x" }], mark: "bar" }]
};
const ids = Object.fromEntries(Object.keys(SPECS).map((k, i) => [k, `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`]));
const view = (key) => {
  const [source, spec] = SPECS[key];
  return {
    id: ids[key], view_type: "jc_visualization", package_id: "pocasie", title: key, description: "",
    titles: JSON.stringify({ sk: `Graf ${key}`, en: `Chart ${key}` }), spec: JSON.stringify(spec),
    source: JSON.stringify(source), endpoint: SLUG
  };
};

export async function serve(context, { trustless = false } = {}) {
  const requests = [];
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const json = (body) => route.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": `https://${VIZ}` }, body: JSON.stringify(body) });
    if (url.hostname === VIZ) {
      const file = url.pathname === "/" ? "site/index.html" : url.pathname.startsWith("/vendor/") ? url.pathname.slice(1) : `site${url.pathname}`;
      const page = ["/", "/render.html", "/map.html"].includes(url.pathname);
      const headers = { "Content-Security-Policy": page ? csp(url.pathname) : "default-src 'none'; frame-ancestors 'none'" };
      // The second line of defence alone: the renderer with its refusal list switched off.
      if (trustless && url.pathname === "/refuse.js") {
        return route.fulfill({ status: 200, contentType: "text/javascript", headers, body: "self.jcRefuse = function () { return []; };" });
      }
      try {
        // MapLibre's modules are stored gzipped; nginx unpacks them (gzip_static), so does this.
        const at = file.startsWith("vendor/") ? path.join(vendor, file.slice("vendor/".length)) : path.join(chart, "files", file);
        const body = file.endsWith(".mjs") ? gunzipSync(readFileSync(at + ".gz")) : readFileSync(at);
        const type = file.endsWith(".html") ? "text/html" : file.endsWith(".css") ? "text/css" : "text/javascript";
        return route.fulfill({ status: 200, contentType: type, headers, body });
      } catch {
        return route.fulfill({ status: 404, body: "" });
      }
    }
    if (url.hostname === `data.${DOMAIN}` && url.pathname === "/api/3/action/resource_view_show") {
      const key = Object.keys(ids).find((k) => ids[k] === url.searchParams.get("id"));
      return key ? json({ success: true, result: view(key) }) : route.fulfill({ status: 404, body: "{}" });
    }
    if (url.hostname === `data.${DOMAIN}`) {
      // The catalogue's dataset page, as jc/visualization.html renders it.
      const key = url.pathname.split("/").pop();
      return route.fulfill({
        status: 200, contentType: "text/html",
        body: `<!doctype html><title>dataset</title><iframe id="viz" data-jc-viz="https://${VIZ}" style="width:100%;height:420px;border:0"
          sandbox="allow-scripts allow-same-origin allow-downloads" src="https://${VIZ}/#${ids[key]}&inline&lang=sk"></iframe>
          <script>${readFileSync(path.join(here, "../../../charts/ckan/files/jc_theme/public__jc-viz.js"), "utf8")}</script>`
      });
    }
    if (url.hostname === `tiles.${DOMAIN}` && url.pathname.startsWith("/styles/light-")) {
      // A basemap with no tiles: the journey is about the data on it.
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": `https://${VIZ}` },
        body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "paper", type: "background", paint: { "background-color": "#eeeeee" } }] }) });
    }
    if (url.hostname === `assistant.${DOMAIN}` || url.hostname === "evil.example") {
      // The assistant's widget as it frames a chart (T-4657), and a stranger doing the same.
      const shown = SHOWN[url.pathname.slice(1)];
      // ?widget: the frame as widget.css and widget.js size it (360px, clamped to 120..900).
      const widget = url.searchParams.has("widget");
      return route.fulfill({
        status: 200, contentType: "text/html; charset=utf-8",
        body: `<!doctype html><title>widget</title><iframe id="viz" style="width:100%;height:${widget ? 360 : 200}px;border:0"
          sandbox="allow-scripts allow-same-origin allow-downloads allow-popups allow-popups-to-escape-sandbox" src="https://${VIZ}/#show"></iframe>
          <script>
          const f = document.getElementById("viz");
          f.addEventListener("load", () => f.contentWindow.postMessage(${JSON.stringify(shown)}, "https://${VIZ}"));
          addEventListener("message", (e) => { if (e.origin === "https://${VIZ}" && e.data.type === "jc-viz-height") f.style.height = ${widget ? "Math.min(Math.max(Math.round(e.data.height), 120), 900)" : "e.data.height"} + "px"; });
          </script>`
      });
    }
    if (url.hostname === `api.${DOMAIN}`) {
      const base = `/api/endpoint/${SLUG}/`;
      if (url.pathname === `${base}ngsi-ld/v1/temporal/entities`) return json(TEMPORAL);
      if (url.pathname === `${base}ngsi-ld/v1/entities`) return json(NAMES);
      if (url.pathname === `${base}odata/v4/WeatherObserved`) return json(ODATA);
      return route.fulfill({ status: 404, body: "" });
    }
    return route.abort();
  });
  return requests;
}

// What the assistant's widget hands the host page in `#show` (ADR-N-053 §2.9).
const MAP_SPEC = {
  $schema: "urn:joinedcontext:map:v1", title: "Kvalita ovzdušia", label: "name", time: "observedAt",
  popup: [{ field: "no2", label: "NO₂", unit: "µg/m³" }, { field: "pm10", label: "PM10", unit: "µg/m³" }],
  data: { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [19.1462, 48.7363] },
    properties: { name: "SK0214A <img src=x onerror=alert(1)>", no2: 14.2, pm10: 21.5, observedAt: "2026-10-18T15:00:00Z" } }] },
  link: `https://data.${DOMAIN}/dataset/ovzdusie`
};
const SHOWN = {
  map: { type: "jc-viz-show", spec: MAP_SPEC, lang: "sk" },
  bar: { type: "jc-viz-show", lang: "sk", rows: [{ name: "Donovaly", temperature: 11.5 }, { name: "Zelená", temperature: 13.4 }],
    spec: { $schema: VL, data: { name: "source" }, mark: { type: "bar", tooltip: true },
      encoding: { y: { field: "name", type: "nominal", title: null }, x: { field: "temperature", type: "quantitative", title: "°C" } } } },
  foreignLink: { type: "jc-viz-show", lang: "sk", spec: { ...MAP_SPEC, link: "https://evil.example/" } }
};

const renderer = (page) => page.frameLocator("#viz").frameLocator("#frame");
const host = (page) => page.frameLocator("#viz");
const foreign = (requests) => requests.filter((u) => !OURS.has(u.hostname)).map(String);

for (const key of ["line", "bar", "brush"]) {
  test(`${key}: draws from the Endpoint's own rows and asks no other host`, async ({ page, context }) => {
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    const requests = await serve(context);
    await page.goto(`https://data.${DOMAIN}/dataset/${key}`);
    await expect(renderer(page).locator("svg .mark-symbol, svg .mark-line, svg .mark-rect").first()).toBeAttached({ timeout: 15000 });
    expect(foreign(requests)).toEqual([]);
    expect(errors).toEqual([]);
    // The frame told the catalogue its height.
    await expect.poll(async () => page.locator("#viz").evaluate((f) => f.style.height)).not.toBe("420px");
    if (key === "bar") {
      // OData leaves the LanguageProperty empty; the names come from NGSI-LD in the page's language.
      await expect(renderer(page).locator("svg.marks")).toContainText("Stanica SHMÚ Donovaly");
    }
    if (key === "brush") {
      // Brushing a stretch of the line redraws the bars as the mean of that stretch alone.
      const bars = () => renderer(page).locator("svg.marks .mark-rect path").evaluateAll((p) => p.map((e) => e.getAttribute("d")).join("|"));
      const before = await bars();
      // The line's plot area: the axis gridlines span it.
      const box = await renderer(page).locator("svg.marks .mark-rule.role-axis-grid").first().boundingBox();
      await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2, { steps: 5 });
      await page.mouse.up();
      await expect.poll(bars).not.toBe(before);
    }
  });
}

test("the renderer frame reads no cookie and calls no host", async ({ page, context }) => {
  await serve(context);
  await page.goto(`https://data.${DOMAIN}/dataset/line`);
  const frame = page.frames().find((f) => f.url().endsWith("/render.html")) ||
    (await expect.poll(() => page.frames().some((f) => f.url().endsWith("/render.html"))).toBe(true), page.frames().find((f) => f.url().endsWith("/render.html")));
  expect(await frame.evaluate(() => origin)).toBe("null");
  expect(await frame.evaluate(() => { try { return document.cookie; } catch (e) { return e.name; } })).toBe("SecurityError");
  expect(await frame.evaluate(() => fetch(`https://api.${location.hostname.slice(4)}/`).then(() => "fetched", () => "refused"))).toBe("refused");
});

for (const key of ["dataUrl", "javascriptHref", "windowExpr"]) {
  test(`${key}: refused, drawn as a message, no outside request`, async ({ page, context }) => {
    const requests = await serve(context);
    await page.goto(`https://data.${DOMAIN}/dataset/${key}`);
    await expect(host(page).locator("#status")).toBeVisible({ timeout: 15000 });
    await expect(host(page).locator("#status")).toContainText(/refused|window/i);
    expect(foreign(requests)).toEqual([]);
    await expect(renderer(page).locator("svg")).toHaveCount(0);
  });

  test(`${key}: with the refusal list off, the renderer still draws nothing from elsewhere`, async ({ page, context }) => {
    const requests = await serve(context, { trustless: true });
    await page.goto(`https://data.${DOMAIN}/dataset/${key}`);
    await page.waitForTimeout(3000);
    expect(foreign(requests)).toEqual([]);
    // No navigation to a javascript: URL and no alert from it.
    let dialog = false;
    page.on("dialog", () => { dialog = true; });
    await renderer(page).locator("svg .mark-rect path").first().click({ timeout: 2000 }).catch(() => {});
    expect(dialog).toBe(false);
  });
}

// T-4657: the assistant's widget hands a map spec; a click on the station opens its popup, text only.
test("show: a map spec draws on our basemap, and a click opens the popup as text", async ({ page, context }) => {
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  let dialog = false;
  page.on("dialog", (d) => { dialog = true; return d.dismiss(); });
  const requests = await serve(context);
  await page.goto(`https://assistant.${DOMAIN}/map`);
  const map = page.frameLocator("#viz").frameLocator("#map");
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 20000 });
  const frame = await expect.poll(() => page.frames().find((f) => f.url().endsWith("/map.html")) ? true : false).toBe(true)
    .then(() => page.frames().find((f) => f.url().endsWith("/map.html")));
  await expect.poll(() => frame.evaluate(() => self.jcMapReady === true), { timeout: 20000 }).toBe(true);
  // One station: the view centres on it, so it sits in the middle of the map.
  const box = await map.locator("#map").boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const pop = map.locator(".jc-pop");
  await expect(pop).toBeVisible();
  await expect(pop.locator("strong")).toHaveText("SK0214A <img src=x onerror=alert(1)>");
  await expect(pop.locator("dd").nth(1)).toHaveText("21,5 µg/m³");
  await expect(pop.locator("a")).toHaveAttribute("href", `https://data.${DOMAIN}/dataset/ovzdusie`);
  expect(await pop.locator("img").count()).toBe(0);
  expect(dialog).toBe(false);
  // Enter on the map opens the same popup from the keyboard.
  await map.locator(".maplibregl-popup-close-button").click();
  await map.locator("canvas.maplibregl-canvas").focus();
  await page.keyboard.press("Enter");
  await expect(pop).toBeVisible();
  expect(foreign(requests)).toEqual([]);
  expect(errors).toEqual([]);
  await expect.poll(async () => page.locator("#viz").evaluate((f) => f.style.height)).not.toBe("200px");
});

// T-4811: in the widget's 360px frame the map and its hint fit, so no frame scrolls inside the chat.
for (const [name, width] of [["desktop", 1280], ["phone", 400]]) {
  test(`show: the map fits the widget's frame with no inner scrollbar (${name})`, async ({ page, context }, info) => {
    await page.setViewportSize({ width, height: 800 });
    await serve(context);
    await page.goto(`https://assistant.${DOMAIN}/map?widget`);
    await expect.poll(() => page.frames().some((f) => f.url().endsWith("/map.html")), { timeout: 20000 }).toBe(true);
    const map = page.frames().find((f) => f.url().endsWith("/map.html"));
    await expect.poll(() => map.evaluate(() => self.jcMapReady === true), { timeout: 20000 }).toBe(true);
    const hint = page.frameLocator("#viz").frameLocator("#map").locator("#hint");
    await expect(hint).toHaveText("Kliknite na bod alebo stlačte Enter.");
    await expect(hint).toBeInViewport({ ratio: 1 });
    const host = page.frames().find((f) => f.url().endsWith("/#show"));
    const overflow = (f) => f.evaluate(() => document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight);
    // Heights settle by message: wait a little, then neither frame may hold more than it shows.
    await page.waitForTimeout(500);
    expect(await overflow(map)).toBeLessThanOrEqual(0);
    expect(await overflow(host)).toBeLessThanOrEqual(0);
    expect(await page.locator("#viz").evaluate((f) => f.getBoundingClientRect().height)).toBe(360);
    await page.locator("#viz").screenshot({ path: info.outputPath(`map-${name}.png`) });
  });
}

test("show: a Vega spec with its rows draws in the sandboxed renderer", async ({ page, context }) => {
  const requests = await serve(context);
  await page.goto(`https://assistant.${DOMAIN}/bar`);
  await expect(renderer(page).locator("svg.marks .mark-rect path").first()).toBeAttached({ timeout: 15000 });
  await expect(renderer(page).locator("svg.marks")).toContainText("Donovaly");
  expect(foreign(requests)).toEqual([]);
});

test("show: a page on another site gets nothing drawn, and a map linking out is refused", async ({ page, context }) => {
  await serve(context);
  await page.goto("https://evil.example/map");
  await page.waitForTimeout(2000);
  await expect(page.frameLocator("#viz").locator("#map")).toHaveCount(0);
  await page.goto(`https://assistant.${DOMAIN}/foreignLink`);
  await expect(page.frameLocator("#viz").locator("#status")).toContainText("/link", { timeout: 10000 });
  await expect(page.frameLocator("#viz").locator("#map")).toHaveCount(0);
});
