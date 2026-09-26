"""Tests asserting workload chart renders correctly and complies with security standards."""

import shutil
import subprocess
from pathlib import Path
import pytest
import yaml

CHART = Path(__file__).resolve().parent.parent / "charts/workload"
requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render_workload(tmp_path: Path, values: dict | None = None, extra_args: list[str] | None = None) -> list[dict]:
    cmd = ["helm", "template", "test", str(CHART)]
    if values is not None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        val_file = tmp_path / "values.yaml"
        val_file.write_text(yaml.dump(values))
        cmd.extend(["-f", str(val_file)])
    if extra_args:
        cmd.extend(extra_args)
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(res.stdout) if doc]


def find_resource(docs: list[dict], kind: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind:
            return doc
    raise AssertionError(f"Resource kind={kind} not found in rendered output")


@requires_helm
def test_image_reference_formatting(tmp_path):
    docs_no_digest = render_workload(tmp_path / "no_digest", {"image": {"repository": "myrepo", "tag": "v1"}})
    dep1 = find_resource(docs_no_digest, "Deployment")
    assert dep1["spec"]["template"]["spec"]["containers"][0]["image"] == "myrepo:v1"

    docs_digest = render_workload(
        tmp_path / "digest",
        {"image": {"repository": "myrepo", "tag": "v1", "digest": "sha256:12345"}}
    )
    dep2 = find_resource(docs_digest, "Deployment")
    assert dep2["spec"]["template"]["spec"]["containers"][0]["image"] == "myrepo:v1@sha256:12345"


@requires_helm
def test_rolling_update_strategy_and_pod_security_flags(tmp_path):
    docs = render_workload(tmp_path)
    dep = find_resource(docs, "Deployment")
    sa = find_resource(docs, "ServiceAccount")

    strat = dep["spec"]["strategy"]["rollingUpdate"]
    assert strat["maxUnavailable"] == 0
    assert strat.get("maxSurge") is not None

    pod_spec = dep["spec"]["template"]["spec"]
    assert pod_spec["automountServiceAccountToken"] is False
    assert sa["automountServiceAccountToken"] is False
    assert pod_spec["enableServiceLinks"] is False

    container = pod_spec["containers"][0]
    readiness = container["readinessProbe"]
    liveness = container["livenessProbe"]
    assert readiness is not None and liveness is not None
    assert readiness != liveness


@requires_helm
def test_autoscaling_hpa_and_replicas(tmp_path):
    docs_default = render_workload(tmp_path / "no_hpa", {"replicaCount": 3})
    dep_default = find_resource(docs_default, "Deployment")
    assert dep_default["spec"]["replicas"] == 3
    assert not any(d.get("kind") == "HorizontalPodAutoscaler" for d in docs_default)

    docs_hpa = render_workload(tmp_path / "hpa", {"autoscaling": {"enabled": True, "minReplicas": 2, "maxReplicas": 5}})
    dep_hpa = find_resource(docs_hpa, "Deployment")
    assert "replicas" not in dep_hpa["spec"]
    hpa = find_resource(docs_hpa, "HorizontalPodAutoscaler")
    assert hpa["spec"]["minReplicas"] == 2


@requires_helm
def test_env_raw_value_and_env_secret(tmp_path):
    values = {
        "env": {"ANTARES_DATABASE_URL": "postgresql://antares:$(PGPASSWORD)@localhost:5432/antares"},
        "envSecret": {"PGPASSWORD": {"secret": "db-antares", "key": "password"}},
    }
    docs = render_workload(tmp_path, values)
    dep = find_resource(docs, "Deployment")
    env_vars = dep["spec"]["template"]["spec"]["containers"][0]["env"]

    url_env = next(e for e in env_vars if e["name"] == "ANTARES_DATABASE_URL")
    assert url_env["value"] == "postgresql://antares:$(PGPASSWORD)@localhost:5432/antares"

    secret_env = next(e for e in env_vars if e["name"] == "PGPASSWORD")
    assert secret_env["valueFrom"]["secretKeyRef"] == {"name": "db-antares", "key": "password"}


@requires_helm
def test_an_optional_env_secret_key_may_be_absent(tmp_path):
    """T-2842: a key only a rotation writes must not hold the pod in CreateContainerConfigError."""
    values = {"envSecret": {"PREV": {"secret": "s", "key": "previous", "optional": True}}}
    env_vars = find_resource(render_workload(tmp_path, values), "Deployment")["spec"]["template"]["spec"]["containers"][0]["env"]
    assert env_vars[0]["valueFrom"]["secretKeyRef"] == {"name": "s", "key": "previous", "optional": True}


@requires_helm
def test_configmap_empty_data_renders_and_annotations(tmp_path):
    docs = render_workload(tmp_path, {"configMap": {"enabled": True, "mountPath": "/streams", "data": {}}})
    cm = find_resource(docs, "ConfigMap")
    assert cm["data"] == {}

    dep = find_resource(docs, "Deployment")
    annotations = dep["spec"]["template"]["metadata"]["annotations"]
    assert "checksum/config" in annotations


@requires_helm
def test_a_workload_with_nothing_to_serve_is_ready_by_command_and_never_restarted_by_a_probe(tmp_path):
    """The forge's runner (components/gitea-runner) serves no HTTP. Kyverno's validate-probes
    wants a probe on every container; a liveness restart would lose the registration token the
    runner read once and deleted, so readiness comes from a command and liveness stays off."""
    docs = render_workload(tmp_path, {
        "image": {"repository": "busybox", "tag": "1"},
        "service": {"enabled": False},
        "probes": {"enabled": False, "readinessExec": ["test", "-s", "/tmp/runner/.runner"]},
    })
    container = find_resource(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert container["readinessProbe"]["exec"]["command"] == ["test", "-s", "/tmp/runner/.runner"]
    assert "livenessProbe" not in container
    assert "httpGet" not in container["readinessProbe"]

    bare = render_workload(tmp_path, {"image": {"repository": "busybox", "tag": "1"},
                                      "service": {"enabled": False}, "probes": {"enabled": False}})
    plain = find_resource(bare, "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert "readinessProbe" not in plain and "livenessProbe" not in plain, "no command, no probe"


@requires_helm
def test_a_stopping_pod_keeps_serving_until_the_edge_and_the_mesh_let_it_go(tmp_path):
    """T-3008, OPS-27: every roll answered ~2 s of 502s in 0.1 s. The kubelet stops the old pod at
    once while APISIX and Linkerd still send to it, and the meshed proxy refuses new connections
    from the same instant. The app pauses first (the kubelet's own sleep: the images are
    distroless), the proxy outlives the pause and the drain, and the grace period outlives both."""
    dep = find_resource(render_workload(tmp_path / "meshed", {"serviceMesh": {"enabled": True}}), "Deployment")
    pod = dep["spec"]["template"]
    pause = pod["spec"]["containers"][0]["lifecycle"]["preStop"]["sleep"]["seconds"]
    assert pause >= 5
    wait = int(pod["metadata"]["annotations"]["config.alpha.linkerd.io/proxy-wait-before-exit-seconds"])
    assert wait > pause
    assert pod["spec"]["terminationGracePeriodSeconds"] > wait

    # Without the mesh there is no proxy to hold; the app still pauses.
    plain = find_resource(render_workload(tmp_path / "plain", {"serviceMesh": {"enabled": False}}), "Deployment")
    template = plain["spec"]["template"]
    assert "config.alpha.linkerd.io/proxy-wait-before-exit-seconds" not in (template["metadata"].get("annotations") or {})
    assert template["spec"]["containers"][0]["lifecycle"]["preStop"]["sleep"]["seconds"] == pause

    # A workload that opts out renders neither.
    off = find_resource(
        render_workload(tmp_path / "off", {"preStopSleepSeconds": 0, "serviceMesh": {"enabled": True}}), "Deployment"
    )
    assert "lifecycle" not in off["spec"]["template"]["spec"]["containers"][0]
    assert "config.alpha.linkerd.io/proxy-wait-before-exit-seconds" not in off["spec"]["template"]["metadata"]["annotations"]


@requires_helm
def test_a_grace_period_shorter_than_the_pause_and_drain_is_refused(tmp_path):
    """A kubelet that kills the pod before its proxy's wait ends cuts the drain it was for."""
    with pytest.raises(subprocess.CalledProcessError) as refused:
        render_workload(tmp_path, {"terminationGracePeriodSeconds": 10, "serviceMesh": {"enabled": True}})
    assert "terminationGracePeriodSeconds (10) must be longer" in refused.value.stderr
