// The live explorer on viz.{domain} (T-5059): the catalogue's view of one public Endpoint. It reads
// the Endpoint's NGSI-LD API anonymously (no token, no cookie) and copies nothing: a table with
// paging, search and filters, a detail drawer and a map of the same query. A filter becomes NGSI-LD
// `q` only from attribute names the Endpoint itself lists and values escaped here (buildQ).
(function (root) {
  "use strict";

  var MAPLIBRE = "/vendor/maplibre-gl-6.14.0.mjs";
  var WORKER = "/vendor/maplibre-gl-worker-6.14.0.mjs";
  var SLUG = /^[a-z0-9]{16,64}$/;
  var NAME = /^[A-Za-z][A-Za-z0-9_]{0,127}$/;
  var DATE = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;
  var TIMEOUT_MS = 15000;
  var SIZES = [20, 50, 100];
  var MAP_LIMIT = 1000;
  var COLOUR = "#1f5fae";
  // Per kind of value, the operators a filter offers; `contains` is a case-blind regex match.
  var OPS = {
    number: ["==", "!=", ">", ">=", "<", "<="],
    date: [">=", "<=", "=="],
    boolean: ["=="],
    text: ["contains", "==", "!="],
    lang: ["contains", "=="]
  };
  var TEXT = {
    en: {
      title: "Live data", entity: "Entity", type: "Entity type", search: "Search", searchHint: "Searches every text attribute, e.g. Kaivopuisto.",
      filters: "Filters", addFilter: "Add filter", attribute: "Attribute", operator: "Condition", value: "Value",
      valueHint: { number: "A number, e.g. 25 or 3.5", date: "A date, e.g. 2026-10-01 or 2026-10-01T08:00:00Z", boolean: "true or false", text: "Any text, e.g. working", lang: "Any text, e.g. Kaivopuisto" },
      contains: "contains", remove: "Remove filter", apply: "Show", reset: "Clear all", columns: "Columns", columnsHint: "Choose which attributes the table shows.",
      table: "Entities", map: "Map", detail: "Details", close: "Close", open: "Open details of", prev: "Previous page", next: "Next page",
      perPage: "Show entries", showing: "Showing {from} to {to} of {total} entries", showingOpen: "Showing {from} to {to} entries", dataApi: "Data API", of: "of", loading: "Loading live data…", none: "No entity matches. Clear a filter or search for something shorter.",
      empty: "This Endpoint holds no entities of this type yet.", noTypes: "This Endpoint publishes no entity types yet.",
      failed: { 403: "This Endpoint is not public: the catalogue shows only what anyone may read.", 404: "The Endpoint was not found. It may have been unpublished.", 502: "The data service did not answer. Try again in a minute.", other: "The data could not be loaded (HTTP {status}). Try again in a minute." },
      timeout: "The data took longer than 15 seconds. Narrow the search or try again.", noAddress: "This page shows the live data of an open-data Endpoint; the address names none.",
      invalid: "Check the highlighted filter: {why}", sorted: "Sorted within this page.", sortBy: "Sort by",
      mapHint: "Click a point to open its details. The table lists the same entities.", mapCap: "The map shows the first {n} of {total} in view; zoom in for the rest.",
      mapNone: "No entity of this page has a location.", links: "This query elsewhere", entityLink: "This entity in NGSI-LD", queryLink: "This query in NGSI-LD",
      yes: "yes", no: "no", retry: "Try again", pages: "Pages"
    },
    sk: {
      title: "Živé dáta", entity: "Entita", type: "Typ entity", search: "Hľadať", searchHint: "Hľadá vo všetkých textových atribútoch, napr. Kaivopuisto.",
      filters: "Filtre", addFilter: "Pridať filter", attribute: "Atribút", operator: "Podmienka", value: "Hodnota",
      valueHint: { number: "Číslo, napr. 25 alebo 3.5", date: "Dátum, napr. 2026-10-01 alebo 2026-10-01T08:00:00Z", boolean: "true alebo false", text: "Ľubovoľný text, napr. working", lang: "Ľubovoľný text, napr. Kaivopuisto" },
      contains: "obsahuje", remove: "Odstrániť filter", apply: "Zobraziť", reset: "Zrušiť všetko", columns: "Stĺpce", columnsHint: "Vyberte, ktoré atribúty tabuľka zobrazí.",
      table: "Entity", map: "Mapa", detail: "Detail", close: "Zavrieť", open: "Otvoriť detail", prev: "Predchádzajúca strana", next: "Ďalšia strana",
      perPage: "Zobraziť záznamov", showing: "Zobrazené {from} až {to} z {total} záznamov", showingOpen: "Zobrazené {from} až {to} záznamov", dataApi: "Dátové API", of: "z", loading: "Načítavam živé dáta…", none: "Žiadna entita nevyhovuje. Zrušte filter alebo hľadajte kratší text.",
      empty: "Tento Endpoint zatiaľ nemá entity tohto typu.", noTypes: "Tento Endpoint zatiaľ nezverejňuje žiadne typy entít.",
      failed: { 403: "Tento Endpoint nie je verejný: katalóg ukazuje len to, čo môže čítať ktokoľvek.", 404: "Endpoint sa nenašiel. Možno ho zrušili.", 502: "Dátová služba neodpovedala. Skúste to o minútu.", other: "Dáta sa nepodarilo načítať (HTTP {status}). Skúste to o minútu." },
      timeout: "Dáta sa načítavali dlhšie ako 15 sekúnd. Zúžte hľadanie alebo to skúste znova.", noAddress: "Táto stránka ukazuje živé dáta Endpointu otvorených dát; adresa žiadny neuvádza.",
      invalid: "Skontrolujte vyznačený filter: {why}", sorted: "Zoradené v rámci tejto strany.", sortBy: "Zoradiť podľa",
      mapHint: "Kliknite na bod a otvorí sa jeho detail. Tabuľka uvádza tie isté entity.", mapCap: "Mapa ukazuje prvých {n} z {total} vo výreze; priblížte pre ďalšie.",
      mapNone: "Žiadna entita tejto strany nemá polohu.", links: "Tento dopyt inde", entityLink: "Táto entita v NGSI-LD", queryLink: "Tento dopyt v NGSI-LD",
      yes: "áno", no: "nie", retry: "Skúsiť znova", pages: "Strany"
    }
  };

  // `#{slug}`, then `&lang=sk`, `&type=T`, `&inline` and `&theme=dark|light` in any order.
  function parseHash(hash) {
    var parts = String(hash || "").replace(/^#/, "").split("&");
    if (!SLUG.test(parts[0])) return null;
    var out = { slug: parts[0], lang: null, type: null, inline: false, theme: null };
    parts.slice(1).forEach(function (p) {
      var m = /^(lang|type|theme)=(.+)$/.exec(p);
      if (p === "inline") out.inline = true;
      else if (m && m[1] === "lang" && /^[a-z]{2}$/.test(m[2])) out.lang = m[2];
      else if (m && m[1] === "type" && NAME.test(m[2])) out.type = m[2];
      else if (m && m[1] === "theme" && /^(dark|light)$/.test(m[2])) out.theme = m[2];
    });
    return out;
  }

  // viz.{domain} → the Endpoint's base on api.{domain}: named by this page's host, never by a parameter.
  function base(hostname, slug) {
    return "https://api." + String(hostname).replace(/^viz\./, "") + "/api/endpoint/" + slug + "/";
  }

  // The kind of each attribute, read from a normalized sample: what a filter on it may compare.
  // Geometry, relationships and structured values get no filter (null).
  function kinds(sample, names) {
    var out = {};
    names.forEach(function (name) { out[name] = null; });
    (Array.isArray(sample) ? sample : []).forEach(function (entity) {
      names.forEach(function (name) {
        if (out[name]) return;
        var a = entity && entity[name];
        a = Array.isArray(a) ? a[0] : a;
        if (!a || typeof a !== "object") return;
        if (a.type === "LanguageProperty") out[name] = "lang";
        else if (a.type !== "Property") return;
        else if (typeof a.value === "number") out[name] = "number";
        else if (typeof a.value === "boolean") out[name] = "boolean";
        else if (typeof a.value === "string") out[name] = DATE.test(a.value) ? "date" : "text";
        else if (a.value && a.value["@type"] === "DateTime") out[name] = "date";
      });
    });
    return out;
  }

  function quote(value) {
    return '"' + String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  }

  function regex(value) {
    return "(?i).*" + String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ".*";
  }

  // One comparison, or an Error naming what is wrong with it. `allowed` is the Endpoint's own list
  // of attribute names and `kind` their kinds: anything else never reaches the query string.
  function term(filter, allowed, kind) {
    var attr = filter && filter.attr;
    if (!NAME.test(attr || "") || allowed.indexOf(attr) < 0 || !kind[attr]) throw new Error("the Endpoint offers no attribute " + JSON.stringify(String(attr)));
    var k = kind[attr];
    if (OPS[k].indexOf(filter.op) < 0) throw new Error("no condition " + JSON.stringify(String(filter.op)) + " for " + attr);
    var v = String(filter.value === undefined || filter.value === null ? "" : filter.value).trim();
    if (!v) throw new Error(attr + " needs a value");
    if (v.length > 200) throw new Error(attr + ": at most 200 characters");
    var path = k === "lang" ? attr + "[*]" : attr;
    if (k === "number") {
      if (!/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(v) || !isFinite(+v)) throw new Error(attr + " needs a number");
      return path + filter.op + String(+v);
    }
    if (k === "boolean") {
      if (v !== "true" && v !== "false") throw new Error(attr + " is true or false");
      return path + "==" + v;
    }
    if (k === "date") {
      if (!DATE.test(v) || isNaN(Date.parse(v))) throw new Error(attr + " needs a date such as 2026-10-01");
      return path + filter.op + (v.length === 10 ? v + "T00:00:00Z" : v);
    }
    return filter.op === "contains" ? path + "~=" + quote(regex(v)) : path + filter.op + quote(v);
  }

  // NGSI-LD `q` of the search box (any text attribute contains it) and the filters, all ANDed.
  function buildQ(filters, search, allowed, kind) {
    var terms = (filters || []).map(function (f) { return term(f, allowed, kind); });
    var words = String(search || "").trim();
    if (words) {
      if (words.length > 200) throw new Error("search: at most 200 characters");
      var texts = allowed.filter(function (a) { return kind[a] === "text" || kind[a] === "lang"; });
      var any = texts.map(function (a) { return term({ attr: a, op: "contains", value: words }, allowed, kind); });
      if (any.length) terms.push(any.length > 1 ? "(" + any.join("|") + ")" : any[0]);
    }
    return terms.join(";");
  }

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
  function links(api, type, q, id) {
    var out = [];
    if (id) out.push({ key: "entityLink", href: api + "ngsi-ld/v1/entities/" + encodeURIComponent(id) });
    out.push({ key: "queryLink", href: entitiesUrl(api, { type: type, q: q }) });
    out.push({ key: "OData v4", href: api + "odata/v4/" + type });
    out.push({ key: "OGC API - Features", href: api + "ogc/features/collections/" + type + "/items" });
    out.push({ key: "CSV", href: api + "file.csv?" + params({ type: type }) });
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

  function sortRows(rows, attr, dir) {
    var sign = dir === "descending" ? -1 : 1;
    return rows.slice().sort(function (a, b) {
      var x = a[attr], y = b[attr];
      if (x === undefined || x === null) return 1;
      if (y === undefined || y === null) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * sign;
      return String(show(x, { yes: "", no: "" }).text).localeCompare(String(show(y, { yes: "", no: "" }).text)) * sign;
    });
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
    $("search").setAttribute("aria-describedby", "search-hint");
    document.querySelector("nav.pager").setAttribute("aria-label", t.pages);
    if (!where) {
      status.textContent = t.noAddress;
      status.className = "status error";
      $("app").hidden = true;
      return height();
    }
    var api = base(location.hostname, where.slug);
    var state = { types: [], type: null, allowed: [], kind: {}, columns: [], filters: [], search: "", q: "", offset: 0, limit: SIZES[0], total: null, rows: [], sort: null, map: null, mapData: null };

    function height() {
      var h = Math.ceil(document.documentElement.getBoundingClientRect().height);
      if (window.parent !== window) window.parent.postMessage({ type: "jc-viz-height", height: h }, "*");
    }

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

    function tell(text, kind) {
      status.textContent = text || "";
      status.className = "status" + (kind ? " " + kind : "");
      var retry = $("retry");
      retry.hidden = kind !== "error";
      height();
    }

    function stop(error) {
      $("results").hidden = true;
      $("controls").hidden = !state.type; // nothing to search before the Endpoint has answered
      tell(failure(error), "error");
    }

    // The Endpoint's types and their attributes: the only names a filter or column may use.
    function start() {
      tell(t.loading, "busy");
      return get(api + "ngsi-ld/v1/types?details=true").then(function (answer) {
        var list = (Array.isArray(answer.body) ? answer.body : []).filter(function (x) { return x && NAME.test(x.typeName || ""); });
        state.types = list;
        if (!list.length) {
          $("results").hidden = true;
          $("controls").hidden = true;
          return tell(t.noTypes, "empty");
        }
        $("controls").hidden = false;
        var picked = list.filter(function (x) { return x.typeName === where.type; })[0] || list[0];
        var select = $("type");
        select.textContent = "";
        list.forEach(function (x) { select.appendChild(el("option", { value: x.typeName, text: x.typeName, selected: x === picked })); });
        $("type-field").hidden = list.length < 2;
        return pickType(picked.typeName);
      }, stop);
    }

    function pickType(name) {
      var info = state.types.filter(function (x) { return x.typeName === name; })[0];
      state.type = name;
      state.allowed = (info.attributeNames || []).filter(function (a) { return NAME.test(a); });
      state.filters = [];
      state.search = "";
      $("search").value = "";
      state.offset = 0;
      state.sort = null;
      return get(entitiesUrl(api, { type: name, limit: 20 })).then(function (answer) {
        state.kind = kinds(answer.body, state.allowed);
        // The first column already names each entity, so `name` and `location` start hidden.
        state.columns = state.allowed.filter(function (a) { return a !== "location" && a !== "name"; }).slice(0, 6);
        drawColumns();
        drawFilters();
        return load();
      }, stop);
    }

    function load() {
      var q;
      try {
        q = buildQ(state.filters, state.search, state.allowed, state.kind);
      } catch (e) {
        return tell(say(t.invalid, { why: e.message }), "error");
      }
      state.q = q;
      tell(t.loading, "busy");
      var url = entitiesUrl(api, { type: state.type, q: q, limit: state.limit, offset: state.offset, count: "true", format: "keyValues", lang: lang });
      return get(url).then(function (answer) {
        state.rows = Array.isArray(answer.body) ? answer.body : [];
        state.total = answer.count === null ? null : +answer.count;
        $("results").hidden = false;
        drawTable();
        drawMap();
        if (!state.rows.length) tell(q ? t.none : t.empty, "empty");
        else tell(range() + (state.sort ? " " + t.sorted : ""));
      }, stop);
    }

    function range() {
      var from = state.rows.length ? state.offset + 1 : 0;
      var to = state.offset + state.rows.length;
      var n = new Intl.NumberFormat(t.locale);
      // CKAN's DataStore preview words, so the catalogue reads as it always did.
      return say(state.total === null ? t.showingOpen : t.showing, { from: n.format(from), to: n.format(to), total: state.total === null ? "" : n.format(state.total) });
    }

    function drawColumns() {
      var box = $("columns-list");
      box.textContent = "";
      state.allowed.forEach(function (a) {
        var id = "col-" + a;
        var input = el("input", { type: "checkbox", id: id, value: a, checked: state.columns.indexOf(a) >= 0 });
        input.addEventListener("change", function () {
          state.columns = state.allowed.filter(function (x) { return x === a ? input.checked : state.columns.indexOf(x) >= 0; });
          drawTable();
        });
        box.appendChild(el("label", { for: id, class: "check" }, [input, document.createTextNode(" " + a)]));
      });
    }

    function drawFilters() {
      var list = $("filter-list");
      list.textContent = "";
      var filterable = state.allowed.filter(function (a) { return state.kind[a]; });
      $("add-filter").disabled = !filterable.length;
      state.filters.forEach(function (f, i) {
        var row = el("div", { class: "filter", role: "group", "aria-label": t.filters + " " + (i + 1) });
        var attr = el("select", { id: "f-attr-" + i, "aria-label": t.attribute });
        filterable.forEach(function (a) { attr.appendChild(el("option", { value: a, text: a, selected: a === f.attr })); });
        var op = el("select", { id: "f-op-" + i, "aria-label": t.operator });
        OPS[state.kind[f.attr]].forEach(function (o) { op.appendChild(el("option", { value: o, text: o === "contains" ? t.contains : o, selected: o === f.op })); });
        var hintId = "f-hint-" + i;
        var value = el("input", { id: "f-value-" + i, "aria-label": t.value, value: f.value, "aria-describedby": hintId, maxlength: "200", inputmode: state.kind[f.attr] === "number" ? "decimal" : null, "aria-invalid": f.invalid ? "true" : null });
        var remove = el("button", { type: "button", class: "icon", "aria-label": t.remove + " " + f.attr, text: "×" });
        attr.addEventListener("change", function () { f.attr = attr.value; f.op = OPS[state.kind[f.attr]][0]; drawFilters(); });
        op.addEventListener("change", function () { f.op = op.value; });
        value.addEventListener("input", function () { f.value = value.value; });
        remove.addEventListener("click", function () { state.filters.splice(i, 1); drawFilters(); $("add-filter").focus(); });
        row.appendChild(attr);
        row.appendChild(op);
        row.appendChild(value);
        row.appendChild(remove);
        row.appendChild(el("p", { id: hintId, class: "hint", text: t.valueHint[state.kind[f.attr]] }));
        list.appendChild(row);
      });
      height();
    }

    function drawTable() {
      var table = $("table");
      table.textContent = "";
      table.appendChild(el("caption", { class: "sr-only", text: t.table + ": " + state.type + ", " + range() }));
      var head = el("tr");
      head.appendChild(el("th", { scope: "col", text: t.entity }));
      state.columns.forEach(function (c) {
        var dir = state.sort && state.sort.attr === c ? state.sort.dir : null;
        var button = el("button", { type: "button", class: "sort", text: c, "aria-label": t.sortBy + " " + c });
        button.addEventListener("click", function () {
          state.sort = { attr: c, dir: dir === "ascending" ? "descending" : "ascending" };
          drawTable();
          tell(range() + " " + t.sorted);
          table.querySelector('th[data-attr="' + c + '"] button').focus();
        });
        head.appendChild(el("th", { scope: "col", "data-attr": c, "aria-sort": dir || "none" }, [button]));
      });
      table.appendChild(el("thead", {}, [head]));
      var body = el("tbody");
      var rows = state.sort ? sortRows(state.rows, state.sort.attr, state.sort.dir) : state.rows;
      rows.forEach(function (row) {
        var tr = el("tr");
        var label = row.name !== undefined ? show(row.name, t).text : String(row.id).split(":").pop();
        var open = el("button", { type: "button", class: "link", "aria-label": t.open + " " + label, text: label });
        open.addEventListener("click", function () { detail(row, open); });
        open.classList.add("clamp");
        tr.appendChild(el("th", { scope: "row" }, [open]));
        state.columns.forEach(function (c) { tr.appendChild(el("td", {}, [el("span", { class: "clamp" }, [valueNode(row[c], t)])])); });
        body.appendChild(tr);
      });
      table.appendChild(body);
      $("prev").disabled = state.offset === 0;
      $("next").disabled = state.total === null ? state.rows.length < state.limit : state.offset + state.rows.length >= state.total;
      $("range").textContent = range();
      height();
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
      var out = $("detail-links");
      out.textContent = "";
      links(api, state.type, state.q, row.id).forEach(function (l) {
        out.appendChild(el("li", {}, [el("a", { href: l.href, target: "_blank", rel: "noopener noreferrer", text: t[l.key] || l.key })]));
      });
      dialog.returnFocus = from;
      dialog.showModal();
    }

    // The map: geo+json of the same query within the view, at most MAP_LIMIT features a view.
    function drawMap() {
      var section = $("map-section");
      var geo = state.allowed.filter(function (a) { return a === "location"; }).length > 0;
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

    // The first view: the bounds of the table's page, so the map opens where the data is.
    function fitFirst() {
      var url = entitiesUrl(api, { type: state.type, q: state.q, limit: state.limit, offset: state.offset, lang: lang, format: "keyValues" });
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

    $("type").addEventListener("change", function () { pickType($("type").value); });
    $("add-filter").addEventListener("click", function () {
      var a = state.allowed.filter(function (x) { return state.kind[x]; })[0];
      state.filters.push({ attr: a, op: OPS[state.kind[a]][0], value: "" });
      drawFilters();
      $("f-value-" + (state.filters.length - 1)).focus();
    });
    $("controls").addEventListener("submit", function (e) {
      e.preventDefault();
      state.search = $("search").value;
      state.offset = 0;
      load();
    });
    $("reset").addEventListener("click", function () {
      state.filters = [];
      state.search = "";
      $("search").value = "";
      state.offset = 0;
      drawFilters();
      load();
    });
    $("prev").addEventListener("click", function () { state.offset = Math.max(0, state.offset - state.limit); load(); });
    $("next").addEventListener("click", function () { state.offset += state.limit; load(); });
    var size = $("size");
    SIZES.forEach(function (n) { size.appendChild(el("option", { value: String(n), text: String(n) })); });
    size.addEventListener("change", function () { state.limit = +size.value; state.offset = 0; load(); });
    $("retry").addEventListener("click", function () { (state.type ? load : start)(); });
    // Data API: where CKAN listed datastore_search, the same query's addresses on the Endpoint.
    $("data-api").addEventListener("click", function () {
      $("detail-title").textContent = t.dataApi;
      $("detail-list").textContent = "";
      $("detail-list").appendChild(el("dt", { text: "q" }));
      $("detail-list").appendChild(el("dd", { text: state.q || "–" }));
      var out = $("detail-links");
      out.textContent = "";
      links(api, state.type, state.q).forEach(function (l) {
        out.appendChild(el("li", {}, [el("a", { href: l.href, target: "_blank", rel: "noopener noreferrer", text: t[l.key] || l.key })]));
      });
      $("detail").returnFocus = $("data-api");
      $("detail").showModal();
    });
    $("detail-close").addEventListener("click", function () { $("detail").close(); });
    $("detail").addEventListener("close", function () { var f = $("detail").returnFocus; if (f && f.focus) f.focus(); });
    window.addEventListener("resize", height);
    start();
  }

  root.jcExplore = { parseHash: parseHash, base: base, kinds: kinds, buildQ: buildQ, entitiesUrl: entitiesUrl, bboxQuery: bboxQuery, links: links, show: show, sortRows: sortRows, OPS: OPS, TEXT: TEXT };
  if (typeof module === "object" && module.exports) module.exports = root.jcExplore;
  else if (typeof document !== "undefined") main();
})(typeof self !== "undefined" ? self : this);
