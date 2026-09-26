"""scripts/wait-rollouts.sh against a stub kubectl: a pod that is not ready fails the apply, the old
pod of a finished rollout does not, even once its containers exited and it shows Error."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wait-rollouts.sh"

KUBECTL = """#!/usr/bin/env bash
case "$*" in
  "get ns -o name") echo namespace/dev ;;
  *"-o jsonpath="*) printf '%s' "$DELETING" ;;
  *"--no-headers"*) printf 'old-7f5c 0/2 Error 0 113m\\nnew-8dc8 2/2 Running 0 3m\\njob-x 0/1 Completed 0 1h\\n' ;;
  *) ;;
esac
"""


def run(tmp_path: Path, deleting: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "kubectl"
    stub.write_text(KUBECTL)
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", DELETING=deleting)
    return subprocess.run(["bash", str(SCRIPT), "dev", "5"], env=env, capture_output=True, text=True)


def test_a_pod_being_deleted_is_not_a_failed_rollout(tmp_path):
    done = run(tmp_path, "old-7f5c\n")
    assert done.returncode == 0, done.stdout
    assert "not ready" not in done.stdout


def test_a_pod_in_error_that_nobody_deletes_fails_the_apply(tmp_path):
    done = run(tmp_path, "")
    assert done.returncode == 1
    assert "--- not ready: dev/old-7f5c" in done.stdout
    assert "new-8dc8" not in done.stdout.split("--- not ready")[1]
