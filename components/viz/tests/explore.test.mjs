// T-5059, T-5082: the explorer page's pure logic under node: the hash (type, query and order of a
// shared view), the map's bbox, the query's API addresses and how a value reads in the map's details.
// The table, its filters and its order are the Portal's Endpoint data view, tested in the Portal.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const x = require("../charts/renderer/files/site/explore.js");

test("the hash names one Endpoint and its options; anything else is dropped", () => {
  assert.deepEqual(x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&lang=sk&type=Bike&inline&theme=dark"),
    { slug: "scsd2eehkx42n53z2zyd6vshfh7s7irf", lang: "sk", type: "Bike", inline: true, theme: "dark", q: null, sort: null, dataset: null, view: null, all: false });
  assert.equal(x.parseHash("#../evil"), null);
  assert.equal(x.parseHash(""), null);
  const odd = x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&type=a;b&lang=english&theme=red");
  assert.equal(odd.type, null);
  assert.equal(odd.lang, null);
  assert.equal(odd.theme, null);
});

test("a shared view's query and order come back from the hash they were written to", () => {
  const view = { slug: "scsd2eehkx42n53z2zyd6vshfh7s7irf", inline: true, all: false, lang: "sk", theme: null, type: "Bike", q: 'name~=".*ivo.*";bikes>=5', sort: "bikes;desc", dataset: null, view: null };
  assert.deepEqual(x.parseHash(x.hashOf(view)), view);
  assert.equal(x.hashOf({ slug: "scsd2eehkx42n53z2zyd6vshfh7s7irf" }), "#scsd2eehkx42n53z2zyd6vshfh7s7irf");
  const bad = x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&sort=a;sideways&q=%E0%A4%A&type=Bike");
  assert.equal(bad.sort, null);
  assert.equal(bad.q, null); // a broken escape is dropped, not thrown
  assert.equal(bad.type, "Bike");
  assert.equal(x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&q=" + "a".repeat(2001)).q, null);
  assert.equal(x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&sort=id").sort, "id");
});

test("the API base comes from the page's own host", () => {
  assert.equal(x.base("viz.dev.joinedcontext.com", "abc"), "https://api.dev.joinedcontext.com/api/endpoint/abc/");
});

test("the map's view becomes a closed within-polygon, clamped to the globe", () => {
  const b = x.bboxQuery([-200, -95, 24.95123456, 60.1]);
  assert.equal(b.georel, "within");
  assert.equal(b.coordinates, JSON.stringify([[[-180, -90], [24.951235, -90], [24.951235, 60.1], [-180, 60.1], [-180, -90]]]));
});

test("links stay under the Endpoint and carry the query", () => {
  const api = "https://api.dev.joinedcontext.com/api/endpoint/abc/";
  const l = x.links(api, "Bike", 'status=="x"', "bikes;desc", "urn:ngsi-ld:Bike:1");
  assert.ok(l.every((k) => k.href.startsWith(api)));
  assert.equal(l[0].href, api + "ngsi-ld/v1/entities/urn%3Angsi-ld%3ABike%3A1");
  assert.ok(l[1].href.includes("q=status%3D%3D%22x%22") && l[1].href.includes("orderBy=bikes%3Bdesc"));
  // The CSV of exactly this view: its query and its order.
  assert.equal(l[4].href, api + "file.csv?type=Bike&q=status%3D%3D%22x%22&orderBy=bikes%3Bdesc");
  assert.equal(l[5].href, api + "ogc/features/collections/Bike/tiles/WebMercatorQuad");
  assert.equal(x.links(api, "Bike", "", null).length, 5);
});

test("cells read as text: numbers by locale, links only for http(s), no raw JSON", () => {
  const t = { yes: "áno", no: "nie", lang: "sk", locale: "sk-SK" };
  assert.equal(x.show(1330091, t).text.replace(/\s/g, " "), "1 330 091");
  assert.equal(x.show(true, t).text, "áno");
  assert.equal(x.show(null, t).text, "–");
  assert.deepEqual(x.show("https://hsl.fi/a", t), { text: "https://hsl.fi/a", href: "https://hsl.fi/a" });
  assert.equal(x.show("javascript:alert(1)", t).href, undefined);
  assert.equal(x.show({ type: "Polygon", coordinates: [[[17.1, 48.1], [17.2, 48.1], [17.1, 48.1]]] }, t).text, "Polygon 17.10000, 48.10000");
  assert.equal(x.show(["a", 2], t).text, "a; 2");
  assert.equal(x.show({ languageMap: { fi: "Kaivopuisto", sk: "Park" } }, t).text, "Park");
  assert.equal(x.show({ streetAddress: "Hlavná 1", postalCode: "97401" }, t).text, "streetAddress: Hlavná 1, postalCode: 97401");
});

test("both languages name every string", () => {
  const keys = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? keys(v, p + k + ".") : [p + k])).sort();
  assert.deepEqual(keys(x.TEXT.sk), keys(x.TEXT.en));
});

test("a timestamp reads as a date in the page's language, in UTC", () => {
  assert.equal(x.show("2026-10-21T19:35:26Z", { locale: "en-GB" }).text, "21 Oct 2026, 19:35 UTC");
  assert.equal(x.show("2026-10-21", { locale: "en-GB" }).text, "2026-10-21");
});

test("the map's tiles come only from the type's own tileset path (T-5189)", () => {
  const api = "https://api.dev.joinedcontext.com/api/endpoint/abc/";
  const at = x.tilesetUrl(api, "Bike");
  const of = (href, type = "application/vnd.mapbox-vector-tile") => x.templateOf({ links: [{ rel: "item", type, templated: true, href }] }, at);
  assert.equal(of(at + "/{tileMatrix}/{tileRow}/{tileCol}"), at + "/{z}/{y}/{x}");
  assert.equal(of("https://evil.example/t/{tileMatrix}/{tileRow}/{tileCol}"), null);
  assert.equal(of("http://antares:9471/ngsi-ld/ogc/collections/Bike/tiles/WebMercatorQuad/{tileMatrix}/{tileRow}/{tileCol}"), null);
  assert.equal(of(at.replace("/Bike/", "/Car/") + "/{tileMatrix}/{tileRow}/{tileCol}"), null);
  assert.equal(of(at + "/{tileMatrix}/{tileRow}/{tileCol}?f=mvt"), null);
  assert.equal(of(at + "/{tileMatrix}/{tileCol}/{tileRow}"), null);
  assert.equal(of(at + "/{tileMatrix}/{tileRow}/{tileCol}", "application/json"), null);
  assert.equal(x.templateOf(null, at), null);
});

// DM-135 (T-5231): the row card a reader opens from the table or the map.
const T = { ...x.TEXT.sk, lang: "sk", locale: "sk-SK", timeZone: "Europe/Bratislava" };
const STOP = {
  type: "GtfsStop", typeLabel: "Železničná stanica", title: "name",
  fields: [
    { name: "name", label: "Názov" },
    { name: "dailyDepartures", label: "Odchody za deň", kind: "integer" },
    { name: "wheelchair", label: "Bezbariérová" },
    { name: "mode", label: "Druh", titles: { rail: "Vlak" } },
    { name: "stopCode", label: "Kód zastávky", hidden: true }
  ]
};

test("the card takes labels and order from the model and hides id, type, empty and system values", () => {
  const row = {
    id: "urn:ngsi-ld:GtfsStop:zilina-zariecie", type: "GtfsStop", "@context": "x", stopCode: "ZZ",
    mode: "rail", wheelchair: true, dailyDepartures: 1234, name: "Žilina-Záriečie", note: "", platformCount: null,
    location: { type: "Point", coordinates: [18.73109, 49.21933] }, dateModified: "2026-10-22T11:00:00Z",
    source: "https://data.slovensko.sk/datasety/abc?x=1", dataProvider: "ŽSR"
  };
  const card = x.cardOf(row, STOP, T);
  assert.equal(card.typeLabel, "Železničná stanica");
  assert.equal(card.title, "Žilina-Záriečie");
  assert.deepEqual(card.fields.map((f) => f.label), ["Odchody za deň", "Bezbariérová", "Druh"]);
  assert.equal(card.fields[0].text.replace(/\s/g, " "), "1 234");
  assert.equal(card.fields[1].text, "Áno");
  assert.equal(card.fields[2].text, "Vlak");
  assert.deepEqual(card.geo, row.location);
  assert.deepEqual(card.source, { provider: "ŽSR", href: "https://data.slovensko.sk/datasety/abc?x=1", host: "data.slovensko.sk" });
  assert.deepEqual(card.dev.map((d) => d.label), ["Identifikátor", "Typ", "Kód zastávky", "Date modified"]);
  assert.equal(JSON.stringify(card.fields).includes("urn:ngsi-ld"), false);
});

test("a type with no labels falls back to humanised keys and its type name made readable", () => {
  const card = x.cardOf({ id: "urn:ngsi-ld:GtfsStop:1", type: "GtfsStop", dailyDepartures: 3 }, null, T);
  assert.equal(card.typeLabel, "Gtfs stop");
  assert.equal(card.title, "urn:ngsi-ld:GtfsStop:1");
  assert.deepEqual(card.fields, [{ label: "Daily departures", text: "3", href: undefined }]);
  assert.equal(x.humanise("dailyDepartures"), "Daily departures");
  // Another type's card is never used for its labels.
  assert.equal(x.cardOf({ id: "a", type: "Event" }, STOP, T).typeLabel, "Event");
});

test("card values: local dates, units, an address by its parts, a web address by its host", () => {
  assert.equal(x.cardValue("2026-11-14T18:00:00Z", {}, T).text.replace(/\s/g, " "), "14. 11. 2026, 19:00");
  assert.equal(x.cardValue("2026-11-14", {}, T).text.replace(/\s/g, " "), "14. 11. 2026");
  assert.equal(x.cardValue(21.5, { unit: "°C" }, T).text, "21,5 °C");
  assert.equal(x.cardValue({ streetAddress: "Hlavná 1", addressLocality: "Žilina" }, {}, T).text, "Hlavná 1, Žilina");
  assert.deepEqual(x.cardValue("https://www.zilina.sk/podujatia/1", {}, T), { text: "zilina.sk", href: "https://www.zilina.sk/podujatia/1" });
  assert.equal(x.cardValue({ languageMap: { en: "Station", sk: "Stanica" } }, {}, T).text, "Stanica");
  assert.equal(x.cardValue(false, {}, T).text, "Nie");
  assert.equal(x.cardValue([], {}, T), null);
});

test("a javascript: or data: value renders as text, never a link", () => {
  for (const bad of ["javascript:alert(1)", "data:text/html,<b>x</b>", "JaVaScRiPt:alert(1)", "https://a b"]) {
    const said = x.cardValue(bad, {}, T);
    assert.equal(said.href, undefined, bad);
    assert.equal(said.text, bad);
    assert.equal(x.hostOf(bad), null);
  }
  const card = x.cardOf({ id: "a", type: "T", source: "javascript:alert(1)" }, null, T);
  assert.deepEqual(card.source, { text: "javascript:alert(1)" });
});

test("the removed default filter rides in the hash", () => {
  const view = { slug: "scsd2eehkx42n53z2zyd6vshfh7s7irf", inline: false, all: true, lang: null, theme: null, type: "Event", q: null, sort: null, dataset: null, view: null };
  assert.equal(x.hashOf(view), "#scsd2eehkx42n53z2zyd6vshfh7s7irf&all&type=Event");
  assert.deepEqual(x.parseHash(x.hashOf(view)), view);
});
