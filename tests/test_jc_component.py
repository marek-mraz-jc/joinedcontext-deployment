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


def jc_container(docs) -> dict:
    (dep,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "jc"]
    (container,) = [c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] in ("jc", "jc-server")]
    return container


def jc_upstreams(docs) -> list[str]:
    """Every APISIX upstream node naming one of jc's Services, in the rendered standalone config."""
    nodes = []
    for d in docs:
        if d.get("kind") in ("Secret", "ConfigMap") and d["metadata"]["name"].startswith("apisix-standalone"):
            text = (d.get("stringData") or d.get("data") or {}).get("apisix.yaml", "")
            nodes += [line.strip() for line in text.splitlines() if "jc.jc-" in line or "jc-pods." in line or ".svc.cluster.local:8080" in line and line.strip().startswith('"jc')]
    return nodes


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_jc_default_values_open_no_import_window(rendered, env):
    # The import window (CLUSTER-IMPORT.md 6) lets an anonymous write in: it must never be the default.
    docs = rendered(env)
    assert jc_toml(docs)["listen"] == "0.0.0.0:8080", f"{env}: jc listens on loopback only outside the window"
    container = jc_container(docs)
    env_vars = {e["name"]: e.get("value") for e in container.get("env", [])}
    assert "ANTARES_POLICY" not in env_vars, f"{env}: ANTARES_POLICY={env_vars.get('ANTARES_POLICY')} overrides jc's joinedcontext policy"
    assert "readinessProbe" in container and "livenessProbe" in container, f"{env}: jc renders without probes"
    services = {d["metadata"]["name"] for d in docs if d.get("kind") == "Service"}
    assert {"jc", "jc-pods"} <= services, f"{env}: jc's Services are missing: {services}"


@requires_helmfile
def test_jc_import_window_routes_nothing_to_jc(rendered_variant):
    def window_on(tree):
        values = tree / "deployment/environments/jc-prod/global.yaml.gotmpl"
        text = values.read_text()
        assert "    mode: host\n" in text, "jc-prod names no host mode"
        values.write_text(text.replace("    mode: host\n", "    mode: host\n    importWindow: true\n", 1))

    docs = rendered_variant("jc-prod", window_on)
    toml = jc_toml(docs)
    assert toml["listen"] == "127.0.0.1:8080", "the window listens beyond the pod's loopback"
    # The kit's slug paths on http://localhost:8080, the Portal's discovery on the same loopback.
    assert (toml["mode"], toml["base_host"], toml["scheme"]) == ("slug", "localhost:8080", "http")
    container = jc_container(docs)
    assert {e["name"]: e.get("value") for e in container.get("env", [])}.get("ANTARES_POLICY") == "allow-all"
    jc_services = [d["metadata"]["name"] for d in docs if d.get("kind") == "Service" and d["metadata"]["name"] in ("jc", "jc-pods")]
    assert not jc_services, f"the window renders Service(s) {jc_services}: their endpoints would reach jc"
    ingresses = [d["metadata"]["name"] for d in docs if d.get("kind") == "Ingress" and "jc" in str(d["spec"].get("rules", [])) and "jc-prod" == d["metadata"].get("namespace") and d["metadata"]["name"].startswith("jc")]
    assert not ingresses, f"the window renders jc Ingress(es) {ingresses}"
    assert not jc_upstreams(docs), f"the window routes the edge to jc: {jc_upstreams(docs)}"
    # Red check of the reader: the default render routes the edge to jc.
    default = rendered_variant("jc-prod", lambda tree: None)
    assert jc_upstreams(default), "the upstream reader finds no jc route in the default render"


@requires_helmfile
def test_jc_prod_carries_the_cutover_parts(rendered):
    # Supervisor 2026-11-10 06:3xZ: prod parity on jc-prod. bbsk. keeps its own certificate, off
    # the copied edge certificate's SAN list; App functions run on jc-prod's realm and gateway; the
    # 24 h temporal rule runs hourly and keeps KPI history and audit rows.
    docs = rendered("jc-prod")
    (cert,) = [d for d in docs if d.get("kind") == "Certificate" and d["metadata"]["name"] == "apisix-edge"]
    assert "bbsk.smartcity.joinedcontext.com" not in cert["spec"]["dnsNames"], "bbsk. on the edge SANs: cert-manager would re-order the copied certificate"
    tls = [t for d in docs if d.get("kind") == "Ingress" for t in d["spec"].get("tls", [])]
    assert {"hosts": ["bbsk.smartcity.joinedcontext.com"], "secretName": "demo-bbsk-tls"} in tls
    (functions,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "jc-functions"]
    env = {e["name"]: e.get("value") for e in functions["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["JC_OIDC_ISSUER"] == "https://idm.smartcity.joinedcontext.com/realms/smartcity"
    assert env["JC_GATEWAY_URL"] == "https://api.smartcity.joinedcontext.com"
    assert {e["name"]: e.get("value") for e in jc_container(docs)["env"]}["JC_FUNCTIONS_URL"].startswith("http://jc-functions.jc-prod.")
    (retain,) = [d for d in docs if d.get("kind") == "CronJob" and d["metadata"]["name"] == "jc-retain"]
    sql = retain["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"][-1]
    assert sql.count("interval '24 hours'") == 2 and sql.count("KeyPerformanceIndicator") == 2
    assert sql.count('\'{"audit": true}\'') == 2, "retain deletes audit rows"


@requires_helmfile
def test_jc_prod_opts_no_pod_out_of_the_mesh_without_a_reason(rendered):
    # Kyverno's justify-linkerd-inject-opt-out refused jc-retain at admission on jc-prod
    # (2026-11-10 07:3xZ): a pod template with linkerd.io/inject disabled needs a reason.
    templates = []
    for d in rendered("jc-prod"):
        spec = d.get("spec") or {}
        if d.get("kind") == "CronJob":
            spec = spec["jobTemplate"]["spec"]
        if d.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            templates.append((d["metadata"]["name"], spec["template"]["metadata"].get("annotations") or {}))
    opted = [(n, a) for n, a in templates if a.get("linkerd.io/inject") == "disabled"]
    assert any(n == "jc-retain" for n, _ in opted), "the reader finds no opted-out pod (jc-retain)"
    assert not [n for n, a in opted if not str(a.get("mesh.joinedcontext.com/opt-out-reason", "")).strip()]


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


@requires_helmfile
@pytest.mark.parametrize("env", jc_environments())
def test_only_the_edge_reaches_jc_public_listener(rendered, env):
    """`trusted_proxies` names the whole pod network (APISIX pods take any address in it), so the
    trust holds only if no pod but APISIX can open a connection to jc's public listener at all."""
    check_only_the_edge_reaches_jc(rendered(env), env)


def check_only_the_edge_reaches_jc(docs, env):
    jc_ns, jc_labels = pod_of(docs, "jc")
    named = named_ports(docs, "jc")
    edge_ns, edge_labels = pod_of(docs, "apisix")
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
