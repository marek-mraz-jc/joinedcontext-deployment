"""What the Portal may write on the cluster, and where (T-0411, AP-13, AP-15, AP-18).

The Portal's app reconciler applies a Deployment, a Service, a Secret and a NetworkPolicy per
app, and starts the build lane's Jobs (AP-80, ADR-N-026). That is the largest privilege the
platform hands any of its own workloads, so the grant is decided in the render and asserted here:
one namespace, the app's four kinds plus the build Jobs and their pods, no ClusterRole, and a
token mount without which the reconciler deploys nothing at all.
"""

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

requires_helmfile = pytest.mark.skipif(
    shutil.which("helmfile") is None, reason="helmfile not installed"
)

# Exactly what an App compiles into (Architecture/16 section 5), and the build lane's Jobs with
# the pods they run and the log a failed build leaves (AP-80, ADR-N-026), and nothing else.
GRANTED = {
    ("apps", "deployments"),
    ("", "services"),
    ("", "secrets"),
    ("networking.k8s.io", "networkpolicies"),
    ("batch", "jobs"),
    ("", "pods"),
    ("", "pods/log"),
}


def portal_deployment(docs):
    return next(
        d
        for d in docs
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "portal"
    )


def portal_env(docs):
    pod = portal_deployment(docs)["spec"]["template"]["spec"]
    container = next(c for c in pod["containers"] if c["name"].startswith("portal"))
    return {e["name"]: e.get("value") for e in container.get("env", [])}


def portal_role(docs):
    return next(
        d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "portal"
    )


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_the_portal_may_write_the_app_kinds_in_one_namespace_and_nothing_else(
    rendered, environment
):
    docs = rendered(environment)
    role = portal_role(docs)

    granted = {
        (group, resource)
        for rule in role["rules"]
        for group in rule["apiGroups"]
        for resource in rule["resources"]
    }
    assert granted == GRANTED, f"{environment}: the Portal's Role is not the app kinds and the build Jobs"

    # Never cluster-wide: a ClusterRole cannot be reasoned about from the chart that renders it.
    cluster_wide = [
        d["metadata"]["name"]
        for d in docs
        if d.get("kind") in {"ClusterRole", "ClusterRoleBinding"}
        and "portal" in d["metadata"]["name"]
    ]
    assert not cluster_wide, f"{environment}: the Portal was granted {cluster_wide}"


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_the_role_is_in_the_namespace_the_portal_is_told_to_deploy_into(
    rendered, environment
):
    """A grant in one namespace and a reconciler writing into another is a 403 per app, once a
    minute, forever. The two come from the same value, and this is what proves it."""
    docs = rendered(environment)
    role = portal_role(docs)
    env = portal_env(docs)

    assert env["JC_PORTAL_APPS_NAMESPACE"] == role["metadata"]["namespace"]

    binding = next(
        d
        for d in docs
        if d.get("kind") == "RoleBinding" and d["metadata"]["name"] == "portal"
    )
    assert binding["metadata"]["namespace"] == role["metadata"]["namespace"]
    assert binding["roleRef"]["kind"] == "Role"
    subject = binding["subjects"][0]
    pod = portal_deployment(docs)["spec"]["template"]["spec"]
    assert subject["name"] == pod["serviceAccountName"]


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_the_portal_carries_the_identity_and_the_settings_together(rendered, environment):
    """Fail-closed in both directions: no token means the client finds no ServiceAccount mount
    and deploys nothing, and no settings means the same. Half of either would be a Portal that
    tries and 403s."""
    docs = rendered(environment)
    pod = portal_deployment(docs)["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is True

    env = portal_env(docs)
    for name in [
        "JC_PORTAL_APPS_NAMESPACE",
        "JC_PORTAL_ORG_DOMAIN",
    ]:
        assert env.get(name), f"{environment}: {name} is not set"
    # AP-26: an app's login is the APISIX edge's openid-connect, so the Portal takes no sidecar image.
    assert "JC_PORTAL_APPS_OAUTH2_PROXY_IMAGE" not in env


def role_verbs(role, group, resource):
    return {
        verb
        for rule in role["rules"]
        if group in rule["apiGroups"] and resource in rule["resources"]
        for verb in rule["verbs"]
    }


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_the_build_lane_grant_starts_and_reads_jobs_and_changes_nothing_else(
    rendered, environment
):
    """The Portal starts a build Job and reads its pod's end; it never edits a running Job or a
    pod (ADR-N-026 section 2)."""
    role = portal_role(rendered(environment))
    assert role_verbs(role, "batch", "jobs") == {"get", "list", "watch", "create", "delete"}
    assert role_verbs(role, "", "pods") == {"get", "list", "watch"}
    assert role_verbs(role, "", "pods/log") == {"get"}


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_the_build_account_mounts_no_token_and_lives_beside_the_apps(rendered, environment):
    """An application's code is untrusted (T-1707): the account its build runs as carries no
    Kubernetes token and is bound to nothing."""
    docs = rendered(environment)
    role = portal_role(docs)
    account = next(
        d
        for d in docs
        if d.get("kind") == "ServiceAccount" and d["metadata"]["name"] == "app-builder"
    )
    assert account["metadata"]["namespace"] == role["metadata"]["namespace"]
    assert account.get("automountServiceAccountToken") is False
    bound = [
        d["metadata"]["name"]
        for d in docs
        if d.get("kind") in {"RoleBinding", "ClusterRoleBinding"}
        and any(s.get("name") == "app-builder" for s in d.get("subjects") or [])
    ]
    assert not bound, f"{environment}: app-builder is bound by {bound}"


@requires_helmfile
@pytest.mark.parametrize("environment", ["local", "dev", "production"])
def test_no_builder_image_is_named_until_one_is_pinned(rendered, environment):
    """Without a pinned digest the Portal starts no build at all, instead of one that pulls a
    moving tag (CC-35)."""
    env = portal_env(rendered(environment))
    image = env.get("JC_APP_BUILDER_IMAGE")
    if image is None:
        assert "JC_APP_BUILDER_SERVICE_ACCOUNT" not in env
    else:
        assert "@sha256:" in image, f"{environment}: builder image {image} is not a digest"
        assert env["JC_APP_BUILDER_SERVICE_ACCOUNT"] == "app-builder"
