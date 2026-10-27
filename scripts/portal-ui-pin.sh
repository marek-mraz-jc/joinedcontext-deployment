#!/usr/bin/env bash
# Which `portal-ui` bundle goes with a portal commit (T-2485, T-5297).
#
# usage: scripts/portal-ui-pin.sh <portal commit, 40 hex>   -> prints "<ui commit> <digest>"
#
# image.yml builds the bundle only for a push that changes ui/ or sdk/, so most portal commits
# publish none. Then the bundle pinned now stays, but only when no file under ui/ or sdk/ changed
# between its commit and this one: a bundle built from other files would call routes the binary
# may not have. Reads the public repository's compare API; GITHUB_TOKEN, when set, lifts its
# rate limit.
set -euo pipefail

commit=${1:-}
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <portal commit, 40 hex>" >&2; exit 2; }
cd "$(dirname "$0")/.."
image=ghcr.io/marek-mraz-jc/joinedcontext-portal-ui

built=$({ docker buildx imagetools inspect "$image:$commit" 2>/dev/null || true; } | awk '/^Digest:/ { print $2; exit }')
if [[ "$built" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "$commit $built"
  exit 0
fi

# The `ui:` block of components/portal/images.yaml: its digest and the commit it was built from.
read -r pinned digest < <(awk '/^  ui:$/ { mine = 1; next } mine && /^  [a-z]/ { exit }
  mine && /digest:/ { gsub(/\x27/, "", $2); d = $2 } mine && /commit:/ { gsub(/\x27/, "", $2); c = $2 }
  END { print c, d }' components/portal/images.yaml)
[[ "$pinned" =~ ^[0-9a-f]{40}$ && "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] ||
  { echo "image.yml published no portal-ui for $commit and none is pinned" >&2; exit 1; }
[ "$pinned" = "$commit" ] && { echo "$pinned $digest"; exit 0; }

auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
# The answer goes through a file: a compare past ~128 KiB exceeds one environment string.
compare=$(mktemp)
trap 'rm -f "$compare"' EXIT
curl -fsSL --max-time 30 "${auth[@]}" -o "$compare" \
  "https://api.github.com/repos/marek-mraz-jc/joinedcontext-portal/compare/$pinned...$commit?per_page=300" 2>/dev/null ||
  { echo "the compare of portal ${pinned:0:7}...${commit:0:7} did not answer; nothing decided" >&2; exit 1; }
python3 - "$pinned" "$commit" "$compare" <<'PY'
import json
import sys

pinned, commit = sys.argv[1][:7], sys.argv[2][:7]
with open(sys.argv[3], encoding="utf-8") as f:
    answer = json.load(f)
if answer.get("status") not in ("ahead", "identical"):
    sys.exit(f"portal {commit} does not descend from the pinned portal-ui {pinned} ({answer.get('status')})")
files = [f["filename"] for f in answer.get("files", [])]
# The API lists at most 300 files: past that a ui/ change may hide in the rest.
if len(files) >= 300:
    sys.exit(f"portal {pinned}...{commit} changed 300 files or more; pin a commit image.yml built portal-ui for")
changed = [f for f in files if f.startswith(("ui/", "sdk/"))]
if changed:
    sys.exit(f"portal {commit} changed {changed[0]} since the pinned portal-ui {pinned} and image.yml "
             "published no portal-ui for it")
PY
echo "$pinned $digest"
