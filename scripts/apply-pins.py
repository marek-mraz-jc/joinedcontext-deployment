#!/usr/bin/env python3
"""The releases a range changes, for `just dev-apply` (T-6135) and `just dev-apply-pins` (T-6110).

    scripts/apply-pins.py plan <environment> <base>       "full", or the releases whose render moved since <base>
    scripts/apply-pins.py releases <environment> <base>   the same for a pin-only range (refuses any other file)
    scripts/apply-pins.py components <environment> <release>...  the components of those releases

An images.yaml feeds every component's values (`.Values.images`, defaults/environment), so the
Portal's pin also moves agent-runner, gitea-runner and mqtt-brokers objects. Guessing by
component would miss those; `releases` renders the environment at <base> (a git worktree) and
at HEAD, one directory per release, and names each release with an object added or changed.
Secret values and checksum/* annotations are masked as scripts/release-diff.py masks them: the
secrets chart invents fresh values on every render.

HEAD is rendered twice: an object whose two HEAD renders differ carries random values (a
chart's generated password), so only that object is compared masked; every other object,
deterministic Secrets included, is compared byte for byte.

`plan` answers "full" (the reason on stderr) whenever a scoped sync could leave a change
unapplied: no trusted base (none recorded, a dirty one, an unreadable range), a change to how
helmfile builds releases (a helmfile template, a component.yaml with its needs and hooks, the
assembled defaults), a failed render, a release added or removed, or a CustomResourceDefinition
added, removed or changed. An empty range plans no release.

`releases` refuses (exit 3) a range that touches any file other than a components/<c>/images.yaml.
Both need deployment/ assembled at HEAD (`just _dev-assemble`) and the environment's chart
repositories added.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changes = _module(ROOT / "scripts/ci/changes.py", "changes")
release_diff = _module(ROOT / "scripts/release-diff.py", "release_diff")


class Refused(Exception):
    pass


FULL = "full"
# Files that change how helmfile builds a release (needs, hooks, conditions, the release list)
# rather than what it renders: a scoped sync cannot be judged from the render.
STRUCTURE = re.compile(r"(^|/)helmfile[^/]*\.(ya?ml|gotmpl)$|^components/[^/]+/component\.yaml$"
                       r"|^defaults/deployment/|^\.ci/example-deployments/helmfile\.yaml$")


def objects(release_dir: Path) -> dict[str, tuple[str, str]]:
    """`kind namespace/name` -> (the object, the object masked), over every file helmfile wrote for a release."""
    out = {}
    for path in sorted(release_dir.rglob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(doc, dict) and doc.get("kind"):
                meta = doc.get("metadata") or {}
                key = f"{doc['kind']} {meta.get('namespace') or '-'}/{meta.get('name')}"
                exact = yaml.safe_dump(doc, sort_keys=True)
                out[key] = (exact, yaml.safe_dump(release_diff.normalise(doc), sort_keys=True))
    return out


def _differs(old: dict, new: dict, again: dict | None) -> list[str]:
    """Object keys added, removed or changed; an object `again` (a second HEAD render) does not
    reproduce is compared masked, every other one exactly."""
    out = sorted(old.keys() ^ new.keys())
    for key in old.keys() & new.keys():
        noisy = again is None or again.get(key, ("", ""))[0] != new[key][0]
        if old[key][1 if noisy else 0] != new[key][1 if noisy else 0]:
            out.append(key)
    return out


def moved(old: Path, new: Path, again: Path | None = None) -> list[str]:
    """Release names under `new` whose objects differ from `old`; a release gone is refused."""
    gone = sorted({p.name for p in old.iterdir()} - {p.name for p in new.iterdir()})
    if gone:
        raise Refused(f"releases gone at HEAD: {', '.join(gone)}; run the full `just dev-apply`")
    out = []
    for r in sorted(new.iterdir(), key=lambda p: p.name):
        twice = objects(again / r.name) if again and (again / r.name).is_dir() else None
        if not (old / r.name).is_dir() or _differs(objects(old / r.name), objects(r), twice):
            out.append(r.name)
    return out


def scoped(old: Path, new: Path, again: Path) -> list[str]:
    """The releases to sync, or Refused when only a full sync is safe: a release added or
    removed, or a CustomResourceDefinition that moved (other releases' objects depend on it)."""
    added = sorted({p.name for p in new.iterdir()} - {p.name for p in old.iterdir()})
    if added:
        raise Refused(f"releases added at HEAD: {', '.join(added)}")
    names = moved(old, new, again)
    for name in names:
        twice = objects(again / name) if (again / name).is_dir() else None
        crds = [k for k in _differs(objects(old / name), objects(new / name), twice)
                if k.startswith("CustomResourceDefinition ")]
        if crds:
            raise Refused(f"{name} changes {', '.join(crds[:3])}")
    return names


def render(tree: Path, environment: str, out: Path) -> None:
    done = subprocess.run(
        ["helmfile", "-f", "deployment/helmfile.yaml", "-e", environment, "template", "--skip-deps", "-q",
         "--output-dir", str(out), "--output-dir-template", "{{ .OutputDir }}/{{ .Release.Name }}"],
        cwd=tree, capture_output=True, text=True, check=False)
    if done.returncode:
        raise Refused(f"render of {environment} in {tree} failed:\n{done.stderr[-4000:]}")


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode:
        raise Refused(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def releases(environment: str, base: str) -> list[str]:
    files = changes.changed(base, "HEAD")
    if files is None:
        raise Refused(f"cannot read the range {base}..HEAD; run the full `just dev-apply`")
    if not files:
        return []
    if not changes.pins_only(files):
        others = [f for f in files if not changes.PIN.match(f)]
        raise Refused(f"{base[:12]}..HEAD changes more than pins ({', '.join(others[:5])}); "
                      "run the full `just dev-apply`")
    return _renders(environment, base, lambda old, new, again: moved(old, new, again))


def plan(environment: str, base: str) -> list[str]:
    """The releases `just dev-apply` syncs for base..HEAD; Refused names why it must be a full sync."""
    if not re.fullmatch(r"[0-9a-f]{40}", base or ""):
        raise Refused(f"no trusted applied commit ({base or 'none recorded'})")
    files = changes.changed(base, "HEAD")
    if files is None:
        raise Refused(f"cannot read the range {base[:12]}..HEAD")
    structure = [f for f in files if STRUCTURE.search(f)]
    if structure:
        raise Refused(f"{base[:12]}..HEAD changes how helmfile builds releases ({', '.join(structure[:5])})")
    if not files:
        return []
    return _renders(environment, base, scoped)


def _renders(environment: str, base: str, judge) -> list[str]:
    """Renders base once and HEAD twice, and hands the three directories to `judge`."""
    with tempfile.TemporaryDirectory(prefix="apply-pins-") as tmp:
        tmp = Path(tmp)
        git("worktree", "add", "--detach", "-q", str(tmp / "base"), base)
        try:
            subprocess.run(["just", "_dev-assemble"], cwd=tmp / "base", check=True, capture_output=True,
                           env={**os.environ, "JUST_NO_DOTENV": "true"})
            # the renders at once: each waits on chart pulls and helm, not on one core
            with ThreadPoolExecutor(3) as pool:
                for job in [pool.submit(render, tmp / "base", environment, tmp / "old"),
                            pool.submit(render, ROOT, environment, tmp / "new"),
                            pool.submit(render, ROOT, environment, tmp / "again")]:
                    job.result()
            return judge(tmp / "old", tmp / "new", tmp / "again")
        finally:
            git("worktree", "remove", "--force", str(tmp / "base"))


def components(environment: str, names: list[str]) -> list[str]:
    """The `component` label helmfile gives each named release (commonLabels of its helmfile)."""
    done = subprocess.run(["helmfile", "-f", "deployment/helmfile.yaml", "-e", environment, "list", "--output", "json"],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode:
        raise Refused(f"helmfile list of {environment} failed:\n{done.stderr[-2000:]}")
    return owners(json.loads(done.stdout), names)


def owners(listing: list[dict], names: list[str]) -> list[str]:
    label = {r["name"]: dict(kv.split(":", 1) for kv in r["labels"].split(",") if ":" in kv).get("component")
             for r in listing}
    unknown = [n for n in names if not label.get(n)]
    if unknown:
        raise Refused(f"no component label on the release(s) {', '.join(unknown)}")
    return sorted({label[n] for n in names})


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[0] == "releases":
            print("\n".join(releases(argv[1], argv[2])))
        elif len(argv) == 3 and argv[0] == "plan":
            try:
                print("\n".join(plan(argv[1], argv[2])))
            except Refused as e:
                print(f"apply-pins: full sync: {e}", file=sys.stderr)
                print(FULL)
        elif len(argv) >= 2 and argv[0] == "components":
            print("\n".join(components(argv[1], argv[2:])))
        else:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
    except Refused as e:
        print(f"apply-pins: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
