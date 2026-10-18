"""T-4641, ADR-N-053: the chart renderer on viz.{domain}. The rendered dev environment carries
the server, its files and the pinned Vega builds, the route and its certificate name; each page
carries the headers that keep a spec harmless; the browser code's own tests run under node."""

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


def test_the_vendored_vega_is_the_release_byte_for_byte_and_each_file_fits_a_configmap(dev):
    sums = [line.split() for line in (FILES / "vendor/SHA256SUMS").read_text().splitlines() if line and not line.startswith("#")]
    assert sorted(name for _, name in sums) == sorted(p.name for p in (FILES / "vendor").glob("*.min.js"))
    for digest, name in sums:
        assert hashlib.sha256((FILES / "vendor" / name).read_bytes()).hexdigest() == digest, name
    page = (FILES / "site/render.html").read_text()
    for _, name in sums:
        assert f'src="vendor/{name}"' in page, name
        cm = one(dev, "ConfigMap", "viz-renderer-" + name.removesuffix(".min.js").replace(".", "-"))
        assert len(cm["data"][name].encode()) < 1024 * 1024 - 4096
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


def test_the_renderer_draws_through_the_interpreter_and_loads_nothing():
    render = (FILES / "site/render.js").read_text()
    assert "ast: true" in render and "expr: vega.expressionInterpreter" in render
    assert "editor: false" in render and "source: false" in render
    assert "loader: loader" in render and "self.jcRefuse(message.spec" in render
    assert "event.source !== window.parent || event.origin !== host" in render
    hostjs = (FILES / "site/host.js").read_text()
    assert 'credentials: "omit"' in hostjs and "root.jcRefuse(spec" in hostjs


def test_the_refusal_list_and_the_host_page_logic_under_node():
    tests = sorted(str(p) for p in (COMPONENT / "tests").glob("*.test.mjs"))
    assert len(tests) == 2
    run = subprocess.run(["node", "--test", *tests], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
