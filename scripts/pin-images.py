#!/usr/bin/env python3
"""Pin the images of the newest commit a source repository's `main` built (ADR-N-056 §2.4, OPS-57).

    python3 scripts/pin-images.py platform     # or: portal
    python3 scripts/pin-images.py platform --tier production
    PIN_COMMIT=<40 hex> python3 scripts/pin-images.py platform   # a green commit behind the head

For the commit of the newest green `image.yml` run on `main` of the source repository (the lane
builds once an hour, not per push, so the head of `main` usually has no images yet; T-4696) it pins, in every
`components/*/images.yaml`, the digest each image of that commit was published under, but only
when the repository's `ci` and `image.yml` runs on the commit are green and `cosign verify` accepts the signature
the repository's own `image.yml` made on `main`. It writes the files and prints the commit
message; it commits nothing (`.github/workflows/pin-images.yml` renders, commits and pushes).
Exit 0 with nothing written when the pins are current or the commit is not ready yet.
A branch preview image (tag pv-<slug>-<sha12>, T-5547) is never pinned: preview.yml builds and
signs it, and this script reads only image.yml runs, the commit's own tag and image.yml's identity
(tests/test_pins.py, "pv_tags_are_never_pinned").

Tiers (T-4721): `dev` (the default) pins the `dev-<N>` images ship publishes, built and
smoke-tested. `production` pins only a digest that also carries the `full-tests/v1` attestation
the repository's `promote.yml` adds when ci-full passed on it, and refuses any other.

The Portal's commit goes through scripts/pin-portal.sh, which also checks the app builders
against the workflows the seeded applications carry. Antares stays a hand pin: each of its pins
records the migrations and runtime keys it brings (components/context-broker/images.yaml).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "marek-mraz-jc"
ISSUER = "https://token.actions.githubusercontent.com"
# Per source: its repository and the image paths its image.yml publishes under the commit's tag;
# the first is required, the others are pinned when that commit built them.
SOURCES = {
    "platform": ("joinedcontext-platform", ["joinedcontext-platform", "joinedcontext-platform/checkouts",
                                            "joinedcontext-platform/model-tools"]),
    "portal": ("joinedcontext-portal", ["joinedcontext-portal", "joinedcontext-portal-ui", "joinedcontext-app-builder",
                                        "joinedcontext-app-builder-rust"]),
}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def run(*args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def built(repository):
    """The commit of the newest green image.yml run on main."""
    out = run("gh", "run", "list", "-R", f"{OWNER}/{repository}", "--workflow", "image.yml", "--branch", "main",
              "--status", "success", "--json", "headSha", "--limit", "1").stdout
    runs = json.loads(out or "[]")
    commit = runs[0].get("headSha", "") if runs else ""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit(f"{repository}: no green image.yml run on main ({out!r})")
    return commit


def green(repository, workflow, commit):
    """The workflow's newest run on the commit finished green."""
    out = run("gh", "run", "list", "-R", f"{OWNER}/{repository}", "--workflow", workflow, "--commit", commit,
              "--json", "status,conclusion", "--limit", "1").stdout
    runs = json.loads(out or "[]")
    return bool(runs) and runs[0]["status"] == "completed" and runs[0]["conclusion"] == "success"


def published(image, commit):
    """The digest of `image:commit`, or None while the commit has no such image."""
    result = run("docker", "buildx", "imagetools", "inspect", f"ghcr.io/{OWNER}/{image}:{commit}", check=False)
    digest = next((line.split()[1] for line in result.stdout.splitlines() if line.startswith("Digest:")), None)
    return digest if digest and DIGEST.match(digest) else None


FULL_TESTS = "https://joinedcontext.com/attestations/full-tests/v1"


def attested(repository, image, digest):
    """The digest carries the full-tests attestation of the repository's promote.yml on main."""
    identity = f"https://github.com/{OWNER}/{repository}/.github/workflows/promote.yml@refs/heads/main"
    result = run("cosign", "verify-attestation", "--type", FULL_TESTS, "--certificate-oidc-issuer", ISSUER,
                 "--certificate-identity", identity, f"ghcr.io/{OWNER}/{image}@{digest}", check=False)
    return result.returncode == 0


def signed(repository, image, digest):
    identity = f"https://github.com/{OWNER}/{repository}/.github/workflows/image.yml@refs/heads/main"
    result = run("cosign", "verify", "--certificate-oidc-issuer", ISSUER, "--certificate-identity", identity,
                 f"ghcr.io/{OWNER}/{image}@{digest}", check=False)
    return result.returncode == 0


def pin(text, image, digest, commit=None):
    """`text` with every block naming `ghcr.io/OWNER/image` pinned to `digest`, and how many. A
    block that records its source commit (`commit:`, read by scripts/check-docs-pin.sh) moves it
    to `commit` with the digest."""
    block = rf"(repository: 'ghcr\.io/{OWNER}/{re.escape(image)}'\n(?:    .*\n)*?    "
    text, n = re.subn(block + r"digest: )'sha256:[0-9a-f]{64}'", rf"\g<1>'{digest}'", text)
    if commit:
        text, _ = re.subn(block + r"commit: )'[0-9a-f]{40}'", rf"\g<1>'{commit}'", text)
    return text, n


def pin_files(pins, commit=None):
    """Pin every images.yaml; the paths that changed."""
    changed = []
    for path in sorted(ROOT.glob("components/*/images.yaml")):
        text = original = path.read_text()
        for image, digest in pins.items():
            text, _ = pin(text, image, digest, commit)
        if text != original:
            path.write_text(text)
            changed.append(path)
    return changed


def main(source, tier="dev"):
    repository, images = SOURCES[source]
    # PIN_COMMIT pins another green commit (one the lane built behind the newest); the
    # signature check below still requires the image.yml of `main` to have signed its images.
    commit = os.environ.get("PIN_COMMIT") or built(repository)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit(f"{source}: PIN_COMMIT must be a full 40-hex commit, not {commit!r}")
    if not green(repository, "ci.yml", commit):
        print(f"{source} {commit[:7]}: ci is not green yet; nothing pinned", file=sys.stderr)
        return
    # A red or unfinished image.yml may have published some images and not others: wait for it
    # like an unfinished ci, never pin half a commit.
    if not green(repository, "image.yml", commit):
        print(f"{source} {commit[:7]}: image.yml is not green (red or still running); nothing pinned", file=sys.stderr)
        return
    pins = {}
    for n, image in enumerate(images):
        digest = published(image, commit)
        if digest is None:
            if n == 0:
                print(f"{source} {commit[:7]}: {image} is not published yet; nothing pinned", file=sys.stderr)
                return
            continue
        if not signed(repository, image, digest):
            sys.exit(f"{source} {commit[:7]}: {image}@{digest} carries no signature of {repository}'s image.yml on main")
        if tier == "production" and not attested(repository, image, digest):
            sys.exit(f"{source} {commit[:7]}: {image}@{digest} has not passed the full tests (no full-tests "
                     f"attestation of {repository}'s promote.yml); a production tier pins only promoted images")
        pins[image] = digest
    if source == "portal":
        # The builder contract check and the builders' own comment line are pin-portal.sh's.
        refused = subprocess.run([str(ROOT / "scripts/pin-portal.sh"), commit], cwd=ROOT, check=False)
        if refused.returncode != 0:
            # Whatever it wrote before it stopped goes back: a pin is all three images or none.
            subprocess.run(["git", "checkout", "--", "components"], cwd=ROOT, check=False)
            print(f"{source} {commit[:7]}: pin-portal.sh refused (exit {refused.returncode}); nothing pinned",
                  file=sys.stderr)
            return
    elif not pin_files(pins, commit):
        print(f"{source} {commit[:7]}: already pinned", file=sys.stderr)
        return
    print(f"pin {source} {commit[:7]} (ci green, signed by {repository} image.yml on main)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[1:2] == ["--tier"] and len(args) == 3 and args[2] in ("dev", "production"):
        tier = args.pop()
        args.pop()
    else:
        tier = "dev"
    if len(args) != 1 or args[0] not in SOURCES:
        sys.exit(f"usage: pin-images.py {{{'|'.join(SOURCES)}}} [--tier dev|production]")
    main(args[0], tier)
