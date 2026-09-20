"""The credential proxy of the builder runs on dev, judged as the deployment renders it (AG-49,
AG-52, AP-56).

What is coupled across files: the token the Portal and the proxy share, the port the proxy
calls the Portal on and the NetworkPolicy that opens it, the client id the proxy mints tokens
with and the ServiceAccount manifest the gateway resolves it to, and the profile name every run
loads and the file the forge seed commits."""

import base64
import json
import shutil

import pytest
import yaml

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def deployment(docs, name):
    return next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == name)


def container(docs, name):
    return deployment(docs, name)["spec"]["template"]["spec"]["containers"][0]


def env_of(c):
    return {e["name"]: e["value"] for e in c.get("env", []) if "value" in e}


def secret_env_of(c):
    return {
        e["name"]: (e["valueFrom"]["secretKeyRef"]["name"], e["valueFrom"]["secretKeyRef"]["key"])
        for e in c.get("env", [])
        if "valueFrom" in e and "secretKeyRef" in e["valueFrom"]
    }


@requires_helmfile
def test_the_proxy_runs_the_proxy_binary_of_the_platform_image_with_its_credentials_mounted(dev):
    proxy = container(dev, "agent-proxy")
    assert proxy["command"] == ["/usr/local/bin/jc-agent-proxy"]
    assert proxy["image"].startswith("ghcr.io/marek-mraz-jc/joinedcontext-platform:main@sha256:")
    env = env_of(proxy)
    assert env["JC_PORTAL_BASE"].endswith(":9090")
    assert env["JC_MODEL_PROVIDER"] == "openai-compatible"
    assert env["JC_OIDC_CLIENT_ID"] == "helsinki-agent-proxy"
    secrets = secret_env_of(proxy)
    # T-2271: no shared bearer any more. The proxy holds its own client's secret and mints a token
    # per audience from the in-cluster token endpoint, which a pod can actually dial (T-2272).
    assert "JC_PROXY_TOKEN" not in secrets
    assert secrets["JC_OIDC_CLIENT_SECRET"] == (
        "keycloak-client-helsinki-agent-proxy",
        "client-secret",
    )
    assert env["JC_OIDC_TOKEN_URL"].startswith("http://keycloak-app-keycloakx-http.")
    assert env["JC_OIDC_TOKEN_URL"].endswith("/protocol/openid-connect/token")
    assert secrets["JC_MODEL_KEY"] == ("agent-runner-model-key", "key")
    assert secrets["JC_OIDC_CLIENT_SECRET"] == ("keycloak-client-helsinki-agent-proxy", "client-secret")
    # No literal credential anywhere in the plain environment.
    assert not any(k.endswith(("KEY", "TOKEN", "SECRET")) for k in env)


@requires_helmfile
def test_the_portal_is_told_where_the_proxy_is_and_opens_its_internal_listener_to_it_alone(dev):
    portal = container(dev, "portal")
    env = env_of(portal)
    assert env["JC_AGENT_PROXY_BASE"] == "http://agent-proxy.dev.svc.cluster.local:8080"
    assert env["JC_AGENTS_NAMESPACE"] == "dev"
    # T-2271: the Portal is told whose token to expect on those routes instead of holding a copy
    # of the proxy's bearer.
    assert "JC_AGENT_PROXY_TOKEN" not in secret_env_of(portal)
    assert env_of(portal)["JC_PORTAL_AGENT_PROXY_CLIENT_ID"] == "helsinki-agent-proxy"
    service = next(d for d in dev if d.get("kind") == "Service" and d["metadata"]["name"] == "portal")
    assert {p["port"] for p in service["spec"]["ports"]} == {8080, 9090}
    policy = next(
        d for d in dev
        if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "portal-internal-from-agent-proxy"
    )
    (rule,) = policy["spec"]["ingress"]
    assert [p["port"] for p in rule["ports"]] == [9090]
    assert rule["from"][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "agent-runner-proxy"}


@requires_helmfile
def test_the_proxy_client_carries_every_endpoint_of_the_project_as_audience_and_a_manifest_names_it(dev):
    secret = next(
        d for d in dev
        if d.get("kind") == "Secret" and d["metadata"]["name"] == "keycloak-config-keycloak-config-cli-config-realms"
    )
    realm = json.loads(base64.b64decode(secret["data"]["dev.json"]))
    client = next(c for c in realm["clients"] if c["clientId"] == "helsinki-agent-proxy")
    assert client["serviceAccountsEnabled"] and not client["publicClient"]
    assert not client["standardFlowEnabled"]
    audiences = {
        m["config"]["included.custom.audience"]
        for m in client["protocolMappers"]
        if m["protocolMapper"] == "oidc-audience-mapper"
    }
    # The endpoint table the gateway serves is the forge's repository, seeded by the bootstrap
    # (T-0278); a key's `__` is a `/`.
    forge = next(d for d in dev if d.get("kind") == "ConfigMap" and d["metadata"]["name"].endswith("bootstrap-seed"))
    documents = [
        yaml.safe_load(text)
        for key, text in forge["data"].items()
        # A bento.yaml beside a pipeline is the author's mapping, not a manifest (PL-03).
        if key.endswith(".yaml") and not key.endswith(".linkml.yaml") and not key.endswith("bento.yaml")
    ]
    # platform-settings.yaml is a plain document of the repository root, not a manifest: it
    # carries no kind (Architecture/06 §1, T-0901).
    manifests = [d for d in documents if isinstance(d, dict) and "kind" in d]
    slugs = {m["spec"]["slug"] for m in manifests if m["kind"] == "Endpoint" and m["metadata"]["namespace"] == "helsinki"}
    # Every seeded slug, and the gateway's own name for the endpoints approved after the realm
    # was written (Architecture/12 §5, T-0666); nothing else.
    # `portal-internal` is beside them since T-2271: the same client answers the Portal's internal
    # listener on the run callbacks, and one audience mapper per door.
    assert audiences == slugs | {"context-gateway", "portal-internal"}
    account = next(m for m in manifests if m["kind"] == "ServiceAccount" and m["metadata"]["name"] == "agent-proxy")
    assert account["spec"]["roles"] == [{"role": "public", "scope": {"contextSpace": "helsinki"}}]


@requires_helmfile
def test_the_forge_seed_commits_the_builder_profile(dev):
    seed = next(
        d for d in dev
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"].endswith("bootstrap-seed")
    )
    profile = yaml.safe_load(seed["data"]["agentprofiles__app-builder.yaml"])
    assert profile["kind"] == "AgentProfile"
    assert profile["spec"]["role"] == "builder"
    assert profile["spec"]["model"]["provider"] == "openai-compatible"
    # SDK-26, AG-72: the first run calls Gemini 3.8 Flash at medium reasoning.
    assert profile["spec"]["model"]["name"] == "google/gemini-3.8-flash"
    assert profile["spec"]["model"]["reasoningEffort"] == "medium"
    # AG-70, AG-77: the assistant's share, KPI, space completion and change steps are granted,
    # never approval or removal.
    access = profile["spec"]["access"]
    # Everything that reads or proposes (T-1475); the person's own grants narrow each call.
    named = set(access["operations"])
    assert {"jc_resource_propose", "jc_change_list", "jc_pipeline_metrics", "jc_datasource_check",
            "jc_workspace_open", "jc_workspace_preview_start"} <= named
    assert len(access["operations"]) == len(named), "an operation is listed once"
    # Never an agent's: approving, deleting, keys, whole projects, bringing a copy back (AG-11, AG-82).
    never = {"jc_change_approve", "jc_change_reject", "jc_resource_delete", "jc_project_delete",
             "jc_project_create", "jc_project_import", "jc_project_export", "jc_flow_start",
             "jc_draft_drop", "jc_workspace_discard", "jc_workspace_propose"}
    assert not named & never, named & never
    assert not any("_key_" in name for name in named)
    assert all(set(grant["verbs"]) <= {"read", "propose"} for grant in access["kinds"])
    assert {"Pipeline", "DataSource", "ContextSpace", "RoleBinding"} <= {grant["kind"] for grant in access["kinds"]}
