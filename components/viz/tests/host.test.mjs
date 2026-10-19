// T-4641: the host page reads only the declared source of the view's Endpoint, within limits.
//   node --test components/viz/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const host = createRequire(import.meta.url)("../charts/renderer/files/site/host.js");
const API = "https://api.dev.joinedcontext.com";
const SLUG = "3iasem46w7d7pxxypwdfdzheyaodv3qn";
const NOW = Date.parse("2026-10-18T16:00:00Z");
const base = `${API}/api/endpoint/${SLUG}/`;

test("the fragment names a view id, inline and a language, nothing else", () => {
  const id = "6f1c2b9e-0d0a-4c35-9a51-3a3f8f6c1d20";
  assert.deepEqual(host.parseHash(`#${id}&inline&lang=sk`), { id, inline: true, lang: "sk" });
  assert.deepEqual(host.parseHash(`#${id}`), { id, inline: false, lang: null });
  for (const bad of ["", "#", "#https://evil.example/", `#${id}x`, "#../../x"]) assert.equal(host.parseHash(bad), null);
  assert.deepEqual(host.hosts("viz.dev.joinedcontext.com"), { domain: "dev.joinedcontext.com", api: API, data: "https://opendata.dev.joinedcontext.com" });
});

test("a window of at most 31 days", () => {
  assert.equal(host.duration("PT24H"), 86400000);
  assert.equal(host.duration("P1DT12H"), 129600000);
  assert.equal(host.duration("P31D"), 31 * 86400000);
  for (const bad of ["P32D", "P", "PT", "PT0H", "24h", "", undefined, "P1Y"]) assert.equal(host.duration(bad), null, String(bad));
});

test("each source is one URL under the view's Endpoint", () => {
  assert.equal(host.firstRequest({ source: "csv", type: "WeatherObserved" }, SLUG, API, NOW).url, `${base}file.csv?type=WeatherObserved`);
  assert.equal(host.firstRequest({ source: "ogc", collection: "AirQualityObserved", filter: "pm10 > 50" }, SLUG, API, NOW).url,
    `${base}ogc/features/collections/AirQualityObserved/items?limit=1000&filter=pm10%20%3E%2050`);
  assert.equal(host.firstRequest({ source: "odata", entitySet: "WeatherObserved", $select: "name,temperature", $filter: "temperature ne null" }, SLUG, API, NOW).url,
    `${base}odata/v4/WeatherObserved?%24filter=temperature%20ne%20null&%24select=name%2Ctemperature`);
  assert.equal(host.firstRequest({ source: "temporal", type: "WeatherObserved", attrs: ["temperature"], last: "PT24H", aggrMethod: "avg", aggrPeriod: "PT1H" }, SLUG, API, NOW).url,
    `${base}ngsi-ld/v1/temporal/entities?type=WeatherObserved&attrs=temperature&timerel=after&timeAt=2026-10-17T16%3A00%3A00Z&format=aggregatedValues&aggrMethods=avg&aggrPeriodDuration=PT1H&limit=1000`);
});

test("nothing that could leave the Endpoint", () => {
  const bad = [
    [{ source: "csv", type: "../../x" }, SLUG],
    [{ source: "odata", entitySet: "WeatherObserved/../../../evil" }, SLUG],
    [{ source: "ogc", collection: "a?x=1" }, SLUG],
    [{ source: "url", url: "https://evil.example/" }, SLUG],
    [{ source: "temporal", type: "W", attrs: ["t"], last: "P90D" }, SLUG],
    [{ source: "temporal", type: "W", attrs: [], last: "PT1H" }, SLUG],
    [{ source: "temporal", type: "W", attrs: ["t"], last: "PT1H", aggrMethod: "eval" , aggrPeriod: "PT1H" }, SLUG],
    [{ source: "csv", type: "W" }, "https://evil.example"],
    [{ source: "csv", type: "W" }, undefined],
  ];
  for (const [source, endpoint] of bad) assert.throws(() => host.firstRequest(source, endpoint, API, NOW), JSON.stringify(source));
});

test("temporal answers become one row per instant, named in the page's language", () => {
  const request = { attrs: ["temperature"], method: "avg" };
  const rows = host.rowsFromTemporal([{ id: "urn:a", temperature: { avg: [[9.1, "2026-10-17T16:00:00Z", "2026-10-17T17:00:00Z"], [8.6, "2026-10-17T17:00:00Z", "x"]] } },
    { id: "urn:b", temperature: { type: "Property" } }], request, { "urn:a": "Donovaly" });
  assert.deepEqual(rows, [{ id: "urn:a", name: "Donovaly", observedAt: "2026-10-17T16:00:00Z", temperature: 9.1 },
    { id: "urn:a", name: "Donovaly", observedAt: "2026-10-17T17:00:00Z", temperature: 8.6 }]);
  assert.deepEqual(host.rowsFromTemporal({ error: 1 }, request, {}), []);
  assert.deepEqual(host.named([{ id: "urn:a", name: null, t: 1 }, { id: "urn:c", name: { languageMap: { en: "C", sk: "Cé" } } }], { "urn:a": "A" }, "sk"),
    [{ id: "urn:a", name: "A", t: 1 }, { id: "urn:c", name: "Cé" }]);
});

const answer = (body, status = 200) => {
  const bytes = new TextEncoder().encode(typeof body === "string" ? body : JSON.stringify(body));
  return { ok: status === 200, status, headers: { get: () => String(bytes.length) },
    body: { getReader() { let done = false; return { read: async () => (done ? { done: true } : (done = true, { done: false, value: bytes })), cancel() {} }; } } };
};
const view = (source) => ({ endpoint: SLUG, source: JSON.stringify(source) });

test("the rows of a view, read anonymously from its Endpoint alone", async () => {
  const asked = [];
  const fetcher = async (url, options) => {
    asked.push(url);
    assert.equal(options.credentials, "omit");
    if (url.includes("/odata/v4/")) return answer({ value: [{ id: "urn:a", name: null, temperature: 11.5 }] });
    return answer([{ id: "urn:a", name: "Stanica SHMÚ Donovaly" }]);
  };
  const data = await host.load(view({ source: "odata", entitySet: "WeatherObserved" }), API, "sk", fetcher, NOW);
  assert.deepEqual(data, { format: "json", rows: [{ id: "urn:a", name: "Stanica SHMÚ Donovaly", temperature: 11.5 }] });
  assert.ok(asked.every((u) => u.startsWith(base)), asked.join());
});

test("a next page off the Endpoint stops the chart, more rows than 50,000 too", async () => {
  const off = async () => answer({ value: [{ id: "urn:a" }], "@odata.nextLink": "https://evil.example/next" });
  await assert.rejects(host.load(view({ source: "odata", entitySet: "W" }), API, "en", off, NOW), /not on the Endpoint/);
  const many = async (url) => answer(url.includes("odata") ? { value: Array.from({ length: 50001 }, (_, i) => ({ i })) } : []);
  await assert.rejects(host.load(view({ source: "odata", entitySet: "W" }), API, "en", many, NOW), /50,000 rows/);
  const huge = async () => ({ ...answer("x"), headers: { get: () => String(21 * 1024 * 1024) } });
  await assert.rejects(host.load(view({ source: "csv", type: "W" }), API, "en", huge, NOW), /20 MB/);
  const refused = async () => answer({}, 403);
  await assert.rejects(host.load(view({ source: "csv", type: "W" }), API, "en", refused, NOW), /answered 403/);
});

test("only a page on our own hosts may hand the host page a spec (T-4657)", () => {
  const domain = "dev.joinedcontext.com";
  assert.equal(host.ourOrigin("https://assistant.dev.joinedcontext.com", domain), true);
  assert.equal(host.ourOrigin("https://dev.joinedcontext.com", domain), true);
  for (const origin of ["null", "http://assistant.dev.joinedcontext.com", "https://evil.example", "https://dev.joinedcontext.com.evil.example",
    "https://evildev.joinedcontext.com", "https://assistant.dev.joinedcontext.com:8443", "", undefined]) {
    assert.equal(host.ourOrigin(origin, domain), false, String(origin));
  }
});
