"""jc's edge trust (J-1): which peers may name the caller in X-Forwarded-For.

jc sits behind APISIX, so without `trusted_proxies` every request comes from the edge's pod and
kaisatsu's per-address sign-in lock and daiya's public rate limit become one bucket for everybody.
The list comes from the environment (the edge's pod network) and never widens to everything.
APISIX pods take any address of that network, so the trust holds because jc's NetworkPolicies
let no pod but APISIX reach its public listener (8080) or the Linkerd inbound proxy (4143).
"""

import copy
import ipaddress
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import TREE_IGNORE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENTS = PROJECT_ROOT / ".ci/example-deployments/environments"

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


def jc_environments() -> list[str]:
    """Every example environment whose component list names jc."""
    return sorted(
        p.parent.name
        for p in ENVIRONMENTS.glob("*/global.yaml.gotmpl")
        if any(line.strip() == "- jc" for line in p.read_text().splitlines())
    )


def jc_toml(docs) -> dict:
    (cm,) = [d for d in docs if d.get("kind") == "ConfigMap" and "jc.toml" in (d.get("data") or {})]
    return tomllib.loads(cm["data"]["jc.toml"])


def client_of(proxies: list[str], peer: str, forwarded: str | None) -> str:
    """jc-router's rule (crates/shared/jc-router resolve_client_addr, tested there by
    client_addr_trusts_forwarded_for_only_from_trusted_proxies): an untrusted peer is the client;
    behind a trusted peer, the right-most hop that is not a proxy."""
    nets = [ipaddress.ip_network(n) for n in proxies]
    trusted = lambda ip: any(ipaddress.ip_address(ip) in n for n in nets)
    if not trusted(peer):
        return peer
    hops = [h.strip() for h in (forwarded or "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not trusted(hop):
            return hop
    return hops[0] if hops else peer


def test_jc_renders_in_some_environment():
    assert jc_environments(), "no example environment lists jc: the render tests below check nothing"


def env_values(docs, name: str) -> list[str]:
    """Every value the rendered objects give the variable `name` (container env or ConfigMap data)."""
    out = []
    for d in docs:
        out += [v for k, v in (d.get("data") or {}).items() if k == name]
        spec = ((d.get("spec") or {}).get("template") or {}).get("spec") or {}
        for c in spec.get("containers") or []:
            out += [e.get("value") for e in c.get("env") or [] if e.get("name") == name]
    return out


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_each_private_broker_host_names_its_own_project(rendered, env):
    """jc's ekiben admits a broker's 1883 only to streams of the project an entry names
    (`project=name:port`); an entry without one opens nothing (jc-mqtt-runner-scope)."""
    for value in env_values(rendered(env), "JC_EKIBEN_PRIVATE_HOSTS"):
        for entry in filter(None, value.split(",")):
            project, _, host = entry.partition("=")
            assert project and host.endswith(":1883"), f"{env}: {entry}"
            assert host.startswith(f"mqtt-{project}-"), f"{env}: {entry} is another project's broker"


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_jc_trusts_forwarded_for_only_from_the_edge(rendered, env):
    proxies = jc_toml(rendered(env)).get("trusted_proxies")
    assert proxies, f"{env}: jc.toml has no trusted_proxies, every caller is the edge's address"
    for net in proxies:
        assert ipaddress.ip_network(net).prefixlen > 0, f"{env}: {net} trusts every address"
    # A caller outside the edge's network, the Service network and the node itself name nobody.
    for outsider in ("203.0.113.7", "10.43.0.10", "116.203.134.249"):
        assert client_of(proxies, outsider, "198.51.100.1") == outsider, f"{env}: {outsider} set the client address"
    # The edge's pod forwards the real caller.
    assert client_of(proxies, "10.42.1.7", "198.51.100.1, 10.42.0.1") == "198.51.100.1"


def render_addons_with(tmp_path, proxies_yaml: str) -> subprocess.CompletedProcess:
    if not (PROJECT_ROOT / "deployment/environments/addons").is_dir():
        pytest.skip("run `just _dev-assemble` first")
    tree = tmp_path / "repo"
    shutil.copytree(PROJECT_ROOT, tree, ignore=TREE_IGNORE)
    values = tree / "deployment/environments/addons/jc.yaml.gotmpl"
    text = values.read_text()
    head, sep, _ = text.partition("    trustedProxies:\n")
    assert sep, "addons names no trustedProxies"
    values.write_text(head + proxies_yaml)
    return subprocess.run(
        [str(tree / "scripts/render.sh"), "addons", str(tmp_path / "out.yaml")],
        cwd=str(tree), capture_output=True, text=True, check=False,
    )


@requires_helmfile
@pytest.mark.parametrize(
    "proxies_yaml, refusal",
    [
        ("    trustedProxies: []\n", "name the pod network the edge"),
        ('    trustedProxies:\n      - "0.0.0.0/0"\n', "narrower than /0"),
        ('    trustedProxies:\n      - "::/0"\n', "narrower than /0"),
        ('    trustedProxies:\n      - "10.42.0.7"\n', "narrower than /0"),
    ],
)
def test_jc_refuses_to_render_without_a_narrow_edge_network(tmp_path, proxies_yaml, refusal):
    result = render_addons_with(tmp_path, proxies_yaml)
    assert result.returncode != 0, "rendered with trusted_proxies missing or wide open"
    assert refusal in result.stderr + result.stdout


def selects(selector: dict | None, labels: dict) -> bool:
    """A Kubernetes label selector, matchExpressions included; an operator it cannot read fails
    the test instead of reading as "selects nothing"."""
    selector = selector or {}
    if not all(labels.get(k) == v for k, v in (selector.get("matchLabels") or {}).items()):
        return False
    for expr in selector.get("matchExpressions") or []:
        key, op, values = expr["key"], expr["operator"], expr.get("values") or []
        if op == "In":
            ok = labels.get(key) in values
        elif op == "NotIn":
            ok = labels.get(key) not in values
        elif op == "Exists":
            ok = key in labels
        elif op == "DoesNotExist":
            ok = key not in labels
        else:
            raise AssertionError(f"unread selector operator {op!r} in {selector}")
        if not ok:
            return False
    return True


def opens_public_port(rule: dict, named: dict[str, int], public: set[int] | None = None) -> bool:
    """Whether an ingress rule covers jc's public listener or the Linkerd inbound proxy (or the
    ports in `public`). No ports means every port; a named port resolves through jc's container
    ports, and a name jc's pod does not declare (the injected proxy's, a typo) counts as public."""
    public = PUBLIC_PORTS if public is None else public
    entries = rule.get("ports")
    if not entries:
        return True
    for entry in entries:
        port = entry.get("port")
        if port is None:
            return True
        if isinstance(port, str):
            port = named.get(port)
            if port is None:
                return True
        end = entry.get("endPort", port)
        if any(port <= p <= end for p in public):
            return True
    return False


def workload(docs, name: str) -> dict:
    (dep,) = [d for d in docs if d.get("kind") in ("Deployment", "StatefulSet") and d["metadata"]["name"] == name]
    return dep


def pod_of(docs, name: str) -> tuple[str, dict]:
    dep = workload(docs, name)
    return dep["metadata"]["namespace"], dep["spec"]["template"]["metadata"]["labels"]


def named_ports(docs, name: str) -> dict[str, int]:
    containers = workload(docs, name)["spec"]["template"]["spec"]["containers"]
    return {p["name"]: p["containerPort"] for c in containers for p in c.get("ports") or [] if p.get("name")}


def workloads(docs, namespace: str):
    """(name, pod labels) of every workload rendered into `namespace`."""
    for d in docs:
        if d.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            continue
        if d["metadata"].get("namespace") != namespace:
            continue
        spec = d["spec"].get("jobTemplate", {}).get("spec", d["spec"])
        yield d["metadata"]["name"], (spec.get("template", {}).get("metadata") or {}).get("labels") or {}


def test_the_selector_and_port_readers_fail_closed():
    """The policy test is only as strict as these two readers."""
    labels = {"app.kubernetes.io/name": "jc-server", "tier": "edge"}
    assert selects({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["edge"]}]}, labels)
    assert not selects({"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["edge"]}]}, labels)
    assert selects({"matchExpressions": [{"key": "tier", "operator": "Exists"}]}, labels)
    assert not selects({"matchExpressions": [{"key": "tier", "operator": "DoesNotExist"}]}, labels)
    with pytest.raises(AssertionError, match="unread selector"):
        selects({"matchExpressions": [{"key": "tier", "operator": "Gt", "values": ["1"]}]}, labels)
    named = {"http": 8080, "admin": 9091}
    assert opens_public_port({"ports": [{"port": "http"}]}, named)
    assert not opens_public_port({"ports": [{"port": "admin"}]}, named)
    assert opens_public_port({"ports": [{"port": "linkerd-proxy"}]}, named)
    assert opens_public_port({"ports": [{"protocol": "TCP"}]}, named)
    assert opens_public_port({"ports": [{"port": 8000, "endPort": 8100}]}, named)
    assert opens_public_port({}, named)
    assert not opens_public_port({"ports": [{"port": 4191}]}, named)


# jc's public listener and the Linkerd inbound proxy meshed traffic to it arrives on.
PUBLIC_PORTS = {8080, 4143}


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_only_the_edge_reaches_jc_public_listener(rendered, env):
    """`trusted_proxies` names the whole pod network (APISIX pods take any address in it), so the
    trust holds only if no pod but APISIX can open a connection to jc's public listener at all."""
    check_only_the_edge_reaches_jc(rendered(env), env)


def mesh_admits_only_the_edge(docs, jc_ns: str, jc_labels: dict, named: dict[str, int], edge: tuple[str, str]) -> bool:
    """Whether jc's Linkerd proxy refuses every identity but the edge's on the public listener:
    one Server on 8080 with accessPolicy deny, no HTTPRoute under it, and every AuthorizationPolicy
    on it requiring a MeshTLSAuthentication that names exactly the edge's ServiceAccount. Then a
    peer a NetworkPolicy lets reach the inbound proxy (4143) for another port still cannot open
    8080 through it."""
    edge_ns, edge_sa = edge
    servers = [
        d for d in docs
        if d.get("kind") == "Server" and d["metadata"].get("namespace") == jc_ns
        and selects(d["spec"].get("podSelector"), jc_labels)
        and named.get(d["spec"].get("port"), d["spec"].get("port")) == 8080
    ]
    if len(servers) != 1 or servers[0]["spec"].get("accessPolicy") != "deny":
        return False
    server = servers[0]["metadata"]["name"]
    in_ns = lambda kind: [d for d in docs if d.get("kind") == kind and d["metadata"].get("namespace") == jc_ns]
    if any(any(ref.get("name") == server for ref in d["spec"].get("parentRefs") or []) for d in in_ns("HTTPRoute")):
        return False
    authentications = {d["metadata"]["name"]: d["spec"] for d in in_ns("MeshTLSAuthentication")}
    policies = [d for d in in_ns("AuthorizationPolicy") if d["spec"]["targetRef"].get("name") == server]
    if not policies:
        return False
    for policy in policies:
        refs = policy["spec"].get("requiredAuthenticationRefs") or []
        if not refs:
            return False
        for ref in refs:
            if ref.get("kind") != "MeshTLSAuthentication":
                return False
            identities = (authentications.get(ref.get("name")) or {}).get("identityRefs")
            if identities != [{"kind": "ServiceAccount", "name": edge_sa, "namespace": edge_ns}]:
                return False
    return True


def check_only_the_edge_reaches_jc(docs, env):
    jc_ns, jc_labels = pod_of(docs, "jc")
    named = named_ports(docs, "jc")
    edge_ns, edge_labels = pod_of(docs, "apisix")
    edge_sa = workload(docs, "apisix")["spec"]["template"]["spec"].get("serviceAccountName", "default")
    # With the proxy itself holding 8080 for the edge, a rule opening 4143 (the MQTT brokers' way to
    # jc's internal port) opens nothing of the public listener; 8080 itself stays the edge's alone.
    public = {8080} if mesh_admits_only_the_edge(docs, jc_ns, jc_labels, named, (edge_ns, edge_sa)) else PUBLIC_PORTS
    namespaces = {d["metadata"]["name"]: d["metadata"].get("labels") or {} for d in docs if d.get("kind") == "Namespace"}
    namespaces.setdefault(edge_ns, {}).setdefault("kubernetes.io/metadata.name", edge_ns)
    policies = [
        d for d in docs
        if d.get("kind") == "NetworkPolicy"
        and d["metadata"].get("namespace") == jc_ns
        and selects(d["spec"].get("podSelector"), jc_labels)
    ]
    ingress = [p for p in policies if "Ingress" in (p["spec"].get("policyTypes") or ["Ingress"])]
    assert ingress, f"{env}: no NetworkPolicy isolates jc's ingress, every pod reaches it"
    opened = 0
    for policy in ingress:
        for rule in policy["spec"].get("ingress") or []:
            if not opens_public_port(rule, named, public):
                continue
            ports = [p.get("port") for p in rule.get("ports") or []]
            name = policy["metadata"]["name"]
            peers = rule.get("from")
            assert peers, f"{env}: {name} opens {ports or 'every port'} to every source"
            for peer in peers:
                assert "ipBlock" not in peer, f"{env}: {name} opens jc to an address block"
                assert "podSelector" in peer, f"{env}: {name} opens jc to whole namespaces"
                ns_sel = peer.get("namespaceSelector")
                peer_ns = [n for n, labels in namespaces.items() if selects(ns_sel, labels)] if ns_sel is not None else [jc_ns]
                assert peer_ns == [edge_ns], f"{env}: {name} admits namespaces {peer_ns}"
                assert peer["podSelector"].get("matchLabels"), f"{env}: {name} admits every pod of {edge_ns}"
                assert selects(peer["podSelector"], edge_labels), f"{env}: {name} admits pods that are not APISIX"
                others = [w for w, labels in workloads(docs, edge_ns) if w != "apisix" and selects(peer["podSelector"], labels)]
                assert not others, f"{env}: {name} also admits {others}, which carry APISIX's labels"
                opened += 1
    assert opened, f"{env}: not even APISIX reaches jc"


def planted(namespace: str, pod_selector: dict, ports: list | None) -> dict:
    rule = {"from": [{"podSelector": {}}]}
    if ports is not None:
        rule["ports"] = ports
    return {
        "kind": "NetworkPolicy",
        "metadata": {"name": "planted", "namespace": namespace},
        "spec": {"podSelector": pod_selector, "policyTypes": ["Ingress"], "ingress": [rule]},
    }


@requires_helmfile
@pytest.mark.parametrize(
    "pod_selector, ports",
    [
        ({"matchExpressions": [{"key": "app.kubernetes.io/name", "operator": "In", "values": ["jc-server"]}]},
         [{"protocol": "TCP", "port": 8080}]),
        ({"matchLabels": {"app.kubernetes.io/name": "jc-server"}}, [{"protocol": "TCP", "port": "http"}]),
        ({"matchLabels": {"app.kubernetes.io/name": "jc-server"}}, [{"protocol": "TCP", "port": "linkerd-proxy"}]),
        ({"matchLabels": {"app.kubernetes.io/name": "jc-server"}}, [{"protocol": "TCP", "port": 4100, "endPort": 4200}]),
        ({}, None),
    ],
    ids=["by-expression", "named-http", "named-unknown", "port-range", "every-pod-every-port"],
)
def test_a_policy_opening_jc_to_every_pod_is_caught(rendered, pod_selector, ports):
    """Each way a NetworkPolicy can select jc or name its port reaches the check: none reads as
    "does not apply" (both used to, for matchExpressions and named ports)."""
    docs = rendered(jc_environments()[0])
    jc_ns, _ = pod_of(docs, "jc")
    with pytest.raises(AssertionError, match="admits every pod"):
        check_only_the_edge_reaches_jc([*docs, planted(jc_ns, pod_selector, ports)], "planted")


@requires_helmfile
def test_beside_the_mqtt_brokers_the_proxy_holds_the_public_listener_for_the_edge(rendered):
    """jc-prod opens jc's inbound proxy (4143) to the MQTT broker pods for the CONNECT check on
    8082. That keeps the edge's X-Forwarded-For trust only while jc's Linkerd Server on 8080 admits
    APISIX's identity alone: without that Server, with a second identity in it or with a policy
    that requires none, the check fails; 8080 opened to every pod still fails with it."""
    docs = rendered("jc-prod")
    jc_ns, _ = pod_of(docs, "jc")
    check_only_the_edge_reaches_jc(docs, "jc-prod")
    (server,) = [d for d in docs if d.get("kind") == "Server" and d["metadata"].get("namespace") == jc_ns and d["spec"]["port"] == 8080]
    name = server["metadata"]["name"]

    without = [d for d in docs if d is not server]
    with pytest.raises(AssertionError, match="admits namespaces"):
        check_only_the_edge_reaches_jc(without, "no-server")

    def edited(kind: str, change) -> list[dict]:
        out = []
        for d in docs:
            if d.get("kind") == kind and d["metadata"].get("namespace") == jc_ns and name in d["metadata"]["name"]:
                d = copy.deepcopy(d)
                change(d["spec"])
            out.append(d)
        return out

    wider = edited("MeshTLSAuthentication", lambda s: s["identityRefs"].append({"kind": "Namespace", "name": "jc-prod-mqtt"}))
    with pytest.raises(AssertionError, match="admits namespaces"):
        check_only_the_edge_reaches_jc(wider, "second-identity")
    open_policy = edited("AuthorizationPolicy", lambda s: s.update(requiredAuthenticationRefs=[]))
    with pytest.raises(AssertionError, match="admits namespaces"):
        check_only_the_edge_reaches_jc(open_policy, "no-authentication")
    allowed = edited("Server", lambda s: s.update(accessPolicy="all-authenticated"))
    with pytest.raises(AssertionError, match="admits namespaces"):
        check_only_the_edge_reaches_jc(allowed, "server-allows")

    for ports in ([{"protocol": "TCP", "port": 8080}], [{"protocol": "TCP", "port": "http"}], None):
        with pytest.raises(AssertionError, match="admits every pod"):
            check_only_the_edge_reaches_jc([*docs, planted(jc_ns, {"matchLabels": {"app.kubernetes.io/name": "jc-server"}}, ports)], "planted")
