"""T-5900: the edge keeps the gateway's anonymous reads of data a few seconds, and nothing private.

The first tests read the committed route and the gateway's values. The last runs the pinned APISIX
image with the committed `proxy-cache` block in front of a stub that answers as the gateway does
(`public, max-age=5` to an anonymous read, `private, no-store` to everything else), because only
answers prove what the edge stores: a token's view, a session and an answer the gateway keeps
private must never come back to someone else.
"""

import http.server
import itertools
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from test_apisix_429_contract import pinned_image

pytestmark = pytest.mark.xdist_group("docker-apisix-cache")

ROOT = Path(__file__).resolve().parent.parent
ROUTES = (ROOT / "components/context-gateway/apisix-routes.yaml").read_text()
ROUTE = yaml.safe_load(ROUTES.replace("{{", "#").replace("}}", ""))["api-context-endpoint"]
VALUES = ROOT / "components/context-gateway/values/gateway/base-values.yaml.gotmpl"


def test_only_the_anonymous_data_host_route_caches():
    assert (ROUTE["subDomain"], ROUTE["uri"], ROUTE["pluginConfig"]) == ("api", "/api/endpoint/*", "context-endpoint")
    cache = ROUTE["plugins"]["proxy-cache"]
    assert (cache["cache_strategy"], cache["cache_zone"]) == ("memory", "memory_cache")
    # The gateway's max-age decides; a `private` or `no-store` answer is never stored.
    assert cache["cache_control"] is True
    for field in ("cache_bypass", "no_cache"):
        assert set(cache[field]) == {"$http_cookie", "$http_authorization", "$http_link", "$http_prefer",
                                     "$http_ngsild_tenant"}, field
    assert cache["cache_http_status"] == [200] and cache["cache_method"] == ["GET", "HEAD"]
    # Every request header the gateway's Vary names, Authorization aside (it bypasses).
    for var in ("$host", "$request_uri", "$http_accept", "$http_accept_language", "$http_accept_encoding",
                "$http_ngsild_results_restricted"):
        assert var in cache["cache_key"], var
    # One route: the apex and Portal-host routes carry bearers and never cache.
    assert ROUTES.count("proxy-cache:") == 1


def test_the_gateway_marks_anonymous_reads_public_for_five_seconds():
    assert 'JC_GATEWAY_PUBLIC_MAX_AGE: "5"' in VALUES.read_text()


class Gateway(http.server.BaseHTTPRequestHandler):
    counter = itertools.count()

    def do_GET(self):
        n = next(self.counter)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        anonymous = all(self.headers.get(h) is None for h in ("Authorization", "Cookie", "Link", "Prefer"))
        self.send_header("Cache-Control", "public, max-age=5" if anonymous else "private, no-store")
        self.send_header("Vary", "Authorization, Accept, Accept-Language, NGSILD-Results-Restricted, Accept-Encoding")
        self.end_headers()
        self.wfile.write(json.dumps({"n": n, "auth": self.headers.get("Authorization"), "link": self.headers.get("Link"),
                                     "lang": self.headers.get("Accept-Language")}).encode())

    def log_message(self, *args):
        pass


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tmp = tmp_path_factory.mktemp("api-cache")
    (tmp / "config.yaml").write_text("deployment:\n  role: data_plane\n  role_data_plane:\n    config_provider: yaml\n")
    rules = {"routes": [{"id": "r", "uri": "/api/endpoint/*",
                         "upstream": {"type": "roundrobin", "nodes": {f"upstream:{server.server_port}": 1}},
                         "plugins": {"proxy-cache": ROUTE["plugins"]["proxy-cache"]}}]}
    (tmp / "apisix.yaml").write_text(yaml.safe_dump(rules) + "#END\n")
    port = free_port()
    name = f"apisix-api-cache-{port}"
    started = subprocess.run(
        ["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:9080",
         "--add-host", "upstream:host-gateway",
         "-v", f"{tmp / 'config.yaml'}:/usr/local/apisix/conf/config.yaml:ro",
         "-v", f"{tmp / 'apisix.yaml'}:/usr/local/apisix/conf/apisix.yaml:ro", pinned_image()],
        capture_output=True, text=True, check=False)
    if started.returncode != 0:
        server.shutdown()
        pytest.skip(f"the pinned image does not run here: {started.stderr.strip()}")
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base + "/api/endpoint/ready", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.skip("APISIX or its upstream did not answer within 60 s")
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        server.shutdown()


def get(url, **headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as answer:
        return json.loads(answer.read()), answer.headers


def test_an_anonymous_read_is_kept_and_a_token_or_a_session_is_never_served_from_it(edge):
    url = edge + "/api/endpoint/s/ngsi-ld/v1/entities?type=A"
    first, _ = get(url)
    again, headers = get(url)
    assert again == first and headers["Apisix-Cache-Status"] == "HIT"
    with_token, _ = get(url, Authorization="Bearer person")
    assert with_token["n"] != first["n"] and with_token["auth"] == "Bearer person"
    with_cookie, _ = get(url, Cookie="session=person")
    assert with_cookie["n"] != first["n"]
    # Neither filled the cache with their answer.
    assert get(url)[0] == first


def test_a_header_the_gateway_varies_by_is_its_own_entry(edge):
    url = edge + "/api/endpoint/s/ngsi-ld/v1/entities?type=B"
    english, _ = get(url, **{"Accept-Language": "en"})
    slovak, _ = get(url, **{"Accept-Language": "sk"})
    assert english["n"] != slovak["n"] and slovak["lang"] == "sk"
    assert get(url, **{"Accept-Language": "sk"})[0] == slovak


def test_an_answer_kept_private_is_never_stored(edge):
    # A token's answer is `private, no-store`: it never comes back, not even to the same token.
    url = edge + "/api/endpoint/s/ngsi-ld/v1/entities?type=C"
    one, _ = get(url, Authorization="Bearer a")
    two, headers = get(url, Authorization="Bearer a")
    assert one["n"] != two["n"] and headers.get("Apisix-Cache-Status") != "HIT"


def test_a_read_with_a_link_context_neither_reads_nor_fills_the_cache(edge):
    # T-5900 review: Link names the @context a compacted answer is written in; it is not in the
    # key, so a Link read must never be served a plain answer nor leave its own for a plain read.
    url = edge + "/api/endpoint/s/ngsi-ld/v1/entities?type=D"
    context = '<https://example.org/ctx.jsonld>; rel="http://www.w3.org/ns/json-ld#context"'
    linked, headers = get(url, Link=context)
    assert linked["link"] == context and headers.get("Apisix-Cache-Status") != "HIT"
    plain, _ = get(url)
    assert plain["n"] != linked["n"] and plain["link"] is None
    again, headers = get(url, Link=context)
    assert again["n"] not in (linked["n"], plain["n"]) and headers.get("Apisix-Cache-Status") != "HIT"
    assert get(url)[0] == plain
