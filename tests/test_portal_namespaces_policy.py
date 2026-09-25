"""The admission policy that bounds the Portal's cluster-wide namespace rights (AP-117), judged
by the kyverno CLI as the chart renders it.

The Portal may create, change and delete a namespace only when it is `{release}-{project}-apps`
and labelled as the Portal's with that project, and may bind only `{release}-portal-apps`, to
itself, in such a namespace. Anyone else's requests are not the policy's business."""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "components/portal/charts/namespaces"
PORTAL = "system:serviceaccount:dev:portal"

requires_kyverno = pytest.mark.skipif(shutil.which("kyverno") is None, reason="kyverno CLI not installed")
requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

pytestmark = [requires_kyverno, requires_helm]


@pytest.fixture(scope="module")
def policy(tmp_path_factory):
    out = tmp_path_factory.mktemp("policy") / "policy.yaml"
    out.write_text(
        subprocess.run(
            ["helm", "template", "portal-namespaces", str(CHART), "--show-only", "templates/policy.yaml",
             "--set", "release=dev", "--set", "serviceAccount.namespace=dev"],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    return out


def judged(policy: Path, resource: dict, tmp_path: Path, username: str = PORTAL, operation: str = "CREATE") -> str:
    """"pass", "fail" or "skip": what admission does with this request."""
    (tmp_path / "resource.yaml").write_text(yaml.safe_dump(resource))
    (tmp_path / "userinfo.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: cli.kyverno.io/v1alpha1
        kind: UserInfo
        metadata: {{name: user}}
        userInfo:
          username: {username}
          groups: [system:serviceaccounts, system:authenticated]
        """))
    (tmp_path / "values.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: cli.kyverno.io/v1alpha1
        kind: Values
        metadata: {{name: values}}
        globalValues:
          request.operation: {operation}
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


def namespace(name: str, **labels: str) -> dict:
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": labels}}


MANAGED = {"joinedcontext.com/managed-by": "joinedcontext-portal"}


def binding(ns: str, role: str = "dev-portal-apps", kind: str = "ClusterRole", subjects=None) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": "joinedcontext-portal", "namespace": ns},
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": kind, "name": role},
        "subjects": subjects if subjects is not None else [{"kind": "ServiceAccount", "name": "portal", "namespace": "dev"}],
    }


@pytest.mark.parametrize("operation", ["CREATE", "UPDATE", "DELETE"])
def test_the_portal_may_write_its_projects_apps_namespace(policy, tmp_path, operation):
    ns = namespace("dev-ovzdusie-apps", **MANAGED, **{"joinedcontext.com/project": "ovzdusie"})
    assert judged(policy, ns, tmp_path, operation=operation) == "pass"


@pytest.mark.parametrize(
    "ns",
    [
        namespace("kube-system", **MANAGED, **{"joinedcontext.com/project": "ovzdusie"}),
        namespace("dev", **MANAGED),
        namespace("dev-ovzdusie-apps", **{"joinedcontext.com/project": "ovzdusie"}),
        namespace("dev-ovzdusie-apps", **MANAGED, **{"joinedcontext.com/project": "doprava"}),
        namespace("dev-ovzdusie-apps", **MANAGED),
        namespace("dev--apps", **MANAGED, **{"joinedcontext.com/project": ""}),
        namespace("prod-ovzdusie-apps", **MANAGED, **{"joinedcontext.com/project": "ovzdusie"}),
    ],
    ids=["system", "its-own", "unmanaged", "other-project", "no-project", "empty-project", "other-release"],
)
@pytest.mark.parametrize("operation", ["CREATE", "DELETE"])
def test_any_other_namespace_is_refused_to_the_portal(policy, tmp_path, ns, operation):
    assert judged(policy, ns, tmp_path, operation=operation) == "fail"


def test_someone_else_is_not_the_policys_business(policy, tmp_path):
    ns = namespace("kube-system")
    assert judged(policy, ns, tmp_path, username="system:serviceaccount:dev:someone") == "skip"


def test_the_portal_may_bind_the_apps_role_to_itself_in_an_apps_namespace(policy, tmp_path):
    assert judged(policy, binding("dev-ovzdusie-apps"), tmp_path) == "pass"


@pytest.mark.parametrize(
    "rb",
    [
        binding("dev"),
        binding("kube-system"),
        binding("dev-ovzdusie-apps", role="cluster-admin"),
        binding("dev-ovzdusie-apps", kind="Role"),
        binding("dev-ovzdusie-apps", subjects=[{"kind": "ServiceAccount", "name": "default", "namespace": "dev-ovzdusie-apps"}]),
        binding("dev-ovzdusie-apps", subjects=[
            {"kind": "ServiceAccount", "name": "portal", "namespace": "dev"},
            {"kind": "Group", "name": "system:authenticated", "apiGroup": "rbac.authorization.k8s.io"},
        ]),
        binding("dev-ovzdusie-apps", subjects=[]),
    ],
    ids=["its-own-namespace", "system", "other-role", "a-role", "other-subject", "extra-subject", "no-subject"],
)
def test_any_other_binding_is_refused_to_the_portal(policy, tmp_path, rb):
    assert judged(policy, rb, tmp_path) == "fail"
