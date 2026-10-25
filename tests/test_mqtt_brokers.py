"""T-3993: the MQTT edge brokers (ADR-N-048, MF-54, PL-74, PL-76, PL-77).

The chart is rendered on its own with three brokers, two in one project and one of the same
name in another, because no environment declares a broker: the Portal's reconciler stamps them
(T-3994). The environment render then checks the wiring around them: the gateway's internal
listener, the runner's namespace variable and the NetworkPolicies.
"""

import json
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "components/mqtt-brokers/charts/brokers"
TEMPLATE = "broker-template"
STORAGE_PLUGINS = {"rmqtt-retainer", "rmqtt-session-storage", "rmqtt-message-storage"}

BASE = {
    "image": {"repository": "rmqtt/rmqtt", "tag": "0.24.0", "digest": "sha256:" + "0" * 64},
    "domain": "dev.example.org",
    "authUrl": "http://context-gateway.jc-context-gateway.svc.cluster.local:8082/internal/mqtt/auth",
    "runner": {"namespace": "jc-pipeline-runner", "serviceAccount": "pipeline-runner"},
    "serviceMesh": {"enabled": True},
    "brokers": [
        {"project": "helsinki", "name": "cameras"},
        {"project": "helsinki", "name": "buses", "limits": {"maxMessageBytes": 1024, "messagesPerSecond": 5, "maxConnections": 3}},
        {"project": "praha", "name": "cameras"},
    ],
}


def helm(values: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    if shutil.which("helm") is None:
        pytest.skip("helm not installed")
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    return subprocess.run(
        ["helm", "template", "t", str(CHART), "-n", "jc-mqtt", "-f", str(path)],
        capture_output=True, text=True,
    )


@pytest.fixture(scope="module")
def docs(tmp_path_factory) -> list[dict]:
    result = helm(BASE, tmp_path_factory.mktemp("mqtt"))
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def of(docs, kind):
    """The objects of one kind by name, the template the Portal stamps from left out."""
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == kind and d["metadata"]["name"] != TEMPLATE}


def config(docs, release):
    data = of(docs, "ConfigMap")[release]["data"]
    return {key: tomllib.loads(text) for key, text in data.items()}


RELEASES = ["mqtt-helsinki-cameras", "mqtt-helsinki-buses", "mqtt-praha-cameras"]


def test_each_broker_is_one_release_with_its_own_identity(docs):
    for kind in ("ServiceAccount", "ConfigMap", "Service", "Deployment", "Certificate", "IngressRouteTCP"):
        assert sorted(of(docs, kind)) == sorted(RELEASES), kind
    for release, deployment in of(docs, "Deployment").items():
        assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == release


def test_the_last_acl_rule_denies_everything_and_nothing_is_stored(docs):
    for release in RELEASES:
        files = config(docs, release)
        assert files["rmqtt-acl.toml"]["rules"] == [["deny", "all"]]
        main = files["rmqtt.toml"]
        started = set(main["plugins"]["default_startups"])
        assert started == {"rmqtt-acl", "rmqtt-auth-http"}
        assert not started & STORAGE_PLUGINS
        # Started by the binary unless disabled: an HTTP API with no token.
        assert main["plugins"]["disabled_default_startups"] == ["rmqtt-http-api"]
        assert set(files) == {"rmqtt.toml", "rmqtt-auth-http.toml", "rmqtt-acl.toml"}


def test_only_the_two_plain_listeners_are_open(docs):
    main = config(docs, "mqtt-helsinki-buses")["rmqtt.toml"]
    listeners = main["listener"]
    for kind in ("tls", "ws", "wss", "quic"):
        assert listeners[kind]["external"]["enable"] is False, kind
    tcp = listeners["tcp"]
    assert tcp["internal"]["addr"] == "0.0.0.0:1883" and tcp["internal"]["proxy_protocol"] is False
    assert tcp["external"]["addr"] == "0.0.0.0:1884" and tcp["external"]["proxy_protocol"] is True
    for listener in tcp.values():
        assert listener["allow_anonymous"] is False
        assert listener["max_qos_allowed"] == 1
        assert listener["max_session_expiry_interval"] == "0s"
        assert listener["max_packet_size"] == "1024B"
        assert listener["max_connections"] == 3
    assert main["rpc"]["server_addr"].startswith("127.0.0.1:")
    assert main["log"]["to"] == "console"


def test_every_connect_asks_the_gateway_and_an_error_refuses(docs):
    auth = config(docs, "mqtt-praha-cameras")["rmqtt-auth-http.toml"]
    assert auth["deny_if_error"] is True
    assert auth["disconnect_if_expiry"] is True
    request = auth["http_auth_req"]
    assert request["url"] == BASE["authUrl"]
    assert request["headers"] == {"content-type": "application/json"}
    assert request["params"] == {"clientid": "%c", "username": "%u", "password": "%P", "ipaddr": "%a"}
    # T-5560: every publish topic is decided by the gateway too, and a refusal disconnects.
    acl = auth["http_acl_req"]
    assert acl["url"] == BASE["authUrl"].removesuffix("/auth") + "/acl"
    assert acl["params"] == {"access": "%A", "clientid": "%c", "username": "%u", "topic": "%t"}
    assert auth["disconnect_if_pub_rejected"] is True


def test_hosts_differ_across_projects_and_tls_is_one_host_each(docs):
    hosts = {}
    for release, certificate in of(docs, "Certificate").items():
        assert certificate["spec"]["issuerRef"]["kind"] == "ClusterIssuer"
        (host,) = certificate["spec"]["dnsNames"]
        assert "*" not in host
        hosts[release] = host
    assert hosts == {
        "mqtt-helsinki-cameras": "cameras.helsinki.mqtt.dev.example.org",
        "mqtt-helsinki-buses": "buses.helsinki.mqtt.dev.example.org",
        "mqtt-praha-cameras": "cameras.praha.mqtt.dev.example.org",
    }
    for release, route in of(docs, "IngressRouteTCP").items():
        spec = route["spec"]
        assert spec["entryPoints"] == ["mqtts"]
        (rule,) = spec["routes"]
        assert rule["match"] == f"HostSNI(`{hosts[release]}`)"
        assert rule["services"] == [{"name": release, "port": 1884, "proxyProtocol": {"version": 2}}]
        assert spec["tls"] == {"secretName": f"{release}-tls"}


def test_no_state_on_disk_and_no_token_mounted(docs):
    for deployment in of(docs, "Deployment").values():
        pod = deployment["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert [v["name"] for v in pod["volumes"]] == ["config"]
        assert "configMap" in pod["volumes"][0]
        (container,) = pod["containers"]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert "@sha256:" in container["image"]
    assert not [d for d in docs if d["kind"] == "PersistentVolumeClaim"]


def test_each_listener_admits_one_mesh_identity(docs):
    servers = of(docs, "Server")
    authentications = of(docs, "MeshTLSAuthentication")
    for release in RELEASES:
        for listener, port, identity in (
            ("internal", 1883, {"kind": "ServiceAccount", "name": "pipeline-runner", "namespace": "jc-pipeline-runner"}),
            ("external", 1884, {"kind": "ServiceAccount", "name": "traefik", "namespace": "traefik"}),
        ):
            server = servers[f"{release}-{listener}"]["spec"]
            assert server["port"] == port and server["accessPolicy"] == "deny"
            assert authentications[f"{release}-{listener}"]["spec"]["identityRefs"] == [identity]


def test_the_internal_listener_admits_the_portals_capture_subscriber_when_named(tmp_path):
    """ADR-N-048 §2.10, T-4880: with the Portal named, 1883 admits its identity beside the
    runner's; 1884 still admits Traefik alone."""
    rendered = [d for d in yaml.safe_load_all(helm({**BASE, **PORTAL}, tmp_path).stdout) if d]
    authentications = of(rendered, "MeshTLSAuthentication")
    for release in RELEASES:
        assert authentications[f"{release}-internal"]["spec"]["identityRefs"] == [
            {"kind": "ServiceAccount", "name": "pipeline-runner", "namespace": "jc-pipeline-runner"},
            {"kind": "ServiceAccount", "name": "portal", "namespace": "jc-portal"},
        ]
        assert authentications[f"{release}-external"]["spec"]["identityRefs"] == [
            {"kind": "ServiceAccount", "name": "traefik", "namespace": "traefik"}]


@pytest.mark.parametrize("brokers, message", [
    ([{"project": "helsinki", "name": "cameras"}] * 2, "two brokers answer on cameras.helsinki.mqtt.dev.example.org"),
    ([{"project": "p" * 40, "name": "n" * 30}], "longer than a DNS label"),
])
def test_a_collision_or_an_unbounded_name_refuses_to_render(tmp_path, brokers, message):
    result = helm({**BASE, "brokers": brokers}, tmp_path)
    assert result.returncode != 0
    assert message in result.stderr


def test_no_broker_renders_only_the_template(tmp_path):
    result = helm({**BASE, "brokers": []}, tmp_path)
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    assert [(d["kind"], d["metadata"]["name"]) for d in docs] == [("ConfigMap", TEMPLATE)]


def fill(template: str, release: str, project: str, name: str, limits: dict) -> list[dict]:
    """The template filled as the Portal fills it (src/reconciler/mqtt_brokers.rs), hash aside."""
    for sentinel, value in (
        ("__RELEASE__", release), ("__PROJECT__", project), ("__NAME__", name),
        ("__MAX_BYTES__", limits["maxMessageBytes"]), ("__PER_SECOND__", limits["messagesPerSecond"]),
        ("__CONNECTIONS__", limits["maxConnections"]), ("__CONFIG_HASH__", "h"),
    ):
        template = template.replace(sentinel, str(value))
    return [d for d in yaml.safe_load_all(template) if d]


def comparable(docs: list[dict]) -> list[dict]:
    for d in docs:
        d["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "-"
        if d["kind"] == "Deployment":
            d["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "-"
            d["spec"]["template"]["metadata"]["annotations"]["checksum/config"] = "-"
    return sorted(docs, key=lambda d: (d["kind"], d["metadata"]["name"]))


def test_the_template_filled_is_the_broker_the_chart_renders(docs):
    """T-3994: one description of a broker; what the Portal stamps is what an entry here runs."""
    (template,) = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == TEMPLATE]
    assert template["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "Helm"
    stamped = fill(template["data"]["objects.yaml"], "mqtt-helsinki-buses", "helsinki", "buses", BASE["brokers"][1]["limits"])
    for d in stamped:
        assert d["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "joinedcontext-portal"
        assert d["metadata"]["labels"]["app.kubernetes.io/part-of"] == "mqtt-brokers"
        assert d["metadata"]["labels"]["app.kubernetes.io/instance"] == "mqtt-helsinki-buses"
        assert d["metadata"]["name"].startswith("mqtt-")
    rendered = [d for d in docs if d["metadata"].get("labels", {}).get("app.kubernetes.io/instance") == "mqtt-helsinki-buses"]
    assert comparable(stamped) == comparable(rendered)
    kinds = {(d["apiVersion"], d["kind"]) for d in stamped}
    # The kinds the Portal's client allows a broker (src/apps/kube.rs MQTT_KINDS), and no other.
    assert kinds == {
        ("v1", "ServiceAccount"), ("v1", "ConfigMap"), ("v1", "Service"), ("apps/v1", "Deployment"),
        ("cert-manager.io/v1", "Certificate"), ("traefik.io/v1alpha1", "IngressRouteTCP"),
        ("policy.linkerd.io/v1beta3", "Server"), ("policy.linkerd.io/v1alpha1", "MeshTLSAuthentication"),
        ("policy.linkerd.io/v1alpha1", "AuthorizationPolicy"),
    }


def test_the_portal_gets_its_role_only_when_named(docs, tmp_path):
    assert not [d for d in docs if d["kind"] in ("Role", "RoleBinding")]
    result = helm({**BASE, "portal": {"namespace": "jc-portal", "serviceAccount": "portal"}}, tmp_path)
    assert result.returncode == 0, result.stderr
    rendered = [d for d in yaml.safe_load_all(result.stdout) if d]
    (role,) = [d for d in rendered if d["kind"] == "Role"]
    (binding,) = [d for d in rendered if d["kind"] == "RoleBinding"]
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "portal", "namespace": "jc-portal"}]
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    granted = {(group, resource) for rule in role["rules"] for group in rule["apiGroups"] for resource in rule["resources"]}
    assert granted == {
        ("", "serviceaccounts"), ("", "configmaps"), ("", "services"), ("apps", "deployments"),
        ("cert-manager.io", "certificates"), ("traefik.io", "ingressroutetcps"),
        ("policy.linkerd.io", "servers"), ("policy.linkerd.io", "httproutes"),
        ("policy.linkerd.io", "meshtlsauthentications"), ("policy.linkerd.io", "authorizationpolicies"),
    }
    for rule in role["rules"]:
        assert "*" not in rule["verbs"] and "escalate" not in rule["verbs"] and "bind" not in rule["verbs"]


PORTAL = {"portal": {"namespace": "jc-portal", "serviceAccount": "portal"}}


def test_the_portal_alone_reads_two_routes_of_the_http_api_under_the_mesh(tmp_path):
    """ADR-N-048 §2.8, T-4043: 6060 admits the Portal's identity on two GET routes; the API's
    publish, subscribe and kick routes match nothing, and the API holds no token."""
    result = helm({**BASE, **PORTAL}, tmp_path)
    assert result.returncode == 0, result.stderr
    rendered = [d for d in yaml.safe_load_all(result.stdout) if d]
    for release in RELEASES:
        files = config(rendered, release)
        assert files["rmqtt.toml"]["plugins"]["disabled_default_startups"] == []
        api = files["rmqtt-http-api.toml"]
        assert api["http_laddr"] == "0.0.0.0:6060" and "http_bearer_token" not in api
        server = of(rendered, "Server")[f"{release}-api"]["spec"]
        assert (server["port"], server["proxyProtocol"], server["accessPolicy"]) == (6060, "HTTP/1", "deny")
        route = of(rendered, "HTTPRoute")[f"{release}-api"]["spec"]
        assert route["parentRefs"] == [{"group": "policy.linkerd.io", "kind": "Server", "name": f"{release}-api"}]
        matches = [m for rule in route["rules"] for m in rule["matches"]]
        assert {(m["method"], m["path"]["type"], m["path"]["value"]) for m in matches} == {
            ("GET", "Exact", "/api/v1/metrics/history/sum"), ("GET", "Exact", "/api/v1/clients")}
        assert of(rendered, "MeshTLSAuthentication")[f"{release}-api"]["spec"]["identityRefs"] == [
            {"kind": "ServiceAccount", "name": "portal", "namespace": "jc-portal"}]
        policy = of(rendered, "AuthorizationPolicy")[f"{release}-api"]["spec"]
        assert policy["targetRef"] == {"group": "policy.linkerd.io", "kind": "HTTPRoute", "name": f"{release}-api"}
        ports = {p["port"] for p in of(rendered, "Service")[release]["spec"]["ports"]}
        assert ports == {1883, 1884, 6060}
    # The Portal stamps the same objects from the template.
    template = next(d for d in rendered if d["kind"] == "ConfigMap" and d["metadata"]["name"] == TEMPLATE)
    stamped = [d for d in yaml.safe_load_all(template["data"]["objects.yaml"]) if d]
    assert {d["kind"] for d in stamped if d["metadata"]["name"] == "__RELEASE__-api"} == {
        "Server", "HTTPRoute", "MeshTLSAuthentication", "AuthorizationPolicy"}


@pytest.mark.parametrize("values", [
    {**PORTAL, "serviceMesh": {"enabled": False}},
    {},
], ids=["no mesh", "no portal"])
def test_without_the_mesh_or_the_portal_the_http_api_stays_off(tmp_path, values):
    result = helm({**BASE, **values}, tmp_path)
    assert result.returncode == 0, result.stderr
    rendered = [d for d in yaml.safe_load_all(result.stdout) if d]
    for release in RELEASES:
        files = config(rendered, release)
        assert files["rmqtt.toml"]["plugins"]["disabled_default_startups"] == ["rmqtt-http-api"]
        assert "rmqtt-http-api.toml" not in files
        assert {p["port"] for p in of(rendered, "Service")[release]["spec"]["ports"]} == {1883, 1884}
    assert not [d for d in rendered if d["kind"] == "HTTPRoute"]


# The environment around the brokers.

@pytest.fixture(scope="module")
def local(rendered):
    return rendered("local")


def one(docs, kind, name):
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected exactly one {kind}/{name}, got {len(found)}"
    return found[0]


def env_of(deployment):
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value") for e in container.get("env", [])}


def test_the_gateway_serves_its_internal_listener_on_8082(local):
    gateway = one(local, "Deployment", "context-gateway")
    assert env_of(gateway)["JC_GATEWAY_INTERNAL_BIND"] == "0.0.0.0:8082"
    ports = {p["name"]: p["port"] for p in one(local, "Service", "context-gateway")["spec"]["ports"]}
    assert ports["internal"] == 8082


def test_the_runner_knows_the_brokers_namespace(local):
    runner = one(local, "Deployment", "pipeline-runner")
    namespace = env_of(runner)["JC_MQTT_NAMESPACE"]
    assert namespace
    policy = one(local, "NetworkPolicy", "mqtt-brokers")
    assert policy["metadata"]["namespace"] == namespace


def test_only_brokers_reach_8082_and_only_the_runner_and_traefik_reach_a_broker(local):
    brokers = one(local, "NetworkPolicy", "mqtt-brokers")["spec"]
    by_port = {rule["ports"][0]["port"]: rule["from"] for rule in brokers["ingress"]}
    assert set(by_port) == {1883, 1884, 6060}
    assert by_port[6060][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "portal-portal"}
    egress = one(local, "NetworkPolicy", "portal-to-mqtt-brokers")["spec"]
    assert [p["port"] for rule in egress["egress"] for p in rule["ports"]] == [6060, 1883]
    assert [peer["podSelector"]["matchLabels"] for peer in by_port[1883]] == [
        {"app.kubernetes.io/name": "pipeline-runner-runner"}, {"app.kubernetes.io/name": "portal-portal"}]
    assert by_port[1884][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "traefik"}
    internal = one(local, "NetworkPolicy", "gateway-from-mqtt-brokers")["spec"]
    (rule,) = internal["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8082}]
    assert rule["from"][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "mqtt-broker"}
    # No other policy opens 8082 on the gateway.
    for doc in local:
        if doc.get("kind") != "NetworkPolicy" or doc["metadata"]["name"] == "gateway-from-mqtt-brokers":
            continue
        for rule in doc["spec"].get("ingress") or []:
            assert 8082 not in [p.get("port") for p in rule.get("ports") or []], doc["metadata"]["name"]


def test_the_portal_knows_the_brokers_namespace_and_holds_its_role_there(local):
    portal = one(local, "Deployment", "portal")
    namespace = env_of(portal)["JC_PORTAL_MQTT_NAMESPACE"]
    assert namespace == one(local, "NetworkPolicy", "mqtt-brokers")["metadata"]["namespace"]
    binding = one(local, "RoleBinding", "portal-mqtt-brokers")
    assert binding["metadata"]["namespace"] == namespace
    (subject,) = binding["subjects"]
    assert subject["namespace"] == portal["metadata"]["namespace"]
    assert subject["name"] == portal["spec"]["template"]["spec"]["serviceAccountName"]


def test_the_gateway_admits_the_tokenless_runner_from_its_pods_only(local):
    """T-4004: the gateway resolves the runner's headless Service, which lists every runner pod
    and nothing else; the public listener stays reachable from Traefik alone (the test above)."""
    host = env_of(one(local, "Deployment", "context-gateway"))["JC_GATEWAY_MQTT_RUNNER_HOST"]
    name, namespace = host.split(".")[:2]
    pods = one(local, "Service", name)
    assert pods["metadata"]["namespace"] == namespace
    assert pods["spec"]["clusterIP"] == "None" and pods["spec"]["publishNotReadyAddresses"] is True
    runner = one(local, "Deployment", "pipeline-runner")
    assert pods["spec"]["selector"] == runner["spec"]["selector"]["matchLabels"]
    assert runner["metadata"]["namespace"] == namespace
    # Only the runner asks for one.
    headless = [d["metadata"]["name"] for d in local if d.get("kind") == "Service" and d["spec"].get("clusterIP") == "None"
                and d["metadata"]["name"].startswith("pipeline-runner")]
    assert headless == [name]


def test_the_gateway_admits_the_portals_capture_subscriber_from_its_pods_only(local):
    """ADR-N-048 §2.10, T-4880: the Portal's headless Service lists the Portal's pods alone."""
    host = env_of(one(local, "Deployment", "context-gateway"))["JC_GATEWAY_MQTT_PORTAL_HOST"]
    name, namespace = host.split(".")[:2]
    pods = one(local, "Service", name)
    assert pods["metadata"]["namespace"] == namespace
    assert pods["spec"]["clusterIP"] == "None" and pods["spec"]["publishNotReadyAddresses"] is True
    portal = one(local, "Deployment", "portal")
    assert pods["spec"]["selector"] == portal["spec"]["selector"]["matchLabels"]
    assert portal["metadata"]["namespace"] == namespace


# The gateway's PUBLISH_CACHE_MS (context-gateway src/mqtt.rs): how long the broker keeps an allow.
PUBLISH_CACHE_MS = 10_000


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Decider(BaseHTTPRequestHandler):
    """The gateway's two internal routes as a stub: every CONNECT allowed, a watcher's with a
    subscription to the cameras, a device's with none, and every publish allowed until `deny`
    is set, as when the repository drops the device's role."""

    deny = threading.Event()
    connects: ClassVar[list[str]] = []
    publishes: ClassVar[list[dict]] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        cache = False
        if self.path.endswith("/acl"):
            Decider.publishes.append(body)
            cache = body["access"] == "2" and not Decider.deny.is_set()
            answer = {"result": "allow" if cache else "deny"}
        else:
            Decider.connects.append(body["clientid"])
            watch = [{"permission": "allow", "action": "subscribe", "topic": "cameras/#", "qos": [0, 1]}]
            answer = {"result": "allow", "superuser": False, "expire_at": int(time.time()) + 3600,
                      "acl": watch if body["username"] == "watcher" else []}
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        if cache:
            self.send_header("x-cache", str(PUBLISH_CACHE_MS))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def image() -> str:
    pinned = yaml.safe_load((PROJECT_ROOT / "components/mqtt-brokers/images.yaml").read_text())["mqtt-brokers"]["brokers"]
    return f"{pinned['repository']}@{pinned['digest']}"


@pytest.mark.skipif(shutil.which("docker") is None or shutil.which("mosquitto_pub") is None,
                    reason="no container runtime or no mosquitto clients, so RMQTT cannot run")
def test_a_publish_is_checked_or_the_client_kicked_after_revocation(tmp_path):
    """T-5560: the pinned RMQTT with the rendered configuration asks the decider for each publish
    topic, keeps an allow for PUBLISH_CACHE_MS, and once the decider denies, delivers nothing
    more of the device within 30 s and disconnects it at each refused publish."""
    decider = ThreadingHTTPServer(("127.0.0.1", 0), Decider)
    threading.Thread(target=decider.serve_forever, daemon=True).start()
    Decider.deny.clear()
    Decider.connects.clear()
    Decider.publishes.clear()
    internal, external = free_port(), free_port()
    values = {**BASE, "brokers": [{"project": "helsinki", "name": "cameras"}],
              "authUrl": f"http://127.0.0.1:{decider.server_port}/internal/mqtt/auth"}
    result = helm(values, tmp_path)
    assert result.returncode == 0, result.stderr
    data = of([d for d in yaml.safe_load_all(result.stdout) if d], "ConfigMap")["mqtt-helsinki-cameras"]["data"]
    (tmp_path / "plugins").mkdir()
    (tmp_path / "rmqtt.toml").write_text(
        data["rmqtt.toml"].replace("0.0.0.0:1883", f"127.0.0.1:{internal}")
        .replace("0.0.0.0:1884", f"127.0.0.1:{external}"))
    for name in ("rmqtt-auth-http.toml", "rmqtt-acl.toml"):
        (tmp_path / "plugins" / name).write_text(data[name])
    tmp_path.chmod(0o755)
    name = f"t5560-rmqtt-{internal}"
    started = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--network", "host", "--read-only",
         "-v", f"{tmp_path}:/etc/rmqtt:ro", image(), "-f", "/etc/rmqtt/rmqtt.toml"],
        capture_output=True, text=True, check=False)
    assert started.returncode == 0, started.stderr
    clients: list[subprocess.Popen] = []
    try:
        deadline = time.monotonic() + 60
        while socket.socket().connect_ex(("127.0.0.1", internal)) != 0:
            assert time.monotonic() < deadline, "RMQTT did not listen"
            time.sleep(0.2)
        mqtt = ["-h", "127.0.0.1", "-p", str(internal), "-q", "1"]
        watcher = subprocess.Popen(["mosquitto_sub", *mqtt, "-i", "watcher", "-u", "watcher", "-P", "a-token",
                                    "-t", "cameras/#"], stdout=subprocess.PIPE, text=True)
        clients.append(watcher)
        received: list[float] = []
        threading.Thread(target=lambda: [received.append(time.monotonic()) for _ in watcher.stdout],
                         daemon=True).start()
        time.sleep(1)
        device = subprocess.Popen(["mosquitto_pub", *mqtt, "-i", "helsinki-cam-1", "-u", "helsinki-cam-1",
                                   "-P", "a-token", "-t", "cameras/helsinki-cam-1/frame", "-l"],
                                  stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        clients.append(device)

        def send(seconds: float):
            """A frame every 0.2 s for `seconds`; mosquitto_pub reconnects when it is cut."""
            start = time.monotonic()
            while time.monotonic() - start < seconds:
                try:
                    device.stdin.write("frame\n")
                    device.stdin.flush()
                except BrokenPipeError:
                    return
                time.sleep(0.2)

        send(3)
        assert len(received) >= 10, "the allowed device's frames did not arrive"
        # Some 15 publishes, one question: the broker keeps the allow for PUBLISH_CACHE_MS.
        asked = [(p["access"], p["clientid"], p["topic"]) for p in Decider.publishes]
        assert asked == [("2", "helsinki-cam-1", "cameras/helsinki-cam-1/frame")], asked
        assert Decider.connects.count("helsinki-cam-1") == 1
        revoked = time.monotonic()
        Decider.deny.set()
        send(25)
        last = max(received) - revoked
        assert last < 30, f"the broker delivered the device's frames {last:.1f} s after its role ended"
        assert last <= PUBLISH_CACHE_MS / 1000 + 2, f"{last:.1f} s exceeds the cache time"
        assert Decider.connects.count("helsinki-cam-1") > 1, "the refused device was never disconnected"
    finally:
        for client in clients:
            client.kill()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        decider.shutdown()
