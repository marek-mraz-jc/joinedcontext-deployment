"""T-4674, ADR-N-056: Argo CD keeps dev on main by rendering the helmfile deployment.

The generated component list is the one the generator writes, every enabled release belongs to
exactly one Application with a sync wave, the hold switch stops every Application but the root,
no Application rewrites a Secret, the helmfile plugin marks every object that holds data so it
is never pruned (OPS-55), and Argo CD fits the 600 Mi the node has for it."""

import json
import os
import re
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


def applications(smoke=False):
    """The component Applications, or with `smoke` the gate's Application alone."""
    rendered = root()
    assert rendered.returncode == 0, rendered.stderr
    apps = [d for d in documents(rendered.stdout) if d["kind"] == "Application"]
    return [a for a in apps if (a["metadata"]["name"] == "dev-smoke") == smoke]


def plugin_env(app):
    return {e["name"]: e["value"] for e in app["spec"]["source"]["plugin"]["env"]}


def labels(release):
    return dict(pair.split(":", 1) for pair in release["labels"].split(",") if ":" in pair)


@requires_helmfile
@pytest.mark.parametrize("env", ["dev", "smartcity"])
def test_the_committed_component_list_is_what_the_generator_writes(assembled, env):
    out = subprocess.run(
        ["python3", "scripts/gitops-apps.py", env], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    assert out == (ROOT / f"gitops/{env}.yaml").read_text(), (
        f"gitops/{env}.yaml is stale: python3 scripts/gitops-apps.py {env} > gitops/{env}.yaml"
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
    [smoke] = applications(smoke=True)
    assert int(smoke["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]) == waves[-1] + 1
    assert plugin_env(smoke) == {"ENVIRONMENT": "dev", "COMPONENT": "smoke"}


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
    assert app["spec"]["source"]["helm"]["valueFiles"] == ["../addons.yaml", "../hold.yaml", "../hold-addons.yaml"]
    assert app["spec"]["source"]["helm"]["ignoreMissingValueFiles"] is True

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


GATE = ROOT / "gitops/smoke/files/gate.sh"


def gate(tmp_path, apps, answers, wait="0"):
    """gate.sh with `kubectl` answering `apps` and `curl` answering `answers` by URL."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (tmp_path / "apps.json").write_text(json.dumps({"items": apps}))
    (bin_ / "kubectl").write_text(f"#!/bin/sh\ncat {tmp_path / 'apps.json'}\n")
    lookup = "\n".join(f'  "{url}") echo {code} ;;' for url, code in answers.items())
    (bin_ / "curl").write_text(f'#!/bin/sh\nfor a; do url="$a"; done\ncase "$url" in\n{lookup}\n  *) exit 7 ;;\nesac\n')
    for tool in ("kubectl", "curl"):
        (bin_ / tool).chmod(0o755)
    checks = tmp_path / "checks"
    checks.write_text("".join(f"{200 if 'health' in url else 401} {url}\n" for url in answers))
    return subprocess.run(
        ["bash", str(GATE)], capture_output=True, text=True, timeout=60,
        env={"PATH": f"{bin_}:/usr/bin:/bin", "REVISION": "abc", "SELF": "dev-smoke", "NAMESPACE": "argocd",
             "WAIT_SECONDS": wait, "CHECKS": str(checks)},
    )


def app(name, sync="Synced", health="Healthy", revision="abc", project="platform"):
    return {"metadata": {"name": name}, "spec": {"project": project},
            "status": {"sync": {"status": sync, "revision": revision}, "health": {"status": health}}}


def test_the_gate_waits_for_every_application_at_the_revision_then_checks_each_surface(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("jq not installed")
    surfaces = {"https://portal.x/api/v1/health": "200", "https://portal.x/api/v1/auth/me": "401"}
    green = gate(tmp_path, [app("dev-portal"), app("dev-smoke", sync="OutOfSync"), app("other", project="default", health="Degraded")], surfaces)
    assert green.returncode == 0, green.stdout + green.stderr
    assert "ok    https://portal.x/api/v1/auth/me (401)" in green.stdout

    for stale in (app("dev-portal", revision="old"), app("dev-portal", health="Progressing"), app("dev-portal", sync="OutOfSync")):
        red = gate(tmp_path, [stale], surfaces)
        assert red.returncode == 1 and "FAIL  not every Application is Synced at abc" in red.stdout, red.stdout
        assert "dev-portal" in red.stdout and "https://" not in red.stdout, "no surface is checked before the sync"

    wrong = gate(tmp_path, [app("dev-portal")], {**surfaces, "https://portal.x/api/v1/auth/me": "200"})
    assert wrong.returncode == 1 and "FAIL  https://portal.x/api/v1/auth/me (expected 401, got 200)" in wrong.stdout
    down = gate(tmp_path, [app("dev-portal")], surfaces | {"https://gone.x/health": "unreachable"})
    assert down.returncode == 1


def test_the_gate_chart_runs_after_the_sync_reads_only_and_checks_only_deployed_surfaces():
    image = "ghcr.io/marek-mraz-jc/joinedcontext-gitops-helmfile:1.8.1@sha256:" + "0" * 64
    rendered = subprocess.run(
        ["helm", "template", "dev-smoke", "gitops/smoke", "--namespace", "argocd", "-f", "gitops/dev.yaml",
         "--set-string", "revision=abc", "--set-string", f"image={image}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert rendered.returncode == 0, rendered.stderr
    docs = {d["kind"]: d for d in documents(rendered.stdout)}
    job = docs["Job"]
    assert job["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "PostSync"
    assert job["spec"]["backoffLimit"] == 0
    pod = job["spec"]["template"]
    assert pod["metadata"]["labels"]["app.kubernetes.io/part-of"] == "argocd", "Argo CD's NetworkPolicy"
    assert pod["spec"]["containers"][0]["image"] == image
    assert docs["Role"]["rules"] == [{"apiGroups": ["argoproj.io"], "resources": ["applications"], "verbs": ["get", "list"]}]
    cm = docs["ConfigMap"]["data"]
    assert cm["revision"] == "abc"
    lines = cm["checks"].strip().splitlines()
    assert lines[0] == "200 https://idm.dev.joinedcontext.com/realms/dev/.well-known/openid-configuration"
    assert "200 https://viz.dev.joinedcontext.com/render.html" in lines
    no_viz = subprocess.run(
        ["helm", "template", "dev-smoke", "gitops/smoke", "-f", "gitops/dev.yaml", "--set-string", "revision=abc",
         "--set-string", f"image={image}", "--set", "components=null"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert [line for line in documents(no_viz.stdout)[1]["data"]["checks"].splitlines() if line] == lines[:1]
    unpinned = subprocess.run(
        ["helm", "template", "x", "gitops/smoke", "-f", "gitops/dev.yaml", "--set-string", f"image={image}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert unpinned.returncode != 0 and "revision is required" in unpinned.stderr


def test_argocd_is_scraped_and_a_stuck_or_failed_sync_alerts_where_monitoring_runs(rendered_variant):
    def with_monitoring(tree):
        path = tree / "deployment/environments/addons/global.yaml.gotmpl"
        path.write_text(path.read_text().replace("  - gitops\n", "  - gitops\n  - monitoring\n", 1))

    docs = rendered_variant("addons", with_monitoring)
    [monitor] = [d for d in docs if d["kind"] == "ServiceMonitor" and d["metadata"]["name"] == "argocd-application-controller"]
    services = [d for d in docs if d["kind"] == "Service" and d["metadata"].get("namespace") == "argocd"
                and d["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "argocd-metrics"]
    assert [p["name"] for s in services for p in s["spec"]["ports"]] == [monitor["spec"]["endpoints"][0]["port"]]
    [group] = [g for d in docs if d["kind"] == "PrometheusRule" for g in d["spec"]["groups"] if g["name"] == "gitops"]
    alerts = {r["alert"]: r for r in group["rules"]}
    assert set(alerts) == {"ArgoCDApplicationOutOfSync", "ArgoCDApplicationDegraded", "ArgoCDSyncFailed"}
    assert alerts["ArgoCDApplicationOutOfSync"]["for"] == "15m" and alerts["ArgoCDApplicationDegraded"]["for"] == "15m"
    assert "{{ $labels.name }}" in alerts["ArgoCDApplicationDegraded"]["annotations"]["summary"]


def test_the_status_script_lists_the_failed_first_and_exits_red_until_all_are_green(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("jq not installed")

    def status(apps):
        (tmp_path / "apps.json").write_text(json.dumps({"items": apps}))
        stub = tmp_path / "kubectl"
        stub.write_text(f"#!/bin/sh\ncat {tmp_path / 'apps.json'}\n")
        stub.chmod(0o755)
        return subprocess.run(
            [str(ROOT / "scripts/gitops-status.sh")], capture_output=True, text=True,
            env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        )

    failed = app("dev-zz", sync="OutOfSync", health="Degraded")
    failed["status"]["operationState"] = {"phase": "Failed", "message": "smoke\nred", "finishedAt": "2026-10-18T21:00:00Z"}
    red = status([app("dev-aa", revision="abcdef1234"), failed])
    assert red.returncode == 1
    rows = red.stdout.splitlines()
    assert rows[1].split("\t")[:5] == ["dev-zz", "OutOfSync", "Degraded", "abc", "Failed"] and "smoke red" in rows[1]
    assert rows[2].split("\t")[:4] == ["dev-aa", "Synced", "Healthy", "abcdef1"] and rows[-1] == "NOT GREEN"
    green = status([app("dev-aa")])
    assert green.returncode == 0 and "NOT GREEN" not in green.stdout


def _pin_images():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pin_images", ROOT / "scripts/pin-images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_platform_pin_moves_every_block_of_that_image_and_no_other():
    pin = _pin_images().pin
    new = "sha256:" + "e" * 64
    gateway = (ROOT / "components/context-gateway/images.yaml").read_text()
    text, n = pin(gateway, "joinedcontext-platform", new)
    assert n == 1
    blocks = yaml.safe_load(text)["context-gateway"]
    assert blocks["gateway"]["digest"] == new
    assert blocks["checkouts"]["digest"] != new and blocks["git-sync"]["digest"] != new
    text, n = pin((ROOT / "components/wasm-host/images.yaml").read_text(), "joinedcontext-platform", new)
    assert n == 3 and all(b["digest"] == new for b in yaml.safe_load(text)["wasm-host"].values())
    # Antares is a hand pin: no source the script knows names it.
    assert not any("antares" in image for _, images in _pin_images().SOURCES.values() for image in images)


def test_the_pin_waits_for_a_green_ci_and_refuses_an_image_image_yml_did_not_sign(monkeypatch, capsys):
    module = _pin_images()
    commit = "a" * 40
    calls = []

    def fake(*args, check=True):
        calls.append(args[0])
        out = {"gh": json.dumps(fake.ci),
               "docker": "Name: x\nMediaType: y\nDigest:    sha256:" + "b" * 64 + "\n"}.get(args[0], "")
        return subprocess.CompletedProcess(args, 0 if args[0] != "cosign" else fake.cosign, out, "")

    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "pin_files", lambda pins: pytest.fail("pinned"))
    fake.ci, fake.cosign = [{"status": "in_progress", "conclusion": "", "headSha": commit}], 0
    module.main("platform")
    assert "docker" not in calls and "ci is not green" in capsys.readouterr().err
    fake.ci, fake.cosign = [{"status": "completed", "conclusion": "success", "headSha": commit}], 1
    with pytest.raises(SystemExit, match="no signature"):
        module.main("platform")


def test_a_red_image_build_or_a_refusing_pin_portal_pins_nothing_and_says_so(monkeypatch, capsys, tmp_path):
    """Supervisor 2026-10-19 (pin-images 39193766897): the Portal's image.yml failed after some
    images were out, and pin-portal.sh then crashed the job. A red image.yml waits like an
    unfinished ci; a pin-portal.sh that refuses is said in words and leaves no half pin."""
    module = _pin_images()
    commit = "c" * 40
    runs = {}

    def fake(*args, check=True):
        if args[0] == "gh":
            workflow = args[args.index("--workflow") + 1]
            return subprocess.CompletedProcess(args, 0, json.dumps(runs[workflow]), "")
        out = {"docker": "Name: x\nMediaType: y\nDigest:    sha256:" + "d" * 64 + "\n"}.get(args[0], "")
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "pin_files", lambda pins: pytest.fail("pinned"))
    ok = [{"status": "completed", "conclusion": "success", "headSha": commit}]
    runs.update({"ci.yml": ok, "image.yml": [{"status": "completed", "conclusion": "failure", "headSha": commit}]})
    module.main("portal")
    captured = capsys.readouterr()
    assert "image.yml is not green" in captured.err and captured.out == ""
    runs["image.yml"] = ok
    ran = []
    real_run = subprocess.run
    monkeypatch.setattr(module.subprocess, "run",
                        lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 255 if argv[0].endswith("pin-portal.sh") else 0))
    module.main("portal")
    captured = capsys.readouterr()
    assert "pin-portal.sh refused (exit 255); nothing pinned" in captured.err and captured.out == ""
    assert ran[-1] == ["git", "checkout", "--", "components"]
    # The script itself names a missing image in words instead of dying in set -e.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "docker").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    script = real_run([str(ROOT / "scripts/pin-portal.sh"), commit], env=env, capture_output=True, text=True)
    assert script.returncode == 1 and "no portal image is published" in script.stderr


def test_the_pin_takes_the_commit_of_the_newest_green_image_build_not_the_head_of_main(monkeypatch):
    """T-4696: image.yml builds once an hour, so main's head usually has no images; the pin asks
    GitHub for the newest green image.yml run on main and pins its commit, or says there is none."""
    module = _pin_images()
    asked = []

    def fake(*args, check=True):
        asked.append(args)
        return subprocess.CompletedProcess(args, 0, fake.out, "")

    monkeypatch.setattr(module, "run", fake)
    fake.out = json.dumps([{"headSha": "e" * 40}])
    assert module.built("joinedcontext-platform") == "e" * 40
    query = asked[-1]
    assert query[0] == "gh" and query[query.index("--workflow") + 1] == "image.yml"
    assert query[query.index("--branch") + 1] == "main" and query[query.index("--status") + 1] == "success"
    fake.out = "[]"
    with pytest.raises(SystemExit, match="no green image.yml run on main"):
        module.built("joinedcontext-platform")


@pytest.mark.skipif(shutil.which("just") is None, reason="just not installed")
def test_promotion_takes_only_dev_green_commits_and_release_only_moves_forward(tmp_path):
    """prod's Argo CD follows `release` (T-4678): promote, rollback, promote again, never forced."""
    def git(*args, cwd=tmp_path / "work"):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def just(*args):
        env = dict(os.environ, JUST_NO_DOTENV="true", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(["just", *args], cwd=tmp_path / "work", env=env, capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(tmp_path / "origin")], check=True)
    git("clone", "-q", str(tmp_path / "origin"), "work", cwd=tmp_path)
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    shutil.copy(ROOT / "justfile", tmp_path / "work/justfile")
    shas = []
    for n in range(3):
        (tmp_path / "work/pin").write_text(f"{n}\n")
        git("add", "-A"); git("commit", "-qm", f"pin {n}"); shas.append(git("rev-parse", "HEAD"))
    git("push", "-q", "origin", "main")

    assert just("dev-green", shas[0]).returncode == 0
    refused = just("promote", shas[1])
    assert refused.returncode != 0 and "not green on dev" in refused.stderr
    assert just("promote", shas[0]).returncode == 0
    assert git("ls-remote", "origin", "refs/heads/release").split()[0] == shas[0]
    first = next(t for t in git("ls-remote", "--tags", "origin").split() if t.startswith("refs/tags/prod-"))

    assert just("dev-green", shas[2]).returncode == 0
    assert just("promote", shas[2]).returncode == 0
    back = just("rollback", first.removeprefix("refs/tags/"))
    assert back.returncode == 0, back.stderr
    git("fetch", "-q", "origin", "release")
    assert git("show", "origin/release:pin") == "0"
    assert git("merge-base", "--is-ancestor", shas[2], "origin/release") == ""

    again = just("promote", shas[2])
    assert again.returncode == 0, again.stderr
    git("fetch", "-q", "origin", "release")
    assert git("show", "origin/release:pin") == "2"
    assert just("rollback", "main").returncode != 0


def test_a_portal_commit_that_built_no_builder_keeps_the_pinned_builders(tmp_path):
    """image.yml builds only what a push's paths need (T-2485), so most portal commits publish the
    portal image alone; pin-portal.sh refused every one of them, which held T-4717's flood fix and
    T-4483's docs off dev and prod. Such a commit keeps the builders pinned now and checks those."""
    runner = (ROOT / "components/gitea-runner/images.yaml").read_text()
    kept = re.search(r"app-builder'\n(?:    .*\n)*?    digest: '(sha256:[0-9a-f]{64})'", runner).group(1)
    bin_dir, log = tmp_path / "bin", tmp_path / "docker.log"
    bin_dir.mkdir()
    # Publishes the portal's image only; any pull stops the script after the decision.
    (bin_dir / "docker").write_text(
        f'#!/bin/sh\necho "$*" >> {log}\n'
        'case "$*" in *joinedcontext-portal:*) echo "Digest:    sha256:' + "e" * 64 + '"; exit 0;; '
        '*imagetools*) exit 1;; esac\nexit 3\n')
    (bin_dir / "docker").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    script = subprocess.run([str(ROOT / "scripts/pin-portal.sh"), "c" * 40], env=env, capture_output=True, text=True)
    assert "no builder image" not in script.stderr and "no portal image" not in script.stderr
    pulls = [line for line in log.read_text().splitlines() if line.startswith("pull")]
    assert pulls == [f"pull -q ghcr.io/marek-mraz-jc/joinedcontext-app-builder@{kept}"], log.read_text()


def test_the_pin_bot_checks_the_docs_pin_before_it_commits():
    # T-4931: the bot's push starts no ci run, and it pinned platform 8f28b80 over docs that did
    # not list the gateway's new variables; deployment main went red on its next commit.
    step = (ROOT / ".github/workflows/pin-images.yml").read_text()
    assert step.index("scripts/check-docs-pin.sh") < step.index('git commit -q -m "$message"')


def _portal_ui_pin(tmp_path, published: bool, compare: dict | None):
    """scripts/portal-ui-pin.sh with docker answering `published` and the compare API `compare`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    digest = "sha256:" + "f" * 64
    (bin_dir / "docker").write_text(
        f'#!/bin/sh\necho "Digest:    {digest}"\nexit 0\n' if published else "#!/bin/sh\nexit 1\n")
    (bin_dir / "curl").write_text(
        f"#!/bin/sh\ncat <<'J'\n{json.dumps(compare)}\nJ\n" if compare is not None else "#!/bin/sh\nexit 22\n")
    for stub in ("docker", "curl"):
        (bin_dir / stub).chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_TOKEN="")
    return subprocess.run([str(ROOT / "scripts/portal-ui-pin.sh"), "c" * 40], env=env, capture_output=True, text=True)


def test_a_portal_commit_with_its_own_ui_bundle_pins_that_bundle(tmp_path):
    """T-5297: image.yml built portal-ui for the commit, so the pin is that bundle."""
    result = _portal_ui_pin(tmp_path, published=True, compare=None)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["c" * 40, "sha256:" + "f" * 64]


def test_a_portal_commit_without_ui_changes_keeps_the_pinned_bundle(tmp_path):
    """Most commits publish no bundle: the pinned one stays when ui/ and sdk/ did not change."""
    pinned = yaml.safe_load((ROOT / "components/portal/images.yaml").read_text())["portal"]["ui"]
    result = _portal_ui_pin(tmp_path, published=False,
                            compare={"status": "ahead", "files": [{"filename": "src/api/health.rs"}]})
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [pinned["commit"], pinned["digest"]]


@pytest.mark.parametrize("compare, reason", [
    ({"status": "ahead", "files": [{"filename": "src/main.rs"}, {"filename": "ui/src/App.tsx"}]},
     "changed ui/src/App.tsx since the pinned portal-ui"),
    ({"status": "ahead", "files": [{"filename": "sdk/src/index.ts"}]}, "changed sdk/src/index.ts"),
    ({"status": "diverged", "files": []}, "does not descend from the pinned portal-ui"),
    ({"status": "ahead", "files": [{"filename": f"src/f{n}.rs"} for n in range(300)]}, "300 files or more"),
    (None, "did not answer; nothing decided"),
])
def test_a_bundle_built_from_other_ui_files_is_refused_in_words(tmp_path, compare, reason):
    """A bundle of other ui/ or sdk/ files would call routes the binary may not have (T-5297)."""
    result = _portal_ui_pin(tmp_path, published=False, compare=compare)
    assert result.returncode != 0 and result.stdout == ""
    assert reason in result.stderr, result.stderr
