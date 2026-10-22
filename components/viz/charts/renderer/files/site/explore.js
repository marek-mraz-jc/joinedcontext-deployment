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
  var MVT = "application/vnd.mapbox-vector-tile";
  var COLOUR = "#1f5fae";
  var TEXT = {
    en: {
      title: "Live data", loading: "Loading live data…", dataApi: "Data API", close: "Close", map: "Map", detail: "Details",
      failed: { 403: "This Endpoint is not public: the catalogue shows only what anyone may read.", 404: "The Endpoint was not found. It may have been unpublished.", 502: "The data service did not answer. Try again in a minute.", other: "The data could not be loaded (HTTP {status}). Try again in a minute." },
      timeout: "The data took longer than 15 seconds. Narrow the search or try again.", noAddress: "This page shows the live data of an open-data Endpoint; the address names none.",
      noWidget: "The table could not start. Reload the page; if it stays, the catalogue's administrators can see why in the browser console.",
      mapHint: "Click a point to open its details. The table lists the same entities.", mapCap: "The map shows the first {n} of {total} in view; zoom in for the rest.",
      mapNone: "No entity of this query has a location.", links: "This query elsewhere", entityLink: "This entity in NGSI-LD", queryLink: "This query in NGSI-LD",
      viewLink: "This view (type, filter and order)", yes: "yes", no: "no",
      embed: "Embed", embedLead: "Put this live table on your own website. It keeps reading the current data; nothing is copied.",
      embedKind: "Code", iframe: "Frame (recommended)", component: "Web component", kindHint: "A frame needs no script and works in a WordPress \u201cCustom HTML\u201d block; the web component grows to its content.",
      viewLabel: "Shows", viewBoth: "Table and map", viewTable: "Table only", viewHint: "The map appears only where the entities have a location.",
      langLabel: "Language", langHint: "The widget's labels, e.g. Slovenčina for a Slovak site.", themeLabel: "Colours", themeAuto: "The visitor's setting", themeLight: "Light", themeDark: "Dark", themeHint: "Light or dark, or as the visitor's device is set.",
      heightLabel: "Height in pixels", heightHint: "From 240 to 2000, e.g. 640.", keep: "Keep the current filter and order", keepHint: "Visitors start from this view: {view}", keepNone: "No filter or order is set: visitors see every entity.",
      filterIs: "filter {q}", orderIs: "ordered by {col}", desc: " (descending)",
      code: "Code to paste", copy: "Copy code", copied: "Copied. Paste it into your page's HTML.", copySelect: "Selected: press Ctrl+C to copy.", preview: "Open the widget alone",
      invalid: "Check this setting: {why}.", source: "Source", licence: "Licence", licenceSee: "see the dataset", catalogue: "open data catalogue"
    },
    sk: {
      title: "Živé dáta", loading: "Načítavam živé dáta…", dataApi: "Dátové API", close: "Zavrieť", map: "Mapa", detail: "Detail",
      failed: { 403: "Tento Endpoint nie je verejný: katalóg ukazuje len to, čo môže čítať ktokoľvek.", 404: "Endpoint sa nenašiel. Možno ho zrušili.", 502: "Dátová služba neodpovedala. Skúste to o minútu.", other: "Dáta sa nepodarilo načítať (HTTP {status}). Skúste to o minútu." },
      timeout: "Dáta sa načítavali dlhšie ako 15 sekúnd. Zúžte hľadanie alebo to skúste znova.", noAddress: "Táto stránka ukazuje živé dáta Endpointu otvorených dát; adresa žiadny neuvádza.",
      noWidget: "Tabuľka sa nespustila. Načítajte stránku znova; ak to pretrváva, správcovia katalógu vidia príčinu v konzole prehliadača.",
      mapHint: "Kliknite na bod a otvorí sa jeho detail. Tabuľka uvádza tie isté entity.", mapCap: "Mapa ukazuje prvých {n} z {total} vo výreze; priblížte pre ďalšie.",
      mapNone: "Žiadna entita tohto dopytu nemá polohu.", links: "Tento dopyt inde", entityLink: "Táto entita v NGSI-LD", queryLink: "Tento dopyt v NGSI-LD",
      viewLink: "Toto zobrazenie (typ, filter a poradie)", yes: "áno", no: "nie",
      embed: "Vložiť na web", embedLead: "Dajte túto živú tabuľku na svoj web. Stále číta aktuálne dáta; nič sa nekopíruje.",
      embedKind: "Kód", iframe: "Rámec (odporúčané)", component: "Webový komponent", kindHint: "Rámec nepotrebuje skript a funguje vo WordPress bloku \u201eVlastné HTML\u201c; webový komponent sa prispôsobí výške obsahu.",
      viewLabel: "Zobrazí", viewBoth: "Tabuľku a mapu", viewTable: "Len tabuľku", viewHint: "Mapa sa zobrazí, len ak entity majú polohu.",
      langLabel: "Jazyk", langHint: "Popisy widgetu, napr. Slovenčina pre slovenský web.", themeLabel: "Farby", themeAuto: "Podľa návštevníka", themeLight: "Svetlé", themeDark: "Tmavé", themeHint: "Svetlé alebo tmavé, alebo podľa nastavenia zariadenia návštevníka.",
      heightLabel: "Výška v pixeloch", heightHint: "Od 240 do 2000, napr. 640.", keep: "Zachovať aktuálny filter a poradie", keepHint: "Návštevníci začnú s týmto zobrazením: {view}", keepNone: "Nie je nastavený filter ani poradie: návštevníci uvidia všetky entity.",
      filterIs: "filter {q}", orderIs: "zoradené podľa {col}", desc: " (zostupne)",
      code: "Kód na vloženie", copy: "Kopírovať kód", copied: "Skopírované. Vložte ho do HTML svojej stránky.", copySelect: "Označené: skopírujte stlačením Ctrl+C.", preview: "Otvoriť samotný widget",
      invalid: "Skontrolujte toto nastavenie: {why}.", source: "Zdroj", licence: "Licencia", licenceSee: "pozri dataset", catalogue: "katalóg otvorených dát"
    }
  };

  var ORDER = /^(id|[A-Za-z][A-Za-z0-9_]{0,127})(;(asc|desc))?$/;
  var MAX_Q = 2000;

  // `#{slug}`, then `&lang=sk`, `&type=T`, `&inline`, `&theme=dark|light`, `&q=…` (the NGSI-LD
  // query, URI-encoded), `&sort=attr;desc` and, as embed.js writes them (T-5129), `&dataset=name`
  // and `&view=table` in any order. The view checks the order against the type's columns again;
  // the Endpoint checks q.
  function parseHash(hash) {
    var parts = String(hash || "").replace(/^#/, "").split("&");
    if (!SLUG.test(parts[0])) return null;
    var out = { slug: parts[0], lang: null, type: null, inline: false, theme: null, q: null, sort: null, dataset: null, view: null };
    parts.slice(1).forEach(function (p) {
      var m = /^(lang|type|theme|q|sort|dataset|view)=(.+)$/.exec(p);
      var v = null;
      try { v = m && decodeURIComponent(m[2]); } catch (e) { v = null; }
      if (p === "inline") out.inline = true;
      else if (!m || v === null) return;
      else if (m[1] === "lang" && /^[a-z]{2}$/.test(v)) out.lang = v;
      else if (m[1] === "type" && NAME.test(v)) out.type = v;
      else if (m[1] === "theme" && /^(dark|light)$/.test(v)) out.theme = v;
      else if (m[1] === "q" && v.length <= MAX_Q) out.q = v;
      else if (m[1] === "sort" && ORDER.test(v)) out.sort = v;
      else if (m[1] === "dataset" && /^[a-z0-9_-]{2,100}$/.test(v)) out.dataset = v;
      else if (m[1] === "view" && v === "table") out.view = v;
    });
    return out;
  }

  // The hash for a view: what parseHash reads back.
  function hashOf(where) {
    var out = "#" + where.slug;
    if (where.inline) out += "&inline";
    ["dataset", "lang", "theme", "view", "type", "q", "sort"].forEach(function (k) {
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

  // The collection's tileset address under the Endpoint (T-5189, Antares antares-ogc tiles).
  function tilesetUrl(api, type) {
    return api + "ogc/features/collections/" + encodeURIComponent(type) + "/tiles/WebMercatorQuad";
  }

  // A tileset's MVT item template as MapLibre's {z}/{y}/{x}, or null when it is missing or leaves
  // the tileset's own path (another host, the broker's address, another collection, a query).
  function templateOf(tileset, at) {
    var item = ((tileset && tileset.links) || []).filter(function (l) { return l && l.rel === "item" && l.type === MVT && typeof l.href === "string"; })[0];
    if (!item) return null;
    var tail = "{z}/{y}/{x}";
    var href = item.href.replace("{tileMatrix}", "{z}").replace("{tileRow}", "{y}").replace("{tileCol}", "{x}");
    if (href.slice(-tail.length) !== tail || /[{}]/.test(href.slice(0, -tail.length))) return null;
    var url;
    try { url = new URL(href.slice(0, -tail.length), at); } catch (e) { return null; }
    var own = new URL(at);
    if (url.origin !== own.origin || url.pathname !== own.pathname + "/" || url.search || url.hash) return null;
    return url.href + tail;
  }

  // The same rows elsewhere: the entity, the query, OData, OGC API Features and CSV of its type.
  function links(api, type, q, order, id) {
    var out = [];
    if (id) out.push({ key: "entityLink", href: api + "ngsi-ld/v1/entities/" + encodeURIComponent(id) });
    out.push({ key: "queryLink", href: entitiesUrl(api, { type: type, q: q, orderBy: order }) });
    out.push({ key: "OData v4", href: api + "odata/v4/" + type });
    out.push({ key: "OGC API - Features", href: api + "ogc/features/collections/" + type + "/items" });
    out.push({ key: "CSV", href: api + "file.csv?" + params({ type: type, q: q, orderBy: order }) });
    out.push({ key: "OGC API - Tiles", href: tilesetUrl(api, type) });
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
    // /embed.html is this page on another site (T-5129): it names its source and licence, and
    // offers no Embed button of its own.
    var embedded = /\/embed\.html$/.test(location.pathname);
    $("embed-open").hidden = embedded || !where;
    var status = $("status");
    Array.prototype.forEach.call(document.querySelectorAll("[data-t]"), function (n) { n.textContent = t[n.getAttribute("data-t")]; });

    // The catalogue sizes the frame from this message. The content's own box, not the document's:
    // the view's stylesheet makes html as tall as the frame, which would hold the frame at its size.
    function height() {
      var h = Math.ceil(document.querySelector("main").getBoundingClientRect().bottom + window.scrollY);
      if (window.parent !== window) window.parent.postMessage({ type: "jc-viz-height", height: h }, "*");
    }
    if (typeof ResizeObserver === "function") new ResizeObserver(height).observe(document.querySelector("main"));
    // The slice of this frame the reader sees, from the page around it (T-5192): dialogs open there.
    window.addEventListener("message", function (event) {
      var d = event.data || {};
      if (event.source !== window.parent || window.parent === window || d.type !== "jc-viz-viewport") return;
      if (typeof d.top !== "number" || typeof d.height !== "number" || !isFinite(d.top) || !isFinite(d.height)) return;
      var top = Math.max(0, Math.min(d.top, document.documentElement.scrollHeight));
      var h = Math.max(120, Math.min(d.height, 4000));
      document.documentElement.style.setProperty("--jc-vv-top", Math.round(top) + "px");
      document.documentElement.style.setProperty("--jc-vv-height", Math.round(h) + "px");
    });

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
    var state = { types: [], type: where.type, q: where.q || "", sort: where.sort, map: null, mapData: null, mapAsk: 0, tiled: null, tilesets: {} };

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
      var geo = where.view !== "table" && !!info && (info.attributeNames || []).indexOf("location") >= 0;
      section.hidden = !geo;
      if (!geo) return;
      if (state.map) return mapMoved();
      // One map: a second call while MapLibre still loads waits for the first (T-5192 drew two).
      if (state.mapLoading) return;
      state.mapLoading = true;
      import(MAPLIBRE).then(function (maplibre) {
        maplibre.setWorkerUrl(WORKER);
        if (root.pmtiles) maplibre.addProtocol("pmtiles", new root.pmtiles.Protocol().tile);
        // The Endpoint's vector tiles, read like every other request here: anonymous, no referrer.
        maplibre.addProtocol("jc-tile", function (request, controller) {
          return fetch(request.url.replace(/^jc-tile:/, "https:"), { credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal, headers: { Accept: MVT } })
            .then(function (r) {
              if (r.status === 204) return { data: new ArrayBuffer(0) };
              if (!r.ok) throw new Error("HTTP " + r.status);
              return r.arrayBuffer().then(function (data) { return { data: data }; });
            });
        });
        var domain = location.hostname.replace(/^viz\./, "");
        var map = new maplibre.Map({ container: "map", style: "https://tiles." + domain + "/styles/light-" + (lang === "sk" ? "sk" : "en") + ".json", attributionControl: false, center: [17.1, 48.15], zoom: 4 });
        state.map = map;
        root.jcExploreMap = map; // for the browser journey
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
          TILE_LAYERS.forEach(function (layer) {
            map.on("click", layer, function (e) {
              var id = e.features[0].properties.id;
              if (typeof id !== "string") return;
              get(api + "ngsi-ld/v1/entities/" + encodeURIComponent(id) + "?" + params({ format: "keyValues", lang: lang })).then(function (answer) {
                if (answer.body && answer.body.id === id) detail(answer.body, map.getCanvas());
              }, function (err) { $("map-note").textContent = failure(err); });
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

    // Past MAP_LIMIT and with no filter (a tile takes no query), the map draws the type's vector
    // tiles: the Endpoint cuts every view to its tiles, so 100 000 entities pan like 100.
    var TILE_LAYERS = ["jc-tile-fill", "jc-tile-line", "jc-tile-point"];
    function untile() {
      var map = state.map;
      TILE_LAYERS.forEach(function (l) { if (map.getLayer(l)) map.removeLayer(l); });
      if (map.getSource("jc-tiles")) map.removeSource("jc-tiles");
      state.tiled = null;
    }
    function tile(type) {
      var at = tilesetUrl(api, type);
      var known = state.tilesets[type] || (state.tilesets[type] = get(at).then(function (a) { return templateOf(a.body, at); }, function () { return null; }));
      return known.then(function (template) {
        var map = state.map;
        if (!template || state.type !== type || state.q || state.tiled === type) return !!template && state.tiled === type;
        untile();
        var is = function (types) { return ["in", ["geometry-type"], ["literal", types]]; };
        map.addSource("jc-tiles", { type: "vector", tiles: [template.replace(/^https:/, "jc-tile:")], minzoom: 0, maxzoom: 16 });
        var of = function (layer) { return Object.assign(layer, { source: "jc-tiles", "source-layer": type }); };
        map.addLayer(of({ id: "jc-tile-fill", type: "fill", filter: is(["Polygon", "MultiPolygon"]), paint: { "fill-color": COLOUR, "fill-opacity": 0.25 } }));
        map.addLayer(of({ id: "jc-tile-line", type: "line", filter: ["!", is(["Point", "MultiPoint"])], paint: { "line-color": COLOUR, "line-width": 2 } }));
        map.addLayer(of({ id: "jc-tile-point", type: "circle", filter: is(["Point", "MultiPoint"]), paint: { "circle-color": COLOUR, "circle-radius": 5, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } }));
        map.getSource("jc").setData({ type: "FeatureCollection", features: [] });
        state.mapData = [];
        state.tiled = type;
        return true;
      });
    }

    function mapMoved() {
      var map = state.map;
      if (!map || !map.getSource("jc")) return;
      if (state.tiled && (state.tiled !== state.type || state.q)) untile();
      if (state.tiled) return;
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
        if (total > features.length && !state.q) {
          tile(state.type).then(function (on) { if (on && asked === state.mapAsk) $("map-note").textContent = t.mapHint; });
        }
      }, function (e) { if (asked === state.mapAsk) $("map-note").textContent = failure(e); });
    }
    state.mapAsk = 0;

    // The view says which type, query and order it shows: the address, the map and the API links follow.
    function onLink(next) {
      var moved = next.type !== state.type || (next.q || "") !== state.q;
      state.type = next.type || null;
      state.q = next.q || "";
      state.sort = next.sort || null;
      history.replaceState(null, "", hashOf({ slug: where.slug, inline: where.inline, lang: where.lang, theme: where.theme, dataset: where.dataset, view: where.view, type: state.type, q: state.q, sort: state.sort }));
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
    // The source line of an embed: the dataset's title, publisher and licence from the catalogue,
    // shown only when that dataset names this very Endpoint; else the catalogue itself.
    function attribute() {
      var catalogue = "https://opendata." + location.hostname.replace(/^viz\./, "");
      var line = $("attribution");
      var draw = function (title, href, publisher, licence, licenceHref) {
        line.textContent = "";
        line.appendChild(document.createTextNode(t.source + ": "));
        line.appendChild(el("a", { href: href, target: "_blank", rel: "noopener noreferrer", text: title }));
        if (publisher) line.appendChild(document.createTextNode(" · " + publisher));
        line.appendChild(document.createTextNode(" · " + t.licence + ": "));
        line.appendChild(licenceHref ? el("a", { href: licenceHref, target: "_blank", rel: "noopener noreferrer", text: licence }) : document.createTextNode(licence));
        line.hidden = false;
        height();
      };
      draw(catalogue.replace("https://", "") + " – " + t.catalogue, catalogue + "/", null, t.licenceSee, null);
      if (!where.dataset) return;
      get(catalogue + "/api/3/action/package_show?id=" + encodeURIComponent(where.dataset)).then(function (answer) {
        var pkg = answer.body && answer.body.success && answer.body.result;
        var extra = ((pkg && pkg.extras) || []).filter(function (x) { return x && x.key === "endpoint"; })[0];
        if (!pkg || !extra || String(extra.value).replace(/\/?$/, "/") !== api) return;
        var href = catalogue + "/dataset/" + where.dataset;
        var licenceHref = /^https?:\/\//.test(pkg.license_url || "") ? pkg.license_url : null;
        draw(String(pkg.title || where.dataset), href, pkg.organization && pkg.organization.title ? String(pkg.organization.title) : null,
          pkg.license_title ? String(pkg.license_title) : t.licenceSee, licenceHref || (pkg.license_title ? null : href));
      }, function () {});
    }

    // The Embed dialog (T-5129): the code for this Endpoint, type and, if kept, the view's filter and order.
    function embedCode() {
      var E = root.jcEmbed;
      var keep = $("embed-keep").checked;
      var o = { slug: where.slug, dataset: where.dataset, type: state.type, lang: $("embed-lang").value, view: $("embed-view").value,
        theme: $("embed-theme").value || null, height: $("embed-height").value, q: keep ? state.q : "", sort: keep ? state.sort : null };
      var words = [];
      if (state.q) words.push(say(t.filterIs, { q: state.q }));
      if (state.sort) words.push(say(t.orderIs, { col: state.sort.split(";")[0] }) + (/;desc$/.test(state.sort) ? t.desc : ""));
      $("embed-keep-hint").textContent = words.length ? say(t.keepHint, { view: words.join("; ") }) : t.keepNone;
      $("embed-copied").textContent = "";
      try {
        $("embed-code").value = E.snippet($("embed-form").querySelector("input[name=kind]:checked").value, o, location.origin, t.title + (state.type ? ": " + state.type : ""));
        $("embed-preview").href = location.origin + "/embed.html" + E.hash(o);
        $("embed-error").hidden = true;
        $("embed-height").removeAttribute("aria-invalid");
        $("embed-copy").disabled = false;
      } catch (e) {
        $("embed-error").textContent = say(t.invalid, { why: e.message });
        $("embed-error").hidden = false;
        if (/^height/.test(e.message)) $("embed-height").setAttribute("aria-invalid", "true");
        $("embed-code").value = "";
        $("embed-copy").disabled = true;
      }
    }

    $("embed-open").addEventListener("click", function () {
      $("embed-lang").value = lang;
      embedCode();
      $("embed").showModal();
    });
    $("embed-form").addEventListener("input", embedCode);
    $("embed-form").addEventListener("change", embedCode);
    $("embed-form").addEventListener("submit", function (e) { e.preventDefault(); });
    $("embed-copy").addEventListener("click", function () {
      var code = $("embed-code");
      var said = function (text) { $("embed-copied").textContent = text; };
      var select = function () { code.focus(); code.select(); said(t.copySelect); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(code.value).then(function () { said(t.copied); }, select);
      else select();
    });
    $("embed-close").addEventListener("click", function () { $("embed").close(); });
    $("embed").addEventListener("close", function () { $("embed-open").focus(); });
    if (embedded) attribute();
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

  root.jcExplore = { parseHash: parseHash, hashOf: hashOf, base: base, entitiesUrl: entitiesUrl, bboxQuery: bboxQuery, links: links, templateOf: templateOf, tilesetUrl: tilesetUrl, show: show, TEXT: TEXT };
  if (typeof module === "object" && module.exports) module.exports = root.jcExplore;
  else if (typeof document !== "undefined") main();
})(typeof self !== "undefined" ? self : this);
