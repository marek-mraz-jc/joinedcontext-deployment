"""CC-01: the context broker stays a vanilla NGSI-LD broker. It reads no configuration of this
plane: no repository, no manifest, no ConfigMap of ours; what it is told arrives as its own
environment and its database, so any compliant broker can take its place (CC-52)."""

import pytest


@pytest.fixture(scope="module")
def broker_pod(rendered):
    dev = rendered("dev")
    deployment = next(
        d for d in dev if d.get("kind") == "Deployment" and d["metadata"]["name"] == "context-broker"
    )
    return deployment["spec"]["template"]["spec"]


def test_the_broker_mounts_no_configuration_of_the_plane(broker_pod):
    """CC-01: one scratch directory and nothing else; no repository, ConfigMap or Secret volume."""
    volumes = broker_pod.get("volumes", [])
    assert all(set(v) == {"name", "emptyDir"} for v in volumes), volumes
    for container in broker_pod.get("initContainers", []) + broker_pod["containers"]:
        assert "git" not in container["name"], "no repository sidecar beside the broker"
        mounts = [m["mountPath"] for m in container.get("volumeMounts", [])]
        assert mounts in ([], ["/tmp"]), mounts
        assert not container.get("envFrom"), "the broker takes no bulk configuration of ours"


def test_the_broker_is_told_only_its_own_settings(broker_pod):
    """CC-01: its environment is the broker's own (`ANTARES_*`) and its database password; nothing
    names the configuration repository, a manifest or a gateway setting."""
    broker = broker_pod["containers"][0]
    names = {e["name"] for e in broker.get("env", [])}
    foreign = {n for n in names if not (n.startswith("ANTARES_") or n == "PGPASSWORD")}
    assert foreign == set()
    assert not any("REPO" in n or n.startswith("JC_") or n.startswith("GITSYNC") for n in names)
