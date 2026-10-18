// The refusal list of ADR-N-053 §2.3 (EP-130), checked again in the browser: the host page checks a
// spec before it fetches a row, the sandboxed renderer before it draws. The publisher's check is
// not trusted alone. One function, no dependency, so node:test runs the same file (refuse.test.mjs).
(function (root) {
  "use strict";

  var MAX_BYTES = 200 * 1024;
  var SCHEMA = /^https:\/\/vega\.github\.io\/schema\/(vega-lite|vega)\/v5(\.\d+){0,2}\.json$/;
  // An image the spec names inline. SVG is left out: an SVG document can carry script.
  var DATA_IMAGE = /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/;
  // Words an expression has no business with. The interpreter refuses them too; this keeps a
  // spec that tries them from reaching it at all.
  var WORDS = /\b(__proto__|constructor|prototype)\b/;

  function onOurHosts(url, domain) {
    if (typeof url !== "string") return false;
    if (DATA_IMAGE.test(url)) return true;
    var parsed;
    try {
      parsed = new URL(url);
    } catch (e) {
      return false;
    }
    var host = parsed.hostname;
    return parsed.protocol === "https:" && parsed.username === "" && parsed.password === "" &&
      (host === domain || host.slice(-(domain.length + 1)) === "." + domain);
  }

  // A member that can name a URL (`href`, `url`): a literal string on our hosts, or a channel
  // whose one constant `value` is. A field, a signal or an expression could name any host.
  function literalUrl(value, domain) {
    if (typeof value === "string") return onOurHosts(value, domain);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      var keys = Object.keys(value);
      return keys.length === 1 && keys[0] === "value" && onOurHosts(value.value, domain);
    }
    return false;
  }

  // A `data` member says where rows come from: only the named source the renderer fills, inline
  // values, or (Vega) a data set derived from another by name. Never a URL.
  function dataAllowed(data) {
    var list = Array.isArray(data) ? data : [data];
    return list.every(function (entry) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
      if ("url" in entry) return false;
      if (Array.isArray(data)) return typeof entry.name === "string"; // Vega: named entries
      return entry.name === "source" || "values" in entry || "sequence" in entry || "graticule" in entry || "sphere" in entry;
    });
  }

  function refuse(spec, domain) {
    var errors = [];
    function no(pointer, rule) {
      errors.push({ pointer: pointer || "/", rule: rule });
    }
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      no("", "a spec is a JSON object");
      return errors;
    }
    var text;
    try {
      text = JSON.stringify(spec);
    } catch (e) {
      no("", "a spec is plain JSON");
      return errors;
    }
    if (new TextEncoder().encode(text).length > MAX_BYTES) no("", "at most 200 KB");
    if (!SCHEMA.test(spec.$schema || "")) no("/$schema", "the Vega-Lite 5 or Vega 5 schema");

    function walk(node, pointer) {
      if (Array.isArray(node)) {
        node.forEach(function (item, index) {
          walk(item, pointer + "/" + index);
        });
        return;
      }
      if (typeof node === "string") {
        if (WORDS.test(node)) no(pointer, "no __proto__, constructor or prototype");
        if (/^\s*javascript:/i.test(node)) no(pointer, "no javascript: URL");
        return;
      }
      if (!node || typeof node !== "object") return;
      Object.keys(node).forEach(function (key) {
        var at = pointer + "/" + key.replace(/~/g, "~0").replace(/\//g, "~1");
        var value = node[key];
        if (WORDS.test(key)) {
          no(at, "no __proto__, constructor or prototype");
          return;
        }
        if (key === "usermeta") return no(at, "no usermeta");
        if (key === "loader") return no(at, "no loader options");
        if (key === "data" && !dataAllowed(value)) return no(at, "data only from the named source or inline values");
        if ((key === "url" || key === "href") && !literalUrl(value, domain)) {
          return no(at, "a " + key + " only as a literal on our hosts");
        }
        walk(value, at);
      });
    }
    walk(spec, "");
    return errors;
  }

  root.jcRefuse = refuse;
  if (typeof module === "object" && module.exports) module.exports = refuse;
})(typeof self !== "undefined" ? self : this);
