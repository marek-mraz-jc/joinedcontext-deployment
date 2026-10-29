"""The short ci set for a pin-only range and the per-release dev apply of a pin (T-6110)."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changes = _load("scripts/ci/changes.py", "ci_changes")
apply_pins = _load("scripts/apply-pins.py", "apply_pins")


@pytest.mark.parametrize("files, short", [
    (["components/portal/images.yaml"], True),
    (["components/portal/images.yaml", "components/context-gateway/images.yaml"], True),
    # a chart file beside a pin, a seed beside a pin, a pin under another name: the full set
    (["components/portal/images.yaml", "components/portal/charts/portal/templates/deployment.yaml"], False),
    (["components/portal/images.yaml", "components/context-gateway/seed/helsinki/helsinki-endpoint-catalog.yaml"], False),
    (["components/portal/values/images.yaml"], False),
    (["images/viz/images.yaml"], False),
    (["components/portal/images.yaml.orig"], False),
    ([], False),
])
def test_only_a_range_of_images_yaml_files_takes_the_short_set(files, short):
    assert changes.pins_only(files) is short


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "components/portal").mkdir(parents=True)
    (tmp_path / "components/portal/images.yaml").write_text("a: 1\n")
    (tmp_path / "components/portal/seed.yaml").write_text("a: 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def run(repo, base, head="HEAD"):
    done = subprocess.run(["python3", str(ROOT / "scripts/ci/changes.py"), base, head], cwd=repo,
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def test_the_cli_reads_the_range_from_git(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "components/portal/images.yaml").write_text("a: 2\n")
    git(repo, "commit", "-qam", "pin")
    assert run(repo, base).splitlines()[0] == "pins_only=true"
    pin = git(repo, "rev-parse", "HEAD")
    (repo / "components/portal/seed.yaml").write_text("a: 2\n")
    (repo / "components/portal/images.yaml").write_text("a: 3\n")
    git(repo, "commit", "-qam", "pin and seed")
    assert run(repo, pin) == "pins_only=false"


@pytest.mark.parametrize("base", ["0" * 40, "", "not-a-sha", "deadbeefdeadbeef"])
def test_an_unreadable_base_takes_the_full_set(repo, base):
    assert run(repo, base) == "pins_only=false"


def write_release(root, name, objects):
    (root / name / "chart/templates").mkdir(parents=True)
    (root / name / "chart/templates/all.yaml").write_text(yaml.safe_dump_all(objects))


def deployment(image):
    return {"kind": "Deployment", "metadata": {"name": "portal", "namespace": "dev",
            "annotations": {"checksum/secret": image}},
            "spec": {"template": {"spec": {"containers": [{"image": image}]}}}}


def test_only_a_release_whose_objects_moved_is_applied(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    write_release(old, "portal-portal", [deployment("p@sha256:1")])
    write_release(new, "portal-portal", [deployment("p@sha256:2")])
    # a random secret value and its checksum annotation move on every render: not a change
    write_release(old, "secrets-db-portal", [{"kind": "Secret", "metadata": {"name": "db"}, "data": {"p": "YQ=="}}])
    write_release(new, "secrets-db-portal", [{"kind": "Secret", "metadata": {"name": "db"}, "data": {"p": "Yg=="}}])
    write_release(old, "agent-runner-proxy", [deployment("x")])
    write_release(new, "agent-runner-proxy", [deployment("x"), {"kind": "ConfigMap", "metadata": {"name": "c"}}])
    write_release(new, "viz-server", [deployment("v")])
    assert apply_pins.moved(old, new) == ["agent-runner-proxy", "portal-portal", "viz-server"]


def test_a_release_gone_is_refused(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    write_release(old, "portal-portal", [deployment("a")])
    write_release(old, "portal-ui", [deployment("a")])
    write_release(new, "portal-portal", [deployment("a")])
    with pytest.raises(apply_pins.Refused, match="portal-ui"):
        apply_pins.moved(old, new)


def test_a_range_with_more_than_pins_is_refused(monkeypatch):
    monkeypatch.setattr(apply_pins.changes, "changed", lambda base, head: ["components/portal/images.yaml", "justfile"])
    with pytest.raises(apply_pins.Refused, match="justfile"):
        apply_pins.releases("dev", "abc1234")
    monkeypatch.setattr(apply_pins.changes, "changed", lambda base, head: None)
    with pytest.raises(apply_pins.Refused, match="cannot read"):
        apply_pins.releases("dev", "abc1234")
    monkeypatch.setattr(apply_pins.changes, "changed", lambda base, head: [])
    assert apply_pins.releases("dev", "abc1234") == []


def test_each_release_maps_to_its_component_label():
    listing = [{"name": "portal-portal", "labels": "chart:portal,component:portal,release:portal-portal"},
               {"name": "networkpolicies-portal", "labels": "component:networkpolicies,name:networkpolicies-portal"},
               {"name": "bare", "labels": ""}]
    assert apply_pins.owners(listing, ["portal-portal", "networkpolicies-portal"]) == ["networkpolicies", "portal"]
    with pytest.raises(apply_pins.Refused, match="bare"):
        apply_pins.owners(listing, ["bare"])


def test_a_pin_reruns_the_tests_of_its_images_and_of_every_images_yaml():
    tests = {
        "tests/test_portal.py": 'yaml.safe_load((ROOT / "components/portal/images.yaml").read_text())',
        "tests/test_gateway.py": '(ROOT / "components" / "context-gateway" / "images.yaml").read_text()',
        "tests/test_keycloak.py": 'IMAGES = ROOT / "components/keycloak/images.yaml"',
        "tests/test_every.py": 'for p in ROOT.glob("components/*/images.yaml"): ...',
        "tests/test_unnamed.py": '"""reads images.yaml through a helper"""',
        "tests/test_other.py": "assert True",
    }
    assert changes.pin_tests(["components/portal/images.yaml"], tests) == [
        "tests/test_every.py", "tests/test_portal.py", "tests/test_unnamed.py"]
    assert changes.pin_tests(["components/context-gateway/images.yaml"], tests) == [
        "tests/test_every.py", "tests/test_gateway.py", "tests/test_unnamed.py"]


HELMFILE_STUB = """#!/usr/bin/env bash
# template: one release directory per component, its object the component's images.yaml;
# list: the component label of each; diff and sync: the arguments they were given.
set -eu
case " $* " in
  *" template "*)
    out=""; prev=""
    for a in "$@"; do [ "$prev" = --output-dir ] && out="$a"; prev="$a"; done
    for c in a b; do
      mkdir -p "$out/$c-x"
      { echo "kind: ConfigMap"; echo "metadata: {name: $c}"; echo "data:"; sed 's/^/  /' "components/$c/images.yaml"; } > "$out/$c-x/t.yaml"
    done ;;
  *" list "*) echo '[{"name":"a-x","labels":"component:a"},{"name":"b-x","labels":"component:b"}]' ;;
  *) echo "HELMFILE $*" ;;
esac
"""

KUBECTL_STUB = """#!/usr/bin/env bash
case "$*" in
  "config view"*) echo "https://116.203.134.249:6443" ;;
  *jc-release*) cat "$STUB_DIR/applied" ;;
esac
"""


@pytest.fixture
def tree(tmp_path):
    """A copy of the repository's apply path with helmfile, kubectl and the cluster scripts stubbed."""
    if shutil.which("just") is None:
        pytest.skip("just not installed")
    work, stubs = tmp_path / "work", tmp_path / "bin"
    for rel in ("justfile", "scripts/apply-pins.py", "scripts/ci/changes.py", "scripts/release-diff.py",
                "defaults/deployment", ".ci/example-deployments"):
        src, dst = ROOT / rel, work / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    for name in ("verify-pinned-images.py", "wait-rollouts.sh", "release.py", "smoke-component.sh"):
        (work / "scripts" / name).write_text(f'#!/bin/sh\necho "RAN {name} $*"\n')
        (work / "scripts" / name).chmod(0o755)
    stubs.mkdir()
    for name, text in (("helmfile", HELMFILE_STUB), ("kubectl", KUBECTL_STUB)):
        (stubs / name).write_text(text)
        (stubs / name).chmod(0o755)
    for c in ("a", "b"):
        (work / "components" / c).mkdir(parents=True)
        (work / "components" / c / "images.yaml").write_text("digest: '1'\n")
    git(work, "init", "-q")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    git(work, "add", ".")
    git(work, "commit", "-qm", "applied")
    (tmp_path / "applied").write_text(git(work, "rev-parse", "HEAD"))
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path), "JUST_NO_DOTENV": "true"}
    return work, env


def just(work, env, *args):
    return subprocess.run(["just", "dev-apply-pins", *args], check=False, cwd=work, env=env, capture_output=True, text=True)


def test_dev_apply_pins_syncs_only_the_release_the_pin_moved(tree):
    work, env = tree
    (work / "components/a/images.yaml").write_text("digest: '2'\n")
    git(work, "commit", "-qam", "pin a")
    dry = just(work, env, "", "true")
    assert dry.returncode == 0, dry.stderr
    assert "HELMFILE -f deployment/helmfile.yaml -e dev diff --concurrency 4 --selector name=a-x" in dry.stdout
    assert "name=b-x" not in dry.stdout and "sync" not in dry.stdout and "RAN" not in dry.stdout
    done = just(work, env)
    assert done.returncode == 0, done.stderr
    assert "HELMFILE -f deployment/helmfile.yaml -e dev sync --concurrency 4 --selector name=a-x\n" in done.stdout
    lines = [line for line in done.stdout.splitlines() if line.startswith("RAN")]
    assert lines == ["RAN verify-pinned-images.py dev", "RAN wait-rollouts.sh dev", "RAN release.py record dev dev",
                     "RAN smoke-component.sh dev.joinedcontext.com dev a"]


def test_dev_apply_pins_refuses_a_range_with_more_than_pins(tree):
    work, env = tree
    (work / "components/a/images.yaml").write_text("digest: '2'\n")
    (work / "components/a/values.yaml").write_text("x: 1\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "pin a and a value")
    done = just(work, env)
    assert done.returncode != 0
    assert "run the full `just dev-apply`" in done.stderr
    assert "HELMFILE" not in done.stdout and "RAN" not in done.stdout
