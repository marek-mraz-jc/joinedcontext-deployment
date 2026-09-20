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
def test_configmap_empty_data_renders_and_annotations(tmp_path):
    docs = render_workload(tmp_path, {"configMap": {"enabled": True, "mountPath": "/streams", "data": {}}})
    cm = find_resource(docs, "ConfigMap")
    assert cm["data"] == {}

    dep = find_resource(docs, "Deployment")
    annotations = dep["spec"]["template"]["metadata"]["annotations"]
    assert "checksum/config" in annotations
