#!/usr/bin/env bash
# Pin the portal and both app-builder images to one portal commit (T-2633, AP-82, AP-106).
#
# usage: scripts/pin-portal.sh <portal commit, 40 hex>
#
# The portal's image.yml tags all three images with the commit. The builder image has to match
# the workflows the seeded applications carry (components/gitea/apps/*/.gitea/workflows), so the
# script reads lane.mjs and build-app out of it and refuses to pin a builder that cannot run them.
set -euo pipefail

commit=${1:-}
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <portal commit, 40 hex>" >&2; exit 2; }
cd "$(dirname "$0")/.."
registry=ghcr.io/marek-mraz-jc

digest() {
  # A missing image is an empty digest, refused below with words, never a bare exit of set -e.
  { docker buildx imagetools inspect "$registry/$1:$commit" 2>/dev/null || true; } | awk '/^Digest:/ { print $2; exit }'
}
# The builder images' own pins, kept when the commit did not rebuild them.
pinned() {
  awk -v repo="$registry/$1" '$0 ~ "repository: .*" repo "\x27" { mine = 1 } mine && /digest:/ { gsub(/\x27/, "", $2); print $2; exit }' components/gitea-runner/images.yaml
}
portal=$(digest joinedcontext-portal)
[[ "$portal" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "no portal image is published for $commit" >&2; exit 1; }
# image.yml builds only what a push's paths need (T-2485): a commit that changed no builder
# publishes no builder, and the builders pinned now are still the ones the workflows run.
builder=$(digest joinedcontext-app-builder)
rust=$(digest joinedcontext-app-builder-rust)
[[ -n "$builder" ]] || builder=$(pinned joinedcontext-app-builder)
[[ -n "$rust" ]] || rust=$(pinned joinedcontext-app-builder-rust)
for d in "$builder" "$rust"; do
  [[ "$d" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "no builder image is published for $commit and none is pinned" >&2; exit 1; }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
docker pull -q "$registry/joinedcontext-app-builder@$builder" >/dev/null
docker run --rm --entrypoint cat "$registry/joinedcontext-app-builder@$builder" /opt/template/lane.mjs >"$work/lane.mjs"
docker run --rm --entrypoint cat "$registry/joinedcontext-app-builder@$builder" /usr/local/bin/build-app >"$work/build-app"
python3 scripts/check-builder-contract.py "$work/lane.mjs" "$work/build-app" components/gitea/apps/*/.gitea/workflows/build.yml

# The docs commit the image's /docs pages are, beside the digest (T-4483).
docs=$(curl -fsSL "https://raw.githubusercontent.com/marek-mraz-jc/joinedcontext-portal/$commit/public-docs/COMMIT")
[[ "$docs" =~ ^[0-9a-f]{40}$ ]] || { echo "portal $commit names no docs commit in public-docs/COMMIT" >&2; exit 1; }

short=${commit:0:7}
python3 - "$short" "$portal" "$builder" "$rust" "$commit" "$docs" <<'EOF'
import re
import sys

short, portal, builder, rust, commit, docs = sys.argv[1:]

def pin(path, pins):
    text = open(path).read()
    for repository, digest in pins:
        text, n = re.subn(
            rf"(repository: '[^']*/{repository}'\n(?:    .*\n)*?    digest: )'sha256:[0-9a-f]{{64}}'",
            rf"\g<1>'{digest}'", text)
        if n != 1:
            sys.exit(f"{path}: no single pin for {repository}")
    open(path, "w").write(text)

pin("components/portal/images.yaml", [("joinedcontext-portal", portal)])
text = open("components/portal/images.yaml").read()
for key, value in (("commit", commit), ("docs", docs)):
    text, n = re.subn(rf"(\n    {key}: )'[0-9a-f]{{40}}'", rf"\g<1>'{value}'", text, count=1)
    if n != 1:
        sys.exit(f"components/portal/images.yaml: no {key} pin")
open("components/portal/images.yaml", "w").write(text)
before = open("components/gitea-runner/images.yaml").read()
pin("components/gitea-runner/images.yaml",
    [("joinedcontext-app-builder", builder), ("joinedcontext-app-builder-rust", rust)])
text = open("components/gitea-runner/images.yaml").read()
# The comment names the portal commit the builders are of: it moves only with them.
if text != before:
    open("components/gitea-runner/images.yaml", "w").write(re.sub(r"Pinned to portal [0-9a-f]{7}", f"Pinned to portal {short}", text))
EOF
echo "pinned portal $short: portal $portal, docs ${docs:0:7}, builder $builder, rust $rust"
scripts/check-docs-pin.sh
