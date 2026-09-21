"""The context broker (Antares) as dev renders it: what is specific to it (T-1668, R1, CC-04).

The shared suites see it as one more workload (image pins, the NetworkPolicy lint, kubeconform).
These pin what only it guarantees: it runs as nobody with nothing writable but /tmp, answers its
probes, fits the node, is reachable from the gateway and the Portal only, reaches its database and
nothing else, and is addressed by the gateway and the Portal at the port its Service serves."""

import shutil

import pytest

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def one(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


def pod_of(docs):
    return one(docs, "Deployment", "context-broker")["spec"]["template"]["spec"]


def env_of(container):
    return {e["name"]: e for e in container.get("env", [])}


def quantity(text):
    """A Kubernetes memory quantity in bytes (Ki, Mi, Gi)."""
    units = {"Ki": 1 << 10, "Mi": 1 << 20, "Gi": 1 << 30}
    for suffix, factor in units.items():
        if text.endswith(suffix):
            return int(text[: -len(suffix)]) * factor
    return int(text)


@requires_helmfile
def test_the_broker_image_is_pinned_by_digest(dev):
    (container,) = pod_of(dev)["containers"]
    image = container["image"]
    assert "@sha256:" in image and len(image.split("@sha256:")[1]) == 64, image


@requires_helmfile
def test_the_broker_runs_as_nobody_with_a_read_only_root_and_no_token(dev):
    pod = pod_of(dev)
    (container,) = pod["containers"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] != 0
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert pod["automountServiceAccountToken"] is False
    context = container["securityContext"]
    assert context["readOnlyRootFilesystem"] is True
    assert context["allowPrivilegeEscalation"] is False
    assert context["capabilities"]["drop"] == ["ALL"]
    assert [m["mountPath"] for m in container.get("volumeMounts", [])] == ["/tmp"]


@requires_helmfile
def test_the_broker_answers_its_probes_on_its_own_port(dev):
    (container,) = pod_of(dev)["containers"]
    port = container["ports"][0]["containerPort"]
    assert container["livenessProbe"]["httpGet"] == {"path": "/q/health", "port": port}
    assert container["readinessProbe"]["httpGet"] == {"path": "/q/ready", "port": port}


@requires_helmfile
def test_the_broker_has_limits_that_fit_the_16_gb_node(dev):
    (container,) = pod_of(dev)["containers"]
    resources = container["resources"]
    assert quantity(resources["requests"]["memory"]) <= quantity(resources["limits"]["memory"])
    assert quantity(resources["limits"]["memory"]) <= 2 * (1 << 30), "one broker may not take an eighth of the node"


@requires_helmfile
def test_the_database_password_comes_from_the_secret_the_database_is_made_with(dev):
    (container,) = pod_of(dev)["containers"]
    env = env_of(container)
    ref = env["PGPASSWORD"]["valueFrom"]["secretKeyRef"]
    secret = one(dev, "Secret", ref["name"])
    assert ref["key"] in (secret.get("data") or secret.get("stringData") or {})
    database = one(dev, "Database", "antares")["spec"]
    url = env["ANTARES_DATABASE_URL"]["value"]
    assert url.startswith(f"postgresql://{database['owner']}:$(PGPASSWORD)@{database['cluster']['name']}-rw."), url
    assert url.endswith(f"/{database['name']}"), url
    literal = [name for name, var in env.items() if "PASSWORD" in name and "valueFrom" not in var]
    assert literal == [], "a password is a secretKeyRef, never a literal value"


@requires_helmfile
def test_row_level_security_is_required(dev):
    (container,) = pod_of(dev)["containers"]
    assert env_of(container)["ANTARES_REQUIRE_RLS"]["value"] == "1"


@requires_helmfile
def test_the_gateway_and_the_portal_address_the_port_the_service_serves(dev):
    service = one(dev, "Service", "context-broker")
    (port,) = service["spec"]["ports"]
    (container,) = pod_of(dev)["containers"]
    assert port["targetPort"] == container["ports"][0]["containerPort"]
    address = f"http://context-broker.dev.svc.cluster.local:{port['port']}"
    gateway = one(dev, "Deployment", "context-gateway")["spec"]["template"]["spec"]["containers"][0]
    portal = one(dev, "Deployment", "portal")["spec"]["template"]["spec"]["containers"][0]
    assert env_of(gateway)["JC_GATEWAY_BROKER_URL"]["value"] == address
    assert env_of(portal)["JC_PORTAL_BROKER_URL"]["value"] == address


@requires_helmfile
def test_only_the_gateway_and_the_portal_reach_the_broker(dev):
    policy = one(dev, "NetworkPolicy", "context-broker")["spec"]
    (container,) = pod_of(dev)["containers"]
    (inbound,) = policy["ingress"]
    peers = sorted(f["podSelector"]["matchLabels"]["app.kubernetes.io/name"] for f in inbound["from"])
    assert peers == ["context-gateway-gateway", "portal-portal"]
    assert [p["port"] for p in inbound["ports"]] == [container["ports"][0]["containerPort"]]


@requires_helmfile
def test_the_broker_reaches_dns_its_database_and_the_gateway_only(dev):
    policy = one(dev, "NetworkPolicy", "context-broker")["spec"]
    targets = sorted(
        (
            next(iter(rule["to"][0].get("podSelector", {}).get("matchLabels", {}).values()), "ipBlock"),
            tuple(sorted({p["port"] for p in rule["ports"]})),
        )
        for rule in policy["egress"]
    )
    assert targets == [
        ("context-gateway-gateway", (8080,)),
        ("kube-dns", (53,)),
        ("postgres-cluster", (5432,)),
    ]
    assert all("ipBlock" not in to for rule in policy["egress"] for to in rule["to"])
    assert one(dev, "NetworkPolicy", "default-deny-context-broker")["spec"]["podSelector"] == {}
