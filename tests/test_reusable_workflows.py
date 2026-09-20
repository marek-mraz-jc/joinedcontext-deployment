"""The reusable workflows other repositories call (T-0010…T-0016).

Two properties are worth a test and the rest is YAML nobody can check without a runner.

The first is drift: `reusable-rust-security.yml` and `reusable-gitleaks.yml` carry a copy of
the shared configuration inside them, because a caller's GITHUB_TOKEN cannot check out this
private repository to read it. A copy that quietly stops matching its source is a gate that
enforces something nobody wrote down, so the shell that writes the copy is executed here and
compared with the file it came from.

The second is the ruleset itself. A regex that matches nothing passes every scan, which reads
exactly like a clean repository. The secret shapes are built at test time and never committed,
so this file adds nothing for the scanner to find.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
SHARED = ROOT / ".ci/shared"

# The four shapes the platform's own rules exist for, none of them real. Assembled at run
# time from parts, because a literal of the right shape in this file is a finding of the very
# scan it tests (T-0542): the whole history is scanned, and a shape that once sat here stays
# in it (.gitleaksignore carries those fingerprints).
LEAKS = {
    "age": "AGE-SECRET-KEY-1" + "QWERTYUIOPASDFGHJKLZXCVBNM234567QWERTYUIOPASDFGHJKLZXCVBNM2",
    "argon2id": "$".join(["", "argon2id", "v=19", "m=65536,t=3,p=4", "c29tZXNhbHR2YWx1ZQ", "aGFzaHZhbHVlaGVyZQ"]),
    "jwt": ".".join(["eyJ" + "hbGciOiJSUzI1NiJ9", "eyJ" + "hdWQiOiJqYy1nYXRld2F5In0", "c2lnbmF0dXJlLXBsYWNlaG9sZGVy"]),
    "client_secret": 'client_secret: "' + "S3cr3tVal" + "ue0123456789abcdef" + '"',
}


def written_by(workflow: str, step_name: str, filename: str) -> str:
    """Run the step that writes the embedded configuration and return what it wrote."""
    document = yaml.safe_load((WORKFLOWS / workflow).read_text())
    job = next(iter(document["jobs"].values()))
    step = next(s for s in job["steps"] if step_name in s.get("name", ""))
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(["bash", "-c", step["run"]], cwd=work, check=True, capture_output=True)
        return (Path(work) / filename).read_text()


@pytest.mark.parametrize(
    "workflow,step,filename,source",
    [
        ("reusable-rust-security.yml", "baseline configuration", "deny.toml", "deny.toml"),
        ("reusable-gitleaks.yml", "platform ruleset", ".gitleaks.toml", "gitleaks.toml"),
    ],
)
def test_the_embedded_configuration_is_the_shared_one(workflow, step, filename, source):
    assert written_by(workflow, step, filename) == (SHARED / source).read_text()


def test_a_repository_with_its_own_configuration_keeps_it():
    document = yaml.safe_load((WORKFLOWS / "reusable-rust-security.yml").read_text())
    step = next(
        s
        for s in document["jobs"]["supply-chain"]["steps"]
        if "baseline configuration" in s.get("name", "")
    )
    with tempfile.TemporaryDirectory() as work:
        own = Path(work, "deny.toml")
        own.write_text("# this repository has a reason of its own\n")
        subprocess.run(["bash", "-c", step["run"]], cwd=work, check=True, capture_output=True)
        assert own.read_text() == "# this repository has a reason of its own\n"


@pytest.fixture(scope="module")
def gitleaks():
    binary = shutil.which("gitleaks")
    if not binary:
        pytest.skip("gitleaks is not installed")
    return binary


def scan(gitleaks: str, contents: str) -> int:
    with tempfile.TemporaryDirectory() as work:
        Path(work, "config.yaml").write_text(contents)
        return subprocess.run(
            [
                gitleaks, "detect", "--no-git", "--source", work,
                "--config", str(SHARED / "gitleaks.toml"), "--redact", "--exit-code", "1",
            ],
            capture_output=True,
        ).returncode


@pytest.mark.parametrize("name", sorted(LEAKS))
def test_every_platform_rule_catches_its_own_shape(gitleaks, name):
    assert scan(gitleaks, f"secret: {LEAKS[name]}\n") == 1


def test_a_manifest_that_carries_no_credential_passes(gitleaks):
    clean = "apiVersion: v1\nkind: Secret\nmetadata: {name: keycloak}\nspec:\n  secretRef: keycloak-admin\n"
    assert scan(gitleaks, clean) == 0


def test_every_action_is_pinned_by_commit():
    """A tag is mutable, so a gate that trusts one is not a gate (OPS-28, TS-23).

    Every workflow, not only the reusable ones a caller depends on (T-0816): `ci.yml` runs on
    every push to `main` and `image-ckan.yml` holds `packages: write` and `id-token: write`, so
    whoever can move a tag those lanes name signs an image and shapes what the cluster applies.
    """
    unpinned = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text())
        for name, job in document["jobs"].items():
            # A job either calls a workflow or runs steps; a local `./…` call is this
            # repository at the commit already checked out, so there is no tag to move.
            entries = [job] if "uses" in job else job.get("steps", [])
            for entry in entries:
                uses = entry.get("uses")
                if uses and not uses.startswith("./") and len(uses.split("@")[-1]) != 40:
                    unpinned.append(f"{workflow.name} ({name}): {uses}")
    assert unpinned == []


# --- the digest gate the signing workflow is the other half of (T-0014) -------------------

DIGEST_CHECK = ROOT / "scripts/ci/check-image-digests.py"

PINNED = """
apiVersion: apps/v1
kind: Deployment
metadata: { name: gateway }
spec:
  template:
    spec:
      initContainers:
        - { name: wait, image: ghcr.io/x/wait@sha256:%s }
      containers:
        - { name: gateway, image: ghcr.io/x/gateway@sha256:%s }
""" % ("a" * 64, "b" * 64)

MUTABLE = """
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: broker }
spec:
  template:
    spec:
      containers:
        - { name: broker, image: ghcr.io/x/broker:main }
"""

HOOK = """
apiVersion: batch/v1
kind: Job
metadata:
  name: ping-test
  annotations: { "helm.sh/hook": test }
spec:
  template:
    spec:
      containers:
        - { name: ping, image: alpine:3.17 }
"""


def digest_check(manifests: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as work:
        rendered = Path(work, "rendered.yaml")
        rendered.write_text(manifests)
        return subprocess.run(
            ["python3", str(DIGEST_CHECK), str(rendered)], capture_output=True, text=True
        )


def test_a_digest_pinned_deployment_passes():
    assert digest_check(PINNED).returncode == 0


def test_a_mutable_tag_is_named_and_refused():
    result = digest_check(MUTABLE)
    assert result.returncode == 1
    assert "ghcr.io/x/broker:main" in result.stderr


def test_a_helm_test_hook_is_not_a_deployed_workload():
    """`helmfile sync` never applies one, so its image is not what the cluster runs."""
    assert digest_check(HOOK).returncode == 0


# --- one repository, one digest (T-2270; OPS-13, AG-52) -------------------------------------

PLATFORM = "ghcr.io/marek-mraz/joinedcontext-platform"

ONE_BUILD = """
apiVersion: apps/v1
kind: Deployment
metadata: { name: context-gateway }
spec:
  template:
    spec:
      containers:
        - { name: gateway, image: "%s:main@sha256:%s" }
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: agent-proxy }
spec:
  template:
    spec:
      containers:
        - { name: proxy, image: "%s:main@sha256:%s" }
""" % (PLATFORM, "c" * 64, PLATFORM, "c" * 64)

TWO_BUILDS = ONE_BUILD.replace(f"{PLATFORM}:main@sha256:{'c' * 64}", f"{PLATFORM}:main@sha256:{'d' * 64}", 1)


def test_the_components_that_share_an_image_may_pin_its_digest_each():
    """Two deployments of one build is the point, not a finding."""
    assert digest_check(ONE_BUILD).returncode == 0


def test_two_digests_behind_one_repository_are_named_and_refused():
    """The drift of 2026-09-19: the gateway eleven commits ahead of the proxy it shares a binary
    with, so a fix *in the proxy* (T-1477, AG-52) shipped to the process that does not run it."""
    result = digest_check(TWO_BUILDS)
    assert result.returncode == 1
    assert PLATFORM in result.stderr
    assert "Deployment/context-gateway/gateway" in result.stderr
    assert "Deployment/agent-proxy/proxy" in result.stderr


def test_a_mutable_tag_is_reported_before_a_drift_is_guessed_at():
    """An unpinned image has no digest to compare, so that finding comes first and alone."""
    result = digest_check(MUTABLE + "\n---" + TWO_BUILDS)
    assert result.returncode == 1
    assert "ghcr.io/x/broker:main" in result.stderr
    assert "builds at once" not in result.stderr


# --- the Rego gate the manifest-lint workflow runs (T-0015) --------------------------------

POLICIES = ROOT / "policies"
FIXTURES = ROOT / "tests/fixtures/policies"


@pytest.fixture(scope="module")
def conftest_binary():
    binary = shutil.which("conftest")
    if not binary:
        pytest.skip("conftest is not installed")
    return binary


def policy_check(conftest_binary: str, manifest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [conftest_binary, "test", "--all-namespaces", "-p", str(POLICIES), str(manifest)],
        capture_output=True,
        text=True,
    )


def test_a_workload_that_declares_all_four_passes(conftest_binary):
    assert policy_check(conftest_binary, FIXTURES / "compliant.yaml").returncode == 0


def test_a_workload_that_declares_none_of_them_is_refused(conftest_binary):
    """One manifest, every rule: a policy that fires on nothing reads like a clean cluster."""
    result = policy_check(conftest_binary, FIXTURES / "violating.yaml")
    assert result.returncode == 1
    for expected in (
        "does not set runAsNonRoot",
        "asks for uid 0",
        "does not drop ALL capabilities",
        "declares no memory limit",
        "default ServiceAccount",
    ):
        assert expected in result.stdout, result.stdout


def test_a_workload_fetching_chosen_addresses_is_refused_a_private_range(conftest_binary):
    """The runner probes URLs people type (MF-39, T-0752): a range that leaves one private
    network reachable is named, and one that excepts them all passes."""
    result = policy_check(conftest_binary, FIXTURES / "egress-open.yaml")
    assert result.returncode == 1
    assert "leaves" in result.stdout and "172.16.0.0/12" in result.stdout, result.stdout
    assert policy_check(conftest_binary, FIXTURES / "egress-closed.yaml").returncode == 0
