// T-5059: the explorer's pure logic under node: the hash, the q builder (allow-listed names,
// operators per kind, escaped values), the map's bbox and how a value reads in a cell.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const x = require("../charts/renderer/files/site/explore.js");

const ALLOWED = ["name", "status", "availableBikeNumber", "dateModified", "open", "location", "refStation"];
const KIND = { name: "lang", status: "text", availableBikeNumber: "number", dateModified: "date", open: "boolean", location: null, refStation: null };
const SAMPLE = [{
  id: "urn:ngsi-ld:BikeHireDockingStation:001", type: "BikeHireDockingStation",
  name: { type: "LanguageProperty", languageMap: { fi: "Kaivopuisto" } },
  status: { type: "Property", value: "working" },
  availableBikeNumber: { type: "Property", value: 23 },
  dateModified: { type: "Property", value: "2026-10-21T19:35:26Z" },
  open: [{ type: "Property", value: true, datasetId: "urn:a" }],
  location: { type: "GeoProperty", value: { type: "Point", coordinates: [24.95, 60.15] } },
  refStation: { type: "Relationship", object: "urn:ngsi-ld:Station:1" }
}];

test("the hash names one Endpoint and its options; anything else is dropped", () => {
  assert.deepEqual(x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&lang=sk&type=Bike&inline&theme=dark"),
    { slug: "scsd2eehkx42n53z2zyd6vshfh7s7irf", lang: "sk", type: "Bike", inline: true, theme: "dark" });
  assert.equal(x.parseHash("#../evil"), null);
  assert.equal(x.parseHash(""), null);
  const odd = x.parseHash("#scsd2eehkx42n53z2zyd6vshfh7s7irf&type=a;b&lang=english&theme=red");
  assert.equal(odd.type, null);
  assert.equal(odd.lang, null);
  assert.equal(odd.theme, null);
});

test("the API base comes from the page's own host", () => {
  assert.equal(x.base("viz.dev.joinedcontext.com", "abc"), "https://api.dev.joinedcontext.com/api/endpoint/abc/");
});

test("kinds come from a normalized sample; geometry and relationships get none", () => {
  assert.deepEqual(x.kinds(SAMPLE, ALLOWED), KIND);
  assert.deepEqual(x.kinds([], ["a"]), { a: null });
});

test("q: operators per kind, values typed and escaped", () => {
  const q = (f, s) => x.buildQ(f, s || "", ALLOWED, KIND);
  assert.equal(q([{ attr: "availableBikeNumber", op: ">=", value: "5" }]), "availableBikeNumber>=5");
  assert.equal(q([{ attr: "dateModified", op: ">=", value: "2026-10-01" }]), "dateModified>=2026-10-01T00:00:00Z");
  assert.equal(q([{ attr: "open", op: "==", value: "true" }]), "open==true");
  assert.equal(q([{ attr: "status", op: "==", value: 'a"b\\c' }]), 'status=="a\\"b\\\\c"');
  assert.equal(q([{ attr: "status", op: "contains", value: "x.*(y)|z;" }]), 'status~="(?i).*x\\\\.\\\\*\\\\(y\\\\)\\\\|z;.*"');
  assert.equal(q([{ attr: "name", op: "==", value: "Kaivopuisto" }]), 'name[*]=="Kaivopuisto"');
  assert.equal(q([{ attr: "status", op: "==", value: "working" }, { attr: "availableBikeNumber", op: ">", value: "5" }]),
    'status=="working";availableBikeNumber>5');
});

test("q: the search box looks in every text attribute, ORed, beside the filters", () => {
  assert.equal(x.buildQ([], "kaivo", ALLOWED, KIND), '(name[*]~="(?i).*kaivo.*"|status~="(?i).*kaivo.*")');
  assert.equal(x.buildQ([{ attr: "availableBikeNumber", op: "<", value: "3" }], "kaivo", ["availableBikeNumber"], KIND), "availableBikeNumber<3");
  assert.equal(x.buildQ([], "  ", ALLOWED, KIND), "");
});

test("q: an attribute the Endpoint does not list, a wrong operator or a bad value is refused", () => {
  const no = (f, re) => assert.throws(() => x.buildQ([f], "", ALLOWED, KIND), re);
  no({ attr: "secret", op: "==", value: "1" }, /offers no attribute/);
  no({ attr: "status;id", op: "==", value: "1" }, /offers no attribute/);
  no({ attr: "location", op: "==", value: "1" }, /offers no attribute/);
  no({ attr: "refStation", op: "==", value: "x" }, /offers no attribute/);
  no({ attr: "status", op: ">", value: "1" }, /no condition/);
  no({ attr: "open", op: "!=", value: "true" }, /no condition/);
  no({ attr: "availableBikeNumber", op: "==", value: "5;id==1" }, /needs a number/);
  no({ attr: "availableBikeNumber", op: "==", value: "Infinity" }, /needs a number/);
  no({ attr: "open", op: "==", value: "yes" }, /true or false/);
  no({ attr: "dateModified", op: ">=", value: "2026-13-45" }, /needs a date/);
  no({ attr: "dateModified", op: ">=", value: "now;x==1" }, /needs a date/);
  no({ attr: "status", op: "==", value: "" }, /needs a value/);
  no({ attr: "status", op: "==", value: "a".repeat(201) }, /200 characters/);
  assert.throws(() => x.buildQ([], "a".repeat(201), ALLOWED, KIND), /200 characters/);
});

test("every operator a kind offers builds, so no select offers a dead option", () => {
  for (const [attr, kind] of Object.entries({ availableBikeNumber: "number", dateModified: "date", open: "boolean", status: "text", name: "lang" })) {
    for (const op of x.OPS[kind]) {
      const value = { number: "1", date: "2026-10-01", boolean: "false", text: "a", lang: "a" }[kind];
      assert.ok(x.buildQ([{ attr, op, value }], "", ALLOWED, KIND).startsWith(attr));
    }
  }
});

test("the map's view becomes a closed within-polygon, clamped to the globe", () => {
  const b = x.bboxQuery([-200, -95, 24.95123456, 60.1]);
  assert.equal(b.georel, "within");
  assert.equal(b.coordinates, JSON.stringify([[[-180, -90], [24.951235, -90], [24.951235, 60.1], [-180, 60.1], [-180, -90]]]));
});

test("links stay under the Endpoint and carry the query", () => {
  const api = "https://api.dev.joinedcontext.com/api/endpoint/abc/";
  const l = x.links(api, "Bike", 'status=="x"', "urn:ngsi-ld:Bike:1");
  assert.ok(l.every((k) => k.href.startsWith(api)));
  assert.equal(l[0].href, api + "ngsi-ld/v1/entities/urn%3Angsi-ld%3ABike%3A1");
  assert.ok(l[1].href.includes("q=status%3D%3D%22x%22"));
  assert.equal(x.links(api, "Bike", "").length, 4);
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

test("sorting a page orders numbers and texts and keeps empty values last", () => {
  const rows = [{ v: 3 }, { v: null }, { v: 10 }, { v: 1 }];
  assert.deepEqual(x.sortRows(rows, "v", "ascending").map((r) => r.v), [1, 3, 10, null]);
  assert.deepEqual(x.sortRows(rows, "v", "descending").map((r) => r.v), [10, 3, 1, null]);
});

test("both languages name every string", () => {
  const keys = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? keys(v, p + k + ".") : [p + k])).sort();
  assert.deepEqual(keys(x.TEXT.sk), keys(x.TEXT.en));
});

test("a timestamp reads as a date in the page's language, in UTC", () => {
  assert.equal(x.show("2026-10-21T19:35:26Z", { locale: "en-GB" }).text, "21 Oct 2026, 19:35 UTC");
  assert.equal(x.show("2026-10-21", { locale: "en-GB" }).text, "2026-10-21");
});
