// The dataset map (T-4639): the features of each table's entity type, read live from the
// Endpoint's OGC API Features by the reader's browser, drawn with MapLibre, and one panel with a
// feature's readable values. Every value reaches the page as text, never as markup. Without
// script, or without a geometry, the block stays hidden and the table is the data.

const PAGE = 1000; // features per request: the Endpoint takes seconds per request, not per feature
const CAP = 5000; // features per view
const UNITS = { Cel: "°C", deg: "°", "m/s": "m/s", hPa: "hPa", mm: "mm", m: "m", km: "km", "%": "%" };
const HIDDEN = new Set(["id", "type", "@context", "location", "geometry"]);

if (typeof document !== "undefined") {
  for (const box of document.querySelectorAll("[data-jc-map]")) {
    start(box).catch((error) => {
      // The block says it failed, the console says why; the table above is the data either way.
      console.warn("jc-map:", error);
      const note = box.querySelector(".jc-map-note");
      try {
        note.textContent = JSON.parse(box.getAttribute("data-jc-map")).t.map_failed;
      } catch {
        note.textContent = "";
      }
    });
  }
}

async function start(box) {
  const config = JSON.parse(box.getAttribute("data-jc-map"));
  const card = box.closest(".jc-map-card");
  const note = box.querySelector(".jc-map-note");
  box.dataset.state = "loading";
  note.textContent = config.t.map_loading;
  // One round trip before the first point (T-4661): the first page of every layer is asked for
  // at once, beside the library, the schemas and the labels, and drawn as soon as it is here.
  let latest = { features: [], capped: false };
  let shown = null; // draws `latest` once the map is up
  let arrived;
  const firstPage = new Promise((resolve) => { arrived = resolve; });
  const all = fetchAll(config.layers, null, (got) => { latest = got; arrived(); if (shown) shown(got); });
  all.then(arrived, arrived);
  const units = schemas(config.layers);
  const [maplibre, order] = await Promise.all([import(config.lib), fieldOrder(config.fields), firstPage]);
  if (!latest.features.length) await all;
  if (!latest.features.length) {
    if (!card) note.textContent = config.t.map_failed;
    return;
  }
  if (card) card.hidden = false;
  if (window.pmtiles && !pmtilesAdded) {
    // The basemap's vector tiles are byte ranges of one file on the tiles host (T-4638).
    maplibre.addProtocol("pmtiles", new window.pmtiles.Protocol().tile);
    pmtilesAdded = true;
  }
  const area = box.querySelector(".jc-map-area");
  const map = new maplibre.Map({ container: area, style: basemap(config.basemap, config.lang), attributionControl: false, center: [0, 0], zoom: 1 });
  map.addControl(new maplibre.NavigationControl({ showCompass: false }));
  map.addControl(new maplibre.AttributionControl({ compact: true }));
  if (card) {
    // On the dataset page the wheel scrolls the page until the reader turns to the map.
    map.scrollZoom.disable();
    const wake = () => map.scrollZoom.enable();
    area.addEventListener("pointerdown", wake, { once: true });
    area.addEventListener("focusin", wake, { once: true });
  }
  const panel = makePanel(box, Object.assign({}, config, { order }), map);
  await new Promise((resolve) => map.once("load", resolve));
  const schemasOf = await units;

  // Points cluster in a source of their own: a clustered source keeps nothing but points.
  map.addSource("jc", { type: "geojson", data: empty(), generateId: true });
  map.addSource("jc-points", { type: "geojson", data: empty(), cluster: true, clusterMaxZoom: 13, generateId: true });
  const colour = getComputedStyle(document.documentElement).getPropertyValue("--jc-primary").trim() || "#1d4ed8";
  const selected = ["boolean", ["feature-state", "selected"], false];
  const hover = ["boolean", ["feature-state", "hover"], false];
  const is = (...types) => ["in", ["geometry-type"], ["literal", types]];
  map.addLayer({ id: "jc-fill", type: "fill", source: "jc", filter: is("Polygon", "MultiPolygon"),
    paint: { "fill-color": colour, "fill-opacity": ["case", selected, 0.45, hover, 0.3, 0.15] } });
  map.addLayer({ id: "jc-outline", type: "line", source: "jc", filter: is("Polygon", "MultiPolygon"),
    paint: { "line-color": colour, "line-width": ["case", selected, 3, 1] } });
  map.addLayer({ id: "jc-line", type: "line", source: "jc", filter: is("LineString", "MultiLineString"),
    paint: { "line-color": colour, "line-width": ["case", selected, 6, hover, 5, 3] } });
  map.addLayer({ id: "jc-point", type: "circle", source: "jc-points",
    filter: ["all", is("Point", "MultiPoint"), ["!", ["has", "point_count"]]],
    paint: { "circle-color": colour, "circle-radius": ["case", selected, 9, 6], "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
  const clickable = ["jc-fill", "jc-line", "jc-point"];

  let features = [];
  let capped = false;
  const put = (got) => {
    features = got.features;
    capped = got.capped;
    const point = (f) => f.geometry.type === "Point" || f.geometry.type === "MultiPoint";
    map.getSource("jc").setData({ type: "FeatureCollection", features: features.filter((f) => !point(f)) });
    map.getSource("jc-points").setData({ type: "FeatureCollection", features: features.filter(point) });
  };
  const fit = () => {
    const bounds = extent(features);
    if (bounds) map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
  };
  const done = () => {
    note.textContent = capped ? config.t.map_cap.replace("{n}", CAP.toLocaleString(config.lang)) : "";
    box.dataset.state = "ready";
  };
  put(latest);
  fit();
  shown = put;
  box.jcMap = map; // a journey test projects features to click from it
  const firstCount = features.length;
  try {
    await all;
  } catch {
    note.textContent = config.t.map_failed;
    box.dataset.state = "failed";
    return;
  }
  shown = null;
  put(latest);
  if (features.length !== firstCount) fit();
  done();
  const load = async (bbox) => {
    box.dataset.state = "loading";
    note.textContent = config.t.map_loading;
    put(await fetchAll(config.layers, bbox, () => {}));
    done();
  };
  // Past the cap the view loads what it shows; under it everything is already here.
  map.on("moveend", () => { if (capped) load(viewBox(map)).catch(() => { note.textContent = config.t.map_failed; }); });

  // Clusters as buttons with their count: no font to fetch, and a keyboard reaches each one.
  const markers = new Map();
  const drawClusters = () => {
    const seen = new Set();
    for (const f of map.querySourceFeatures("jc-points", { filter: ["has", "point_count"] })) {
      const id = f.properties.cluster_id;
      if (seen.has(id)) continue;
      seen.add(id);
      if (!markers.has(id)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "jc-map-cluster";
        button.textContent = Number(f.properties.point_count).toLocaleString(config.lang);
        button.addEventListener("click", async () => {
          const zoom = await map.getSource("jc-points").getClusterExpansionZoom(id);
          map.easeTo({ center: f.geometry.coordinates, zoom });
        });
        markers.set(id, new maplibre.Marker({ element: button }).setLngLat(f.geometry.coordinates).addTo(map));
      }
    }
    for (const [id, marker] of markers) if (!seen.has(id)) { marker.remove(); markers.delete(id); }
  };
  map.on("render", () => { if (map.isSourceLoaded("jc-points")) drawClusters(); });

  let hovered = null;
  const setState = (id, state) => id !== null && map.setFeatureState({ source: "jc", id }, state); // lines and areas
  for (const layer of ["jc-fill", "jc-line"]) {
    map.on("mousemove", layer, (e) => {
      if (hovered !== e.features[0].id) { setState(hovered, { hover: false }); hovered = e.features[0].id; setState(hovered, { hover: true }); }
    });
    map.on("mouseleave", layer, () => { setState(hovered, { hover: false }); hovered = null; });
  }
  for (const layer of clickable) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", (e) => {
    // A thin line is hard to hit with a finger: the exact point first, then a small box around it.
    const { x, y } = e.point;
    const hit = map.queryRenderedFeatures(e.point, { layers: clickable })[0]
      || map.queryRenderedFeatures([[x - 8, y - 8], [x + 8, y + 8]], { layers: clickable })[0];
    if (hit) panel.open(hit, features[hit.properties._n], schemasOf);
  });
  // Enter opens what sits in the middle of the view; the arrows and +/- are MapLibre's own.
  map.getCanvas().addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const { x, y } = map.project(map.getCenter());
    const hit = map.queryRenderedFeatures([[x - 12, y - 12], [x + 12, y + 12]], { layers: clickable })[0];
    if (hit) panel.open(hit, features[hit.properties._n], schemasOf);
  });
}

let pmtilesAdded = false;

// The importance order and labels the DataStore table and the assistant share (T-4661); without
// them the panel reads the attribute names in the broker's order.
async function fieldOrder(url) {
  try {
    return url ? await getJson(new URL(url, location.href).href) : null;
  } catch {
    return null;
  }
}

async function getJson(url) {
  const response = await fetch(url, { credentials: "omit", headers: { Accept: "application/geo+json, application/json" } });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function withParams(url, params) {
  const out = new URL(url);
  for (const [k, v] of Object.entries(params)) out.searchParams.set(k, v);
  return out.href;
}

// Every layer's features, page by page along the `next` links, at most CAP in all, handed to
// `onPage` after each page. A `next` link is followed only on the same address, so a response
// cannot send the browser elsewhere.
async function fetchAll(layers, bbox, onPage) {
  const features = [];
  for (const [index, layer] of layers.entries()) {
    const base = new URL(layer.items);
    let url = withParams(layer.items, bbox ? { limit: String(PAGE), bbox: bbox.join(",") } : { limit: String(PAGE) });
    while (url && features.length < CAP) {
      const page = await getJson(url);
      for (const f of page.features || []) {
        if (!f || !f.geometry || features.length >= CAP) continue;
        // The drawn feature is cut to its tile; `_n` finds the whole one for length and area.
        f.properties = Object.assign({}, f.properties, { _layer: index, _id: f.id || "", _n: features.length });
        features.push(f);
      }
      onPage({ features: features.slice(), capped: features.length >= CAP });
      const next = (page.links || []).find((l) => l.rel === "next");
      url = null;
      if (next && next.href) {
        const candidate = new URL(next.href, base);
        if (candidate.origin === base.origin && candidate.pathname === base.pathname) url = candidate.href;
      }
    }
    if (features.length >= CAP) return { features, capped: true };
  }
  return { features, capped: false };
}

// The view as a bbox the Endpoint accepts: inside the world, six decimals.
function viewBox(map) {
  const b = map.getBounds();
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, Number(v.toFixed(6))));
  return [clamp(b.getWest(), -180, 180), clamp(b.getSouth(), -90, 90), clamp(b.getEast(), -180, 180), clamp(b.getNorth(), -90, 90)];
}

function extent(features) {
  let box = null;
  const walk = (c) => {
    if (typeof c[0] === "number") {
      box = box ? [Math.min(box[0], c[0]), Math.min(box[1], c[1]), Math.max(box[2], c[0]), Math.max(box[3], c[1])] : [c[0], c[1], c[0], c[1]];
    } else c.forEach(walk);
  };
  for (const f of features) walk(f.geometry.coordinates);
  return box && [[box[0], box[1]], [box[2], box[3]]];
}

function empty() {
  return { type: "FeatureCollection", features: [] };
}

// The tiles host's style in the page's language where it has one (light-sk.json, light-en.json…).
function basemap(base, lang) {
  const code = String(lang || "").split(/[-_]/)[0];
  if (base && base.style) return ["sk", "en", "cs", "fi"].includes(code) ? base.style.replace(/-[a-z]{2}\.json$/, "-" + code + ".json") : base.style;
  return { version: 8, sources: {}, layers: [{ id: "paper", type: "background", paint: { "background-color": "#f3f4f1" } }] };
}

// Per layer, each property's unit and description from the collection's schema.
async function schemas(layers) {
  return Promise.all(layers.map(async (layer) => {
    try {
      const schema = await getJson(layer.schema);
      return schema.properties || {};
    } catch {
      return {};
    }
  }));
}

function makePanel(box, config, map) {
  const panel = document.createElement("section");
  panel.className = "jc-map-panel";
  panel.hidden = true;
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", config.t.map_panel);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "jc-map-close";
  close.setAttribute("aria-label", config.t.map_close);
  close.textContent = "✕";
  const title = document.createElement("h3");
  const list = document.createElement("dl");
  panel.append(close, title, list);
  box.append(panel);
  let selected = null; // { source, id } of the drawn feature
  const shut = () => {
    panel.hidden = true;
    if (selected) map.setFeatureState(selected, { selected: false });
    selected = null;
    map.getCanvas().focus();
  };
  close.addEventListener("click", shut);
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") shut(); });
  map.getCanvas().addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) shut(); });
  return {
    open(drawn, feature, units) {
      if (!feature) return;
      if (selected) map.setFeatureState(selected, { selected: false });
      selected = { source: drawn.source, id: drawn.id };
      map.setFeatureState(selected, { selected: true });
      const schema = units[feature.properties._layer] || {};
      const rows = describe(feature, schema, config);
      title.textContent = rows.title;
      list.replaceChildren();
      for (const [label, value, hint, kind] of rows.rows) {
        const dt = document.createElement("dt");
        dt.textContent = label;
        if (hint) dt.title = hint;
        const dd = document.createElement("dd");
        if (kind === "link") {
          const a = document.createElement("a");
          a.href = value;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = value;
          dd.append(a);
        } else {
          dd.textContent = value;
        }
        if (kind === "meta") dt.className = dd.className = "jc-map-meta";
        list.append(dt, dd);
      }
      panel.hidden = false;
      close.focus();
    },
  };
}

// A feature's properties as rows a person reads, in the order and with the labels the DataStore
// table has (T-4661, `config.order`): the page's language of a name as the title, the start with
// its time, numbers with their unit, a category in words, a link, the rest, and the record's
// source and dates last in small type. A time reads as "5 min ago" or a date, a line's length
// and an area's size follow. Identifiers, links to other entities and nested objects stay out.
// Each row is [label, text, hint, kind], kind "link" (an http(s) address), "meta" or "".
export function describe(feature, schema, config) {
  const lang = String(config.lang || "en").split(/[-_]/)[0];
  const order = config.order || { groups: [], labels: {}, enums: {} };
  const props = feature.properties || {};
  const plain = {};
  let title = "";
  for (const [key, raw] of Object.entries(props)) {
    if (HIDDEN.has(key) || key.startsWith("_") || /^ref[A-Z]/.test(key)) continue;
    let value = raw;
    if (value && typeof value === "object" && value.languageMap) value = value.languageMap[lang] ?? Object.values(value.languageMap)[0];
    if (value === null || value === undefined || value === "" || typeof value === "object") continue;
    if (typeof value === "string" && value.startsWith("urn:")) continue;
    if (key === "name" && !title) { title = String(value); continue; }
    plain[key] = value;
  }
  // A start takes its time along, and the time is not repeated; the same for the end.
  for (const [date, time] of [["startDate", "startTime"], ["endDate", "endTime"]]) {
    if (typeof plain[date] !== "string" || typeof plain[time] !== "string") continue;
    if (/^\d{4}-\d{2}-\d{2}$/.test(plain[date]) && /^\d{2}:\d{2}(:\d{2})?$/.test(plain[time])) {
      plain[date] += "T" + plain[time];
      delete plain[time];
    } else if (plain[date].includes("T")) {
      delete plain[time];
    }
  }
  const at = (key) => rank(order, key, typeof plain[key] === "number");
  const rows = [];
  for (const key of Object.keys(plain).sort((a, b) => at(a) - at(b))) {
    const value = plain[key];
    const meta = schema[key] || {};
    const group = groupOf(order, key, typeof value === "number");
    let text;
    let kind = group === "meta" ? "meta" : "";
    if (typeof value === "number") {
      text = value.toLocaleString(lang, { maximumFractionDigits: 3 });
      const unit = UNITS[meta["x-ogc-unit"]] ?? meta["x-ogc-unit"];
      if (unit) text += (unit === "°" || unit === "%" ? "" : "\u00a0") + unit;
    } else if (typeof value === "string" && DATED.has(key) && /^\d{4}-\d{2}-\d{2}/.test(value)) {
      text = dated(value, lang);
    } else if (typeof value === "string" && (meta.format === "date-time" || /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value))) {
      text = when(value, lang);
    } else if (group === "link" && web(value)) {
      text = String(value);
      kind = "link";
    } else if (group === "category" && typeof value === "string") {
      text = words(order.enums, value, lang, /^[a-z]+([A-Z][a-z0-9]*)+$/.test(value));
    } else {
      text = String(value);
    }
    rows.push([words(order.labels, key, lang, true), text, meta.description || "", kind]);
  }
  const g = feature.geometry || {};
  if (g.type === "LineString" || g.type === "MultiLineString") rows.push([config.t.map_length, distance(length(g), lang), "", ""]);
  if (g.type === "Polygon" || g.type === "MultiPolygon") rows.push([config.t.map_area, surface(area(g), lang), "", ""]);
  return { title: title || (feature.properties && feature.properties._id ? String(feature.properties._id).split(":").pop() : ""), rows };
}

// The times that are a date on a calendar, not a moment just measured.
const DATED = new Set(["startDate", "endDate", "validFrom", "validTo"]);

// Ranks per group, as jc-core's field_order: a group's index times this plus the attribute's
// place in its list; one it does not list goes last among the values (a number) or the rest.
const PER_GROUP = 1000;

function rank(order, key, numeric) {
  const groups = order.groups || [];
  for (const [index, g] of groups.entries()) {
    const at = (g.attributes || []).indexOf(key);
    if (at >= 0) return index * PER_GROUP + at;
  }
  const index = groups.findIndex((g) => g.group === (numeric ? "value" : "other"));
  return index < 0 ? Number.MAX_SAFE_INTEGER : index * PER_GROUP + PER_GROUP - 1;
}

function groupOf(order, key, numeric) {
  const g = (order.groups || [])[Math.floor(rank(order, key, numeric) / PER_GROUP)];
  return g ? g.group : "other";
}

// The entry of `table` in `lang`, else in English, else the code spelt as words when `spell`.
function words(table, code, lang, spell) {
  const entry = table && Object.prototype.hasOwnProperty.call(table, code) ? table[code] : null;
  if (entry) return entry[lang] || entry.en;
  if (!spell) return String(code);
  const spelt = String(code).replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return spelt.charAt(0).toUpperCase() + spelt.slice(1);
}

function web(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

// "15. 10. 2026" for a date, "15. 10. 2026, 18:00" for a date with its time.
function dated(value, lang) {
  const t = Date.parse(value);
  if (Number.isNaN(t)) return value;
  // A bare date is midnight UTC to Date.parse, so it is read back in UTC, never the day before.
  const style = value.length > 10 ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium", timeZone: "UTC" };
  return new Intl.DateTimeFormat(lang, style).format(t);
}

function when(stamp, lang) {
  const t = Date.parse(stamp);
  if (Number.isNaN(t)) return stamp;
  const minutes = Math.round((t - Date.now()) / 60000);
  if (Math.abs(minutes) < 60) return new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(minutes, "minute");
  if (Math.abs(minutes) < 24 * 60) return new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(Math.round(minutes / 60), "hour");
  return new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" }).format(t);
}

const R = 6371008.8;
const rad = (d) => (d * Math.PI) / 180;

// Metres along a line, on the sphere.
export function length(geometry) {
  const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
  let m = 0;
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const [x1, y1] = line[i - 1];
      const [x2, y2] = line[i];
      const a = Math.sin(rad(y2 - y1) / 2) ** 2 + Math.cos(rad(y1)) * Math.cos(rad(y2)) * Math.sin(rad(x2 - x1) / 2) ** 2;
      m += 2 * R * Math.asin(Math.sqrt(a));
    }
  }
  return m;
}

// Square metres of a polygon, holes subtracted, on the sphere (Chamberlain and Duquette).
export function area(geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const ring = (coords) => {
    let sum = 0;
    for (let i = 0; i < coords.length - 1; i++) {
      const [x1, y1] = coords[i];
      const [x2, y2] = coords[i + 1];
      sum += rad(x2 - x1) * (2 + Math.sin(rad(y1)) + Math.sin(rad(y2)));
    }
    return Math.abs((sum * R * R) / 2);
  };
  let m2 = 0;
  for (const rings of polygons) rings.forEach((r, i) => { m2 += i === 0 ? ring(r) : -ring(r); });
  return Math.max(0, m2);
}

function distance(m, lang) {
  return m >= 1000
    ? (m / 1000).toLocaleString(lang, { maximumFractionDigits: 2 }) + " km"
    : Math.round(m).toLocaleString(lang) + " m";
}

function surface(m2, lang) {
  if (m2 >= 1e6) return (m2 / 1e6).toLocaleString(lang, { maximumFractionDigits: 2 }) + " km²";
  if (m2 >= 1e4) return (m2 / 1e4).toLocaleString(lang, { maximumFractionDigits: 2 }) + " ha";
  return Math.round(m2).toLocaleString(lang) + " m²";
}
