#!/usr/bin/env python3
"""Which ci set a commit range needs (T-6110): the short pin set or the full set.

    scripts/ci/changes.py <base> <head>     prints pins_only=true|false and pin_tests=<files>
                                            (GITHUB_OUTPUT lines)

A range whose every changed file is a components/<c>/images.yaml (the commits pin-images writes)
is pins_only: ci renders every environment, verifies the pinned signatures, checks the docs pin
and runs the tests that read an images.yaml, not the six shards. Anything else, an unreadable
range (a new branch's all-zero base, a force-pushed base), or an empty diff is the full set: a
missed match costs minutes, a wrong match would skip a gate.

pin_tests are the tests/*.py files that read an images.yaml (grep -l): those naming only other
components' images.yaml are left out (a Portal pin need not rerun keycloak's 13 minutes); one
reading every images.yaml (a glob) or naming none by path stays in.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PIN = re.compile(r"^components/([a-z0-9-]+)/images\.yaml$")
# components/<c>/images.yaml, or "components" / "<c>" / "images.yaml" as pathlib spells it
NAMED = re.compile(r'components/([a-z0-9-]+)/images\.yaml|"components" */ *"([a-z0-9-]+)" */ *"images\.yaml"')


def pins_only(files: list[str]) -> bool:
    return bool(files) and all(PIN.match(f) for f in files)


def pin_tests(files: list[str], tests: dict[str, str]) -> list[str]:
    """The test files (name -> text) a pin of `files` reruns."""
    moved = {m.group(1) for f in files if (m := PIN.match(f))}
    keep = []
    for name, text in sorted(tests.items()):
        if "images.yaml" not in text:
            continue
        named = {a or b for a, b in NAMED.findall(text)}
        if "*/images.yaml" in text or not named or named & moved:
            keep.append(name)
    return keep


def changed(base: str, head: str) -> list[str] | None:
    if not re.fullmatch(r"[0-9a-f]{7,40}", base or "") or set(base) == {"0"}:
        return None
    done = subprocess.run(["git", "diff", "--name-only", "--no-renames", base, head],
                          capture_output=True, text=True, check=False)
    return done.stdout.split() if done.returncode == 0 else None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    files = changed(argv[0], argv[1])
    short = files is not None and pins_only(files)
    print(f"pins_only={'true' if short else 'false'}")
    if short:
        tests = {str(p): p.read_text(encoding="utf-8") for p in Path("tests").glob("*.py")}
        print(f"pin_tests={' '.join(pin_tests(files, tests))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
