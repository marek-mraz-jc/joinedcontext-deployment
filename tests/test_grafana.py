"""The dashboards add-on: what the render has to prove before anyone applies it (T-0039).

An add-on is opt-in per environment, so this one is rendered in `addons` — the environment
that exists to render add-ons — and what is asserted here is everything that is decidable
without a cluster: that the component refuses to run without a Prometheus, that the dashboards
reach the pod, that the login is the realm's, and that the edge may actually reach it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = PROJECT_ROOT / "components/grafana"
# What a render needs, copied into a temporary tree the way test_networkpolicies does, so a
# test that changes an environment value changes nobody else's render.
TREE = ("components", "defaults", ".ci", "scripts", "helmfile-root.yaml.gotmpl",
        "helmfile-components.yaml.gotmpl")

requires_helmfile = pytest.mark.skipif(
    shutil.which("helmfile") is None, reason="helmfile not installed"
)


@pytest.fixture(scope="module")
def addons(rendered):
    return rendered("addons")


def by_name(docs, kind, name):
    match = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert match, f"{kind}/{name} is not in the render"
    return match[0]


def container(docs):
    return by_name(docs, "Deployment", "grafana")["spec"]["template"]["spec"]["containers"][0]


def test_the_workload_the_route_names_is_the_workload_that_renders(addons):
    """docs Deployment/10 section 2 publishes `grafana:3000`, and one number has to hold from
    the container port to the Service to the route's upstream: the edge answers 502 for a
    Service that listens somewhere else, with the pod healthy."""
    service = by_name(addons, "Service", "grafana")["spec"]
    # The target is the container port by name, so the two are checked against each other
    # rather than against a number written twice.
    assert [p["port"] for p in service["ports"]] == [3000]
    target = service["ports"][0]["targetPort"]
    named = {p["name"]: p["containerPort"] for p in container(addons)["ports"]}
    assert named[target] == 3000, named

    config = yaml.safe_load(
        by_name(addons, "ConfigMap", "apisix-standalone-base")["data"]["apisix.yaml"]
    )
    route = next(r for r in config["routes"] if r["id"] == "grafana")
    assert route["uri"] == "/grafana*"
    upstream = next(u for u in config["upstreams"] if u["id"] == "grafana")
    assert list(upstream["nodes"]) == ["grafana.addons.svc.cluster.local:3000"]


def test_the_edge_is_allowed_to_reach_it(addons):
    """APISIX runs under a default-deny egress and its own component names only the upstreams
    every installation has. An add-on brings its own line, or the route resolves and the
    connection is dropped on the way out: 504 at the edge with the pod 1/1 (T-0419)."""
    policy = by_name(addons, "NetworkPolicy", "apisix-egress-to-grafana")["spec"]
    peers = [
        (peer["podSelector"]["matchLabels"], port["port"])
        for rule in policy["egress"]
        for peer in rule["to"]
        for port in rule["ports"]
    ]
    assert any(
        labels.get("app.kubernetes.io/name") == "grafana" and port == 3000
        for labels, port in peers
    ), peers

    meshed = by_name(addons, "NetworkPolicy", "apisix-linkerd-egress-to-grafana")["spec"]
    assert any(
        port["port"] == 4143 for rule in meshed["egress"] for port in rule["ports"]
    ), "the outbound proxy connects to the peer's inbound proxy, not to the service port"


def test_it_talks_to_prometheus_and_the_realm_and_to_nothing_else(addons):
    """A dashboard viewer reads one Prometheus and logs people in. Anything else it could
    reach is blast radius after a break-in (OPS-38)."""
    egress = by_name(addons, "NetworkPolicy", "grafana")["spec"]["egress"]
    reached = {
        (
            peer.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/name")
            or peer.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/instance")
            or peer.get("podSelector", {}).get("matchLabels", {}).get("k8s-app"),
            port["port"],
        )
        for rule in egress
        for peer in rule["to"]
        for port in rule["ports"]
    }
    assert reached == {
        ("kube-dns", 53),
        ("prometheus", 9090),
        ("keycloak-app", 8080),
    }, reached


def test_the_dashboards_are_committed_json_and_reach_the_pod(addons):
    """Four dashboards, provisioned from files rather than fetched at start-up: the egress
    policy above allows no outbound call that could fetch one, which is the point."""
    dashboards = by_name(addons, "ConfigMap", "grafana-dashboards")["data"]
    assert sorted(dashboards) == [
        "context-broker.json",
        "context-gateway.json",
        "edge-apisix.json",
        "portal.json",
    ]
    for name, raw in dashboards.items():
        parsed = json.loads(raw)
        assert parsed["panels"], f"{name} renders no panel"
        assert parsed["editable"] is False, f"{name} may be edited in the UI"

    pod = by_name(addons, "Deployment", "grafana")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "dashboards-platform")
    assert volume["configMap"]["name"] == "grafana-dashboards"
    mounts = {m["mountPath"] for m in container(addons)["volumeMounts"]}
    provider = yaml.safe_load(
        by_name(addons, "ConfigMap", "grafana")["data"]["dashboardproviders.yaml"]
    )
    path = provider["providers"][0]["options"]["path"]
    assert path in mounts, f"the provider reads {path} and nothing is mounted there"


def test_no_dashboard_queries_a_metric_no_component_exports():
    """A panel is a claim that somebody exports that series. These four prefixes are the ones
    this platform actually has: APISIX's own, Antares's own, and — since T-0463 — the Context
    Gateway's and the Portal's."""
    allowed = ("apisix_", "antares_", "jc_gateway_", "jc_portal_")
    for path in sorted((COMPONENT / "charts/dashboards/files").glob("*.json")):
        for panel in json.loads(path.read_text())["panels"]:
            for target in panel["targets"]:
                expression = target["expr"]
                assert any(
                    prefix in expression for prefix in allowed
                ), f"{path.name}: {expression} queries no series this platform exports"


# What each exporter publishes, from `telemetry.rs` in the platform and the Portal. A panel
# that reads a duration must read it as buckets: both exporters render histograms, and a
# `histogram_quantile` over `_bucket` is the only form that survives the HPA adding a replica.
GATEWAY_SERIES = (
    "jc_gateway_requests_total",
    "jc_gateway_request_duration_seconds_bucket",
    "jc_gateway_pdp_decisions_total",
    "jc_gateway_broker_request_duration_seconds_bucket",
)
PORTAL_SERIES = (
    "jc_portal_requests_total",
    "jc_portal_request_duration_seconds_bucket",
    "jc_portal_changes_total",
)


def expressions(name):
    path = COMPONENT / "charts/dashboards/files" / name
    return [t["expr"] for panel in json.loads(path.read_text())["panels"] for t in panel["targets"]]


def test_the_gateway_dashboard_draws_what_only_the_gateway_can_see():
    """A policy decision and a broker round trip are the two the edge can never answer: a
    request allowed by a policy and one allowed because nothing looked are the same 200 at
    APISIX (T-0464, OPS-16)."""
    drawn = expressions("context-gateway.json")
    for series in GATEWAY_SERIES:
        assert any(series in expression for expression in drawn), f"{series} is not drawn"
    # And the edge panels stay, because only APISIX sees a request the gateway never received.
    assert any("apisix_" in expression for expression in drawn)


def test_the_portal_dashboard_draws_proposals_by_lane():
    """The lane is the Portal's own classification — green applied, amber and red waiting for
    a person — and nothing outside the process knows which one a change landed in (CC-63)."""
    drawn = expressions("portal.json")
    for series in PORTAL_SERIES:
        assert any(series in expression for expression in drawn), f"{series} is not drawn"
    assert any(
        "jc_portal_changes_total" in expression and "by (lane)" in expression
        for expression in drawn
    ), drawn


def test_no_duration_is_read_as_a_summary_quantile():
    """`quantile="0.95"` on a duration is a per-replica number that cannot be combined with
    another replica's, so a panel written that way silently draws one pod (T-0464)."""
    for path in sorted((COMPONENT / "charts/dashboards/files").glob("*.json")):
        for expression in expressions(path.name):
            assert "quantile=" not in expression, f"{path.name}: {expression}"


def test_nothing_is_authored_in_the_ui(addons):
    """Everything provisioned is read-only, and the login form is off: a datasource or a
    dashboard changed in the UI is configuration that exists nowhere in Git (CC-02)."""
    config = by_name(addons, "ConfigMap", "grafana")["data"]
    datasource = yaml.safe_load(config["datasources.yaml"])["datasources"][0]
    assert datasource["editable"] is False
    assert datasource["url"].startswith("http://prometheus-operated.")

    provider = yaml.safe_load(config["dashboardproviders.yaml"])["providers"][0]
    assert provider["editable"] is False and provider["disableDeletion"] is True

    ini = config["grafana.ini"]
    assert "disable_login_form = true" in ini
    assert "allow_sign_up = false" in ini


def test_the_realm_owns_the_login_and_the_secret_is_a_reference(addons):
    """The client secret is generated by the secrets component and reaches the pod as an
    environment variable; nothing that could be a credential is rendered into the config
    (CC-06)."""
    ini = by_name(addons, "ConfigMap", "grafana")["data"]["grafana.ini"]
    assert "client_id = grafana" in ini
    # The browser follows auth_url, the pod makes the other two calls.
    assert "auth_url = https://idm.addons.example.org/" in ini
    assert "token_url = http://keycloak-app-keycloakx-http." in ini
    assert "client_secret" not in ini

    env = {e["name"]: e for e in container(addons)["env"]}
    reference = env["GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
    assert reference == {"name": "keycloak-client-grafana", "key": "client-secret"}
    assert "value" not in env["GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET"]


def test_the_pod_is_pinned_unprivileged_and_needs_no_api_access(addons):
    """The production baseline, asserted here because this component is in no environment the
    baseline suite renders."""
    pod = by_name(addons, "Deployment", "grafana")["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert not pod.get("initContainers"), "an init container is an image to pin for nothing"

    grafana = container(addons)
    assert "@sha256:" in grafana["image"], grafana["image"]
    assert grafana["securityContext"]["readOnlyRootFilesystem"] is True
    assert grafana["securityContext"]["allowPrivilegeEscalation"] is False
    assert grafana["resources"]["requests"] and grafana["resources"]["limits"]
    assert not [d for d in addons if d.get("kind") in ("Role", "ClusterRole")
                and d["metadata"]["name"] == "grafana"]


@requires_helmfile
def test_the_component_refuses_to_render_without_a_prometheus(tmp_path):
    """Enabled and pointed at nothing is the one state that looks healthy and shows nothing,
    so it stops the render instead (the audit collector refuses the same way without a
    bucket)."""
    for entry in TREE:
        source = PROJECT_ROOT / entry
        (shutil.copytree if source.is_dir() else shutil.copy)(source, tmp_path / entry)
    shutil.copytree(tmp_path / "defaults/deployment", tmp_path / "deployment")
    shutil.copy(tmp_path / ".ci/example-deployments/helmfile.yaml", tmp_path / "deployment/helmfile.yaml")
    shutil.copytree(tmp_path / ".ci/example-deployments/environments",
                    tmp_path / "deployment/environments", dirs_exist_ok=True)

    # The root helmfile reads `global.yaml.gotmpl` itself and passes the result down, so that
    # file is where an environment's value lives; a second file beside it is merged with lower
    # precedence and would change nothing.
    environment = tmp_path / "deployment/environments/addons/global.yaml.gotmpl"
    text = environment.read_text()
    assert "prometheusUrl: 'http" in text, "fixture moved"
    environment.write_text(text.replace("prometheusUrl: 'http://prometheus-operated.monitoring.svc.cluster.local:9090'",
                                        "prometheusUrl: ''"))

    result = subprocess.run(
        ["helmfile", "-f", "deployment/helmfile.yaml", "-e", "addons", "template",
         "--skip-deps", "-q", "--selector", "component=grafana"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert result.returncode != 0, "a Grafana with no datasource rendered fine"
    assert "no prometheusUrl is set" in result.stdout + result.stderr
