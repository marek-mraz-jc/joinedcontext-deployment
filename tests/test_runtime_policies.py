"""The policies this chart deploys, judged as the chart renders them.

Two groups. The CNPG label-protection policies must let the operator's own initdb Job
through and still block anyone else claiming those labels (T-0232 / T-0234). The Pod
Security Standards policies must hold for the workloads this deployment owns and stop at
its namespaces (T-0008)."""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "components/runtime-policies/charts/runtime-policies"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CNPG_SA = "system:serviceaccount:dev:postgres-operator-cloudnative-pg"
JOB_CONTROLLER_SA = "system:serviceaccount:kube-system:job-controller"

requires_kyverno = pytest.mark.skipif(shutil.which("kyverno") is None, reason="kyverno CLI not installed")
requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module")
def policies(tmp_path_factory):
    """The two operator policies as the chart renders them for an enforcing environment."""
    out = tmp_path_factory.mktemp("policies") / "policies.yaml"
    rendered = subprocess.run(
        ["helm", "template", "runtime-policies", str(CHART),
         "--set", "failureAction=Enforce", "--set", "linkerd.enabled=false",
         "--set", "cnpgOperatorNamespace=dev", "--namespace", "dev"],
        capture_output=True, text=True, check=True,
    ).stdout
    out.write_text(rendered)
    return out


def userinfo(tmp_path: Path, username: str) -> Path:
    path = tmp_path / "userinfo.yaml"
    path.write_text(
        textwrap.dedent(
            f"""\
            apiVersion: cli.kyverno.io/v1alpha1
            kind: UserInfo
            metadata:
              name: user
            userInfo:
              username: {username}
              groups: [system:serviceaccounts, system:authenticated]
            """
        )
    )
    return path


def failed_rules(policies: Path, resource: Path, username: str, tmp_path: Path) -> set:
    """Names of the rules `kyverno apply` reports as failed for this creator."""
    result = subprocess.run(
        ["kyverno", "apply", str(policies), "--resource", str(resource),
         "--userinfo", str(userinfo(tmp_path, username))],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode in (0, 1), result.stderr or result.stdout
    return set(re.findall(r"^\d+ - (\S+) ", result.stdout, re.M))


@requires_kyverno
@requires_helm
def test_cnpg_initdb_job_and_its_pod_are_allowed(policies, tmp_path):
    """The operator creates the Job; the Job controller creates its Pod. Both pass."""
    assert failed_rules(policies, FIXTURES / "cnpg-initdb-job.yaml", CNPG_SA, tmp_path) == set()
    assert failed_rules(policies, FIXTURES / "cnpg-initdb-job.yaml", JOB_CONTROLLER_SA, tmp_path) == set()


@requires_kyverno
@requires_helm
def test_a_foreign_identity_may_not_claim_the_cnpg_labels(policies, tmp_path):
    # Kyverno autogen mirrors the Pod rules onto the Job, which is what keeps the
    # job-controller exemption honest.
    failed = failed_rules(policies, FIXTURES / "spoofed-cnpg-pod.yaml",
                          "system:serviceaccount:dev:attacker", tmp_path)
    assert {"cnpg-labels-only-from-cnpg", "cnpg-jobrole-only-from-cnpg",
            "autogen-cnpg-labels-only-from-cnpg", "autogen-cnpg-jobrole-only-from-cnpg"} <= failed


POD_SECURITY_RULES = {"require-drop-all", "validate-readOnlyRootFilesystem",
                      "run-as-non-root-user", "run-as-non-root"}


@pytest.fixture(scope="module")
def pod_security(tmp_path_factory):
    """The Pod Security policies as the chart renders them for the `dev` deployment.

    Rendered rather than read from files/upstream, because two of the things worth testing
    — that the policies stop at this deployment's namespaces, and that the action is the
    environment's — exist only after the template has run."""
    out = tmp_path_factory.mktemp("pod-security") / "policies.yaml"
    rendered = subprocess.run(
        ["helm", "template", "runtime-policies", str(CHART),
         "--set", "failureAction=Enforce", "--set", "linkerd.enabled=false",
         "--set", "operators.enabled=false", "--set", "podSecurity.namespaces={dev}",
         "--namespace", "dev"],
        capture_output=True, text=True, check=True,
    ).stdout
    out.write_text(rendered)
    return out


@requires_helm
def test_the_rendered_policies_carry_the_environment_action_and_stop_at_its_namespaces(pod_security):
    """The vendored copies match every namespace and carry the deprecated
    spec.validationFailureAction; neither may survive into what gets applied."""
    docs = [d for d in yaml.safe_load_all(pod_security.read_text()) if d]
    by_name = {d["metadata"]["name"]: d for d in docs}
    assert {"drop-all-capabilities", "require-ro-rootfs",
            "require-run-as-non-root-user", "require-run-as-nonroot"} <= set(by_name)
    for name in ("drop-all-capabilities", "require-ro-rootfs",
                 "require-run-as-non-root-user", "require-run-as-nonroot"):
        policy = by_name[name]
        assert "validationFailureAction" not in policy["spec"], f"{name} kept the deprecated field"
        for rule in policy["spec"]["rules"]:
            assert rule["validate"]["failureAction"] == "Enforce", f"{name}/{rule['name']}"
            for matcher in rule["match"]["any"]:
                assert matcher["resources"]["namespaces"] == ["dev"], f"{name}/{rule['name']}"


@requires_helm
def test_no_pod_security_policy_is_rendered_without_a_namespace_to_apply_it_to(tmp_path):
    """A ClusterPolicy with no namespace scope matches every namespace, including the ones
    the cluster distribution owns. Rendering nothing is the safe answer."""
    rendered = subprocess.run(
        ["helm", "template", "runtime-policies", str(CHART),
         "--set", "failureAction=Enforce", "--set", "linkerd.enabled=false",
         "--set", "operators.enabled=false", "--namespace", "dev"],
        capture_output=True, text=True, check=True,
    ).stdout
    names = {d["metadata"]["name"] for d in yaml.safe_load_all(rendered) if d}
    assert "drop-all-capabilities" not in names, "scopeless Pod Security policy rendered"


@requires_kyverno
@requires_helm
def test_a_hardened_pod_passes_every_pod_security_policy(pod_security, tmp_path):
    assert failed_rules(pod_security, FIXTURES / "hardened-pod.yaml", CNPG_SA, tmp_path) == set()


@requires_kyverno
@requires_helm
def test_an_unhardened_pod_fails_every_pod_security_policy(pod_security, tmp_path):
    failed = failed_rules(pod_security, FIXTURES / "unhardened-pod.yaml", CNPG_SA, tmp_path)
    assert POD_SECURITY_RULES <= failed, f"missed: {sorted(POD_SECURITY_RULES - failed)}"


@requires_kyverno
@requires_helm
def test_the_same_pod_outside_this_deployment_is_not_judged(pod_security, tmp_path):
    """`traefik` belongs to the cluster distribution. Its pods are none of our business, and
    a policy that blocked its upgrades would be worse than the gap it closes."""
    failed = failed_rules(pod_security, FIXTURES / "unhardened-pod-other-namespace.yaml",
                          CNPG_SA, tmp_path)
    assert not (POD_SECURITY_RULES & failed), f"judged outside its scope: {sorted(failed)}"


@requires_kyverno
@requires_helm
def test_the_linkerd_init_container_may_still_add_the_capabilities_it_needs(pod_security, tmp_path):
    """It drops ALL and adds back the two it needs for iptables. disallow-capabilities-strict
    would reject it, and with it every meshed pod on the cluster."""
    assert failed_rules(pod_security, FIXTURES / "linkerd-meshed-pod.yaml", CNPG_SA, tmp_path) == set()


def mutated(policies: Path, resource: Path, tmp_path: Path) -> dict:
    """The resource as admission would let it through, after the chart's mutations."""
    out = tmp_path / "mutated"
    subprocess.run(
        ["kyverno", "apply", str(policies), "--resource", str(resource), "-o", str(out)],
        capture_output=True, text=True, check=False,
    )
    written = list(out.rglob("*.yaml"))
    assert len(written) == 1, f"expected one mutated resource, got {written}"
    # kyverno writes the patched resource followed by a document separator
    return next(d for d in yaml.safe_load_all(written[0].read_text()) if d)


@requires_kyverno
@requires_helm
def test_a_pod_that_never_asked_for_a_token_does_not_get_one(pod_security, tmp_path):
    """The upstream charts of apisix, Keycloak and keycloak-config-cli expose no
    automountServiceAccountToken field at all, so the pod is where it has to be set."""
    pod = mutated(pod_security, FIXTURES / "hardened-pod.yaml", tmp_path)
    assert pod["spec"]["automountServiceAccountToken"] is False


@requires_kyverno
@requires_helm
def test_a_justified_pod_keeps_its_token(pod_security, tmp_path):
    """Taking the token from the CloudNativePG instance manager would stop it watching its
    own Cluster; the annotation is how that stays visible instead of hard-coded."""
    pod = mutated(pod_security, FIXTURES / "api-token-justified-pod.yaml", tmp_path)
    assert "automountServiceAccountToken" not in pod["spec"]
    failed = failed_rules(pod_security, FIXTURES / "api-token-justified-pod.yaml",
                          CNPG_SA, tmp_path)
    assert "api-token-needs-a-reason" not in failed


@requires_kyverno
@requires_helm
def test_a_pod_that_asks_for_a_token_without_a_reason_is_refused(pod_security, tmp_path):
    failed = failed_rules(pod_security, FIXTURES / "api-token-unjustified-pod.yaml",
                          CNPG_SA, tmp_path)
    assert "api-token-needs-a-reason" in failed


@requires_kyverno
@requires_helm
def test_a_pod_outside_this_deployment_keeps_its_token(pod_security, tmp_path):
    """traefik, cert-manager and kyverno itself are API clients by trade. A cluster-wide
    token mutation would break them on their next restart."""
    pod = mutated(pod_security, FIXTURES / "unhardened-pod-other-namespace.yaml", tmp_path)
    assert "automountServiceAccountToken" not in pod["spec"]


HELM_TEST_HOOK = "helm.sh/hook"


def _pod_specs_of_jobs(docs: list[dict]):
    """Every Job and CronJob pod template the deployment renders, minus helm test hooks.

    Test hooks are excluded on the same grounds the repository's own Kyverno scan excludes
    them: `helmfile sync` never applies them, so no admission webhook ever judges them.
    """
    for doc in docs:
        kind = doc.get("kind")
        if kind not in ("Job", "CronJob"):
            continue
        hook = (doc["metadata"].get("annotations") or {}).get(HELM_TEST_HOOK, "")
        if "test" in hook:
            continue
        spec = doc["spec"]
        template = (
            spec["template"]
            if kind == "Job"
            else spec["jobTemplate"]["spec"]["template"]
        )
        yield doc["metadata"]["name"], template["spec"]


@pytest.mark.parametrize("env", ["local", "dev", "production"])
def test_every_rendered_job_satisfies_the_policies_this_cluster_enforces(rendered, env):
    """The Pod Security policies are tested above against synthetic pods, and the render is
    tested elsewhere, but nothing put the two together — so a Job that the cluster would refuse
    rendered happily and only failed at `dev-apply`, inside a post-upgrade hook:

        admission webhook "validate.kyverno.svc-fail" denied the request:
        Job/dev/ckan-datastore-db-create-role-ckan-datastore-read-readonly was blocked
        drop-all-capabilities, require-ro-rootfs, require-run-as-nonroot

    A hook Job is the worst place to learn it: the release is already half-upgraded.
    """
    failures = []
    for name, spec in _pod_specs_of_jobs(rendered(env)):
        pod = spec.get("securityContext") or {}
        for container in spec.get("containers", []):
            ctx = container.get("securityContext") or {}
            where = f"{name}/{container['name']}"
            if not ctx.get("runAsNonRoot", pod.get("runAsNonRoot")):
                failures.append(f"{where}: runAsNonRoot is not true")
            if not ctx.get("readOnlyRootFilesystem"):
                failures.append(f"{where}: readOnlyRootFilesystem is not true")
            if (ctx.get("capabilities") or {}).get("drop") != ["ALL"]:
                failures.append(f"{where}: capabilities.drop is not [ALL]")
    assert not failures, f"{env} renders Jobs this cluster's Kyverno policies refuse:\n" + "\n".join(
        failures
    )


@pytest.mark.parametrize("env", ["local", "dev", "production"])
def test_every_workload_that_mounts_an_api_token_justifies_it(rendered, env):
    """`justify-api-token-access` refuses a pod that mounts a ServiceAccount token without
    `security.joinedcontext.com/api-access-reason`. The policy is judged at admission, so a
    workload that forgets the annotation renders cleanly, passes CI, and then fails silently on
    the cluster: the ReplicaSet cannot create a pod, the Deployment sits at UP-TO-DATE 0, the old
    pod keeps serving, and `helm --wait` reports only `context deadline exceeded`.

    That is what T-0411 did to the Portal — the reason was written, but in a YAML comment rather
    than the annotation the policy reads.
    """
    failures = []
    for doc in rendered(env):
        if doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        template = doc["spec"]["template"]
        spec = template["spec"]
        if spec.get("automountServiceAccountToken") is not True:
            continue
        reason = (template["metadata"].get("annotations") or {}).get(
            "security.joinedcontext.com/api-access-reason"
        )
        if not (reason or "").strip():
            failures.append(f"{doc['kind']}/{doc['metadata']['name']}")
    assert not failures, (
        f"{env}: these mount an API token with no security.joinedcontext.com/api-access-reason, "
        f"so Kyverno refuses their pods: {failures}"
    )


@requires_helm
def test_every_placeholder_is_substituted(policies):
    """A placeholder the chart never replaced is a rule comparing a real principal against a
    string nobody can be: Kyverno accepts the policy, the reports stay clean, and the control
    the rule names is never enforced (T-0815, OPS-30, CC-12)."""
    left = sorted(set(re.findall(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+", policies.read_text())))
    assert left == [], f"the rendered policies still carry placeholders: {left}"
