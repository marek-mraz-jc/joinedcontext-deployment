"""T-4694: the standalone assistant on ai.{domain}. The rendered dev environment carries a
read-only static server, the bundle with the chat host filled in, the route and its certificate
name; the page's policy runs only its own scripts and asks only the chat's host."""

import gzip
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "components/ai"
SITE = COMPONENT / "charts/app/files/site"
HOST = "ai.dev.joinedcontext.com"
API = "https://assistant.dev.joinedcontext.com"


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def one(docs, kind, name):
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected one {kind}/{name}, got {len(found)}"
    return found[0]


def test_dev_renders_a_read_only_server_and_its_route_on_its_own_host(dev):
    pod = one(dev, "Deployment", "ai-app")["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False and pod["securityContext"]["runAsNonRoot"] is True
    container = pod["containers"][0]
    assert "@sha256:" in container["image"]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    one(dev, "Service", "ai-app")
    routes = yaml.safe_load((COMPONENT / "apisix-routes.yaml").read_text().replace("{{", "#{{"))
    assert routes["ai"]["subDomain"] == "ai" and routes["ai"]["uri"] == "/*"
    assert HOST in one(dev, "Certificate", "apisix-edge")["spec"]["dnsNames"]


def test_the_bundle_asks_only_the_chat_host_and_runs_only_its_own_scripts(dev):
    site = one(dev, "ConfigMap", "ai-app-site")["data"]
    assert sorted(site) == ["app.js", "embed.js", "index.html", "visitor.js", "widget.css", "widget.js"]
    page = site["index.html"]
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1)
    assert "script-src 'self';" in policy and f"connect-src {API};" in policy
    assert "frame-src https://viz.dev.joinedcontext.com;" in policy
    assert "unsafe" not in policy and "*" not in policy
    assert f'<meta name="jc-api" content="{API}">' in page
    assert "__API__" not in "".join(site.values()) and "__FRAMES__" not in "".join(site.values())
    assert not re.search(r"<script>|style=", page), "no inline script or style"
    assert sum(len(gzip.compress(text.encode())) for text in site.values()) <= 200 * 1024
    assert not re.search(r"sk-or-v1-|client_secret|PRIVATE KEY", "".join(site.values()))
    conf = one(dev, "ConfigMap", "ai-app")["data"]["default.conf"]
    assert f"connect-src {API};" in conf and "__API__" not in conf
    assert "location = /index.html { return 404; }" in conf


def test_the_committed_bundle_is_the_template_build():
    """build.mjs --template leaves the placeholders for the chart; a hand edit would drop them."""
    page = (SITE / "index.html").read_text()
    assert "connect-src __API__;" in page and '<meta name="jc-api" content="__API__">' in page
    widget = (SITE / "widget.js").read_text()
    assert widget.startswith("var JC_FIELDS = ") and "JCRender.connector" in widget
