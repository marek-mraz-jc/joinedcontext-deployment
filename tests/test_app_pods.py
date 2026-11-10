"""The ui-rust App pods jc's Portal proxies on their App hosts (components/app-pods).

Prod's reconciler ran hsl-transport as Deployment and Service `app-hsl-transport`; jc runs the same
pod from the image the monorepo's image-apps.yml signs. The pod is reached by jc alone and reaches
jc alone (both halves of each NetworkPolicy, Linkerd's proxy port beside the app port), and jc
mounts the gateway's /api/endpoint on its own Service host for it, as prod's pod read the gateway's
Service.
"""

import json
import re

import pytest

from conftest import load_yaml

PIN = """
---
images:
  app-pods:
    hsl-transport:
      repository: 'ghcr.io/marek-mraz-jc/jc-app-hsl-transport'
      tag: 'main'
      digest: 'sha256:0000000000000000000000000000000000000000000000000000000000000000'
"""


def of_kind(docs, kind, name=None):
    return [d for d in docs if d.get("kind") == kind and name in (None, d["metadata"]["name"])]


def with_app_pods(tree):
    """jc-prod with app-pods listed after jc and an example pin."""
    path = tree / "deployment/environments/jc-prod/global.yaml.gotmpl"
    text = path.read_text()
    assert "\n  - jc\n" in text
    path.write_text(text.replace("\n  - jc\n", "\n  - jc\n  - app-pods\n", 1))
    (path.parent / "app-pods.yaml.gotmpl").write_text(PIN)


RENDERED: list[list[dict]] = []


@pytest.fixture
def prod(rendered_variant):
    """jc-prod with app-pods, rendered once for the module (the fixture copies the tree)."""
    if not RENDERED:
        RENDERED.append(rendered_variant("jc-prod", with_app_pods))
    return RENDERED[0]


def policies(docs):
    """Every NetworkPolicy of the render by name."""
    return {p["metadata"]["name"]: p for p in of_kind(docs, "NetworkPolicy")}


def admits(policy, direction, labels, port):
    peer_key = "from" if direction == "ingress" else "to"
    for rule in policy["spec"].get(direction, []):
        ports = {p.get("port") for p in rule.get("ports", [])}
        for peer in rule.get(peer_key, []):
            match = (peer.get("podSelector") or {}).get("matchLabels", {})
            if match and all(labels.get(k) == v for k, v in match.items()) and port in ports:
                return True
    return False


JC = {"app.kubernetes.io/name": "jc-server", "app.kubernetes.io/instance": "jc-server"}
POD = {"app.kubernetes.io/name": "app-hsl-transport", "app.kubernetes.io/instance": "app-pods-hsl-transport"}


def test_the_pod_runs_as_prod_ran_it_pinned_nonroot_and_limited(prod):
    (deployment,) = of_kind(prod, "Deployment", "app-hsl-transport")
    assert deployment["metadata"]["namespace"] == "jc-prod"
    spec = deployment["spec"]["template"]["spec"]
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["runAsUser"] == 65532
    assert spec["automountServiceAccountToken"] is False
    (container,) = spec["containers"]
    assert re.fullmatch(r"ghcr\.io/marek-mraz-jc/jc-app-hsl-transport:main@sha256:[0-9a-f]{64}", container["image"])
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["limits"]["memory"] and container["resources"]["limits"]["cpu"]
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["JC_ENDPOINT_URL"] == (
        "http://jc.jc-prod.svc.cluster.local:8080/api/endpoint/sv4ibpmhwowb6gnzqy6vp2b3iy/"
    )
    assert env["JC_BASE_PATH"] == "/"
    config = json.loads(env["JC_APP_CONFIG"])
    assert config["portal"] == "https://portal.smartcity.joinedcontext.com/projects/helsinki"
    assert config["slug"] == "sv4ibpmhwowb6gnzqy6vp2b3iy"
    (service,) = of_kind(prod, "Service", "app-hsl-transport")
    assert [p["port"] for p in service["spec"]["ports"]] == [8080]


def test_jc_proxies_the_app_host_and_mounts_the_endpoint_on_its_service(prod):
    (jc,) = of_kind(prod, "Deployment", "jc")
    env = {e["name"]: e.get("value") for c in jc["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
    assert env["JC_PORTAL_APP_PODS"] == (
        "hsl-transport=http://app-hsl-transport.jc-prod.svc.cluster.local:8080"
    )
    toml = next(c["data"]["jc.toml"] for c in of_kind(prod, "ConfigMap") if "jc.toml" in (c.get("data") or {}))
    gateway = re.findall(r'\[\[mounts\.gateway\]\]\s*\nhost = "([^"]+)"\s*\npath_prefix = "([^"]*)"', toml)
    assert ("jc.jc-prod.svc.cluster.local", "/api/endpoint") in gateway, gateway
    # Only the endpoint path on that host: no MCP, no catalogue, no Portal.
    assert [g for g in gateway if g[0].endswith(".svc.cluster.local")] == [
        ("jc.jc-prod.svc.cluster.local", "/api/endpoint")
    ]


def test_without_app_pods_jc_neither_proxies_nor_mounts_the_service_host(rendered):
    docs = rendered("jc-prod")
    assert not of_kind(docs, "Deployment", "app-hsl-transport")
    (jc,) = of_kind(docs, "Deployment", "jc")
    env = {e["name"] for c in jc["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
    assert "JC_PORTAL_APP_PODS" not in env
    toml = next(c["data"]["jc.toml"] for c in of_kind(docs, "ConfigMap") if "jc.toml" in (c.get("data") or {}))
    assert ".svc.cluster.local" not in toml


def test_jc_and_the_pod_reach_each_other_alone_both_halves_both_ports(prod):
    found = policies(prod)
    by_target = {}
    for policy in found.values():
        selector = policy["spec"]["podSelector"].get("matchLabels", {})
        by_target.setdefault(selector.get("app.kubernetes.io/name"), []).append(policy)

    def any_admits(target, direction, peer, port):
        return any(admits(p, direction, peer, port) for p in by_target.get(target, []))

    for port in (8080, 4143):
        # jc -> pod: jc's egress, the pod's ingress
        assert any_admits("jc-server", "egress", POD, port), port
        assert any_admits("app-hsl-transport", "ingress", JC, port), port
        # pod -> jc (the gateway): the pod's egress, jc's ingress
        assert any_admits("app-hsl-transport", "egress", JC, port), port
        assert any_admits("jc-server", "ingress", POD, port), port
    # The pod takes nothing from the edge or any other pod, and calls nothing but jc and DNS.
    for policy in by_target["app-hsl-transport"]:
        for rule in policy["spec"].get("ingress", []):
            for peer in rule.get("from", []):
                assert (peer.get("podSelector") or {}).get("matchLabels") == JC, policy["metadata"]["name"]
        for rule in policy["spec"].get("egress", []):
            for peer in rule.get("to", []):
                labels = (peer.get("podSelector") or {}).get("matchLabels")
                namespace = (peer.get("namespaceSelector") or {}).get("matchLabels", {})
                assert labels == JC or labels == {"k8s-app": "kube-dns"} or (
                    labels is None and namespace == {"kubernetes.io/metadata.name": "linkerd"}
                ), policy["metadata"]["name"]
                assert "ipBlock" not in peer, policy["metadata"]["name"]


def test_the_pods_mesh_server_admits_jc_alone(prod):
    authentications = [a for a in of_kind(prod, "MeshTLSAuthentication") if a["metadata"]["namespace"] == "jc-prod"]
    assert authentications
    for authentication in authentications:
        identities = authentication["spec"].get("identityRefs") or authentication["spec"].get("identities")
        assert identities, authentication
        assert all("jc" == (i.get("name") if isinstance(i, dict) else i.split(".")[0]) for i in identities), identities
