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
    # The image's own JCBIN_LISTEN (0.0.0.0:8080) beats jc.toml unless the pod names it.
    assert {e["name"]: e.get("value") for e in container.get("env", [])}.get("JCBIN_LISTEN") == "127.0.0.1:8080"
    jc_services = [d["metadata"]["name"] for d in docs if d.get("kind") == "Service" and d["metadata"]["name"] in ("jc", "jc-pods")]
    assert not jc_services, f"the window renders Service(s) {jc_services}: their endpoints would reach jc"
    ingresses = [d["metadata"]["name"] for d in docs if d.get("kind") == "Ingress" and "jc" in str(d["spec"].get("rules", [])) and "jc-prod" == d["metadata"].get("namespace") and d["metadata"]["name"].startswith("jc")]
    assert not ingresses, f"the window renders jc Ingress(es) {ingresses}"
    assert not jc_upstreams(docs), f"the window routes the edge to jc: {jc_upstreams(docs)}"
    # No App runtime path in the window: no API token, no kube-api egress, no apps-db or store login.
    (deployment,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "jc"]
    assert deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert not [d for d in docs if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "jc-server-kube-api"]
    names = {e["name"] for e in container.get("env", [])}
    assert not names & {"APPS_DB_PASSWORD", "JC_PORTAL_APPS_DB_URL", "JC_PORTAL_ARTIFACT_STORE_ACCESS_KEY", "JC_PORTAL_ARTIFACT_STORE_SECRET_KEY"}
    # Red check of the reader: the default render routes the edge to jc.
    default = rendered_variant("jc-prod", lambda tree: None)
    assert jc_upstreams(default), "the upstream reader finds no jc route in the default render"
    (default_jc,) = [d for d in default if d.get("kind") == "Deployment" and d["metadata"]["name"] == "jc"]
    assert default_jc["spec"]["template"]["spec"]["automountServiceAccountToken"] is True, "jc-prod's default render holds no App runtime token"


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
    # tmpfs keeps each file in a 4 KiB page: prod's realm names 903 client secrets plus the
    # pipeline clients, which overflowed a 2Mi realm-secrets volume (seed-realm, 2026-11-10).
    (jc,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "jc"]
    (vol,) = [v for v in jc["spec"]["template"]["spec"]["volumes"] if v["name"] == "realm-secrets"]
    assert vol["emptyDir"]["sizeLimit"] == "8Mi"
    # The gateway's checkouts (70 MB in prod's rehearsal) live in the state tmpfs; 1Mi gave ENOSPC.
    (state,) = [v for v in jc["spec"]["template"]["spec"]["volumes"] if v["name"] == "state"]
    assert state["emptyDir"] == {"medium": "Memory", "sizeLimit": "192Mi"}
    assert not [m for m in jc_container(docs)["volumeMounts"] if m["mountPath"].startswith("/var/lib/jc/state/")]
    env = {e["name"]: e.get("value") for e in jc["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert (env["JCBIN_LISTEN"], env["JCBIN_STATE_DIR"]) == ("0.0.0.0:8080", "/var/lib/jc/state")
    # Antares' in-process bus: one jc process per database, so no rollout overlaps two.
    assert (env["ANTARES_BUS"], env["ANTARES_ALLOW_SHARED_LOCAL"]) == ("local", "1")
    # The import's shako calls were refused (401) while jc held a per-boot token: jc reads jc-setup's.
    assert env["JCBIN_SHAKO_TOKEN_FILE"] == "/run/jc/setup/shako-token"
    # The edge blocks /git: the Portal reaches its forge on jc's loopback, the public base stays.
    assert [m["host"] for m in jc_toml(docs)["mounts"]["shako"]] == ["smartcity.joinedcontext.com", "localhost:8080"]
    assert (env["JC_SHAKO_URL"], env["JC_SHAKO_OWNER"], env["JC_SHAKO_REPO"]) == ("http://localhost:8080/git", "joinedcontext", "configuration")
    mounts = jc_toml(docs)["mounts"]
    assert [m["host"] for m in mounts["ekiben"] + mounts["antares"]] == ["localhost:8080", "localhost:8080"]
    assert (env["JC_PORTAL_PIPELINE_RUNNER_URL"], env["JC_PORTAL_BROKER_URL"]) == ("http://localhost:8080/streams", "http://localhost:8080/broker")
    # Host mode routes by name: the kubelet's probes name the hosts jc answers them on.
    probes = jc["spec"]["template"]["spec"]["containers"][0]
    assert probes["readinessProbe"]["httpGet"]["httpHeaders"] == [{"name": "Host", "value": "portal.smartcity.joinedcontext.com"}]
    assert probes["livenessProbe"]["httpGet"]["httpHeaders"] == [{"name": "Host", "value": "localhost:8080"}]
    # Each harvest reads its Endpoints on this instance's gateway and links under its catalogue.
    for h in jc_toml(docs)["dataroom"]["harvest"]:
        assert "api.smartcity.joinedcontext.com" in h["allowed_hosts"]
        assert h.get("datasets_base", "https://opendata.smartcity.joinedcontext.com/") == "https://opendata.smartcity.joinedcontext.com/"
    assert jc["spec"]["strategy"]["type"] == "Recreate" and jc["spec"]["replicas"] == 1


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
    "does not apply" (both used to, for matchExpressions and named ports). Planted where no
    Linkerd Server holds 8080 for the edge (jc-dev: no MQTT brokers, no App pods), so the inbound
    proxy port (4143, inside the port range) still reaches the public listener."""
    docs = rendered("jc-dev")
    jc_ns, jc_labels = pod_of(docs, "jc")
    edge_ns, _ = pod_of(docs, "apisix")
    edge_sa = workload(docs, "apisix")["spec"]["template"]["spec"].get("serviceAccountName", "default")
    assert not mesh_admits_only_the_edge(docs, jc_ns, jc_labels, named_ports(docs, "jc"), (edge_ns, edge_sa))
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
    (server,) = [d for d in docs if d.get("kind") == "Server" and d["metadata"].get("namespace") == jc_ns and d["spec"]["port"] == 8080
                 and d["spec"]["podSelector"].get("matchLabels", {}).get("app.kubernetes.io/name") == "jc-server"]
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
