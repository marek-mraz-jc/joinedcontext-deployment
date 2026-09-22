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
  docker buildx imagetools inspect "$registry/$1:$commit" | awk '/^Digest:/ { print $2; exit }'
}
portal=$(digest joinedcontext-portal)
builder=$(digest joinedcontext-app-builder)
rust=$(digest joinedcontext-app-builder-rust)
for d in "$portal" "$builder" "$rust"; do
  [[ "$d" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "not all three images are published for $commit" >&2; exit 1; }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
docker pull -q "$registry/joinedcontext-app-builder@$builder" >/dev/null
docker run --rm --entrypoint cat "$registry/joinedcontext-app-builder@$builder" /opt/template/lane.mjs >"$work/lane.mjs"
docker run --rm --entrypoint cat "$registry/joinedcontext-app-builder@$builder" /usr/local/bin/build-app >"$work/build-app"
python3 scripts/check-builder-contract.py "$work/lane.mjs" "$work/build-app" components/gitea/apps/*/.gitea/workflows/build.yml

short=${commit:0:7}
python3 - "$short" "$portal" "$builder" "$rust" <<'EOF'
import re
import sys

short, portal, builder, rust = sys.argv[1:]

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
pin("components/gitea-runner/images.yaml",
    [("joinedcontext-app-builder", builder), ("joinedcontext-app-builder-rust", rust)])
text = open("components/gitea-runner/images.yaml").read()
open("components/gitea-runner/images.yaml", "w").write(re.sub(r"Pinned to portal [0-9a-f]{7}", f"Pinned to portal {short}", text))
EOF
echo "pinned portal $short: portal $portal, builder $builder, rust $rust"
