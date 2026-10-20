"""Who may call the context broker's port inside the mesh (T-4875).

The broker believes the caller the `x-jc-*` headers name. `context-broker-allow-linkerd` opens the
Linkerd inbound port 4143 to the gateway and the Portal, but a meshed pod's connection lands on
that proxy whatever the NetworkPolicy says about 9090. The Linkerd `Server` on 9090 and its
`AuthorizationPolicy` keep every identity but those two out, so a pod in any other namespace
cannot forge a subject, on the API or on a WebSocket upgrade.

Conftest reads one document at a time in CI, so the pairing is checked here, over the whole
render; policies/brokers.rego checks that no broker's identity list grows.
"""

import pytest

ENVIRONMENTS = ("local", "dev", "production")
CALLERS = {"context-gateway": "context-gateway", "portal": "portal"}


def linkerd(docs, kind):
    return [
        d
        for d in docs
        if d.get("kind") == kind
        and d.get("apiVersion", "").startswith("policy.linkerd.io/")
    ]


def namespace_of(docs, deployment):
    return next(
        d
        for d in docs
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == deployment
    )["metadata"]["namespace"]


def broker_pods(docs):
    return [
        d
        for d in docs
        if d.get("kind") == "Deployment"
        and d["spec"]["selector"]["matchLabels"]
        .get("app.kubernetes.io/name", "")
        .startswith("context-broker-")
    ]


def meshed(pod):
    annotations = pod["spec"]["template"]["metadata"].get("annotations", {})
    return annotations.get("linkerd.io/inject") == "enabled"


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_only_the_gateway_and_the_portal_are_authorized_on_the_broker_port(
    rendered, environment
):
    docs = rendered(environment)
    brokers = [b for b in broker_pods(docs) if meshed(b)]
    if not brokers:
        pytest.skip(f"{environment} runs no meshed broker")
    expected = sorted(
        (
            {
                "kind": "ServiceAccount",
                "name": sa,
                "namespace": namespace_of(docs, deployment),
            }
            for deployment, sa in CALLERS.items()
        ),
        key=lambda r: r["name"],
    )
    for broker in brokers:
        name = broker["spec"]["selector"]["matchLabels"]["app.kubernetes.io/name"]
        servers = [
            s
            for s in linkerd(docs, "Server")
            if s["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/name")
            == name
        ]
        assert len(servers) == 1, (name, [s["metadata"]["name"] for s in servers])
        server = servers[0]
        assert server["spec"]["port"] == 9090
        assert server["spec"]["accessPolicy"] == "deny", (
            "what the policy does not name is refused"
        )
        (policy,) = [
            p
            for p in linkerd(docs, "AuthorizationPolicy")
            if p["spec"]["targetRef"]["name"] == server["metadata"]["name"]
        ]
        (required,) = policy["spec"]["requiredAuthenticationRefs"]
        assert required["kind"] == "MeshTLSAuthentication"
        (authentication,) = [
            m
            for m in linkerd(docs, "MeshTLSAuthentication")
            if m["metadata"]["name"] == required["name"]
        ]
        own = {
            "kind": "ServiceAccount",
            "name": broker["spec"]["template"]["spec"]["serviceAccountName"],
            "namespace": broker["metadata"]["namespace"],
        }
        assert own["name"] == broker["metadata"]["name"], (
            "the broker runs as its own ServiceAccount"
        )
        assert sorted(
            authentication["spec"]["identityRefs"], key=lambda r: r["name"]
        ) == sorted(expected + [own], key=lambda r: r["name"]), name
        for obj in (server, policy, authentication):
            assert obj["metadata"]["namespace"] == broker["metadata"]["namespace"]


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_named_identities_are_the_callers_own_service_accounts(
    rendered, environment
):
    docs = rendered(environment)
    for deployment, sa in CALLERS.items():
        pod = next(
            d
            for d in docs
            if d.get("kind") == "Deployment" and d["metadata"]["name"] == deployment
        )
        assert pod["spec"]["template"]["spec"]["serviceAccountName"] == sa
