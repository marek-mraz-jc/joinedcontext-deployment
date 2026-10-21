// T-5059: the live explorer in a browser, over the combinations the owner asked for: viewer
// {anonymous, signed-in} x width {1440, 400} x theme {light, dark} x language {en, sk} x data {point,
// polygon, no geometry, 0, 1, >10 000 with paging, long texts and URLs, multi-valued and
// LanguageProperty} and the failures {403, 404, 502, slow}. Every host is routed inside the test
// (viz with nginx.conf's CSP, the Endpoint with answers shaped like dev's of 2026-10-21), so it runs
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
  zero: { type: "KeyPerformanceIndicator", rows: [] },
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

export async function serve(context) {
  const requests = [];
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ url, headers: await request.allHeaders() });
    const cors = { "Access-Control-Allow-Origin": `https://${VIZ}`, "Access-Control-Expose-Headers": "NGSILD-Results-Count" };
    if (url.hostname === VIZ) {
      const file = url.pathname.startsWith("/vendor/") ? url.pathname.slice(1) : `site${url.pathname}`;
      const headers = { "Content-Security-Policy": url.pathname === "/explore.html" ? csp("/explore.html") : "default-src 'none'; frame-ancestors 'none'" };
      try {
        const at = file.startsWith("vendor/") ? path.join(vendor, file.slice("vendor/".length)) : path.join(chart, "files", file);
        const body = file.endsWith(".mjs") ? gunzipSync(readFileSync(at + ".gz")) : readFileSync(at);
        const type = file.endsWith(".html") ? "text/html" : file.endsWith(".css") ? "text/css" : "text/javascript";
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
            src="https://${VIZ}/explore.html#${SLUGS[name]}&inline&lang=${q.get("lang") || "en"}${q.get("theme") ? "&theme=" + q.get("theme") : ""}"></iframe>
          <script>${readFileSync(path.join(here, "../../../charts/ckan/files/jc_theme/public__jc-viz.js"), "utf8")}</script>`
      });
    }
    if (url.hostname === `tiles.${DOMAIN}` && url.pathname.startsWith("/styles/light-")) {
      return route.fulfill({ status: 200, contentType: "application/json", headers: cors,
        body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "paper", type: "background", paint: { "background-color": "#e8ecef" } }] }) });
    }
    if (url.hostname === API) {
      const m = /^\/api\/endpoint\/([a-z0-9]+)\/ngsi-ld\/v1\/(types|entities)$/.exec(url.pathname);
      const name = m && key(m[1]);
      if (!name) return route.fulfill({ status: 404, headers: cors, body: "{}" });
      if (name in FAIL) {
        if (!FAIL[name]) return; // never answers: the page gives up at 15 s
        return route.fulfill({ status: FAIL[name], headers: cors, contentType: "application/json", body: JSON.stringify({ type: "https://uri.etsi.org/ngsi-ld/errors/Error", title: "x" }) });
      }
      const d = DATA[name];
      const json = (body, count) => route.fulfill({ status: 200, contentType: request.headers().accept === "application/geo+json" ? "application/geo+json" : "application/json",
        headers: { ...cors, ...(count === undefined ? {} : { "NGSILD-Results-Count": String(count) }) }, body: JSON.stringify(body) });
      if (m[2] === "types") {
        if (d.types) return json(d.types);
        const sample = d.rows || manyRows(0, 5);
        return json([{ id: `https://uri.etsi.org/ngsi-ld/default-context/${d.type}`, type: "EntityType", typeName: d.type, attributeNames: attrs(sample) }]);
      }
      const p = url.searchParams;
      const offset = +(p.get("offset") || 0);
      const limit = +(p.get("limit") || 20);
      let rows = d.rows || manyRows(offset, limit);
      let count = d.count ?? rows.length;
      if (p.get("q")) { rows = rows.slice(0, 1); count = rows.length; }
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
const open = async (page, name, { lang = "en", theme, width = 1440 } = {}) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`https://${CATALOGUE}/dataset/${name}?lang=${lang}${theme ? "&theme=" + theme : ""}`);
};
const settle = (page) => expect(frame(page).locator("#status")).not.toHaveText(/Loading|Načítavam/, { timeout: 20000 });
const shot = (page, name) => page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });

// What each data set shows once loaded: rows in the table, whether a map appears, the status text.
const EXPECT = {
  point: { rows: 3, map: true }, polygon: { rows: 2, map: true }, nogeo: { rows: 4, map: false }, zero: { rows: 0, map: false, status: { en: /no entities/, sk: /nemá entity/ } },
  one: { rows: 1, map: true }, many: { rows: 20, map: false, status: { en: /Showing 1 to 20 of 12,345 entries/, sk: /Zobrazené 1 až 20 z 12\s345 záznamov/ } },
  long: { rows: 1, map: false }, multi: { rows: 1, map: false }, notypes: { rows: null, map: false, status: { en: /no entity types/, sk: /žiadne typy/ } }
};

for (const name of Object.keys(EXPECT)) {
  for (const width of [1440, 400]) {
    for (const theme of ["light", "dark"]) {
      for (const lang of ["en", "sk"]) {
        test(`${name} ${width} ${theme} ${lang}: shows the Endpoint's own rows and asks no other host`, async ({ page, context }) => {
          const errors = [];
          page.on("pageerror", (e) => errors.push(String(e)));
          const requests = await serve(context);
          await open(page, name, { lang, theme, width });
          await settle(page);
          const e = EXPECT[name];
          const f = frame(page);
          if (e.rows === null) await expect(f.locator("#results")).toBeHidden();
          else await expect(f.locator("#table tbody tr")).toHaveCount(e.rows);
          if (e.status) await expect(f.locator("#status")).toHaveText(e.status[lang]);
          await expect(f.locator("#map-section")).toBeVisible({ visible: e.map });
          if (e.map) await expect(f.locator("#map-note")).not.toBeEmpty();
          await expect(f.locator("html")).toHaveAttribute("lang", lang);
          await expect(f.locator("#type-field")).toBeHidden(); // one type: nothing to choose
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
  test(`${viewer}: the explorer sends no Authorization, no cookie and never asks CKAN's Action API`, async ({ page, context }) => {
    if (viewer === "signed-in") {
      // The catalogue's session cookie and a token in the page's storage: neither may reach the API.
      await context.addCookies([{ name: "ckan", value: "session-xyz", domain: CATALOGUE, path: "/", secure: true, httpOnly: true },
        { name: "auth_tkt", value: "abc", domain: `.${DOMAIN}`, path: "/", secure: true }]);
    }
    const requests = await serve(context);
    await open(page, "point");
    await settle(page);
    await frame(page).locator("#search").fill("asema");
    await frame(page).locator("button[type=submit]").click();
    await settle(page);
    const calls = apiCalls(requests);
    expect(calls.length).toBeGreaterThan(2);
    for (const c of calls) {
      expect(c.headers.authorization).toBeUndefined();
      expect(c.headers.cookie).toBeUndefined();
    }
    expect(requests.filter((r) => /\/api\/3\/action\//.test(r.url.pathname))).toEqual([]);
    await shot(page, `viewer-${viewer}`);
  });
}

const FAILED = { forbidden: { en: /not public/, sk: /nie je verejný/ }, missing: { en: /not found/, sk: /nenašiel/ }, gateway: { en: /did not answer/, sk: /neodpovedala/ }, slow: { en: /15 seconds/, sk: /15 sekúnd/ } };
for (const name of Object.keys(FAILED)) {
  for (const [width, lang] of [[1440, "en"], [400, "sk"]]) {
    test(`${name} ${width} ${lang}: a failure says what happened and offers a retry`, async ({ page, context }) => {
      test.setTimeout(45000);
      await serve(context);
      await open(page, name, { lang, width });
      await expect(frame(page).locator("#status")).toHaveText(FAILED[name][lang], { timeout: 25000 });
      await expect(frame(page).locator("#retry")).toBeVisible();
      await expect(frame(page).locator("#results")).toBeHidden();
      await expect(frame(page).locator("#controls")).toBeHidden();
      await shot(page, `fail-${name}-${width}-${lang}`);
    });
  }
}

test("search and filters become one NGSI-LD q from the Endpoint's attributes", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "point");
  await settle(page);
  const f = frame(page);
  await f.locator("#add-filter").click();
  await f.locator("#f-attr-0").selectOption("availableBikeNumber");
  await f.locator("#f-op-0").selectOption(">=");
  await f.locator("#f-value-0").fill("5");
  await f.locator("#search").fill('as"ema');
  await f.locator("#f-value-0").press("Enter");
  await settle(page);
  const q = apiCalls(requests).map((r) => r.url.searchParams.get("q")).filter(Boolean).pop();
  expect(q).toBe('availableBikeNumber>=5;(name[*]~="(?i).*as\\"ema.*"|status~="(?i).*as\\"ema.*"|source~="(?i).*as\\"ema.*")');
  await expect(f.locator("#table tbody tr")).toHaveCount(1);
  await shot(page, "filtered-1440");
  // A value the attribute cannot hold is refused in the page, before any request.
  const before = apiCalls(requests).length;
  await f.locator("#f-value-0").fill("five");
  await f.locator("button[type=submit]").click();
  await expect(f.locator("#status")).toHaveText(/needs a number/);
  expect(apiCalls(requests).length).toBe(before);
  await shot(page, "filter-refused-1440");
  await page.setViewportSize({ width: 400, height: 900 });
  await shot(page, "filter-refused-400");
});

test("paging walks a large Endpoint by offset with its count", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "many");
  await settle(page);
  const f = frame(page);
  await expect(f.locator("#prev")).toBeDisabled();
  await f.locator("#next").click();
  await expect(f.locator("#status")).toHaveText(/Showing 21 to 40 of 12,345 entries/);
  await f.locator("#size").selectOption("100");
  await expect(f.locator("#table tbody tr")).toHaveCount(100);
  const last = apiCalls(requests).filter((r) => r.url.pathname.endsWith("/entities")).pop().url.searchParams;
  expect([last.get("limit"), last.get("offset"), last.get("count")]).toEqual(["100", "0", "true"]);
});

test("the detail drawer opens from the keyboard, lists every attribute and links, and gives focus back", async ({ page, context }) => {
  await serve(context);
  await open(page, "long");
  await settle(page);
  const f = frame(page);
  const opener = f.locator("#table tbody th button").first();
  await opener.focus();
  await opener.press("Enter");
  const dialog = f.locator("#detail");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("dd").filter({ hasText: "<img src=x" }).first()).toBeVisible();
  await expect(dialog.locator("img")).toHaveCount(0);
  await expect(dialog.locator("#detail-links a")).toHaveCount(5);
  for (const a of await dialog.locator("#detail-links a").all()) expect(await a.getAttribute("href")).toMatch(new RegExp(`^https://${API}/api/endpoint/${SLUGS.long}/`));
  await shot(page, "detail-1440");
  await page.setViewportSize({ width: 400, height: 900 });
  await shot(page, "detail-400");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
});

test("sorting a column says it sorts this page and marks the header", async ({ page, context }) => {
  await serve(context);
  await open(page, "point");
  await settle(page);
  const f = frame(page);
  await f.locator('th[data-attr="availableBikeNumber"] button').click();
  await expect(f.locator('th[data-attr="availableBikeNumber"]')).toHaveAttribute("aria-sort", "ascending");
  await expect(f.locator("#status")).toHaveText(/Sorted within this page/);
  await expect(f.locator("#table tbody tr").first().locator("td").nth(1)).toHaveText("17");
});

test("the column picker hides and shows a column", async ({ page, context }) => {
  await serve(context);
  await open(page, "point");
  await settle(page);
  const f = frame(page);
  await f.locator("details.columns summary").click();
  await f.locator("#col-status").uncheck();
  await expect(f.locator('th[data-attr="status"]')).toHaveCount(0);
  await shot(page, "columns-1440");
});

test("the map asks the same query within its view as GeoJSON", async ({ page, context }) => {
  const requests = await serve(context);
  await open(page, "point");
  await settle(page);
  await expect.poll(() => apiCalls(requests).some((r) => r.url.searchParams.get("georel") === "within" && r.headers.accept === "application/geo+json"), { timeout: 15000 }).toBe(true);
  const geo = apiCalls(requests).filter((r) => r.url.searchParams.get("georel") === "within").pop().url.searchParams;
  expect(geo.get("limit")).toBe("1000");
  expect(JSON.parse(geo.get("coordinates"))[0]).toHaveLength(5);
});

test("Data API lists the current query's addresses on the Endpoint", async ({ page, context }) => {
  await serve(context);
  await open(page, "point", { width: 400 });
  await settle(page);
  const f = frame(page);
  await f.locator("#data-api").click();
  const links = f.locator("#detail-links a");
  await expect(links).toHaveCount(4);
  for (const a of await links.all()) expect(await a.getAttribute("href")).toMatch(new RegExp(`^https://${API}/api/endpoint/${SLUGS.point}/`));
  await shot(page, "data-api-400");
  await page.keyboard.press("Escape");
  await expect(f.locator("#data-api")).toBeFocused();
});
