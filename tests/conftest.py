"""Shared, cached environment renders.

Rendering one environment takes about half a minute, and several modules want the same
one, so the render happens once per session per environment and every test reads the same
list of documents.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDER_SH = PROJECT_ROOT / "scripts/render.sh"


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    cache: dict[str, list[dict]] = {}
    out_dir = tmp_path_factory.mktemp("rendered")

    def _rendered(env: str) -> list[dict]:
        if env not in cache:
            if shutil.which("helmfile") is None:
                pytest.skip("helmfile not installed")
            # `deployment/` is gitignored and assembled from the committed defaults plus the
            # example environments; rendering a half-built tree would test the wrong thing.
            if not (PROJECT_ROOT / f"deployment/environments/{env}").is_dir():
                pytest.skip("run `just _dev-assemble` first")
            out = out_dir / f"{env}.yaml"
            result = subprocess.run(
                [str(RENDER_SH), env, str(out)],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr
            cache[env] = [d for d in yaml.safe_load_all(out.read_text()) if isinstance(d, dict)]
        return cache[env]

    return _rendered


@pytest.fixture
def rendered_variant(tmp_path_factory):
    """Render an environment from a copy of the tree, with the committed defaults edited.

    A `--state-values-set` on the command line is merged after the environment values files
    have already rendered, so a flag one of those files reads — `global.ckan.sso`, the
    component list — cannot be overridden that way. The tree is a few megabytes; copying it
    is cheaper than a second committed environment that exists only to be rendered by a test.
    """
    made = tmp_path_factory.mktemp("variant")
    count = 0

    def _rendered(env: str, edit) -> list[dict]:
        nonlocal count
        if shutil.which("helmfile") is None:
            pytest.skip("helmfile not installed")
        if not (PROJECT_ROOT / f"deployment/environments/{env}").is_dir():
            pytest.skip("run `just _dev-assemble` first")
        count += 1
        tree = made / f"tree-{count}"
        shutil.copytree(
            PROJECT_ROOT, tree,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules"),
        )
        edit(tree)
        out = made / f"{env}-{count}.yaml"
        result = subprocess.run(
            [str(tree / "scripts/render.sh"), env, str(out)],
            cwd=str(tree), capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return [d for d in yaml.safe_load_all(out.read_text()) if isinstance(d, dict)]

    return _rendered


def drop_component(tree, env: str, name: str):
    """Remove one component, and the comment above it, from an environment's list.

    The list is read while the environment values render, so `--state-values-set` cannot reach
    it; a copied tree is how an environment without a component is rendered. Edited as text
    because the file is a Go template and a YAML round trip would eat its directives.
    """
    path = tree / f"deployment/environments/{env}/global.yaml.gotmpl"
    lines = path.read_text().splitlines(keepends=True)
    kept = []
    for line in lines:
        if line.strip() == f"- {name}":
            while kept and kept[-1].lstrip().startswith("#"):
                kept.pop()
            continue
        kept.append(line)
    assert len(kept) < len(lines), f"{name} is not in the {env} component list"
    path.write_text("".join(kept))


def set_global(tree, dotted: str, value):
    """Edit one `global.*` value of the copied tree's committed defaults."""
    path = tree / "defaults/environment/global.yaml"
    values = yaml.safe_load(path.read_text())
    target = values["global"]
    *parents, leaf = dotted.split(".")
    for key in parents:
        target = target[key]
    target[leaf] = value
    path.write_text(yaml.safe_dump(values, sort_keys=False))
