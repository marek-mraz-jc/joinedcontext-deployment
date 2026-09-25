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
    assert "error_page 429 = @too_many_requests;" in snippet, snippet
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


def answer(url: str) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read().decode()


@contextlib.contextmanager
def pinned_apisix(tmp_path: Path, rules: str):
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
        assert "problem+json" not in headers.get("Content-Type", ""), headers
        assert PROBLEM_TYPE not in body, "an answer that is not a refusal is left alone"

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
