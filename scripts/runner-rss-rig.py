#!/usr/bin/env python3
"""What a scheduled pipeline leaves in the runner's memory after its run (T-5285).

  scripts/runner-rss-rig.py [--names 500] [--port 42150] [--check 1.0]

Starts the pinned Bento twice in streams mode on the local Docker, once with the runner's `--set`
arguments from components/pipeline-runner/values/runner/base-values.yaml.gotmpl and once with all
but `metrics.mapping`, then creates and deletes --names distinct streams in each, the way the Portal
runs a scheduled pipeline. Prints per runner the series lines one stream leaves in /metrics and the
anonymous RSS growth per name. --check fails when the shipped runner grows by that many MB or more
per name. Needs docker; reads /proc/<pid>/status of the container's process.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "components/pipeline-runner/values/runner/base-values.yaml.gotmpl"
IMAGES = ROOT / "components/pipeline-runner/images.yaml"


def set_args(values: str) -> list[str]:
    """The values of every `- --set` pair in the runner's args, unquoted."""
    out = []
    for raw in re.findall(r"^\s*- --set\n\s*- (.+)$", values, re.MULTILINE):
        raw = raw.strip()
        if raw[:1] == raw[-1:] and raw[:1] in "'\"":
            raw = raw[1:-1]
        out.append(raw)
    return out


def image(images: str) -> str:
    runner = images.split("runner:", 1)[1]
    repo = re.search(r"repository: '([^']+)'", runner).group(1)
    digest = re.search(r"digest: '([^']+)'", runner).group(1)
    return f"{repo}@{digest}"


def stream(processors: int = 30) -> dict:
    """One message through `processors` labelled steps, two of them writes, like a rendered pipeline."""
    steps = [{"label": f"mapping_{i}", "mapping": "root = this"} for i in range(processors - 2)]
    steps += [{"label": "write_0", "mapping": "root = this"}, {"label": "route_1_write_0", "mapping": "root = this"}]
    return {"input": {"label": "input", "generate": {"count": 1, "interval": "", "mapping": 'root = {"a": 1}'}},
            "pipeline": {"processors": steps}, "output": {"label": "output", "drop": {}}}


def per_name_mb(before_kb: int, after_kb: int, names: int) -> float:
    return (after_kb - before_kb) / 1024 / names


def rss_anon_kb(status: str) -> int:
    return int(re.search(r"^RssAnon:\s+(\d+) kB", status, re.MULTILINE).group(1))


def call(method: str, url: str, body: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def run(img: str, sets: list[str], port: int, names: int) -> tuple[int, float]:
    name = f"runner-rss-rig-{port}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    argv = ["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:4195", img, "-w"]
    for s in sets:
        argv += ["--set", s]
    subprocess.run(argv + ["streams"], capture_output=True, check=True)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                call("GET", base + "/ping")
                break
            except OSError:
                time.sleep(0.2)
        pid = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", name],
                             capture_output=True, text=True, check=True).stdout.strip()
        body = json.dumps(stream()).encode()
        call("POST", base + "/streams/probe", body)
        time.sleep(1)
        lines = sum(1 for line in call("GET", base + "/metrics").splitlines() if 'stream="probe"' in line)
        call("DELETE", base + "/streams/probe")
        before = rss_anon_kb(Path(f"/proc/{pid}/status").read_text())
        for i in range(names):
            call("POST", f"{base}/streams/rig-{i}", body)
            call("DELETE", f"{base}/streams/rig-{i}")
        time.sleep(2)
        after = rss_anon_kb(Path(f"/proc/{pid}/status").read_text())
        return lines, per_name_mb(before, after, names)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--names", type=int, default=500)
    ap.add_argument("--port", type=int, default=42150)
    ap.add_argument("--check", type=float, help="fail at this many MB per name or more")
    a = ap.parse_args()
    img = image(IMAGES.read_text())
    shipped = set_args(VALUES.read_text())
    unmapped = [s for s in shipped if not s.startswith("metrics.mapping=")]
    result = {}
    for label, sets, port in (("shipped", shipped, a.port), ("without mapping", unmapped, a.port + 1)):
        lines, mb = run(img, sets, port, a.names)
        result[label] = mb
        print(f"{label}: {lines} series lines per stream, {mb:.3f} MB anonymous RSS per deleted name ({a.names} names)")
    if a.check is not None and result["shipped"] >= a.check:
        print(f"FAIL: {result['shipped']:.3f} MB per name, limit {a.check}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
