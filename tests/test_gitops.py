"""T-4674, ADR-N-054: Argo CD keeps dev on main by rendering the helmfile deployment.

The generated component list is the one the generator writes, every enabled release belongs to
exactly one Application with a sync wave, the hold switch stops every Application but the root,
no Application rewrites a Secret, the helmfile plugin marks every object that holds data so it
is never pruned (OPS-55), and Argo CD fits the 600 Mi the node has for it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "gitops/chart"
STATEFUL = {"PersistentVolumeClaim", "Secret", "Namespace", "CustomResourceDefinition"}
NEVER_PRUNED = "Prune=false,Delete=false"

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


@pytest.fixture(scope="module")
def assembled():
    if not (ROOT / "deployment/environments/dev").is_dir():
        pytest.skip("run `just _dev-assemble` first")


@pytest.fixture(scope="module")
def releases(assembled):
    out = subprocess.run(
        ["helmfile", "-f", "deployment/helmfile.yaml", "-e", "dev", "list", "--output", "json"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def root(*args):
    """The root chart rendered with dev's list and the hold file, plus `args`."""
    return subprocess.run(
        ["helm", "template", "dev", str(CHART), "-f", "gitops/dev.yaml", "-f", "gitops/hold.yaml", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def documents(text):
    return [d for d in yaml.safe_load_all(text) if d]


def applications():
    rendered = root()
    assert rendered.returncode == 0, rendered.stderr
    return [d for d in documents(rendered.stdout) if d["kind"] == "Application"]


def plugin_env(app):
    return {e["name"]: e["value"] for e in app["spec"]["source"]["plugin"]["env"]}


def labels(release):
    return dict(pair.split(":", 1) for pair in release["labels"].split(",") if ":" in pair)


@requires_helmfile
def test_the_committed_component_list_is_what_the_generator_writes(assembled):
    out = subprocess.run(
        ["python3", "scripts/gitops-apps.py", "dev"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    assert out == (ROOT / "gitops/dev.yaml").read_text(), (
        "gitops/dev.yaml is stale: python3 scripts/gitops-apps.py dev > gitops/dev.yaml"
    )


@requires_helmfile
def test_every_enabled_release_has_exactly_one_application_and_the_waves_keep_helmfiles_order(releases):
    apps = applications()
    assert len({a["metadata"]["name"] for a in apps}) == len(apps)
    for release in releases:
        component = labels(release).get("component")
        if not release["enabled"] or component == "gitops":
            continue
        owners = [
            a for a in apps
            if plugin_env(a)["COMPONENT"] == component
            and a["spec"]["destination"]["namespace"] == release["namespace"]
            and plugin_env(a).get("NAMESPACE", release["namespace"]) == release["namespace"]
        ]
        assert len(owners) == 1, f"{release['name']} ({component}, {release['namespace']}): {len(owners)} Applications"
    listed = yaml.safe_load((ROOT / "gitops/dev.yaml").read_text())["components"]
    waves = [int(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]) for a in apps]
    assert waves == sorted(waves) and waves == [c["wave"] for c in listed]
    assert all(plugin_env(a)["ENVIRONMENT"] == "dev" and a["spec"]["source"]["plugin"]["name"] == "helmfile" for a in apps)
    assert "gitops" not in {plugin_env(a)["COMPONENT"] for a in apps}, "Argo CD never manages itself"


def test_every_application_syncs_by_itself_and_never_rewrites_a_secret():
    owned = set()
    for app in applications():
        spec, name = app["spec"], app["metadata"]["name"]
        assert spec["project"] == "platform"
        assert spec["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}, name
        options = spec["syncPolicy"]["syncOptions"]
        assert {"ServerSideApply=true", "RespectIgnoreDifferences=true"} <= set(options), name
        assert {"kind": "Secret", "jsonPointers": ["/data", "/stringData"]} in spec["ignoreDifferences"], name
        # Deleting an Application leaves what it applied.
        assert not app["metadata"].get("finalizers"), name
        namespace = spec["destination"]["namespace"]
        creates = "CreateNamespace=true" in options
        assert creates == (namespace not in owned and not namespace.startswith("kube-")), name
        assert ("managedNamespaceMetadata" in spec["syncPolicy"]) == creates, name
        owned.add(namespace)


def test_the_hold_switch_stops_every_application_but_the_root():
    assert yaml.safe_load((ROOT / "gitops/hold.yaml").read_text())["hold"] is False, "main is never committed on hold"
    project = next(d for d in documents(root().stdout) if d["kind"] == "AppProject")
    assert "syncWindows" not in project["spec"]

    held = root("--set", "hold=true", "--set", "reason=Postgres upgrade")
    assert held.returncode == 0, held.stderr
    project = next(d for d in documents(held.stdout) if d["kind"] == "AppProject")
    [window] = project["spec"]["syncWindows"]
    assert window["kind"] == "deny" and window["manualSync"] is True
    assert window["schedule"] == "* * * * *" and window["applications"] == ["dev-*"]
    # The root Application is `dev`, which `dev-*` does not match, so `hold: false` always lands.
    assert all(a["metadata"]["name"].startswith("dev-") for a in applications())

    unexplained = root("--set", "hold=true")
    assert unexplained.returncode != 0 and "a hold names its reason" in unexplained.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_the_plugin_marks_every_object_that_holds_data_and_renders_what_helmfile_does(assembled, tmp_path):
    """The plugin in the sidecar's own image, as Argo CD's uid, on a copy of the tree: the same
    objects `helmfile template` renders for the component, each that holds data marked never to
    be pruned or deleted, and no Helm test hook."""
    images = yaml.safe_load((ROOT / "components/gitops/images.yaml").read_text())["gitops"]["helmfile"]
    image = f"{images['repository']}:{images['tag']}@{images['digest']}"
    component = "postgres"
    plugin = subprocess.run(
        ["docker", "run", "--rm", "-u", "999", "-e", "HOME=/tmp", "-e", "HELM_CACHE_HOME=/tmp/helm/cache",
         "-e", "HELM_CONFIG_HOME=/tmp/helm/config", "-e", "ARGOCD_ENV_ENVIRONMENT=dev",
         "-e", f"ARGOCD_ENV_COMPONENT={component}", "-v", f"{ROOT}:/src:ro", "--entrypoint", "bash", image,
         "-c", "cp -r /src /tmp/repo && cd /tmp/repo && gitops/cmp/generate.sh"],
        capture_output=True, text=True, timeout=600,
    )
    assert plugin.returncode == 0, plugin.stderr[-2000:]
    rendered = documents(plugin.stdout)
    assert rendered, "the plugin rendered nothing"

    helmfile = subprocess.run(
        ["helmfile", "-f", "deployment/helmfile.yaml", "-e", "dev", "-l", f"component={component}",
         "template", "--skip-deps", "-q", "--include-crds"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )

    def identity(d):
        return (d["kind"], d["metadata"]["name"], d["metadata"].get("namespace", ""))

    def is_test_hook(d):
        hooks = (d["metadata"].get("annotations") or {}).get("helm.sh/hook", "")
        return any(h.startswith("test") for h in hooks.split(","))

    expected = [d for d in documents(helmfile.stdout) if d.get("kind") and not is_test_hook(d)]
    assert sorted(map(identity, rendered)) == sorted(map(identity, expected))
    assert not any(is_test_hook(d) for d in rendered)
    holding = [d for d in rendered if d["kind"] in STATEFUL or (d["kind"] == "Cluster" and d["apiVersion"] == "postgresql.cnpg.io/v1")]
    assert {d["kind"] for d in holding} >= {"Cluster", "CustomResourceDefinition"}, "the fixture lost what it tests"
    for d in holding:
        annotations = d["metadata"].get("annotations") or {}
        assert annotations.get("argocd.argoproj.io/sync-options") == NEVER_PRUNED, identity(d)
    for d in rendered:
        if d not in holding:
            assert "argocd.argoproj.io/sync-options" not in (d["metadata"].get("annotations") or {}), identity(d)


def test_the_plugin_refuses_a_name_that_is_no_name(tmp_path):
    for env, component in (("dev", "../etc"), ("dev;rm", "viz"), ("dev", ""), ("dev", "viz,namespace=kube-system")):
        result = subprocess.run(
            ["bash", str(ROOT / "gitops/cmp/generate.sh")], cwd=tmp_path, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "ARGOCD_ENV_ENVIRONMENT": env, "ARGOCD_ENV_COMPONENT": component},
        )
        assert result.returncode != 0 and ("refusing" in result.stderr or "names no" in result.stderr), (env, component)
    assert not any(tmp_path.iterdir()), "a refused name wrote nothing"


MEBI = {"Mi": 1, "Gi": 1024}


def mebibytes(quantity):
    return int(quantity[:-2]) * MEBI[quantity[-2:]]


def test_argocd_and_its_root_render_in_the_addons_environment_within_600_mi(rendered):
    docs = rendered("addons")
    argocd = [d for d in docs if d["metadata"].get("namespace") == "argocd"]
    [app] = [d for d in argocd if d["kind"] == "Application"]
    assert app["metadata"]["name"] == "addons" and app["spec"]["project"] == "default"
    assert app["spec"]["source"]["path"] == "gitops/chart"
    assert app["spec"]["source"]["helm"]["valueFiles"] == ["../addons.yaml", "../hold.yaml"]

    requested = 0
    for workload in argocd:
        if workload["kind"] not in ("Deployment", "StatefulSet") or workload["spec"].get("replicas") == 0:
            continue
        for container in workload["spec"]["template"]["spec"]["containers"]:
            assert "@sha256:" in container["image"], container["name"]
            assert container["resources"]["limits"]["memory"], container["name"]
            requested += mebibytes(container["resources"]["requests"]["memory"])
    assert requested <= 600, f"Argo CD requests {requested} Mi"

    repo = next(d for d in argocd if d["kind"] == "Deployment" and d["metadata"]["name"] == "argocd-repo-server")
    sidecar = next(c for c in repo["spec"]["template"]["spec"]["containers"] if c["name"] == "helmfile")
    assert sidecar["securityContext"]["runAsUser"] == 999 and sidecar["command"] == ["/var/run/argocd/argocd-cmp-server"]

    cm = next(d for d in argocd if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "argocd-cm")["data"]
    assert cm["users.anonymous.enabled"] == "false" and cm["exec.enabled"] == "false"
    oidc = yaml.safe_load(cm["oidc.config"])
    assert oidc["clientID"] == "argocd" and oidc["enablePKCEAuthentication"] is True and "clientSecret" not in oidc
    rbac = next(d for d in argocd if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "argocd-rbac-cm")["data"]
    assert rbac["policy.default"] == "role:readonly" and rbac["policy.csv"].strip() == "g, platform-admin, role:admin"
    assert not [d for d in argocd if d["kind"] == "Deployment" and "dex" in d["metadata"]["name"]]
