#!/usr/bin/env python3
"""The test files one ci.yml `tests` shard runs, balanced by measured time (T-4789).

usage: scripts/ci/test-shard.py <shard> <shards>      prints that shard's files (tests/<name>), one per line
       scripts/ci/test-shard.py --record <pytest log>  rewrites .ci/test-durations.json from the
                                                       output of `pytest --durations=0`

Split by file position (line n in shard n mod 4), the heavy render and container files met in
one shard: shard 4 ran 13.6 min of pytest against 3-5.5 min for the others and passed the job's
15 minutes on three main runs of 2026-10-20. Here each file weighs its seconds in
.ci/test-durations.json and goes, heaviest first, to the shard with the least time so far
(longest processing time first); a file the table lacks weighs the median, so a new test file
still lands in exactly one shard. Shard 1 starts with SHARD_ONE_STEPS seconds, its extra steps
(gitleaks over the history, the docs pin, the kyverno apply).
"""
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / ".ci" / "test-durations.json"
SHARD_ONE_STEPS = 60
# `12.34s call     test_x.py::test_y[param]` (setup and teardown lines count too)
DURATION = re.compile(r"^(\d+(?:\.\d+)?)s (?:call|setup|teardown)\s+(?:tests/)?(test_[\w]+\.py)::")


def files() -> list[str]:
    return sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))


def shards(names: list[str], weights: dict[str, float], count: int) -> list[list[str]]:
    known = [weights[n] for n in names if n in weights]
    default = statistics.median(known) if known else 1.0
    load = [0.0] * count
    load[0] = SHARD_ONE_STEPS
    out: list[list[str]] = [[] for _ in range(count)]
    for name in sorted(names, key=lambda n: (-weights.get(n, default), n)):
        least = min(range(count), key=lambda i: (load[i], i))
        out[least].append(name)
        load[least] += weights.get(name, default)
    return [sorted(s) for s in out]


def record(log: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        m = DURATION.match(line.strip())
        if m:
            totals[m.group(2)] = totals.get(m.group(2), 0.0) + float(m.group(1))
    if not totals:
        raise SystemExit(f"{log}: no `pytest --durations=0` lines in it")
    # pytest hides durations under 5 ms, so a file of only such tests is absent: it weighs nothing
    return {name: round(totals.get(name, 0.0), 1) for name in files()}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--record":
        TABLE.write_text(json.dumps(record(Path(argv[1])), indent=1) + "\n", encoding="utf-8")
        return 0
    if len(argv) != 2 or not all(a.isdigit() for a in argv) or not 1 <= int(argv[0]) <= int(argv[1]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    weights = json.loads(TABLE.read_text(encoding="utf-8"))
    # paths from the repo root, where ci.yml runs pytest: a bare name collects nothing (T-4791)
    print("\n".join(f"tests/{n}" for n in shards(files(), weights, int(argv[1]))[int(argv[0]) - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
