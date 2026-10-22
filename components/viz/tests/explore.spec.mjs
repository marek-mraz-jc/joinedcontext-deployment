// T-5059, T-5082: the live explorer in a browser. The table is the Portal's Endpoint data view
// (images/viz/explorer, scripts/viz-explorer-bundle.sh); this page adds the address, the map and the
// Data API dialog. Combinations: viewer {anonymous, signed-in} x width {1440, 400} x language {en, sk}
// x data {point, polygon, no geometry, 0, 1, >10 000 with paging, long texts and URLs, multi-valued and
// LanguageProperty} x theme for two of them, the failures {403, 404, 502}, a shared link's query and
// order, the server-side order, Fields, full window and CSV. Every host is routed inside the test (viz
// with nginx.conf's CSP, the Endpoint with answers shaped like dev's of 2026-10-21), so it runs
// anywhere; each state leaves a screenshot in test-results/explore/ for the UX read in the task.
//   npm i --no-save --no-package-lock @playwright/test@1.63.0 (chromium 1243, as the Portal pins)
//   PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright test -c components/viz/tests explore
import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const chart = path.join(here, "../charts/renderer");
const vendor = path.join(here, "../../../images/viz/vendor");
const explorer = path.join(here, "../../../images/viz/explorer");
const shots = path.join(here, "test-results/explore");
mkdirSync(shots, { recursive: true });
const DOMAIN = "dev.joinedcontext.com";
const VIZ = `viz.${DOMAIN}`;
const CATALOGUE = `opendata.${DOMAIN}`;
const API = `api.${DOMAIN}`;

const conf = readFileSync(path.join(chart, "files/nginx.conf"), "utf8").replaceAll("__HOST__", VIZ).replaceAll("__DOMAIN__", DOMAIN);
const csp = (location) => /Content-Security-Policy "([^"]+)"/.exec(conf.slice(conf.indexOf(`location = ${location} {`)))[1];

// keyValues records per data set; the normalized form is derived from them.
const bike = (i, extra = {}) => ({
  id: `urn:ngsi-ld:BikeHireDockingStation:hel.fi:helsinki:${String(i).padStart(3, "0")}`, type: "BikeHireDockingStation",
  name: { languageMap: { fi: `Asema ${i}`, sk: `Stanica ${i}`, en: `Station ${i}` } }, status: "working", availableBikeNumber: 20 - i,
  dateModified: "2026-10-21T19:35:26Z", source: "https://www.hsl.fi/en/citybikes",
  location: { type: "Point", coordinates: [24.95 + i / 100, 60.155 + i / 200] }, ...extra
});
const square = (x, y) => ({ type: "Polygon", coordinates: [[[x, y], [x + 0.05, y], [x + 0.05, y + 0.03], [x, y + 0.03], [x, y]]] });
const kpi = (i) => ({
  id: `urn:ngsi-ld:KeyPerformanceIndicator:susr:pl2016rs-${i}`, type: "KeyPerformanceIndicator", name: "Stavy hospodárskych zvierat k 31.12.",
  kpiValue: 1330091 + i, refArea: "SK0", refPeriod: String(1970 + (i % 50)), dataSet: "pl2016rs"
});
const DATA = {
  point: { type: "BikeHireDockingStation", rows: [1, 2, 3].map((i) => bike(i)) },
  polygon: { type: "AdministrativeArea", rows: [0, 1].map((i) => ({ id: `urn:ngsi-ld:AdministrativeArea:bb:${i}`, type: "AdministrativeArea", name: `Mestská časť ${i + 1}`, population: 12000 + i, location: square(19.1 + i * 0.06, 48.72) })) },
  nogeo: { type: "KeyPerformanceIndicator", rows: [1, 2, 3, 4].map(kpi) },
  zero: { type: "KeyPerformanceIndicator", rows: [], sample: [kpi(1)] }, // the schema lists attributes, the broker holds none
  one: { type: "BikeHireDockingStation", rows: [bike(7)] },
  many: { type: "KeyPerformanceIndicator", count: 12345, rows: null },
  long: { type: "Event", rows: [{ id: "urn:ngsi-ld:Event:bbsk:" + "x".repeat(80), type: "Event", name: "Festival " + "veľmi dlhý názov podujatia ".repeat(6),
    description: "Opis <img src=x onerror=alert(1)> ".repeat(20), url: "https://www.bbsk.sk/podujatia/" + "a-b-c-".repeat(30), startDate: "2026-11-01T18:00:00Z" }] },
  multi: { type: "WeatherObserved", rows: [{ id: "urn:ngsi-ld:WeatherObserved:shmu:11894", type: "WeatherObserved", name: { languageMap: { sk: "Stanica Donovaly", en: "Donovaly station" } },
    temperature: [11.5, 12.1], address: { addressLocality: "Donovaly", postalCode: "97639" }, refDevice: "urn:ngsi-ld:Device:1" }] },
  notypes: { types: [] }
};
const SLUGS = Object.fromEntries(Object.keys(DATA).map((k) => [k, (k + "slug").padEnd(32, "0").slice(0, 32)]));
const FAIL = { forbidden: 403, missing: 404, gateway: 502, slow: 0 };
for (const k of Object.keys(FAIL)) SLUGS[k] = (k + "fail").padEnd(32, "0").slice(0, 32);
const key = (slug) => Object.keys(SLUGS).find((k) => SLUGS[k] === slug);

const attrs = (rows) => [...new Set(rows.flatMap((r) => Object.keys(r).filter((a) => a !== "id" && a !== "type")))];
const normal = (r) => Object.fromEntries(Object.entries(r).map(([k, v]) => {
  if (k === "id" || k === "type") return [k, v];
  if (k === "location") return [k, { type: "GeoProperty", value: v }];
  if (v && v.languageMap) return [k, { type: "LanguageProperty", languageMap: v.languageMap }];
  if (k.startsWith("ref")) return [k, { type: "Relationship", object: v }];
  if (Array.isArray(v)) return [k, v.map((x, i) => ({ type: "Property", value: x, datasetId: `urn:ds:${i}` }))];
  return [k, { type: "Property", value: v }];
}));
const localized = (r, lang) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v && v.languageMap ? v.languageMap[lang] || Object.values(v.languageMap)[0] : v]));
const manyRows = (offset, limit) => Array.from({ length: Math.max(0, Math.min(limit, 12345 - offset)) }, (_, i) => kpi(offset + i + 1));

// The Endpoint's JSON Schema as the gateway serves it: one definition, a type and a description per attribute.
const kindOf = (v) => (typeof v === "number" ? { type: "number" } : typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) ? { type: "string", format: "date-time" } : { type: "string" });
const schemaOf = (d) => {
  const sample = d.sample || d.rows || manyRows(0, 5);
  const properties = Object.fromEntries(attrs(sample).map((a) => [a, { ...kindOf(sample.find((r) => r[a] !== undefined)[a]), description: `The ${a} of the ${d.type}` }]));
  return { $defs: { [d.type]: { type: "object", properties } } };
};
const problem = (status) => ({ type: "about:blank", title: "refused", status, detail: { 403: "no policy grants anonymous reads on this endpoint", 404: "the endpoint does not exist", 502: "the broker did not answer" }[status] });
const valueOf = (r, a) => (r[a] && r[a].languageMap ? Object.values(r[a].languageMap)[0] : r[a]);
const ordered = (rows, orderBy) => {
  if (!orderBy) return rows;
  const [a, dir] = orderBy.split(";");
  const f = dir === "desc" ? -1 : 1;
  return [...rows].sort((x, y) => (valueOf(x, a) === undefined) - (valueOf(y, a) === undefined) || (typeof valueOf(x, a) === "number" ? f * (valueOf(x, a) - valueOf(y, a)) : f * String(valueOf(x, a)).localeCompare(String(valueOf(y, a)))));
};

export async function serve(context) {
  const requests = [];
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ url, headers: await request.allHeaders() });
    const cors = { "Access-Control-Allow-Origin": `https://${VIZ}`, "Access-Control-Expose-Headers": "NGSILD-Results-Count" };
    if (url.hostname === VIZ) {
      const headers = { "Content-Security-Policy": url.pathname === "/explore.html" ? csp("/explore.html") : "default-src 'none'; frame-ancestors 'none'" };
      try {
        const at = url.pathname.startsWith("/vendor/") ? path.join(vendor, url.pathname.slice("/vendor/".length))
          : url.pathname.startsWith("/explorer/") ? path.join(explorer, url.pathname.slice("/explorer/".length))
            : path.join(chart, "files/site", url.pathname);
        const body = at.endsWith(".mjs") ? gunzipSync(readFileSync(at + ".gz")) : readFileSync(at);
        const type = at.endsWith(".html") ? "text/html" : at.endsWith(".css") ? "text/css" : "text/javascript";
        return route.fulfill({ status: 200, contentType: type, headers, body });
      } catch {
        return route.fulfill({ status: 404, body: "" });
      }
    }
    if (url.hostname === CATALOGUE) {
      // The dataset page as jc_explorer.html renders it, with jc-viz.js sizing the frame.
      const [, , name] = url.pathname.split("/");
      const q = url.searchParams;
      return route.fulfill({
        status: 200, contentType: "text/html",
        body: `<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><title>dataset</title>
          <style>body{margin:0;font:15px system-ui;background:${q.get("theme") === "dark" ? "#0b1220" : "#fff"}}</style>
          <iframe id="explore" data-jc-viz="https://${VIZ}" title="Live data" style="width:100%;height:600px;border:0"
            src="https://${VIZ}/explore.html#${SLUGS[name]}&inline&lang=${q.get("lang") || "en"}${q.get("theme") ? "&theme=" + q.get("theme") : ""}${q.get("extra") || ""}"></iframe>
          <script>${readFileSync(path.join(here, "../../../charts/ckan/files/jc_theme/public__jc-viz.js"), "utf8")}</script>`
      });
    }
    if (url.hostname === `tiles.${DOMAIN}` && url.pathname.startsWith("/styles/light-")) {
      return route.fulfill({ status: 200, contentType: "application/json", headers: cors,
        body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "paper", type: "background", paint: { "background-color": "#e8ecef" } }] }) });
    }
    if (url.hostname === API) {
      const m = /^\/api\/endpoint\/([a-z0-9]+)\/(ngsi-ld\/v1\/types|ngsi-ld\/v1\/entities|schema\/index\.json|schema\/v1\/json-schema)$/.exec(url.pathname);
      const name = m && key(m[1]);
      if (!name) return route.fulfill({ status: 404, headers: cors, body: "{}" });
      if (name in FAIL) {
        if (!FAIL[name]) return; // never answers
        return route.fulfill({ status: FAIL[name], headers: cors, contentType: "application/problem+json", body: JSON.stringify(problem(FAIL[name])) });
      }
      const d = DATA[name];
      const json = (body, count) => route.fulfill({ status: 200, contentType: request.headers().accept === "application/geo+json" ? "application/geo+json" : "application/json",
        headers: { ...cors, ...(count === undefined ? {} : { "NGSILD-Results-Count": String(count) }) }, body: JSON.stringify(body) });
      if (m[2] === "schema/index.json") return json({ models: d.types ? [] : [{ name: d.type, version: 1 }] });
      if (m[2] === "schema/v1/json-schema") return json(d.types ? { $defs: {} } : schemaOf(d));
      if (m[2].endsWith("types")) {
        if (d.types) return json(d.types);
        const sample = d.sample || d.rows || manyRows(0, 5);
        return json([{ id: `https://uri.etsi.org/ngsi-ld/default-context/${d.type}`, type: "EntityType", typeName: d.type, attributeNames: attrs(sample) }]);
      }
      const p = url.searchParams;
      const offset = +(p.get("offset") || 0);
      const limit = +(p.get("limit") || 20);
      let rows = d.rows || manyRows(offset, limit);
      let count = d.count ?? rows.length;
      if (p.get("q")) { rows = rows.slice(0, 1); count = rows.length; }
      rows = ordered(rows, p.get("orderBy"));
      if (d.rows) rows = rows.slice(offset, offset + limit);
      if (request.headers().accept === "application/geo+json") {
        return json({ type: "FeatureCollection", features: rows.filter((r) => r.location).map((r) => ({ id: r.id, type: "Feature", geometry: r.location, properties: localized(r, p.get("lang")) })) }, count);
      }
      return json(p.get("format") === "keyValues" ? rows.map((r) => localized(r, p.get("lang"))) : rows.map(normal), count);
    }
    return route.abort();
  });
  return requests;
}

const frame = (page) => page.frameLocator("#explore");
const apiCalls = (requests) => requests.filter((r) => r.url.hostname === API);
const entityCalls = (requests) => apiCalls(requests).filter((r) => r.url.pathname.endsWith("/ngsi-ld/v1/entities") && r.headers.accept !== "application/geo+json");
const open = async (page, name, { lang = "en", theme, width = 1440, extra = "" } = {}) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`https://${CATALOGUE}/dataset/${name}?lang=${lang}${theme ? "&theme=" + theme : ""}${extra ? "&extra=" + encodeURIComponent(extra) : ""}`);
};
const shot = (page, name) => page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
const rows = (f) => f.getByRole("grid").locator("tbody tr");

// What each data set shows once loaded: data rows in the grid, whether a map appears, a text it says.
const EXPECT = {
  point: { rows: 3, map: true }, polygon: { rows: 2, map: true }, nogeo: { rows: 4, map: false }, zero: { rows: 0, map: false, says: { en: /No entities/, sk: /Žiadne entity/ } },
  one: { rows: 1, map: true }, many: { rows: 25, map: false, says: { en: /12345 matching/, sk: /12345 vyhovujúcich/ } },
  long: { rows: 1, map: false }, multi: { rows: 1, map: false }, notypes: { rows: null, map: false }
};
const THEMED = new Set(["point", "many"]);

for (const name of Object.keys(EXPECT)) {
  for (const width of [1440, 400]) {
    for (const theme of THEMED.has(name) ? ["light", "dark"] : ["light"]) {
      for (const lang of ["en", "sk"]) {
        test(`${name} ${width} ${theme} ${lang}: shows the Endpoint's own rows and asks no other host`, async ({ page, context }) => {
          const errors = [];
          page.on("pageerror", (e) => errors.push(String(e)));
          const requests = await serve(context);
          await open(page, name, { lang, theme, width });
          const e = EXPECT[name];
          const f = frame(page);
          if (e.rows === null) {
            await expect(f.locator("#grid")).not.toBeEmpty();
            await expect(f.getByRole("grid")).toHaveCount(0);
          } else {
            await expect(f.getByRole("grid")).toBeVisible({ timeout: 20000 });
            if (e.rows > 0) await expect(rows(f)).toHaveCount(e.rows);
          }
          if (e.says) await expect(f.locator("#grid")).toContainText(e.says[lang]);
          await expect(f.locator("#map-section")).toBeVisible({ visible: e.map });
          if (e.map) await expect(f.locator("#map-note")).not.toBeEmpty();
          await expect(f.locator("html")).toHaveAttribute("lang", lang);
          expect(requests.filter((r) => ![VIZ, CATALOGUE, API, `tiles.${DOMAIN}`].includes(r.url.hostname)).map((r) => String(r.url))).toEqual([]);
          expect(errors).toEqual([]);
          if (e.map) await page.waitForTimeout(500);
          await shot(page, `${name}-${width}-${theme}-${lang}`);
        });
      }
    }
  }
}

for (const viewer of ["anonymous", "signed-in"]) {
  test(`${viewer}: the explorer sends no Authorization, no cookie and never asks the DataStore`, async ({ page, context }) => {
    if (viewer === "signed-in") {
      // The catalogue's session cookie and a cookie for the whole domain: neither may reach the API.
      await context.addCookies([{ name: "ckan", value: "session-xyz", domain: CATALOGUE, path: "/", secure: true, httpOnly: true },
        { name: "auth_tkt", value: "abc", domain: `.${DOMAIN}`, path: "/", secure: true }]);
    }
    const requests = await serve(context);
    await open(page, "point");
    await expect(rows(frame(page))).toHaveCount(3, { timeout: 20000 });
    const calls = apiCalls(requests);
    expect(calls.length).toBeGreaterThan(3);
    for (const c of calls) {
      expect(c.headers.authorization).toBeUndefined();
      expect(c.headers.cookie).toBeUndefined();
    }
    expect(requests.filter((r) => /datastore_/.test(r.url.pathname))).toEqual([]);
    await shot(page, `viewer-${viewer}`);
  });
}

// The surface's own sentence, as the Portal shows it.
const FAILED = { forbidden: /no policy grants anonymous reads/, missing: /does not exist/, gateway: /did not answer/ };
for (const name of Object.keys(FAILED)) {
  for (const [width, lang] of [[1440, "en"], [400, "sk"]]) {
    test(`${name} ${width} ${lang}: a failure says what happened`, async ({ page, context }) => {
      await serve(context);
      await open(page, name, { lang, width });
      await expect(frame(page).locator("#grid")).toContainText(FAILED[name], { timeout: 20000 });
      await expect(frame(page).getByRole("grid")).toHaveCount(0);
      await shot(page, `fail-${name}-${width}-${lang}`);
    });
  }
}

test("a shared link opens its query and order, and a header sorts every row through orderBy", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "point", { extra: "&type=BikeHireDockingStation&q=" + encodeURIComponent('status=="working"') + "&sort=availableBikeNumber" });
  const f = frame(page);
  await expect(f.getByRole("grid")).toBeVisible({ timeout: 20000 });
  await expect.poll(() => entityCalls(requests).some((r) => r.url.searchParams.get("orderBy") === "availableBikeNumber" && r.url.searchParams.get("q") === 'status=="working"')).toBe(true);
  const sort = f.getByRole("button", { name: /availableBikeNumber/ }).first();
  await sort.click();
  await expect.poll(() => entityCalls(requests).some((r) => r.url.searchParams.get("orderBy") === "availableBikeNumber;desc")).toBe(true);
  await expect.poll(async () => decodeURIComponent(await f.locator("html").evaluate(() => location.hash))).toContain("sort=availableBikeNumber;desc");
  await shot(page, "sorted-1440");
});

test("Data API lists the view's addresses, CSV with its query and order", async ({ page, context }) => {
  await serve(context);
  await open(page, "point", { extra: "&q=" + encodeURIComponent('status=="working"') + "&sort=availableBikeNumber;desc" });
  const f = frame(page);
  await expect(f.getByRole("grid")).toBeVisible({ timeout: 20000 });
  await f.locator("#data-api").click();
  const links = f.locator("#detail-links a");
  await expect(links).toHaveCount(5);
  const csv = await links.nth(3).getAttribute("href");
  expect(csv).toBe(`https://${API}/api/endpoint/${SLUGS.point}/file.csv?type=BikeHireDockingStation&q=status%3D%3D%22working%22&orderBy=availableBikeNumber%3Bdesc`);
  expect(await links.nth(4).getAttribute("href")).toMatch(/explore\.html#.*sort=availableBikeNumber%3Bdesc/);
  await shot(page, "data-api-1440");
  await f.locator("#detail-close").click();
  await expect(f.locator("#data-api")).toBeFocused();
});

for (const width of [1440, 400]) {
  test(`${width}: Fields names each column's type and description; the full window opens and leaves by Escape`, async ({ page, context }) => {
    await serve(context);
    await open(page, "point", { width });
    const f = frame(page);
    await expect(f.getByRole("grid")).toBeVisible({ timeout: 20000 });
    await f.getByText("Fields", { exact: true }).first().click();
    await expect(f.getByText("The availableBikeNumber of the BikeHireDockingStation")).toBeVisible();
    await shot(page, `fields-${width}`);
    await f.getByRole("button", { name: "Full window" }).click();
    await expect(f.getByRole("dialog", { name: /endpoint/i })).toBeVisible();
    await shot(page, `full-${width}`);
    await page.keyboard.press("Escape");
    await expect(f.getByRole("dialog", { name: /endpoint/i })).toHaveCount(0);
  });
}

test("paging walks a large Endpoint by offset with its count", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "many");
  const f = frame(page);
  await expect(rows(f)).toHaveCount(25, { timeout: 20000 });
  await f.getByRole("button", { name: /Next/ }).first().click();
  await expect.poll(() => entityCalls(requests).some((r) => r.url.searchParams.get("offset") === "25")).toBe(true);
  await shot(page, "paged-1440");
});

test("the map asks the grid's query within its view as GeoJSON", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "point", { extra: "&q=" + encodeURIComponent('status=="working"') });
  await expect(frame(page).locator("#map-section")).toBeVisible({ timeout: 20000 });
  await expect.poll(() => apiCalls(requests).some((r) => r.headers.accept === "application/geo+json" && r.url.searchParams.get("georel") === "within" && r.url.searchParams.get("q") === 'status=="working"')).toBe(true);
});
