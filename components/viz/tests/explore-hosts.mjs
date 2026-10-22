// The hosts of the explorer journeys (T-5059, T-5082, T-5129), shared by explore, embed and wordpress
// specs: Playwright refuses a spec importing another spec.
import { readFileSync, mkdirSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const here = path.dirname(fileURLToPath(import.meta.url));
const chart = path.join(here, "../charts/renderer");
const vendor = path.join(here, "../../../images/viz/vendor");
const explorer = path.join(here, "../../../images/viz/explorer");
export const shots = path.join(here, "test-results/explore");
mkdirSync(shots, { recursive: true });
export const DOMAIN = "dev.joinedcontext.com";
export const VIZ = `viz.${DOMAIN}`;
export const CATALOGUE = `opendata.${DOMAIN}`;
export const API = `api.${DOMAIN}`;

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
export const DATA = {
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
export const SLUGS = Object.fromEntries(Object.keys(DATA).map((k) => [k, (k + "slug").padEnd(32, "0").slice(0, 32)]));
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
      // /embed.html is /explore.html under its own CSP (nginx try_files, T-5129).
      const page = ["/explore.html", "/embed.html"].includes(url.pathname);
      const headers = { "Content-Security-Policy": page ? csp(url.pathname) : "default-src 'none'; frame-ancestors 'none'" };
      try {
        const at = url.pathname.startsWith("/vendor/") ? path.join(vendor, url.pathname.slice("/vendor/".length))
          : url.pathname.startsWith("/explorer/") ? path.join(explorer, url.pathname.slice("/explorer/".length))
            : path.join(chart, "files/site", url.pathname === "/embed.html" ? "/explore.html" : url.pathname);
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
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer"
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

// T-5129: the catalogue datasets an embed names for its source line.
export const PACKAGES = {
  "bike-stations": { name: "bike-stations", title: "Stanice zdieľaných bicyklov", license_title: "Creative Commons Attribution 4.0",
    license_url: "https://creativecommons.org/licenses/by/4.0/", organization: { title: "Mesto Banská Bystrica" },
    extras: [{ key: "endpoint", value: `https://${API}/api/endpoint/${SLUGS.point}/` }] },
  "other-endpoint": { name: "other-endpoint", title: "Iný dataset", license_title: "Proprietary", license_url: "", organization: { title: "Niekto iný" },
    extras: [{ key: "endpoint", value: `https://${API}/api/endpoint/${SLUGS.polygon}/` }] }
};

// The catalogue's action API (CORS for viz alone, as CKAN__CORS__ORIGIN_WHITELIST) and its dataset
// page with the explorer frame jc_explorer.html renders, the dataset named in the hash.
export async function catalogue(context) {
  await context.route((url) => url.hostname === CATALOGUE, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/3/action/package_show") {
      const pkg = PACKAGES[url.searchParams.get("id")];
      return route.fulfill({ status: pkg ? 200 : 404, contentType: "application/json", headers: { "Access-Control-Allow-Origin": `https://${VIZ}` },
        body: JSON.stringify(pkg ? { success: true, result: pkg } : { success: false, error: { message: "Not found" } }) });
    }
    const lang = url.searchParams.get("lang") || "en";
    return route.fulfill({ status: 200, contentType: "text/html", body: `<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><title>dataset</title>
      <style>body{margin:0;font:15px system-ui}</style>
      <iframe id="explore" data-jc-viz="https://${VIZ}" title="Live data" style="width:100%;height:600px;border:0" allow="clipboard-write"
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer"
        src="https://${VIZ}/explore.html#${SLUGS.point}&inline&lang=${lang}&dataset=bike-stations${url.searchParams.get("extra") || ""}"></iframe>
      <script>${readFileSync(path.join(here, "../../../charts/ckan/files/jc_theme/public__jc-viz.js"), "utf8")}</script>` });
  });
}
