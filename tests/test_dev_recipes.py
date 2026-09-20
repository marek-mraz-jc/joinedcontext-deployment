"""T-0232: the dev-cluster recipes must never touch a foreign cluster."""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_SERVER = "https://2.28.67.127:6443"
FOREIGN_SERVER = "https://10.11.12.13:6443"

requires_just = pytest.mark.skipif(shutil.which("just") is None, reason="just not installed")
requires_kubectl = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")


def kubeconfig(tmp_path: Path, server: str) -> Path:
    path = tmp_path / "kubeconfig.yaml"
    path.write_text(
        textwrap.dedent(
            f"""\
            apiVersion: v1
            kind: Config
            current-context: ctx
            clusters:
              - name: c
                cluster:
                  server: {server}
            contexts:
              - name: ctx
                context: {{cluster: c, user: u}}
            users:
              - name: u
                user: {{token: not-a-real-token}}
            """
        )
    )
    return path


def run_guard(tmp_path: Path, server: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, KUBECONFIG=str(kubeconfig(tmp_path, server)))
    return subprocess.run(
        ["just", "_dev-guard"], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=False
    )


@requires_just
@requires_kubectl
def test_guard_aborts_on_a_foreign_context(tmp_path):
    result = run_guard(tmp_path, FOREIGN_SERVER)
    assert result.returncode != 0
    assert "refusing" in result.stderr


@requires_just
@requires_kubectl
def test_guard_accepts_the_dev_cluster(tmp_path):
    result = run_guard(tmp_path, DEV_SERVER)
    assert result.returncode == 0, result.stderr


@requires_just
@pytest.mark.parametrize("recipe", ["dev-apply", "dev-smoke", "dev-destroy"])
def test_recipe_is_parseable(recipe):
    result = subprocess.run(
        ["just", "--dry-run", recipe], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_smoke_script_requires_both_urls():
    result = subprocess.run(
        ["./scripts/smoke.sh"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "usage" in result.stderr


# T-0388: a meshed ingress controller must also mark 443 opaque, or a meshed client that
# sends its own TLS through it has the stream parsed as HTTP and reset.
MESH_INGRESS_SOURCES = ("justfile", "scripts/test-deployment-variants.sh")


@pytest.mark.parametrize("source", MESH_INGRESS_SOURCES)
def test_every_place_that_meshes_the_ingress_marks_443_opaque(source):
    text = (PROJECT_ROOT / source).read_text(encoding="utf-8")
    if "linkerd.io/inject=enabled" not in text:
        pytest.skip(f"{source} does not mesh a namespace")
    assert "config.linkerd.io/opaque-ports=443" in text, (
        f"{source} meshes the ingress controller without marking 443 opaque: the Portal "
        "resolves the public issuer host onto that controller, so its own HTTPS reaches a "
        "meshed destination on 443 and Linkerd's protocol detection resets it"
    )
