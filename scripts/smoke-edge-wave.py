#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""Make the Portal push one edge wave and check that it reached the served Secret (T-5318).

    scripts/smoke-edge-wave.py [--timeout SECONDS]

The rest of the smoke reads the edge APISIX serves, which stays the same when the Portal's write
of Secret apisix-standalone-config is refused (prod, 2026-10-20: a ValidatingAdmissionPolicy
answered 422 for hours, every smoke green). This step takes the Portal's marker
`joinedcontext.com/composed-by: portal` off that Secret and nothing else: the file APISIX serves
is left as it is. The Portal's leader composes the edge file on every sync (reconciler/daemon.rs
converge_edge_file); finding the marker gone, it writes the same file back with the marker
(reconciler/edge_file.rs converge). ok: the marker is back on a newer resourceVersion and no
Portal pod logged "edge file not written" since the step began. ko: the timeout passes, or the
Portal logged that line; the step then puts the marker back itself, because a helm sync of the
apisix configuration chart rewrites the base over the Apps' routes while the marker is missing.
"""

import argparse
import json
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime

SECRET = "apisix-standalone-config"
MARKER = "joinedcontext.com/composed-by"
MARKED = "portal"
PORTAL_LABEL = "app.kubernetes.io/name=portal-portal"
REFUSED = "edge file not written"


def kubectl(*args: str) -> str:
    done = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args[:3])}: {done.stderr.strip()[:300]}")
    return done.stdout


def served() -> dict:
    items = json.loads(kubectl("get", "secrets", "-A", "--field-selector", f"metadata.name={SECRET}", "-o", "json"))["items"]
    if len(items) != 1:
        raise RuntimeError(f"{len(items)} Secrets named {SECRET} in the cluster, expected one in the APISIX namespace")
    return items[0]["metadata"]


def marked(meta: dict) -> bool:
    return (meta.get("annotations") or {}).get(MARKER) == MARKED


def refusals(since: str) -> list[str]:
    """The Portal's "edge file not written" lines since `since`, from every Portal pod."""
    namespaces = kubectl("get", "pods", "-A", "-l", PORTAL_LABEL, "-o", "jsonpath={.items[*].metadata.namespace}").split()
    if not namespaces:
        raise RuntimeError(f"no Portal pod ({PORTAL_LABEL}) in the cluster")
    lines = []
    for namespace in sorted(set(namespaces)):
        logs = kubectl("logs", "-n", namespace, "-l", PORTAL_LABEL, "--all-containers=true",
                       "--since-time", since, "--tail=-1", "--max-log-requests=10")
        lines += [line.strip()[:400] for line in logs.splitlines() if REFUSED in line]
    return lines


def restore(namespace: str) -> None:
    if not marked(served()):
        kubectl("annotate", "secret", "-n", namespace, SECRET, f"{MARKER}={MARKED}", "--overwrite")


def wave(timeout: float, poll: float = 5.0, clock=time.monotonic, sleep=time.sleep) -> tuple[bool, str]:
    meta = served()
    namespace, before = meta["namespace"], meta["resourceVersion"]
    if not marked(meta):
        return False, f"{namespace}/{SECRET} carries no {MARKER}: {MARKED}, the Portal never composed the edge file"
    since = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # --resource-version: a Portal write between the read and this patch fails it, not lost.
    kubectl("annotate", "secret", "-n", namespace, SECRET, f"{MARKER}-", f"--resource-version={before}")
    deadline = clock() + timeout
    try:
        while True:
            refused = refusals(since)
            if refused:
                return False, f"the Portal logged '{REFUSED}': {refused[-1]}"
            meta = served()
            if marked(meta):
                return True, f"the Portal wrote {namespace}/{SECRET} back (resourceVersion {before} -> {meta['resourceVersion']})"
            if clock() >= deadline:
                return False, f"the Portal did not write {namespace}/{SECRET} within {timeout:.0f} s (no sync ran, or its write never landed)"
            sleep(poll)
    finally:
        restore(namespace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Two sync intervals (JC_PORTAL_SYNC_INTERVAL 60 s) plus a slow run on the 16 GB node.
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    # A stopped smoke still puts the marker back (wave's finally).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    try:
        ok, said = wave(args.timeout)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as err:
        ok, said = False, str(err)
    print(f"  {'ok  ' if ok else 'FAIL'}  edge wave: {said}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
