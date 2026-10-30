"""`just dev-apply` syncs only the releases whose render moved since dev's applied commit (T-6135).

Each case is a range (the files it touches) and two renders, base and HEAD, one directory per
release as helmfile writes them; the plan is the release list or a full sync. Whatever the
planner cannot judge safely is a full sync: a skipped release would leave a NetworkPolicy,
RBAC or Kyverno change unapplied.
"""

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = "4a1de6980a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d"

spec = importlib.util.spec_from_file_location("apply_scoped", ROOT / "scripts/apply-pins.py")
apply_pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply_pins)


def deployment(name, image):
    return {"kind": "Deployment", "metadata": {"name": name, "namespace": "dev",
            "annotations": {"checksum/secret": image}},
            "spec": {"template": {"spec": {"containers": [{"image": image}]}}}}


def config(name, data):
    return {"kind": "ConfigMap", "metadata": {"name": name, "namespace": "dev"}, "data": data}


def secret(name, value):
    return {"kind": "Secret", "metadata": {"name": name, "namespace": "dev"}, "data": {"p": value}}


def crd(version):
    return {"kind": "CustomResourceDefinition", "metadata": {"name": "endpoints.jc.example"},
            "spec": {"versions": [{"name": version}]}}


BEFORE = {
    "portal-portal": [deployment("portal", "p@sha256:1")],
    "gitea-seed": [config("seed", {"bbsk.yaml": "a: 1"})],
    "keycloak-keycloak": [deployment("keycloak", "k@sha256:1"), config("realm", {"x": "1"})],
    "secrets-db-portal": [secret("db", "YQ==")],
    "operator-crds": [crd("v1")],
}


def write(root, releases):
    for name, objects in releases.items():
        (root / name / "chart/templates").mkdir(parents=True)
        (root / name / "chart/templates/all.yaml").write_text(yaml.safe_dump_all(objects))


def change(**moved):
    out = {k: list(v) for k, v in BEFORE.items()}
    for name, objects in moved.items():
        if objects is None:
            out.pop(name)
        else:
            out[name] = objects
    return out


def plan(monkeypatch, tmp_path, files, head, again=None, base=BASE):
    """The plan for a range touching `files` whose HEAD renders `head` (and `again` the second time)."""
    def renders(environment, base, judge):
        dirs = [tmp_path / "old", tmp_path / "new", tmp_path / "again"]
        for d, releases in zip(dirs, [BEFORE, head, head if again is None else again]):
            write(d, releases)
        return judge(*dirs)

    monkeypatch.setattr(apply_pins.changes, "changed", lambda b, h: files)
    monkeypatch.setattr(apply_pins, "_renders", renders)
    try:
        return apply_pins.plan("dev", base)
    except apply_pins.Refused as e:
        return f"full: {e}"


@pytest.mark.parametrize("files, head, expected", [
    # a pin moves the one release that renders the image
    (["components/portal/images.yaml"], change(**{"portal-portal": [deployment("portal", "p@sha256:2")]}),
     ["portal-portal"]),
    # a seed edit moves only the seed release
    (["seeds/bbsk/pipelines/air.yaml"], change(**{"gitea-seed": [config("seed", {"bbsk.yaml": "a: 2"})]}),
     ["gitea-seed"]),
    # a values change in one component moves that component's release
    (["components/keycloak/values/keycloak/base-values.yaml.gotmpl"],
     change(**{"keycloak-keycloak": [deployment("keycloak", "k@sha256:1"), config("realm", {"x": "2"})]}),
     ["keycloak-keycloak"]),
    # a range whose render did not move syncs nothing
    (["README.md"], change(), []),
])
def test_a_range_syncs_only_the_releases_whose_render_moved(monkeypatch, tmp_path, files, head, expected):
    assert plan(monkeypatch, tmp_path, files, head) == expected


@pytest.mark.parametrize("files, head, reason", [
    (["components/viz/values/server/base-values.yaml.gotmpl"],
     {**BEFORE, "viz-server": [deployment("viz", "v")]}, "releases added at HEAD: viz-server"),
    (["components/viz/component.yaml"], change(), "changes how helmfile builds releases"),
    (["components/secrets/charts/secrets-generator/values.yaml"], change(**{"gitea-seed": None}),
     "releases gone at HEAD: gitea-seed"),
    (["components/operator/charts.yaml"], change(**{"operator-crds": [crd("v2")]}),
     "operator-crds changes CustomResourceDefinition -/endpoints.jc.example"),
    (["components/portal/helmfile.yaml.gotmpl"], change(), "changes how helmfile builds releases"),
    (["defaults/deployment/environments/default.yaml"], change(), "changes how helmfile builds releases"),
    (["components/portal/images.yaml"], change(), "no trusted applied commit"),
    (None, change(), "cannot read the range"),
])
def test_what_the_render_cannot_judge_is_a_full_sync(monkeypatch, tmp_path, files, head, reason):
    base = "" if reason.startswith("no trusted") else BASE
    got = plan(monkeypatch, tmp_path, files, head, base=base)
    assert got.startswith("full: ") and reason in got, got


def test_a_failed_render_is_a_full_sync(monkeypatch, capsys):
    monkeypatch.setattr(apply_pins.changes, "changed", lambda b, h: ["components/portal/images.yaml"])

    def fails(environment, base, judge):
        raise apply_pins.Refused("render of dev in /tmp/x failed:\nError: chart not found")

    monkeypatch.setattr(apply_pins, "_renders", fails)
    assert apply_pins.main(["plan", "dev", BASE]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "full"
    assert "full sync: render of dev" in out.err


def test_a_secrets_chart_re_render_alone_selects_nothing(monkeypatch, tmp_path):
    # the secrets chart invents a fresh value per render: both HEAD renders differ, so it is masked
    head = change(**{"secrets-db-portal": [secret("db", "Yg==")],
                     "portal-portal": [deployment("portal", "p@sha256:1") | {"metadata": {
                         "name": "portal", "namespace": "dev", "annotations": {"checksum/secret": "new"}}}]})
    again = change(**{"secrets-db-portal": [secret("db", "Yw==")],
                      "portal-portal": [deployment("portal", "p@sha256:1") | {"metadata": {
                          "name": "portal", "namespace": "dev", "annotations": {"checksum/secret": "again"}}}]})
    assert plan(monkeypatch, tmp_path, ["seeds/x.yaml"], head, again) == []


def test_a_deterministic_secret_change_is_synced(monkeypatch, tmp_path):
    # both HEAD renders agree, so the Secret is compared unmasked and its new value is applied
    head = change(**{"secrets-db-portal": [secret("db", "Yg==")]})
    assert plan(monkeypatch, tmp_path, ["components/secrets/secrets.yaml"], head) == ["secrets-db-portal"]


def test_dev_apply_falls_back_to_a_full_sync_and_keeps_its_gates():
    text = (ROOT / "justfile").read_text()
    body = text[text.index("\ndev-apply full="):text.index("\n_smoke ")]
    assert "apply-pins.py plan dev" in body and "|| plan=full" in body
    assert "*-dirty) base=\"\"" in body
    order = ["_dev-guard", "verify-pinned-images.py dev", "-e dev sync", "wait-rollouts.sh dev", "release.py record dev dev"]
    assert [body.index(s) for s in order] == sorted(body.index(s) for s in order)
