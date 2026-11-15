#!/usr/bin/env python3
"""Render parity (T-6979 §4.4, T-6982): two checkouts render every environment to the same manifests.

    scripts/render-parity.py <old-checkout> <new-checkout> <environment>...
    scripts/render-parity.py --compare <old-dir> <new-dir> [--again <old-dir-2>] <environment>...

The first form assembles deployment/ in each checkout (`just _dev-assemble`, JC_ENVIRONMENTS passed
through) and renders the environments with its own scripts/render-all.sh; the second compares
<dir>/<environment>.yaml files rendered before. Each render is compared as FULL manifests: the
documents matched by kind, namespace and name, `checksum/...` annotations masked, and the values
the charts generate at random (passwords, keys) masked where two renders of the old tree differ
(the render form renders the old checkout twice; --again names that second render). The goldens
(.ci/golden, kind and name only) are no proof of parity. Exit 0 when every environment matches,
1 with a unified diff per environment that does not, 2 on a usage or render error.
"""

import difflib
import os
import re
import subprocess
import sys
import tempfile

import yaml

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
ENV_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MASK = "<masked>"


def mask(node):
    """The document with every `checksum/...` key's value masked: a hash of other rendered text."""
    if isinstance(node, dict):
        return {k: MASK if isinstance(k, str) and k.startswith("checksum/") else mask(v) for k, v in node.items()}
    if isinstance(node, list):
        return [mask(v) for v in node]
    return node


def documents(path: str) -> dict:
    """Each document of a render under "<kind> <namespace>/<name>" (#n for a repeat), checksums masked."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    docs: dict = {}
    for doc in yaml.load_all(text, Loader=Loader):
        if not isinstance(doc, dict) or not doc:
            continue
        meta = doc.get("metadata") or {}
        key = f"{doc.get('kind', '')} {meta.get('namespace', '')}/{meta.get('name', '')}"
        n, unique = 1, key
        while unique in docs:
            n += 1
            unique = f"{key} #{n}"
        docs[unique] = mask(doc)
    return docs


def noise(a, b, path=()):
    """The paths where two renders of ONE tree differ: values the chart generates at random."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {p for k in a.keys() & b.keys() for p in noise(a[k], b[k], path + (k,))}
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return {p for i, (x, y) in enumerate(zip(a, b)) for p in noise(x, y, path + (i,))}
    return set() if a == b else {path}


def masked(doc, paths, path=()):
    if path in paths:
        return MASK
    if isinstance(doc, dict):
        return {k: masked(v, paths, path + (k,)) for k, v in doc.items()}
    if isinstance(doc, list):
        return [masked(v, paths, path + (i,)) for i, v in enumerate(doc)]
    return doc


def lines(doc) -> list[str]:
    return yaml.dump(doc, Dumper=Dumper, sort_keys=True, default_flow_style=False, width=1 << 20).splitlines(keepends=True)


def compare(old_dir: str, new_dir: str, envs: list[str], again_dir: str = "") -> int:
    """Diff each environment's documents; with again_dir (a second render of the old tree), the
    paths where the two old renders differ are masked on both sides first."""
    changed = 0
    for env in envs:
        paths = [os.path.join(d, f"{env}.yaml") for d in (old_dir, new_dir, again_dir) if d]
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            print(f"render-parity: {missing[0]} is missing", file=sys.stderr)
            return 2
        old, new = documents(paths[0]), documents(paths[1])
        again = documents(paths[2]) if again_dir else {}
        differing = masked_paths = 0
        for key in sorted(old.keys() | new.keys()):
            random = noise(old[key], again[key]) if key in old and key in again else set()
            masked_paths += len(random)
            a = lines(masked(old[key], random)) if key in old else []
            b = lines(masked(new[key], random)) if key in new else []
            diff = list(difflib.unified_diff(a, b, f"old/{env}: {key}", f"new/{env}: {key}", n=2))
            if diff:
                differing += 1
                sys.stdout.writelines(diff)
        changed += bool(differing)
        print(f"render-parity: {env}: {differing} of {len(old.keys() | new.keys())} documents differ"
              f" ({masked_paths} generated values masked)", file=sys.stderr)
    return 1 if changed else 0


def render(checkout: str, out: str, envs: list[str]) -> None:
    env = dict(os.environ, JUST_NO_DOTENV="true")
    subprocess.run(["just", "_dev-assemble"], cwd=checkout, env=env, check=True)
    subprocess.run([os.path.join(checkout, "scripts/render-all.sh"), out, *envs], cwd=checkout, env=env, check=True)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    again = ""
    if "--again" in argv:
        i = argv.index("--again")
        if i + 1 >= len(argv):
            print("render-parity: --again names a directory", file=sys.stderr)
            return 2
        again = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    first, second, envs = (argv[2], argv[3], argv[4:]) if argv[1] == "--compare" else (argv[1], argv[2], argv[3:])
    if not envs or not all(ENV_NAME.match(e) for e in envs):
        print("render-parity: name one or more environments ([a-z0-9-])", file=sys.stderr)
        return 2
    if argv[1] == "--compare":
        return compare(first, second, envs, again)
    with tempfile.TemporaryDirectory(prefix="render-parity.") as tmp:
        dirs = [os.path.join(tmp, "old"), os.path.join(tmp, "new"), os.path.join(tmp, "again")]
        try:
            for checkout, d in zip((first, second, first), dirs):
                render(os.path.abspath(checkout), d, envs)
        except subprocess.CalledProcessError as err:
            print(f"render-parity: render failed: {err}", file=sys.stderr)
            return 2
        return compare(dirs[0], dirs[1], envs, dirs[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
