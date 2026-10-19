"""T-4775: the admission policy that holds the sandbox reaper's cluster-wide `delete` on
namespaces to the namespaces its script reaps, judged by the kyverno CLI as the chart renders it.

RBAC cannot name a label, so without the policy the reaper's token deletes kube-system as readily
as an expired sandbox."""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "components/sandbox-reaper/charts/reaper"
REAPER = "system:serviceaccount:ops:sandbox-reaper"
LABEL = "sandbox.joinedcontext.com/lifecycle"

pytestmark = [
    pytest.mark.skipif(shutil.which("kyverno") is None, reason="kyverno CLI not installed"),
    pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed"),
]


@pytest.fixture(scope="module")
def policy(tmp_path_factory):
    out = tmp_path_factory.mktemp("policy") / "policy.yaml"
    out.write_text(
        subprocess.run(
            ["helm", "template", "sandbox-reaper", str(CHART), "--namespace", "ops",
             "--show-only", "templates/policy.yaml"],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    return out


def judged(policy: Path, labels: dict, tmp_path: Path, username: str = REAPER) -> str:
    """"pass", "fail" or "skip": what admission does with a DELETE of a namespace with these labels."""
    resource = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "target", "labels": labels}}
    (tmp_path / "resource.yaml").write_text(yaml.safe_dump(resource))
    (tmp_path / "userinfo.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: cli.kyverno.io/v1alpha1
        kind: UserInfo
        metadata: {{name: user}}
        userInfo:
          username: {username}
          groups: [system:serviceaccounts, system:authenticated]
        """))
    (tmp_path / "values.yaml").write_text(textwrap.dedent("""\
        apiVersion: cli.kyverno.io/v1alpha1
        kind: Values
        metadata: {name: values}
        globalValues:
          request.operation: DELETE
        """))
    result = subprocess.run(
        ["kyverno", "apply", str(policy), "--resource", str(tmp_path / "resource.yaml"),
         "--userinfo", str(tmp_path / "userinfo.yaml"), "--values-file", str(tmp_path / "values.yaml")],
        capture_output=True, text=True, check=False,
    )
    summary = next(line for line in result.stdout.splitlines() if line.startswith("pass:"))
    counts = dict(part.strip().split(": ") for part in summary.split(","))
    assert counts["error"] == "0", result.stdout
    if counts["fail"] != "0":
        return "fail"
    return "pass" if counts["pass"] != "0" else "skip"


@pytest.mark.parametrize("lifecycle", ["unmanaged", "preview"])
def test_the_reaper_may_delete_a_sandbox(policy, tmp_path, lifecycle):
    assert judged(policy, {LABEL: lifecycle}, tmp_path) == "pass"


@pytest.mark.parametrize(
    "labels",
    [{}, {LABEL: "managed"}, {LABEL: ""}, {"kubernetes.io/metadata.name": "kube-system"}],
    ids=["unlabelled", "other-lifecycle", "empty-lifecycle", "system"],
)
def test_the_reaper_may_not_delete_any_other_namespace(policy, tmp_path, labels):
    assert judged(policy, labels, tmp_path) == "fail"


def test_someone_else_is_not_the_policys_business(policy, tmp_path):
    assert judged(policy, {}, tmp_path, username="system:serviceaccount:ops:someone") == "skip"
