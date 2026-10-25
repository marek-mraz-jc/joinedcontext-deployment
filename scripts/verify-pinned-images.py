#!/usr/bin/env python3
"""Refuse an apply whose render carries a platform image without our signature (T-5564, OPS-27).

`scripts/pin-images.py` checks the signature when it pins, and `scripts/validate-dev.py` checks the
running pods an hour later. A digest written into an images.yaml by hand passed neither before it
ran. This script sits between the render and `helmfile sync` in `just dev-apply` and
`just prod-apply`: every `ghcr.io/marek-mraz-jc/*@sha256:` reference anywhere in the rendered
environment (container images, init containers, env values, config) must pass `cosign verify` for
a keyless certificate our own GitHub workflows minted, and every `image:` of ours must be a digest.
Every problem is printed, so one run names each digest to fix; any problem exits 1 and the apply
stops before it changes the cluster.

  scripts/verify-pinned-images.py <environment>          render, then verify (deployment/ assembled)
  scripts/verify-pinned-images.py <env> --render FILE    verify an existing render

`--registry` and `--key` exist for the offline selftest (tests/test_verify_pinned_images.py): a
throwaway registry on localhost and a local key pair stand in for ghcr.io and the keyless identity.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "marek-mraz-jc"
ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY = rf"^https://github\.com/{OWNER}/"


def references(render: str, registry: str):
    """(every pinned image of ours as `repo@digest`, every `image:` of ours that is not pinned)."""
    prefix = re.escape(f"{registry}/{OWNER}/")
    pinned = {
        f"{m.group(1)}@{m.group(2)}"
        for m in re.finditer(rf"({prefix}[a-z0-9._/-]+)(?::[\w.-]+)?@(sha256:[0-9a-f]{{64}})", render)
    }
    unpinned = {
        m.group(1)
        for m in re.finditer(rf"""^\s*-?\s*image:\s*["']?({prefix}[^\s"']+)""", render, re.MULTILINE)
        if "@sha256:" not in m.group(1)
    }
    return sorted(pinned), sorted(unpinned)


def cosign_verify(image: str, key: str | None) -> str | None:
    """None when the signature holds, else the reason cosign gave."""
    trust = ["--key", key, "--insecure-ignore-tlog=true"] if key else [
        "--certificate-oidc-issuer", ISSUER, "--certificate-identity-regexp", IDENTITY]
    try:
        run = subprocess.run(["cosign", "verify", *trust, image], check=False, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "cosign verify did not answer within 120 s"
    if run.returncode == 0:
        return None
    lines = run.stderr.strip().splitlines()
    return lines[-1] if lines else f"cosign exited {run.returncode}"


def problems(render: str, registry: str, key: str | None) -> tuple[int, list[str]]:
    pinned, unpinned = references(render, registry)
    found = [f"{image} is not pinned by digest: pin it with scripts/pin-images.py" for image in unpinned]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for image, why in zip(pinned, pool.map(lambda i: cosign_verify(i, key), pinned)):
            if why is not None:
                found.append(
                    f"{image} carries no signature from a {OWNER} workflow ({why}); "
                    "pin a digest the image workflow signed (scripts/pin-images.py)"
                )
    return len(pinned), found


def render(environment: str, out: Path):
    run = subprocess.run([str(ROOT / "scripts/render.sh"), environment, str(out), "--deployed"], check=False, cwd=ROOT)
    if run.returncode != 0:
        sys.exit(f"verify-pinned-images: rendering {environment} failed; run `just _dev-assemble` first")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("environment")
    parser.add_argument("--render", type=Path, help="an existing render of the environment")
    parser.add_argument("--registry", default="ghcr.io")
    parser.add_argument("--key", help="verify against this public key instead of the keyless identity")
    args = parser.parse_args()
    if shutil.which("cosign") is None:
        print("verify-pinned-images: cosign is not installed, so no signature can be verified", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        path = args.render or Path(scratch) / f"{args.environment}.yaml"
        if args.render is None:
            render(args.environment, path)
        checked, found = problems(path.read_text(), args.registry, args.key)
    for problem in found:
        print(f"verify-pinned-images: {problem}", file=sys.stderr)
    if found:
        print(f"verify-pinned-images: {len(found)} problem(s) in {args.environment}; nothing was applied", file=sys.stderr)
        return 1
    if checked == 0:
        print(f"verify-pinned-images: the {args.environment} render names no {OWNER} image", file=sys.stderr)
        return 1
    print(f"verify-pinned-images: {checked} {OWNER} digest(s) of {args.environment} carry our signature")
    return 0


if __name__ == "__main__":
    sys.exit(main())
