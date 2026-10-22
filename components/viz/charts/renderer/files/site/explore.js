// The live explorer on viz.{domain} (T-5059, T-5082): the catalogue's view of one public Endpoint.
// The table is the Portal's Endpoint data view, the same component (explorer/explorer.js, built
// from the Portal by scripts/viz-explorer-bundle.sh): filters, server-side order, paging, Fields,
// full window and CSV. This script holds the address (type, q and order in the hash, so a link
// opens the same view), the map of the same query and the query's API addresses. Everything is
// read from api.{domain} anonymously (no token, no cookie) and nothing is copied.
(function (root) {
  "use strict";

  var MAPLIBRE = "/vendor/maplibre-gl-6.14.0.mjs";
  var WORKER = "/vendor/maplibre-gl-worker-6.14.0.mjs";
  var SLUG = /^[a-z0-9]{16,64}$/;
  var NAME = /^[A-Za-z][A-Za-z0-9_]{0,127}$/;
  var DATE = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;
  var TIMEOUT_MS = 15000;
  var MAP_LIMIT = 1000;
  var COLOUR = "#1f5fae";
  var TEXT = {
    en: {
      title: "Live data", loading: "Loading live data…", dataApi: "Data API", close: "Close", map: "Map", detail: "Details",
      failed: { 403: "This Endpoint is not public: the catalogue shows only what anyone may read.", 404: "The Endpoint was not found. It may have been unpublished.", 502: "The data service did not answer. Try again in a minute.", other: "The data could not be loaded (HTTP {status}). Try again in a minute." },
      timeout: "The data took longer than 15 seconds. Narrow the search or try again.", noAddress: "This page shows the live data of an open-data Endpoint; the address names none.",
      noWidget: "The table could not start. Reload the page; if it stays, the catalogue's administrators can see why in the browser console.",
      mapHint: "Click a point to open its details. The table lists the same entities.", mapCap: "The map shows the first {n} of {total} in view; zoom in for the rest.",
      mapNone: "No entity of this query has a location.", links: "This query elsewhere", entityLink: "This entity in NGSI-LD", queryLink: "This query in NGSI-LD",
      viewLink: "This view (type, filter and order)", yes: "yes", no: "no"
    },
    sk: {
      title: "Živé dáta", loading: "Načítavam živé dáta…", dataApi: "Dátové API", close: "Zavrieť", map: "Mapa", detail: "Detail",
      failed: { 403: "Tento Endpoint nie je verejný: katalóg ukazuje len to, čo môže čítať ktokoľvek.", 404: "Endpoint sa nenašiel. Možno ho zrušili.", 502: "Dátová služba neodpovedala. Skúste to o minútu.", other: "Dáta sa nepodarilo načítať (HTTP {status}). Skúste to o minútu." },
      timeout: "Dáta sa načítavali dlhšie ako 15 sekúnd. Zúžte hľadanie alebo to skúste znova.", noAddress: "Táto stránka ukazuje živé dáta Endpointu otvorených dát; adresa žiadny neuvádza.",
      noWidget: "Tabuľka sa nespustila. Načítajte stránku znova; ak to pretrváva, správcovia katalógu vidia príčinu v konzole prehliadača.",
      mapHint: "Kliknite na bod a otvorí sa jeho detail. Tabuľka uvádza tie isté entity.", mapCap: "Mapa ukazuje prvých {n} z {total} vo výreze; priblížte pre ďalšie.",
      mapNone: "Žiadna entita tohto dopytu nemá polohu.", links: "Tento dopyt inde", entityLink: "Táto entita v NGSI-LD", queryLink: "Tento dopyt v NGSI-LD",
      viewLink: "Toto zobrazenie (typ, filter a poradie)", yes: "áno", no: "nie"
    }
  };

  var ORDER = /^(id|[A-Za-z][A-Za-z0-9_]{0,127})(;(asc|desc))?$/;
  var MAX_Q = 2000;

  // `#{slug}`, then `&lang=sk`, `&type=T`, `&inline`, `&theme=dark|light`, `&q=…` (the NGSI-LD
  // query, URI-encoded) and `&sort=attr;desc` in any order. The view checks the order against
  // the type's columns again; the Endpoint checks q.
  function parseHash(hash) {
    var parts = String(hash || "").replace(/^#/, "").split("&");
    if (!SLUG.test(parts[0])) return null;
    var out = { slug: parts[0], lang: null, type: null, inline: false, theme: null, q: null, sort: null };
    parts.slice(1).forEach(function (p) {
      var m = /^(lang|type|theme|q|sort)=(.+)$/.exec(p);
      var v = null;
      try { v = m && decodeURIComponent(m[2]); } catch (e) { v = null; }
      if (p === "inline") out.inline = true;
      else if (!m || v === null) return;
      else if (m[1] === "lang" && /^[a-z]{2}$/.test(v)) out.lang = v;
      else if (m[1] === "type" && NAME.test(v)) out.type = v;
      else if (m[1] === "theme" && /^(dark|light)$/.test(v)) out.theme = v;
      else if (m[1] === "q" && v.length <= MAX_Q) out.q = v;
      else if (m[1] === "sort" && ORDER.test(v)) out.sort = v;
    });
    return out;
  }

  // The hash for a view: what parseHash reads back.
  function hashOf(where) {
    var out = "#" + where.slug;
    if (where.inline) out += "&inline";
    ["lang", "theme", "type", "q", "sort"].forEach(function (k) {
      if (where[k]) out += "&" + k + "=" + encodeURIComponent(where[k]);
    });
    return out;
  }

  // viz.{domain} → the Endpoint's base on api.{domain}: named by this page's host, never by a parameter.
  function base(hostname, slug) {
    return "https://api." + String(hostname).replace(/^viz\./, "") + "/api/endpoint/" + slug + "/";
  }

  // The kind of each attribute, read from a normalized sample: what a filter on it may compare.
  // Geometry, relationships and structured values get no filter (null).
  function params(map) {
    return Object.keys(map)
      .filter(function (k) { return map[k] !== undefined && map[k] !== null && map[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(map[k]); })
      .join("&");
  }

  function entitiesUrl(api, query) {
    return api + "ngsi-ld/v1/entities?" + params(query);
  }

  // The map's view as an NGSI-LD `within` polygon, west/south/east/north clamped to the globe.
  function bboxQuery(b) {
    var c = function (v, lim) { return Math.max(-lim, Math.min(lim, Math.round(v * 1e6) / 1e6)); };
    var w = c(b[0], 180), s = c(b[1], 90), e = c(b[2], 180), n = c(b[3], 90);
    return { georel: "within", geometry: "Polygon", coordinates: JSON.stringify([[[w, s], [e, s], [e, n], [w, n], [w, s]]]) };
  }

  // The same rows elsewhere: the entity, the query, OData, OGC API Features and CSV of its type.
  function links(api, type, q, order, id) {
    var out = [];
    if (id) out.push({ key: "entityLink", href: api + "ngsi-ld/v1/entities/" + encodeURIComponent(id) });
    out.push({ key: "queryLink", href: entitiesUrl(api, { type: type, q: q, orderBy: order }) });
    out.push({ key: "OData v4", href: api + "odata/v4/" + type });
    out.push({ key: "OGC API - Features", href: api + "ogc/features/collections/" + type + "/items" });
    out.push({ key: "CSV", href: api + "file.csv?" + params({ type: type, q: q, orderBy: order }) });
    return out;
  }

  // A keyValues value as a person reads it: text, and a link when it is a web address. GeoJSON
  // becomes its kind and first position, a list its items, an object its members; never raw JSON.
  function show(value, t) {
    if (value === null || value === undefined || value === "") return { text: "–" };
    if (typeof value === "boolean") return { text: value ? t.yes : t.no };
    if (typeof value === "number") return { text: new Intl.NumberFormat(t.locale, { maximumFractionDigits: 6 }).format(value) };
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) && DATE.test(value) && t.locale) {
      return { text: new Intl.DateTimeFormat(t.locale, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(Date.parse(value)) + " UTC" };
    }
    if (typeof value === "string") return /^https?:\/\/[^\s]+$/.test(value) ? { text: value, href: value } : { text: value };
    if (Array.isArray(value)) return { text: value.map(function (v) { return show(v, t).text; }).join("; ") };
    if (typeof value.type === "string" && Array.isArray(value.coordinates)) {
      var p = value.coordinates;
      while (Array.isArray(p[0])) p = p[0];
      return { text: value.type + " " + p.slice(0, 2).map(function (n) { return Number(n).toFixed(5); }).join(", ") };
    }
    if (value.languageMap && typeof value.languageMap === "object") {
      var m = value.languageMap;
      return { text: String(m[t.lang] || m[Object.keys(m)[0]] || "–") };
    }
    if (value["@value"] !== undefined) return show(value["@value"], t);
    return { text: Object.keys(value).map(function (k) { return k + ": " + show(value[k], t).text; }).join(", ") };
  }

  function say(text, vars) {
    return String(text).replace(/\{(\w+)\}/g, function (_, k) { return vars && vars[k] !== undefined ? vars[k] : ""; });
  }

  // ---- the page ----

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else if (attrs[k] !== false && attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  function valueNode(value, t) {
    var said = show(value, t);
    if (!said.href) return document.createTextNode(said.text);
    return el("a", { href: said.href, target: "_blank", rel: "noopener noreferrer", text: said.text });
  }

  function main() {
    var where = parseHash(location.hash);
    var lang = (where && where.lang) || ((navigator.language || "en").slice(0, 2) === "sk" ? "sk" : "en");
    var t = TEXT[lang] || TEXT.en;
    t.lang = lang;
    t.locale = lang === "sk" ? "sk-SK" : "en-GB";
    document.documentElement.lang = lang;
    if (where && where.theme) document.documentElement.setAttribute("data-theme", where.theme);
    if (where && where.inline) document.body.classList.add("inline");
    var $ = function (id) { return document.getElementById(id); };
    var status = $("status");
    Array.prototype.forEach.call(document.querySelectorAll("[data-t]"), function (n) { n.textContent = t[n.getAttribute("data-t")]; });

    // The catalogue sizes the frame from this message. The content's own box, not the document's:
    // the view's stylesheet makes html as tall as the frame, which would hold the frame at its size.
    function height() {
      var h = Math.ceil(document.querySelector("main").getBoundingClientRect().bottom + window.scrollY);
      if (window.parent !== window) window.parent.postMessage({ type: "jc-viz-height", height: h }, "*");
    }
    if (typeof ResizeObserver === "function") new ResizeObserver(height).observe(document.querySelector("main"));

    function tell(text, kind) {
      status.textContent = text || "";
      status.className = "status" + (kind ? " " + kind : "");
      height();
    }

    if (!where) {
      $("app").hidden = true;
      return tell(t.noAddress, "error");
    }
    var api = base(location.hostname, where.slug);
    var state = { types: [], type: where.type, q: where.q || "", sort: where.sort, map: null, mapData: null, mapAsk: 0 };

    // Every request: anonymous, no referrer, given up after 15 seconds; a non-2xx is an Error with its status.
    function get(url, accept) {
      var controller = new AbortController();
      var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);
      return fetch(url, { credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal, headers: { Accept: accept || "application/json" } })
        .then(function (r) {
          if (!r.ok) {
            var e = new Error("HTTP " + r.status);
            e.status = r.status;
            throw e;
          }
          return r.json().then(function (body) { return { body: body, count: r.headers.get("NGSILD-Results-Count") }; });
        })
        .finally(function () { clearTimeout(timer); });
    }

    function failure(error) {
      if (error && error.name === "AbortError") return t.timeout;
      var s = error && error.status;
      return s ? t.failed[s] || say(t.failed.other, { status: s }) : say(t.failed.other, { status: "–" });
    }

    function detail(row, from) {
      var dialog = $("detail");
      $("detail-title").textContent = row.name !== undefined ? show(row.name, t).text : row.id;
      var list = $("detail-list");
      list.textContent = "";
      list.appendChild(el("dt", { text: "id" }));
      list.appendChild(el("dd", { text: row.id }));
      Object.keys(row).filter(function (k) { return k !== "id" && k !== "@context"; }).forEach(function (k) {
        list.appendChild(el("dt", { text: k }));
        list.appendChild(el("dd", {}, [valueNode(row[k], t)]));
      });
      linkList(row.id);
      dialog.returnFocus = from;
      dialog.showModal();
    }

    function linkList(id) {
      var out = $("detail-links");
      out.textContent = "";
      links(api, state.type, state.q, state.sort, id).concat(id ? [] : [{ key: "viewLink", href: location.href }]).forEach(function (l) {
        out.appendChild(el("li", {}, [el("a", { href: l.href, target: "_blank", rel: "noopener noreferrer", text: t[l.key] || l.key })]));
      });
    }

    // The map: geo+json of the same query within the view, at most MAP_LIMIT features a view.
    function drawMap() {
      var section = $("map-section");
      var info = state.types.filter(function (x) { return x.typeName === state.type; })[0];
      var geo = !!info && (info.attributeNames || []).indexOf("location") >= 0;
      section.hidden = !geo;
      if (!geo) return;
      if (state.map) return mapMoved();
      import(MAPLIBRE).then(function (maplibre) {
        maplibre.setWorkerUrl(WORKER);
        if (root.pmtiles) maplibre.addProtocol("pmtiles", new root.pmtiles.Protocol().tile);
        var domain = location.hostname.replace(/^viz\./, "");
        var map = new maplibre.Map({ container: "map", style: "https://tiles." + domain + "/styles/light-" + (lang === "sk" ? "sk" : "en") + ".json", attributionControl: false, center: [17.1, 48.15], zoom: 4 });
        state.map = map;
        state.maplibre = maplibre;
        map.addControl(new maplibre.NavigationControl({ showCompass: false }));
        map.addControl(new maplibre.AttributionControl({ compact: true }));
        map.once("load", function () {
          map.addSource("jc", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
          map.addLayer({ id: "jc-fill", type: "fill", source: "jc", filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": COLOUR, "fill-opacity": 0.25 } });
          map.addLayer({ id: "jc-line", type: "line", source: "jc", filter: ["!", ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]]], paint: { "line-color": COLOUR, "line-width": 2 } });
          map.addLayer({ id: "jc-point", type: "circle", source: "jc", filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]], paint: { "circle-color": COLOUR, "circle-radius": 6, "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
          ["jc-point", "jc-line", "jc-fill"].forEach(function (layer) {
            map.on("click", layer, function (e) {
              var f = (state.mapData || []).filter(function (x) { return x.id === e.features[0].properties.jcId; })[0];
              if (f) detail(Object.assign({ id: f.id }, f.properties), map.getCanvas());
            });
            map.on("mouseenter", layer, function () { map.getCanvas().style.cursor = "pointer"; });
            map.on("mouseleave", layer, function () { map.getCanvas().style.cursor = ""; });
          });
          map.on("moveend", mapMoved);
          fitFirst().then(mapMoved);
        });
      }, function () { $("map-note").textContent = failure(null); });
    }

    // The first view: the bounds of the query's first page, so the map opens where the data is.
    function fitFirst() {
      var url = entitiesUrl(api, { type: state.type, q: state.q, limit: 25, lang: lang, format: "keyValues" });
      return get(url, "application/geo+json").then(function (answer) {
        var all = [];
        ((answer.body && answer.body.features) || []).forEach(function (f) {
          var walk = function (c) { if (typeof c[0] === "number") all.push(c); else c.forEach(walk); };
          if (f.geometry && f.geometry.coordinates) walk(f.geometry.coordinates);
        });
        if (!all.length) return;
        var lon = all.map(function (p) { return p[0]; }), lat = all.map(function (p) { return p[1]; });
        var box = [[Math.min.apply(null, lon), Math.min.apply(null, lat)], [Math.max.apply(null, lon), Math.max.apply(null, lat)]];
        if (box[0][0] === box[1][0] && box[0][1] === box[1][1]) state.map.jumpTo({ center: box[0], zoom: 14 });
        else state.map.fitBounds(box, { padding: 30, maxZoom: 15, animate: false });
      }, function () {});
    }

    function mapMoved() {
      var map = state.map;
      if (!map || !map.getSource("jc")) return;
      var b = map.getBounds();
      var query = Object.assign({ type: state.type, q: state.q, limit: MAP_LIMIT, count: "true", lang: lang, format: "keyValues" }, bboxQuery([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]));
      var asked = ++state.mapAsk;
      get(entitiesUrl(api, query), "application/geo+json").then(function (answer) {
        if (asked !== state.mapAsk) return;
        var features = ((answer.body && answer.body.features) || []).filter(function (f) { return f && f.geometry; });
        state.mapData = features;
        map.getSource("jc").setData({ type: "FeatureCollection", features: features.map(function (f) {
          return { type: "Feature", geometry: f.geometry, properties: { jcId: f.id } };
        }) });
        var total = answer.count === null ? features.length : +answer.count;
        $("map-note").textContent = !features.length ? t.mapNone : total > features.length ? say(t.mapCap, { n: features.length, total: total }) : t.mapHint;
      }, function (e) { if (asked === state.mapAsk) $("map-note").textContent = failure(e); });
    }
    state.mapAsk = 0;

    // The view says which type, query and order it shows: the address, the map and the API links follow.
    function onLink(next) {
      var moved = next.type !== state.type || (next.q || "") !== state.q;
      state.type = next.type || null;
      state.q = next.q || "";
      state.sort = next.sort || null;
      history.replaceState(null, "", hashOf({ slug: where.slug, inline: where.inline, lang: where.lang, theme: where.theme, type: state.type, q: state.q, sort: state.sort }));
      if (moved) drawMap();
    }

    $("data-api").addEventListener("click", function () {
      $("detail-title").textContent = t.dataApi;
      $("detail-list").textContent = "";
      $("detail-list").appendChild(el("dt", { text: "q" }));
      $("detail-list").appendChild(el("dd", { text: state.q || "–" }));
      linkList(null);
      $("detail").returnFocus = $("data-api");
      $("detail").showModal();
    });
    $("detail-close").addEventListener("click", function () { $("detail").close(); });
    $("detail").addEventListener("close", function () { var f = $("detail").returnFocus; if (f && f.focus) f.focus(); });
    window.addEventListener("resize", height);

    // The type list only says which types have a location, for the map; the view reads its own.
    get(api + "ngsi-ld/v1/types?details=true").then(function (answer) {
      state.types = (Array.isArray(answer.body) ? answer.body : []).filter(function (x) { return x && NAME.test(x.typeName || ""); });
      drawMap();
    }, function () {});

    if (!root.jcExplorer || typeof root.jcExplorer.mount !== "function") return tell(t.noWidget, "error");
    try {
      root.jcExplorer.mount($("grid"), {
        origin: "https://api." + String(location.hostname).replace(/^viz\./, ""),
        slug: where.slug,
        lang: lang,
        link: { type: where.type || undefined, q: where.q || undefined, sort: where.sort || undefined },
        onLink: onLink,
        csv: true
      });
    } catch (e) {
      tell(t.noWidget, "error");
    }
    height();
  }

  root.jcExplore = { parseHash: parseHash, hashOf: hashOf, base: base, entitiesUrl: entitiesUrl, bboxQuery: bboxQuery, links: links, show: show, TEXT: TEXT };
  if (typeof module === "object" && module.exports) module.exports = root.jcExplore;
  else if (typeof document !== "undefined") main();
})(typeof self !== "undefined" ? self : this);
