"""The local k3d harness that ci-full's deployment-variants job drives.

Its failures cost a 45-minute job to discover, so the cheap preconditions are asserted here.
"""

import re
import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_DEPLOYMENT = PROJECT_ROOT / "dev-deployment"
STARTUP = DEV_DEPLOYMENT / "startup.sh"


def test_the_k3d_config_startup_asks_for_exists():
    """A rename that misses the file only shows as `no context exists with the name`."""
    configs = set(re.findall(r"k3d cluster create --config (\S+)", STARTUP.read_text()))
    assert configs, "startup.sh no longer creates a cluster from a config file"
    for config in configs:
        assert (DEV_DEPLOYMENT / config).is_file(), f"{config} is referenced but not in dev-deployment/"


def test_the_harness_only_needs_tools_a_ci_runner_has():
    """dos2unix cost a whole ci-full run; nothing here may depend on a desktop utility."""
    desktop_only = ("dos2unix", "unix2dos", "pbcopy", "open ", "xdg-open")
    for script in sorted(DEV_DEPLOYMENT.glob("*.sh")) + [PROJECT_ROOT / "scripts/test-deployment-variants.sh"]:
        body = "\n".join(
            line for line in script.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        for tool in desktop_only:
            assert tool not in body, f"{script.name} calls {tool.strip()}, which no runner has"


VARIANTS = PROJECT_ROOT / "scripts/test-deployment-variants.sh"


def test_the_variant_harness_builds_the_deployment_tree_it_syncs_from():
    """`deployment/` is assembled, not committed, so a fresh checkout has no state file.

    The harness syncing from a tree it never built is invisible locally — anyone who has run
    `just dev-apply` has the directory already — and costs a 45-minute CI job to discover.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "deployment"], cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    ).stdout
    assert not tracked.strip(), "deployment/ is tracked now; this test's premise is stale"

    body = VARIANTS.read_text()
    assert "helmfile -f ./deployment/" in body, "harness no longer syncs from deployment/"
    assert "_dev-assemble" in body, "syncs from a tree a fresh checkout does not have"

    # Order inside run_variant, not order of definitions: assembling starts by removing
    # deployment/, so doing it after the scratch environment is written throws that away.
    run_variant = body[body.index("run_variant() {"):].split("\n}\n")[0]
    code = "\n".join(l for l in run_variant.splitlines() if not l.lstrip().startswith("#"))
    calls = [m.group(1) for m in re.finditer(r"\b(assemble_deployment|write_env_overlay|deploy_variant)\b", code)]
    assert calls[:3] == ["assemble_deployment", "write_env_overlay", "deploy_variant"], calls


CI_FULL = PROJECT_ROOT / ".github/workflows/ci-full.yml"


def k3d_deploy_job():
    return yaml.safe_load(CI_FULL.read_text())["jobs"]["k3d-deploy"]


def test_the_nightly_deployment_job_runs_the_one_variant_that_fits_a_runner():
    """0,0,0 is single namespace, all-in-one, no mesh. Any other triplet on a 7 GB runner is
    the eight-variant sweep's job, and a job that quietly grew a second variant is a job that
    stopped finishing inside its timeout (TS-19)."""
    job = k3d_deploy_job()
    runs = [step["run"] for step in job["steps"] if "run" in step]
    variants = [line for line in "\n".join(runs).splitlines() if "test-deployment-variants.sh" in line]
    assert variants == ["./scripts/test-deployment-variants.sh 0,0,0"], variants
    assert job["if"] == "github.event_name != 'push'", "nightly and on dispatch, never a push gate"
    # The Done-when asks for a median under 25 minutes; the ceiling has to be near it, or a
    # job that doubled in length is only discovered by a human noticing.
    assert job["timeout-minutes"] <= 30, job["timeout-minutes"]


def test_the_nightly_deployment_job_keeps_what_it_needs_to_explain_a_failure():
    """A red 25-minute job whose logs are gone by the time anyone looks is a red job nobody
    fixes. Both steps are `if: failure()`, so a green run uploads nothing."""
    steps = k3d_deploy_job()["steps"]
    collect = next(step for step in steps if "diagnostics" in step.get("run", ""))
    assert collect["if"] == "failure()"
    for command in ("kubectl get all -A", "kubectl describe pod", "kubectl logs", "--previous"):
        assert command in collect["run"], command

    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact"))
    assert upload["if"] == "failure()"
    assert upload["with"]["path"] == "diagnostics/"


def test_the_nightly_deployment_job_installs_every_tool_the_harness_demands():
    """The harness stops at its pre-flight with `missing required tools`, which costs a job
    and says nothing about the deployment. `linkerd` is the exception: it is demanded only by
    a variant that enables the mesh, and this job runs the one that does not."""
    needed = set(re.search(r"^need=\(([^)]*)\)", VARIANTS.read_text(), re.M).group(1).split())
    needed |= {"k3d", "curl"}  # added by the managed-cluster branch, which this job takes
    needed -= {"kubectl", "helm", "yq", "curl"}  # every GitHub runner image ships these
    job = yaml.safe_dump(k3d_deploy_job())
    for tool in sorted(needed):
        assert tool in job, f"the harness needs {tool} and the job never installs it"
