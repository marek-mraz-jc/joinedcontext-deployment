"""jc-prod's edge in host mode reaches jc only on the hosts it names (T-6705).

jc serves some modules inside the pod only: shako (`/git`), ekiben (`/streams`, or its default host
`streams.{domain}`) and the in-binary broker (`/broker`, or `broker.{domain}`); the Portal and the
gateway call them on jc's own listener under their host. A route with no host answers every Host,
so a pod that reaches the edge could name one of those hosts and reach the module past the
gateway. Every jc route names its host, and the uri-blocker keeps the paths closed on the hosts
it does name.
"""

import http.client
import json
import re
import shutil
import subprocess
import time

import pytest
import yaml

from test_jc_app_hosts import edge_file

ENV = "jc-prod"
DOMAIN = "smartcity.joinedcontext.com"
JC = "jc.jc-prod.svc.cluster.local:8080"
BLOCKED = re.compile(r"^/(git|streams|broker)([/?]|$)")


@pytest.fixture(scope="module")
def edge(rendered):
    return edge_file(rendered(ENV))


def jc_routes(edge):
    upstreams = {u["id"]: u for u in edge["upstreams"]}
    return [r for r in edge["routes"] if JC in upstreams[r["upstream_id"]]["nodes"]]


def test_every_jc_route_names_its_host(edge):
    routes = jc_routes(edge)
    assert {r["id"] for r in routes} >= {"jc-host-apex", "jc-host-api", "jc"}
    for route in routes:
        assert route.get("host") or route.get("hosts"), f"{route['id']} answers every Host"
    hosts = {r.get("host") for r in routes} | {h for r in routes for h in r.get("hosts", [])}
    assert DOMAIN in hosts
    for inside in (f"broker.{DOMAIN}", f"streams.{DOMAIN}", "localhost:8080", "localhost"):
        assert inside not in hosts, inside


# Requests that must reach no jc module: a host jc serves inside the pod only, or a blocked path
# in any spelling on a host the edge does route.
FORGED = [
    ("localhost:8080", "/git/api/v1/version"),
    ("localhost:8080", "/streams/ping"),
    ("localhost:8080", "/broker/ngsi-ld/v1/entities"),
    (f"broker.{DOMAIN}", "/"),
    (f"broker.{DOMAIN}", "/ngsi-ld/v1/entities"),
    (f"streams.{DOMAIN}", "/"),
    (f"streams.{DOMAIN}", "/ping"),
    (DOMAIN, "/git/api/v1/version"),
    (DOMAIN, "/%67it/api/v1/version"),
    (DOMAIN, "//git/api/v1/version"),
    (DOMAIN, "/./git/api/v1/version"),
    (DOMAIN, "/streams/ping"),
    (DOMAIN, "/broker/ngsi-ld/v1/entities"),
    (f"api.{DOMAIN}", "/git/api/v1/version"),
    (f"portal.{DOMAIN}", "//broker/ngsi-ld/v1/entities"),
]
# And the hosts it routes still reach jc.
ROUTED = [(DOMAIN, "/grafana/"), (f"portal.{DOMAIN}", "/"), (f"api.{DOMAIN}", "/api/endpoint/x")]


def ask(port: int, host: str, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, response.read().decode(errors="replace")
    finally:
        conn.close()


@pytest.mark.xdist_group("docker-apisix-jc-host")
@pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
def test_the_pinned_edge_reaches_no_inside_module_on_a_forged_host_or_path(edge, tmp_path):
    """Played on `apache/apisix` as pinned with jc-prod's rendered jc routes and their plugin
    configs; jc is an echo route that names what it was sent."""
    from test_apisix_429_contract import pinned_image
    from test_edge_csp_baseline import free_port

    routes = jc_routes(edge)
    ids = {r["upstream_id"] for r in routes}
    configs = {r.get("plugin_config_id") for r in routes}
    echo = (
        'return function() ngx.say(require("cjson").encode({reached = true, '
        'host = ngx.var.http_x_sent_host, uri = ngx.var.request_uri})); ngx.exit(200) end'
    )
    upstreams = [
        {"id": u, "type": "roundrobin", "nodes": {"127.0.0.1:9080": 1},
         "pass_host": "rewrite", "upstream_host": "echo.test"}
        for u in sorted(ids)
    ]
    played = [dict(r) for r in routes]
    played.append({"id": "echo", "uri": "/*", "host": "echo.test", "priority": 100,
                   "plugins": {"serverless-pre-function": {"phase": "rewrite", "functions": [echo]}}})
    plugin_configs = []
    for config in edge.get("plugin_configs", []):
        if config["id"] in configs:
            config = json.loads(json.dumps(config))
            # The echo learns which Host the edge forwarded.
            rewrite = config["plugins"].setdefault("proxy-rewrite", {})
            rewrite.setdefault("headers", {}).setdefault("set", {})["X-Sent-Host"] = "$host"
            plugin_configs.append(config)
    (tmp_path / "config.yaml").write_text(
        "deployment:\n  role: data_plane\n  role_data_plane:\n    config_provider: yaml\n"
    )
    (tmp_path / "apisix.yaml").write_text(
        yaml.safe_dump({"routes": played, "upstreams": upstreams, "plugin_configs": plugin_configs})
        + "#END\n"
    )
    port = free_port()
    name = f"apisix-jc-host-{port}"
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
        deadline = time.time() + 60
        while True:
            try:
                status, body = ask(port, *ROUTED[0])
                if status == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True).stderr
                pytest.fail(f"APISIX did not start or route {ROUTED[0]}:\n{logs[-3000:]}")
            time.sleep(1)
        answers = {(h, p): ask(port, h, p) for h, p in FORGED + ROUTED}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    for host, path in ROUTED:
        status, body = answers[(host, path)]
        assert status == 200 and json.loads(body)["host"] == host, (host, path, status, body)
    for host, path in FORGED:
        status, body = answers[(host, path)]
        if status != 200 or '"reached":true' not in body:
            continue
        # Forwarded: jc routes the raw path by prefix (no decoding, no dot segments), so it
        # must name no blocked mount, on a host jc's edge routes.
        seen = json.loads(body)
        assert seen["host"] in {DOMAIN, f"api.{DOMAIN}", f"portal.{DOMAIN}"}, (host, path, seen)
        assert not BLOCKED.match(seen["uri"]), (host, path, seen)
