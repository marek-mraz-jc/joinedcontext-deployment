"""The prepare component as dev builds it: the hook that readies the namespaces (T-1666, OPS-19).

Prepare renders no manifest; its whole contract is the `prepare` hook of its helmfile, run before
every other release. The shared suites never see it. These pin what that script does on dev: only
on sync and apply, every namespace a component deploys into is ensured, Linkerd injection and the
authenticated default inbound policy are set on each, and a refusal is logged with its words."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


@pytest.fixture(scope="module")
def hook():
    """The prepare hook's shell script, as `helmfile build` resolves it for dev."""
    if not (PROJECT_ROOT / "deployment/environments/dev").is_dir():
        pytest.skip("run `just _dev-assemble` first")
    built = subprocess.run(
        ["helmfile", "-f", "deployment/helmfile.yaml", "-e", "dev", "build"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert built.returncode == 0, built.stderr
    states = [s for s in yaml.safe_load_all(built.stdout) if isinstance(s, dict)]
    (prepare,) = [s for s in states if (s.get("commonLabels") or {}).get("component") == "prepare"]
    (only,) = prepare["hooks"]
    assert only["events"] == ["prepare"] and only["command"] == "sh"
    return only["args"][-1]


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def first_command(script):
    """Where the first kubectl command starts (the comments mention kubectl too)."""
    return script.index("\nkubectl ")


def ensured(script):
    return re.findall(r'kubectl get namespace "([^"]+)" >/dev/null 2>&1 \|\| kubectl create namespace "\1"', script)


@requires_helmfile
def test_the_hook_changes_the_cluster_only_on_sync_and_apply(hook):
    guard = hook.index('if [ "$cmd" != "sync" ] && [ "$cmd" != "apply" ]; then')
    assert hook.index("exit 0", guard) < first_command(hook), "a diff or a template must not touch the cluster"


@requires_helmfile
def test_a_refusal_is_logged_with_its_words(hook):
    assert "set -eu" in hook
    assert hook.index("exec 2>&1") < first_command(hook)


@requires_helmfile
def test_every_namespace_a_component_deploys_into_is_ensured(hook, dev):
    wanted = {d["metadata"]["namespace"] for d in dev if d.get("metadata", {}).get("namespace")}
    assert wanted, "the dev render names no namespace"
    assert wanted <= set(ensured(hook)), f"not ensured: {sorted(wanted - set(ensured(hook)))}"


@requires_helmfile
def test_each_namespace_is_ensured_once_and_quoted(hook):
    names = ensured(hook)
    assert names and len(names) == len(set(names)), names
    assert not re.search(r"kubectl \w+ namespace [^\"\s]", hook), "an unquoted namespace name"


@requires_helmfile
def test_every_ensured_namespace_gets_linkerd_injection(hook):
    for name in ensured(hook):
        assert f'kubectl annotate namespace "{name}" linkerd.io/inject=enabled --overwrite' in hook, name


@requires_helmfile
def test_every_ensured_namespace_admits_only_authenticated_mesh_traffic(hook):
    # Linkerd's default inbound policy decides what a pod without its own Server admits; on dev
    # that is traffic from a meshed, authenticated workload of this cluster and nothing else.
    for name in ensured(hook):
        assert (
            f'kubectl annotate namespace "{name}" config.linkerd.io/default-inbound-policy="cluster-authenticated" --overwrite'
            in hook
        ), name
    assert "default-inbound-policy-" not in hook, "dev must not clear the policy"
