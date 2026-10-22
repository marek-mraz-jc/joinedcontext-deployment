"""The shape of the refusal the edge writes itself: a 429 is Problem Details (T-2237).

Every `limit-count` in `components/*/apisix-plugins.yaml` answers `rejected_code: 429`, and
without the handler the server block carries APISIX serves its own HTML error page. The
platform's error contract is RFC 9457 `application/problem+json` (API-08), and for the NGSI-LD
routes ETSI CIM 009 requires it on an error response (GW26); a refusal names no route, no quota
and no upstream (R20).

The first four tests read the committed configuration. The last one runs the pinned APISIX image
with that same snippet and one route whose limit is 1, because a header contract is only proved
by an answer: it is skipped where there is no docker, and it needs no cluster.
"""

import contextlib
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

# Starts its own containers from module-scoped fixtures; split over xdist workers, each worker
# would start a second set beside the first. One worker runs the whole module (ci.yml loadgroup).
pytestmark = pytest.mark.xdist_group("docker-apisix-429")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VALUES = PROJECT_ROOT / "components/apisix/values/apisix/base-values.yaml.gotmpl"
IMAGES = PROJECT_ROOT / "components/apisix/images.yaml"
# A route may carry a plugin of its own beside its plugin config (T-2892), so both files count.
PLUGIN_FILES = sorted(PROJECT_ROOT.glob("components/*/apisix-plugins.yaml")) + sorted(
    PROJECT_ROOT.glob("components/*/apisix-routes.yaml")
)
PROBLEM_TYPE = "https://joinedcontext.com/errors/too-many-requests"


def server_snippet() -> str:
    """The `httpSrv` snippet of the APISIX values, which is the server block of the edge."""
    lines = VALUES.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "httpSrv: |")
    body = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("        "):
            break
        body.append(line[8:])
    return "\n".join(body)


def http_end_snippet(maintenance: dict[str, int] | None = None) -> str:
    """The `httpEnd` snippet (the edge's http block) as the chart renders it for a test: the
    template's control lines dropped, the trusted proxy range filled in, and `maintenance`
    (host -> Retry-After seconds) written into the map the switch renders (T-5119)."""
    lines = VALUES.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "httpEnd: |")
    body = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("        "):
            break
        if line.strip().startswith("{{"):
            continue
        body.append(line[8:].replace("{{ $this.trustedProxyCidr }}", "10.42.0.0/16"))
    text = "\n".join(body)
    hosts = "".join(f"\n  {host} {seconds};" for host, seconds in (maintenance or {}).items())
    return text.replace('map $host $jc_maintenance {\n  default "";', 'map $host $jc_maintenance {\n  default "";' + hosts)


def limit_count_blocks() -> list[tuple[str, str, dict]]:
    """Every `limit-count` configuration of the edge, with the file and entry it belongs to."""
    found = []
    for path in PLUGIN_FILES:
        document = yaml.safe_load(path.read_text()) or {}
        for name, route in document.items():
            plugins = (route or {}).get("plugins") or {}
            if "limit-count" in plugins:
                found.append((path.name, name, plugins["limit-count"]))
    return found


def test_the_server_block_answers_a_429_with_problem_details():
    snippet = server_snippet()
    assert "error_page 429 = @too_many_requests_$jc_refusal;" in snippet, snippet
    assert "set $jc_refusal json;" in snippet, "a client that does not ask for a page gets the contract"
    assert "default_type application/problem+json;" in snippet, snippet
    document = re.search(r"return 429 '(\{.*\})';", snippet)
    assert document, snippet
    problem = json.loads(document.group(1))
    assert problem["status"] == 429
    assert problem["title"] == "Too Many Requests"
    assert problem["type"] == PROBLEM_TYPE


def test_the_refusal_names_nothing_of_the_deployment():
    """R20: a refusal that named the route, the quota or the upstream would be a probe."""
    snippet = server_snippet()
    document = re.search(r"return 429 '(\{.*\})';", snippet)
    assert document
    text = document.group(1)
    for internal in ("svc.cluster.local", "upstream", "portal", "keycloak", "context-gateway"):
        assert internal not in text, f"{internal} is in the refusal: {text}"
    for count in {str(block.get("count")) for _, _, block in limit_count_blocks()}:
        assert count not in text, f"the quota {count} is in the refusal: {text}"


def test_the_refusal_carries_the_headers_a_refusal_needs():
    """The named location is written after the plugin chain, so it sets them itself."""
    snippet = server_snippet()
    for header in (
        'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;',
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Cache-Control "no-store, no-cache, must-revalidate" always;',
    ):
        assert header in snippet, snippet


def html_pages(snippet: str) -> dict[str, str]:
    """T-4201: the refusal page per language, by the named location that answers it."""
    return dict(re.findall(r"location @too_many_requests_html_(\w+) \{.*?return 429 '(<!doctype html>.*?)';", snippet, re.S))


def test_a_browser_gets_a_page_in_its_language():
    """T-4201: the bare JSON in a browser's pretty-print box was the page a visitor met."""
    snippet = server_snippet()
    pages = html_pages(snippet)
    assert sorted(pages) == ["cs", "de", "en", "sk"], sorted(pages)
    for lang, page in pages.items():
        assert f'<html lang="{lang}">' in page, lang
        # T-5078: a timed reload the reader cannot stop fails WCAG 2.2.1 (axe meta-refresh,
        # critical); the page names the seconds and links the same address instead.
        assert "http-equiv" not in page.lower(), f"{lang}: no timed refresh"
        assert "$sent_http_x_ratelimit_reset s" in page, f"{lang}: the page says when"
        assert re.findall(r"<a [^>]*>", page) == ['<a href="">'], f"{lang}: one link, to the same address"
        assert "<script" not in page and "src=" not in page and page.count("href=") == 1, f"{lang}: it loads nothing"
        for count in {str(block.get("count")) for _, _, block in limit_count_blocks()}:
            assert f" {count} " not in page, f"{lang}: the quota {count} is in the page"
    assert 'if ($http_accept ~* "text/html") {' in snippet
    for lang in ("sk", "cs", "de"):
        assert f'if ($jc_refusal_lang ~* "^\\s*{lang}") {{' in snippet, lang
    # Each page's location sets the headers a refusal needs, and a CSP that allows nothing to load.
    for block in re.findall(r"location @too_many_requests_\w+ \{(.*?)\n        \}", snippet, re.S):
        assert "add_header Retry-After $sent_http_x_ratelimit_reset always;" in block
        assert 'add_header X-Content-Type-Options "nosniff" always;' in block
        assert 'add_header Cache-Control "no-store, no-cache, must-revalidate" always;' in block
        assert "add_header Content-Security-Policy" in block


def test_retry_after_is_the_window_the_limit_published():
    """A constant would lie the day a route's `time_window` changes."""
    assert "add_header Retry-After $sent_http_x_ratelimit_reset always;" in server_snippet()


@pytest.mark.parametrize("path,route,block", limit_count_blocks(),
                         ids=[f"{p}:{r}" for p, r, _ in limit_count_blocks()])
def test_every_limit_count_publishes_the_window_it_refuses_for(path, route, block):
    """`Retry-After` reads `X-RateLimit-Reset`, which only a route with the quota headers sends."""
    assert block.get("rejected_code") == 429, f"{path}:{route}"
    assert block.get("show_limit_quota_header") is True, f"{path}:{route}"
    assert "rejected_msg" not in block, (
        f"{path}:{route}: `rejected_msg` answers `{{\"error_msg\": …}}` as text/plain, which is "
        "not Problem Details; the server block's handler is what shapes the refusal"
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def pinned_image() -> str:
    gateway = yaml.safe_load(IMAGES.read_text())["apisix"]["apisix"]["gateway"]
    return f"{gateway['repository']}:{gateway['tag']}@{gateway['digest']}"


def answer(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read().decode()


@contextlib.contextmanager
def pinned_apisix(tmp_path: Path, rules: str, maintenance: dict[str, int] | None = None):
    """The pinned image serving these standalone rules behind the edge's server block; yields
    the base URL once it answers, and removes the container afterwards."""
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    port = free_port()
    (tmp_path / "config.yaml").write_text(
        "deployment:\n"
        "  role: data_plane\n"
        "  role_data_plane:\n"
        "    config_provider: yaml\n"
        "nginx_config:\n"
        "  error_log_level: warn\n"
        "  http_server_configuration_snippet: |\n"
        + "".join(f"    {line}\n" for line in server_snippet().splitlines())
        + "  http_end_configuration_snippet: |\n"
        + "".join(f"    {line}\n" for line in http_end_snippet(maintenance).splitlines())
    )
    (tmp_path / "apisix.yaml").write_text(rules)
    name = f"apisix-429-contract-{port}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    started = subprocess.run(
        ["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:9080",
         "-v", f"{tmp_path / 'config.yaml'}:/usr/local/apisix/conf/config.yaml:ro",
         "-v", f"{tmp_path / 'apisix.yaml'}:/usr/local/apisix/conf/apisix.yaml:ro",
         pinned_image()],
        capture_output=True, text=True, check=False,
    )
    if started.returncode != 0:
        pytest.skip(f"the pinned image does not run here: {started.stderr.strip()}")
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base + "/", timeout=5)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail("APISIX did not start")
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def test_the_pinned_image_answers_problem_details_for_a_real_refusal(tmp_path):
    # One route with a limit of 1 and the security headers every real route carries, so the
    # answer is the whole chain and not the handler alone. The upstream is a closed port: the
    # first request is a 502 the handler must leave alone, the second is the refusal.
    rules = """
routes:
  - uri: /probe
    plugins:
      limit-count:
        count: 1
        time_window: 60
        key_type: var
        key: remote_addr
        rejected_code: 429
        policy: local
        show_limit_quota_header: true
      response-rewrite:
        headers:
          set:
            X-Content-Type-Options: "nosniff"
    upstream:
      nodes:
        "127.0.0.1:9": 1
      type: roundrobin
#END
"""
    with pinned_apisix(tmp_path, rules) as base:
        url = base + "/probe"
        status, headers, body = answer(url)
        assert status == 502, f"the first request is inside the limit: {status} {body}"
        assert PROBLEM_TYPE not in body, "an answer that is not a refusal is not the refusal"

        status, headers, body = answer(url)
        assert status == 429, body
        assert headers["Content-Type"] == "application/problem+json", headers
        problem = json.loads(body)
        assert problem["status"] == 429
        assert problem["type"] == PROBLEM_TYPE
        assert problem["title"] == "Too Many Requests"
        assert headers["Retry-After"] == headers["X-RateLimit-Reset"], headers
        assert 0 < int(headers["Retry-After"]) <= 60, headers
        # nginx writes this answer after the plugin chain, so the headers a refusal needs are
        # the ones the server block sets itself.
        assert headers["X-Content-Type-Options"] == "nosniff", headers
        assert headers["Strict-Transport-Security"].startswith("max-age=31536000"), headers
        assert headers["X-Frame-Options"] == "DENY", headers
        assert headers["Referrer-Policy"] == "no-referrer", headers
        assert "no-store" in headers["Cache-Control"], headers

        # T-4201: the same refusal, asked for by a Slovak browser, is a Slovak page that
        # names when to try again; a German one gets German, anyone else English.
        page = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
        status, headers, body = answer(url, {**page, "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8"})
        assert status == 429, body
        assert headers["Content-Type"] == "text/html; charset=utf-8", headers
        assert '<html lang="sk">' in body and "Príliš veľa požiadaviek" in body, body
        assert f'o {headers["Retry-After"]} s' in body, "the page names the seconds Retry-After names"
        assert "http-equiv" not in body and '<a href="">' in body, "no timed refresh, a link to load again"
        assert "default-src 'none'" in headers["Content-Security-Policy"], headers
        assert headers["X-Content-Type-Options"] == "nosniff", headers
        assert PROBLEM_TYPE not in body
        assert '<html lang="de">' in answer(url, {**page, "Accept-Language": "de-AT"})[2]
        assert '<html lang="en">' in answer(url, {**page, "Accept-Language": "fi"})[2]
        assert '<html lang="en">' in answer(url, page)[2], "no Accept-Language is English"
        status, headers, body = answer(url, {"Accept": "application/json", "Accept-Language": "sk"})
        assert headers["Content-Type"] == "application/problem+json" and json.loads(body)["type"] == PROBLEM_TYPE


def test_the_pinned_image_counts_space_reads_and_writes_apart(tmp_path):
    """T-2892, ADR-N-035: the -read route shares the write route's chain, both labelled, and its
    own limit-count replaces the chain's, so reads and writes fill two buckets. The same shape
    as context-space and context-space-read, with limits of 1 read and 2 writes."""
    limit = "count: {count}\n        time_window: 60\n        key_type: var\n        key: remote_addr\n        rejected_code: 429\n        policy: local\n        show_limit_quota_header: true"
    rules = f"""
plugin_configs:
  - id: chain
    labels:
      jc-rate-class: dataWrite
    plugins:
      limit-count:
        {limit.format(count=2)}
upstreams:
  - id: closed
    type: roundrobin
    nodes:
      "127.0.0.1:9": 1
routes:
  - id: write
    uri: /cs/*
    priority: 15
    upstream_id: closed
    plugin_config_id: chain
  - id: read
    uri: /cs/*
    priority: 16
    methods: ["GET", "HEAD"]
    upstream_id: closed
    plugin_config_id: chain
    labels:
      jc-rate-class: dataRead
    plugins:
      limit-count:
        {limit.format(count=1)}
#END
"""

    def call(base: str, method: str) -> tuple[int, str]:
        body = b"{}" if method == "POST" else None
        request = urllib.request.Request(base + "/cs/space/ngsi-ld/v1/entities", method=method, data=body)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers.get("X-RateLimit-Limit", "")
        except urllib.error.HTTPError as refused:
            return refused.code, refused.headers.get("X-RateLimit-Limit", "")

    with pinned_apisix(tmp_path, rules) as base:
        assert call(base, "GET") == (502, "1"), "the read counts the route's own limit"
        assert call(base, "GET")[0] == 429
        # The spent read bucket leaves the writes alone, and they count the chain's limit.
        assert call(base, "POST") == (502, "2")
        assert call(base, "POST") == (502, "2")
        assert call(base, "POST")[0] == 429


def test_the_pinned_image_holds_bodies_to_the_organizations_edge_limit(tmp_path):
    """T-2892, ADR-N-035: the server block's ceiling is the catalog's largest value and the
    `client-control` global rule the Portal writes holds each body to the Organization's
    `spec.limits.edge.maxRequestBodyMegabytes`, above the old fixed 16 MiB and below the ceiling
    alike, with a Content-Length and streamed in chunks (T-2263)."""
    mib = 1024 * 1024
    rules = f"""
global_rules:
  - id: edge-body
    plugins:
      client-control:
        max_body_size: {20 * mib}
routes:
  - uri: /probe
    upstream:
      nodes:
        "127.0.0.1:9": 1
      type: roundrobin
#END
"""

    def post(base: str, size: int, chunked: bool) -> int:
        payload = b"x" * size
        data = iter([payload[i : i + mib] for i in range(0, size, mib)]) if chunked else payload
        headers = {"Content-Type": "application/octet-stream"}
        request = urllib.request.Request(base + "/probe", method="POST", data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status
        except urllib.error.HTTPError as refused:
            return refused.code

    with pinned_apisix(tmp_path, rules) as base:
        for chunked in (False, True):
            # Past the edge to the (closed) upstream: over the old 16 MiB, under the rule's 20.
            assert post(base, 18 * mib, chunked) == 502, f"chunked={chunked}"
            assert post(base, 21 * mib, chunked) == 413, f"chunked={chunked}"


def test_the_pinned_image_counts_anonymous_named_mcp_calls_per_client(tmp_path):
    """T-4141: the public named MCP servers. The committed `context-mcp-named` route's `vars` and
    limit, in front of a route that counts nothing, as the hub's 5,000 is nothing to this test:
    a caller without a bearer is refused after the route's count, a client header does not
    reset the bucket, and a bearer takes the other route and is never counted here."""
    routes = yaml.safe_load((PROJECT_ROOT / "components/context-gateway/apisix-routes.yaml").read_text())
    named = routes["context-mcp-named"]
    limit = named["plugins"]["limit-count"]
    assert named["uri"] == "/api/mcp/*" and named["priority"] > routes["context-mcp-hub"]["priority"]
    rules = f"""
upstreams:
  - id: closed
    type: roundrobin
    nodes:
      "127.0.0.1:9": 1
routes:
  - id: hub
    uri: {routes["context-mcp-hub"]["uri"]}
    priority: {routes["context-mcp-hub"]["priority"]}
    upstream_id: closed
  - id: named
    uri: {named["uri"]}
    priority: {named["priority"]}
    vars: {json.dumps(named["vars"])}
    upstream_id: closed
    plugins:
      limit-count: {json.dumps(limit)}
#END
"""

    def call(base: str, headers: dict[str, str]) -> int:
        request = urllib.request.Request(
            base + "/api/mcp/bbsk/otvorene-data", method="POST", data=b"{}", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as refused:
            return refused.code

    with pinned_apisix(tmp_path, rules) as base:
        for _ in range(limit["count"]):
            assert call(base, {}) == 502, "inside the limit the call reaches the (closed) upstream"
        assert call(base, {}) == 429
        assert call(base, {"Authorization": ""}) == 429, "an empty Authorization is anonymous"
        for spoof in ("X-Forwarded-For", "X-Real-IP"):
            assert call(base, {spoof: "203.0.113.7"}) == 429, f"{spoof} chose a fresh bucket"
        # A bearer is the gateway's to verify; it never spends or meets the anonymous bucket.
        assert call(base, {"Authorization": "Bearer token"}) == 502
        status, _, _ = answer(base + "/api/mcp")
        assert status == 502, "the hub itself is not this route's"


def test_the_pinned_image_puts_the_header_floor_on_every_answer(tmp_path, rendered):
    """T-5107 (ZAP 10035, 10063): the committed `edge-headers` global rule on the pinned image. The
    edge's own 404 for an address no route serves carries HSTS, nosniff and the Permissions-Policy;
    a route's own Permissions-Policy is the one sent; an App's host gets none from the edge."""
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-base"
    )
    rule = next(r for r in yaml.safe_load(cm["data"]["apisix.yaml"])["global_rules"] if r["id"] == "edge-headers")
    apps = re.search(r'local apps = "\.(apps\.[a-z0-9.-]+)"', "".join(rule["plugins"]["serverless-post-function"]["functions"])).group(1)
    rules = yaml.safe_dump({
        "global_rules": [rule],
        "routes": [{
            "uri": "/own",
            "plugins": {
                "fault-injection": {"abort": {"http_status": 200, "body": "ok"}},
                "response-rewrite": {"headers": {"set": {"Permissions-Policy": "geolocation=(self)"}}},
            },
            "upstream": {"nodes": {"127.0.0.1:9": 1}, "type": "roundrobin"},
        }],
    }) + "#END\n"
    floor = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    with pinned_apisix(tmp_path, rules) as base:
        status, headers, _ = answer(base + "/no-route-serves-this")
        assert status == 404
        assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains; preload"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Permissions-Policy"] == floor
        status, headers, _ = answer(base + "/own")
        assert (status, headers["Permissions-Policy"]) == (200, "geolocation=(self)")
        status, headers, _ = answer(base + "/no-route-serves-this", {"Host": f"map.{apps}"})
        assert status == 404 and "Permissions-Policy" not in headers
        assert headers["Strict-Transport-Security"].startswith("max-age=31536000")
