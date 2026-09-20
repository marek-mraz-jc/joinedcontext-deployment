#!/usr/bin/env bash
# Render one environment into a single manifest file.
#   scripts/render.sh <environment> <output-file> [extra helmfile args...]
# With --deployed, Helm test hooks (helm.sh/hook: test) are dropped: `helmfile sync`
# never applies them, so they are not part of what runs on a cluster and must not be
# judged as if they were.
set -euo pipefail

env="${1:?usage: render.sh <environment> <output-file> [--deployed] [helmfile args...]}"
out="${2:?usage: render.sh <environment> <output-file> [--deployed] [helmfile args...]}"
shift 2

deployed_only=false
args=()
for a in "$@"; do
	if [ "$a" = "--deployed" ]; then deployed_only=true; else args+=("$a"); fi
done

helmfile -f deployment/helmfile.yaml -e "$env" template --skip-deps -q "${args[@]+"${args[@]}"}" > "$out"

if [ "$deployed_only" = true ]; then
	python3 - "$out" <<'PY'
import sys, yaml
path = sys.argv[1]
with open(path) as fh:
    docs = [d for d in yaml.safe_load_all(fh) if d]
def is_test_hook(doc):
    hooks = ((doc.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "")
    return "test" in str(hooks).split(",")

kept = [d for d in docs if isinstance(d, dict) and not is_test_hook(d)]
with open(path, "w") as fh:
    yaml.safe_dump_all(kept, fh, default_flow_style=False)
print(f"{path}: {len(kept)} objects ({len(docs) - len(kept)} helm test hooks dropped)")
PY
fi
