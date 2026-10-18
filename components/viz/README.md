# viz

The chart renderer of [ADR-N-053](https://github.com/marek-mraz/joinedcontext-docs/blob/main/Decisions/adr-n-053-declarative-visualizations.md)
on `https://viz.{domain}/` (T-4641). An Endpoint lists Vega-Lite 5 or Vega 5 specs in
`spec.catalog.visualizations`; the reconciler publishes each as a CKAN resource view of type
`jc_visualization` (T-4642); the catalogue frames this host to draw it.

Two documents, two origins of trust:

- **The host page** (`/#{viewId}`, `files/site/index.html` and `host.js`). Our code, no spec
  runs here. It reads the view anonymously from CKAN's action API (`resource_view_show` on
  `data.{domain}`, which answers CORS for this origin alone), checks the spec against the
  refusal list (`refuse.js`), fetches the declared source of that Endpoint on `api.{domain}`
  without a token (`csv`, `ogc`, `odata` or `temporal`), stops at 15 seconds, 50,000 rows or
  20 MB, and posts spec and rows to the renderer. `&inline` hides its title, description and
  link (the dataset page shows them); `&lang=sk` names the language. Any site may frame it: it
  holds no secret, and the "Embed on a website" snippet is exactly that frame.
- **The renderer** (`/render.html`, `render.js`). Framed by the host page with
  `sandbox="allow-scripts allow-downloads"`, so it runs in an opaque origin and reads no cookie
  of any host. Its CSP allows no connection (`connect-src 'none'`) and no `eval`; it checks the
  spec again and draws it with `vega-embed`, `ast: true` and `vega-interpreter`, with a loader
  that refuses every load, and offers PNG and SVG export only.

The Vega builds are the npm releases byte for byte (`charts/renderer/files/vendor/SHA256SUMS`),
one ConfigMap each, served from this host: no CDN.

Tests: `tests/test_viz.py` (render, headers, checksums, and `node --test` on
`components/viz/tests/*.test.mjs`); the browser journey `components/viz/tests/journey.spec.mjs`
runs the good specs and the hostile ones with the hosts routed to these files.
