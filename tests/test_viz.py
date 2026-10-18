"""T-4641, ADR-N-053: the chart renderer on viz.{domain}. The rendered dev environment carries
the server, its files and the pinned Vega builds, the route and its certificate name; each page
carries the headers that keep a spec harmless; the browser code's own tests run under node."""

import base64
import gzip
import hashlib
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "components/viz"
FILES = COMPONENT / "charts/renderer/files"
HOST = "viz.dev.joinedcontext.com"


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def one(docs, kind, name):
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected one {kind}/{name}, got {len(found)}"
    return found[0]


def test_dev_renders_a_read_only_server_and_its_route_on_its_own_host(dev):
    pod = one(dev, "Deployment", "viz-renderer")["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False and pod["securityContext"]["runAsNonRoot"] is True
    container = pod["containers"][0]
    assert "@sha256:" in container["image"]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert all(m["readOnly"] for m in container["volumeMounts"] if m["name"] in ("config", "site", "vendor"))
    one(dev, "Service", "viz-renderer")
    routes = yaml.safe_load((COMPONENT / "apisix-routes.yaml").read_text().replace("{{", "#{{"))
    assert routes["viz"]["subDomain"] == "viz" and routes["viz"]["uri"] == "/*"
    assert HOST in one(dev, "Certificate", "apisix-edge")["spec"]["dnsNames"]
    # Any site may frame the host page (the embed snippet): the edge adds no X-Frame-Options.
    plugins = yaml.safe_load((COMPONENT / "apisix-plugins.yaml").read_text())["viz"]["plugins"]
    assert "X-Frame-Options" not in plugins["response-rewrite"]["headers"]["set"]


# The npm builds the two gzipped MapLibre modules unpack to (T-4657), as SHA256SUMS notes them.
UNPACKED = {
    "maplibre-gl-6.14.0.mjs.gz": "244d36122c1398da3a8259817cc6d71e04321afe6404f32606b4b6c6cc4f26fb",
    "maplibre-gl-worker-6.14.0.mjs.gz": "5f1e2f0e1624082b7e88a06e4c86085992b0f8c02929801e552f3f7a119856a9",
}


def test_the_vendored_files_are_the_releases_byte_for_byte_and_each_fits_a_configmap(dev):
    vendor = FILES / "vendor"
    sums = [line.split() for line in (vendor / "SHA256SUMS").read_text().splitlines() if line and not line.startswith("#")]
    assert sorted(name for _, name in sums) == sorted(p.name for p in vendor.iterdir() if p.name != "SHA256SUMS")
    for digest, name in sums:
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name
    for name, digest in UNPACKED.items():
        assert hashlib.sha256(gzip.decompress((vendor / name).read_bytes())).hexdigest() == digest, name
        assert digest in (vendor / "SHA256SUMS").read_text()
    pages = (FILES / "site/render.html").read_text() + (FILES / "site/map.html").read_text() + (FILES / "site/map.js").read_text()
    for _, name in sums:
        assert name.removesuffix(".gz") in pages, name
        cm = one(dev, "ConfigMap", "viz-renderer-" + name.removesuffix(".min.js").replace(".", "-"))
        size = len(base64.b64decode(cm["binaryData"][name])) if name.endswith(".gz") else len(cm["data"][name].encode())
        assert size < 1024 * 1024 - 4096, name
    # No page loads a script from anywhere but this host.
    for path in (FILES / "site").glob("*.html"):
        assert not re.search(r"(src|href)=\"(https?:)?//", path.read_text()), path.name


def csp(conf, location):
    block = conf[conf.index(f"location = {location} {{"):]
    return re.search(r'Content-Security-Policy "([^"]+)"', block).group(1)


def test_each_page_carries_the_headers_that_keep_a_spec_harmless(dev):
    conf = one(dev, "ConfigMap", "viz-renderer")["data"]["default.conf"]
    host = csp(conf, "/")
    assert "connect-src https://api.dev.joinedcontext.com https://data.dev.joinedcontext.com;" in host
    assert f"script-src https://{HOST};" in host and "frame-ancestors *" in host
    render = csp(conf, "/render.html")
    assert "connect-src 'none'" in render, "the frame that runs a spec calls no host"
    assert f"script-src https://{HOST};" in render
    for policy in (host, render):
        assert "unsafe-eval" not in policy and "default-src 'none'" in policy and "base-uri 'none'" in policy
        assert "'unsafe-inline'" not in policy.split("script-src")[1].split(";")[0]
    assert "Set-Cookie" not in conf and "add_header Referrer-Policy no-referrer always;" in conf
    assert conf.count("limit_except GET") >= 3
    page = (FILES / "site/index.html").read_text()
    assert 'sandbox="allow-scripts allow-downloads"' in page, "the renderer runs in an opaque origin"
    # T-4657: the map page reaches the tiles and nothing else, and MapLibre's modules leave as .gz.
    mapped = csp(conf, "/map.html")
    assert "connect-src https://tiles.dev.joinedcontext.com;" in mapped and "unsafe-eval" not in mapped
    assert f"script-src https://{HOST};" in mapped and "worker-src blob: https://" + HOST in mapped
    assert "gzip_static always;" in conf and "text/javascript js mjs;" in conf


def test_the_renderer_draws_through_the_interpreter_and_loads_nothing():
    render = (FILES / "site/render.js").read_text()
    assert "ast: true" in render and "expr: vega.expressionInterpreter" in render
    assert "editor: false" in render and "source: false" in render
    assert "loader: loader" in render and "self.jcRefuse(message.spec" in render
    assert "event.source !== window.parent || event.origin !== host" in render
    hostjs = (FILES / "site/host.js").read_text()
    assert 'credentials: "omit"' in hostjs and "root.jcRefuse(spec" in hostjs
    # `#show` takes a spec only from a parent on our hosts, and checks it before any frame sees it.
    assert "ourOrigin(event.origin, h.domain)" in hostjs and "root.jcRefuseMap(data.spec, h.domain)" in hostjs
    mapjs = (FILES / "site/map.js").read_text()
    assert "innerHTML" not in mapjs and "root.jcRefuseMap(spec, domain)" in mapjs
    assert "event.source !== window.parent || event.origin !== location.origin" in mapjs


def test_the_refusal_list_and_the_host_page_logic_under_node():
    tests = sorted(str(p) for p in (COMPONENT / "tests").glob("*.test.mjs"))
    assert len(tests) == 3
    run = subprocess.run(["node", "--test", *tests], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
