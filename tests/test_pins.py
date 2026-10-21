"""Exact pins in the files a reader sees, no lock file, tool versions in one file (T-4954).

docs/analysis/iac-practices.md R1-R4. A gate that never fails reads exactly like a clean
repository, so each check is fed a planted floating chart version, a tag-only image and a
helmfile.lock, and must refuse each one.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART_PINS = ROOT / "scripts/ci/check-chart-pins.py"
IMAGE_DIGESTS = ROOT / "scripts/ci/check-image-digests.py"
TOOLS = ROOT / "tools.env"
WORKFLOWS = ROOT / ".github/workflows"


def run(script: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def release(chart: str, version: str) -> dict:
    return {"name": "r", "namespace": "ns", "chart": chart, "version": version}


@pytest.mark.parametrize(
    "chart",
    ["cc2-codecentric/keycloakx", "oci://ghcr.io/cloudnative-pg/charts/cluster"],
)
@pytest.mark.parametrize(
    "version", ["", "~7.2.0", "^7", ">=7.0.0", "7.2.x", "7.2", "*", "latest"]
)
def test_a_floating_remote_chart_version_fails(chart, version):
    result = run(CHART_PINS, "-", stdin=json.dumps([release(chart, version)]))
    assert result.returncode == 1, result.stdout
    assert "pin one exact chart version" in result.stdout


@pytest.mark.parametrize("version", ["7.2.0", "v1.19.0", "0.7.0-rc.1", "1.2.3+build.4"])
def test_an_exact_remote_chart_version_passes(version):
    result = run(
        CHART_PINS, "-", stdin=json.dumps([release("cc2-vector/vector", version)])
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "chart", ["charts/theme", "./charts/networkpolicies", "../../charts/workload"]
)
def test_a_local_chart_needs_no_version(chart):
    assert run(CHART_PINS, "-", stdin=json.dumps([release(chart, "")])).returncode == 0


def test_a_helmfile_lock_fails(tmp_path):
    assert run(CHART_PINS, "--no-lock", str(tmp_path)).returncode == 0
    (tmp_path / "components/keycloak").mkdir(parents=True)
    (tmp_path / "components/keycloak/helmfile.lock").write_text("version: v1.8.1\n")
    result = run(CHART_PINS, "--no-lock", str(tmp_path))
    assert result.returncode == 1
    assert "helmfile.lock" in result.stdout


def pod(image: str) -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "p"},
            "spec": {"containers": [{"name": "c", "image": image}]},
        }
    )


def test_a_tag_only_image_fails(tmp_path):
    rendered = tmp_path / "rendered.yaml"
    rendered.write_text(pod("quay.io/keycloak/keycloak:26.8.0"))
    result = run(IMAGE_DIGESTS, str(rendered))
    assert result.returncode != 0
    assert "quay.io/keycloak/keycloak:26.8.0" in result.stdout + result.stderr
    rendered.write_text(pod("quay.io/keycloak/keycloak:26.8.0@sha256:" + "0" * 64))
    assert run(IMAGE_DIGESTS, str(rendered)).returncode == 0


def tools() -> dict[str, str]:
    lines = [
        line
        for line in TOOLS.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert all(re.fullmatch(r"[A-Z0-9_]+=\S+", line) for line in lines), lines
    return dict(line.split("=", 1) for line in lines)


def test_every_tool_version_is_exact_and_every_download_has_a_checksum():
    pinned = tools()
    for key, value in pinned.items():
        if key.endswith("_VERSION"):
            assert re.fullmatch(r"v?\d+\.\d+\.\d+", value), f"{key}={value}"
    downloaded = {
        "KUBECONFORM",
        "CONFTEST",
        "GITLEAKS",
        "KYVERNO",
        "SOPS",
        "AGE",
        "TRIVY",
    }
    for tool in downloaded:
        assert re.fullmatch(r"[0-9a-f]{64}", pinned.get(f"{tool}_CHECKSUM", "")), tool


def test_renovate_sees_every_tool_it_should_bump():
    config = json.loads((ROOT / "renovate.json").read_text())
    manager = next(
        m
        for m in config["customManagers"]
        if "/^tools\\.env$/" in m["managerFilePatterns"]
    )
    found = {
        m.group("depName")
        for pattern in manager["matchStrings"]
        for m in re.finditer(pattern.replace("(?<", "(?P<"), TOOLS.read_text())
    }
    commented = TOOLS.read_text().count("# renovate:")
    assert len(found) == commented >= 11, found
    # The cluster's version moves with the cluster, not with upstream.
    assert "KUBERNETES_VERSION" in tools()
    assert config["minimumReleaseAge"] == "7 days"
    assert config["baseBranchPatterns"] == ["main"]
    assert "gitlabci" not in config["enabledManagers"]


def digests(node) -> int:
    """Image entries (`repository` + `digest`) in a parsed images.yaml."""
    if isinstance(node, dict):
        return int("repository" in node and "digest" in node) + sum(
            digests(v) for v in node.values()
        )
    return 0


def test_renovate_matches_every_image_with_its_digest():
    config = json.loads((ROOT / "renovate.json").read_text())
    manager = next(
        m for m in config["customManagers"] if "images" in m["managerFilePatterns"][0]
    )
    pattern = re.compile(manager["matchStrings"][0].replace("(?<", "(?P<"))
    files = sorted(ROOT.glob("components/*/images.yaml"))
    matched = sum(len(pattern.findall(f.read_text())) for f in files)
    declared = sum(
        digests(doc) for f in files for doc in yaml.safe_load_all(f.read_text())
    )
    assert matched == declared > 40


def test_workflows_take_tool_versions_from_tools_env():
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text()
        assert "releases/latest" not in text, workflow.name
        if workflow.name.startswith("reusable-"):
            continue  # other repositories call these with their own inputs
        assert "helmfile/helmfile-action@" not in text, (
            f"{workflow.name}: use ./.github/actions/tools"
        )
        # A version written into the workflow is a second source beside tools.env. LINKERD2_VERSION
        # names an edge build the k3d smoke installs; Renovate cannot order edge tags.
        written = set(re.findall(r"\b([A-Z0-9]+_VERSION): ", text)) - {
            "LINKERD2_VERSION"
        }
        assert not written, f"{workflow.name}: {written} belongs in tools.env"
