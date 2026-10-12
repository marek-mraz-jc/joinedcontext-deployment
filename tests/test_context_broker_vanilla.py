"""CC-01: the context broker reads no configuration of this plane: no repository, no manifest, no
ConfigMap of ours; what it is told arrives as its own environment, its own admin credential and its
database. The image is the jc build (surfaces and the joinedcontext engine, T-3642); the views and
rule documents it serves are written into its database by the Portal through `/q`, never mounted."""

import pytest


@pytest.fixture(scope="module")
def broker_pod(rendered):
    dev = rendered("dev")
    deployment = next(
        d for d in dev if d.get("kind") == "Deployment" and d["metadata"]["name"] == "context-broker"
    )
    return deployment["spec"]["template"]["spec"]


ADMIN_TOKEN = {"secretName": "context-broker-admin-token", "items": [{"key": "token", "path": "token"}]}


def test_the_broker_mounts_no_configuration_of_the_plane(broker_pod):
    """CC-01: one scratch directory and its own admin credential, nothing else; no repository,
    ConfigMap or other Secret volume."""
    volumes = broker_pod.get("volumes", [])
    scratch = [v for v in volumes if set(v) == {"name", "emptyDir"}]
    secrets = [v for v in volumes if "secret" in v]
    assert len(scratch) + len(secrets) == len(volumes), volumes
    assert [v["secret"] for v in secrets] == [ADMIN_TOKEN], secrets
    for container in broker_pod.get("initContainers", []) + broker_pod["containers"]:
        assert "git" not in container["name"], "no repository sidecar beside the broker"
        mounts = sorted(m["mountPath"] for m in container.get("volumeMounts", []))
        assert mounts in ([], ["/tmp"], ["/tmp", "/var/run/secrets/antares/admin"]), mounts
        assert not container.get("envFrom"), "the broker takes no bulk configuration of ours"


def test_the_broker_runs_the_surfaces_and_requires_its_admin_credential(broker_pod):
    """T-3642: the views, MCP and access surfaces beside `/q`, the subject headers the gateway sets
    (platform T-3641), and `/q` behind the mounted secret with only the metrics open."""
    env = {e["name"]: e.get("value") for e in broker_pod["containers"][0].get("env", [])}
    assert env["ANTARES_API_SURFACES"].split(",") == ["admin", "views", "mcp", "access", "ws", "ogc"]
    # T-3905: the view WebSocket is bounded for the one node, under the broker's own defaults.
    assert 0 < int(env["ANTARES_WS_MAX_CONNECTIONS_PER_TENANT"]) <= int(env["ANTARES_WS_MAX_CONNECTIONS"]) <= 1000
    assert 0 < int(env["ANTARES_WS_MAX_SUBSCRIPTIONS"]) <= 64
    assert 0 < int(env["ANTARES_WS_QUEUE"]) <= 256
    assert "ANTARES_WS_ALLOWED_ORIGINS" not in env, "browsers reach the socket through the gateway alone"
    assert env["ANTARES_POLICY_SUBJECT_HEADERS"].split(",") == [
        "x-jc-subject", "x-jc-groups", "x-jc-roles", "x-jc-client", "x-jc-restricted", "x-jc-did"]
    assert not {"authorization", "cookie"} & set(env["ANTARES_POLICY_SUBJECT_HEADERS"].split(","))
    assert env["ANTARES_ADMIN_TOKEN_FILE"] == "/var/run/secrets/antares/admin/token"
    assert env["ANTARES_ADMIN_METRICS"] == "open"
    assert int(env["ANTARES_SCHEMA_MAX_BYTES"]) > 0
    # T-3768: the joinedcontext engine decides every request, after the gateway's own hops carry
    # a subject (T-3767) and a participant's DID is a header it reads (T-3810).
    assert env["ANTARES_POLICY"] == "joinedcontext"


def test_the_broker_is_told_only_its_own_settings(broker_pod):
    """CC-01: its environment is the broker's own (`ANTARES_*`) and its database password; nothing
    names the configuration repository, a manifest or a gateway setting."""
    broker = broker_pod["containers"][0]
    names = {e["name"] for e in broker.get("env", [])}
    foreign = {n for n in names if not (n.startswith("ANTARES_") or n == "PGPASSWORD")}
    assert foreign == set()
    assert not any("REPO" in n or n.startswith("JC_") or n.startswith("GITSYNC") for n in names)


def test_the_broker_s_mcp_answers_the_host_the_gateway_calls(rendered, broker_pod):
    """T-3647: the gateway reaches an Endpoint's MCP on the broker by its Service name; the MCP
    surface refuses any Host it does not list (DNS rebinding), so the two must name the same."""
    env = {e["name"]: e.get("value") for e in broker_pod["containers"][0].get("env", [])}
    gateway = next(d for d in rendered("dev") if d.get("kind") == "Deployment"
                   and d["metadata"]["name"] == "context-gateway")
    gateway_env = {e["name"]: e.get("value") for c in gateway["spec"]["template"]["spec"]["containers"]
                   for e in c.get("env", [])}
    authority = gateway_env["JC_GATEWAY_BROKER_URL"].split("://", 1)[1].split("/", 1)[0]
    assert authority in env["ANTARES_MCP_ALLOWED_HOSTS"].split(","), (authority, env["ANTARES_MCP_ALLOWED_HOSTS"])
