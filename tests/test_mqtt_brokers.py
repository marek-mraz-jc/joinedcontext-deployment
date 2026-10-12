"""T-3993: the MQTT edge brokers (ADR-N-048, MF-54, PL-74, PL-76, PL-77).

The chart is rendered on its own with three brokers, two in one project and one of the same
name in another, because no environment declares a broker: the Portal's reconciler stamps them
(T-3994). The environment render then checks the wiring around them: the gateway's internal
listener, the runner's namespace variable and the NetworkPolicies.
"""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "components/mqtt-brokers/charts/brokers"
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
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == kind}


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
    assert "http_acl_req" not in auth


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


@pytest.mark.parametrize("brokers, message", [
    ([{"project": "helsinki", "name": "cameras"}] * 2, "two brokers answer on cameras.helsinki.mqtt.dev.example.org"),
    ([{"project": "p" * 40, "name": "n" * 30}], "longer than a DNS label"),
])
def test_a_collision_or_an_unbounded_name_refuses_to_render(tmp_path, brokers, message):
    result = helm({**BASE, "brokers": brokers}, tmp_path)
    assert result.returncode != 0
    assert message in result.stderr


def test_no_broker_renders_nothing(tmp_path):
    result = helm({**BASE, "brokers": []}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert [d for d in yaml.safe_load_all(result.stdout) if d] == []


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
    assert set(by_port) == {1883, 1884}
    assert by_port[1883][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "pipeline-runner-runner"}
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
