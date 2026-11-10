"""jc's edge trust (J-1): which peers may name the caller in X-Forwarded-For.

jc sits behind APISIX, so without `trusted_proxies` every request comes from the edge's pod and
kaisatsu's per-address sign-in lock and daiya's public rate limit become one bucket for everybody.
The list comes from the environment (the edge's pod network) and never widens to everything.
APISIX pods take any address of that network, so the trust holds because jc's NetworkPolicies
let no pod but APISIX reach its public listener (8080) or the Linkerd inbound proxy (4143).
"""

import ipaddress
import shutil
import subprocess
import sys
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


def opens_public_port(rule: dict, named: dict[str, int]) -> bool:
    """Whether an ingress rule covers jc's public listener or the Linkerd inbound proxy. No ports
    means every port; a named port resolves through jc's container ports, and a name jc's pod
    does not declare (the injected proxy's, a typo) counts as public."""
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
        if any(port <= p <= end for p in PUBLIC_PORTS):
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

# Peers besides APISIX that may reach jc's public listener because they send no forwarding header
# of their own: (workload name prefix, its pod's app.kubernetes.io/name). A WASM shard calls jc as
# its Apps' gateway and Portal (components/wasm-host shard values). It is tenant code, so it is
# admitted only while the pinned jc-wasm-host forwards nothing but `accept` and `content-type`
# from a component (platform crates/wasm-host/src/host.rs `sent_headers`, jc-wasm-headers
# 2026-11-10; before it the host passed a component's X-Forwarded-*, x-jc-* and l5d-* on, and jc
# trusts X-Forwarded-* from the whole pod network). HEADER_CLEAN_WASM_HOST lists the platform
# image digests built from that fix or later: whoever re-pins components/wasm-host/images.yaml
# adds the new digest here in the same commit, after checking the image's commit carries the fix.
HEADER_CLEAN_PEERS = (("jc-wasm-host-", "wasm-host-shard"),)
HEADER_CLEAN_WASM_HOST: set[str] = set()


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_only_the_edge_reaches_jc_public_listener(rendered, env):
    """`trusted_proxies` names the whole pod network (APISIX pods take any address in it), so the
    trust holds only if no pod but APISIX can open a connection to jc's public listener at all,
    besides the header-clean peers (HEADER_CLEAN_PEERS), which send no forwarding header."""
    check_only_the_edge_reaches_jc(rendered(env), env)


def header_clean_peers(docs, env) -> list[tuple[str, str, dict]]:
    """(name, namespace, pod labels) of each rendered workload HEADER_CLEAN_PEERS admits; each must
    run a header-clean jc-wasm-host image, or the test fails here, not by admitting it."""
    found = []
    for d in docs:
        if d.get("kind") != "Deployment":
            continue
        name = d["metadata"]["name"]
        labels = d["spec"]["template"]["metadata"].get("labels") or {}
        for prefix, app in HEADER_CLEAN_PEERS:
            if name.startswith(prefix) and labels.get("app.kubernetes.io/name") == app:
                images = {c["image"].rsplit("@", 1)[-1] for c in d["spec"]["template"]["spec"]["containers"]}
                stale = images - HEADER_CLEAN_WASM_HOST
                assert not stale, (
                    f"{env}: {name} reaches jc but runs {sorted(stale)}, not a header-clean jc-wasm-host "
                    "(HEADER_CLEAN_WASM_HOST): re-pin components/wasm-host/images.yaml to a build of the fix"
                )
                found.append((name, d["metadata"]["namespace"], labels))
    return found


def check_only_the_edge_reaches_jc(docs, env):
    jc_ns, jc_labels = pod_of(docs, "jc")
    named = named_ports(docs, "jc")
    edge_ns, edge_labels = pod_of(docs, "apisix")
    clean = None
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
            if not opens_public_port(rule, named):
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
                if peer["podSelector"].get("matchLabels") and not selects(peer["podSelector"], edge_labels):
                    clean = header_clean_peers(docs, env) if clean is None else clean
                    admitted = [w for w, ns, labels in clean if [ns] == peer_ns and selects(peer["podSelector"], labels)]
                    assert admitted, f"{env}: {name} admits pods that are neither APISIX nor a header-clean peer"
                    for ns in peer_ns:
                        others = [w for w, labels in workloads(docs, ns) if w not in admitted and selects(peer["podSelector"], labels)]
                        assert not others, f"{env}: {name} also admits {others} beside {admitted}"
                    continue
                assert peer_ns == [edge_ns], f"{env}: {name} admits namespaces {peer_ns}"
                assert peer["podSelector"].get("matchLabels"), f"{env}: {name} admits every pod of {edge_ns}"
                assert selects(peer["podSelector"], edge_labels), f"{env}: {name} admits pods that are not APISIX"
                others = [w for w, labels in workloads(docs, edge_ns) if w != "apisix" and selects(peer["podSelector"], labels)]
                assert not others, f"{env}: {name} also admits {others}, which carry APISIX's labels"
                opened += 1
    assert opened, f"{env}: not even APISIX reaches jc"


@requires_helmfile
def test_a_shard_reaches_jc_only_on_a_header_clean_host(rendered, monkeypatch):
    """The shard rule stands on the pin: the same render fails once the pinned jc-wasm-host is not
    a header-clean build, and passes for a digest named header-clean."""
    env = "jc-prod"
    docs = rendered(env)
    shards = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"].startswith("jc-wasm-host-")
              and d["spec"]["template"]["metadata"]["labels"].get("app.kubernetes.io/name") == "wasm-host-shard"]
    assert shards, f"{env}: no WASM shard rendered"
    pinned = {c["image"].rsplit("@", 1)[-1] for d in shards for c in d["spec"]["template"]["spec"]["containers"]}
    monkeypatch.setattr(sys.modules[__name__], "HEADER_CLEAN_WASM_HOST", set())
    with pytest.raises(AssertionError, match="not a header-clean jc-wasm-host"):
        check_only_the_edge_reaches_jc(docs, env)
    monkeypatch.setattr(sys.modules[__name__], "HEADER_CLEAN_WASM_HOST", pinned)
    check_only_the_edge_reaches_jc(docs, env)


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
