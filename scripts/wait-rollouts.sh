#!/usr/bin/env bash
# Wait for every workload of a deployed instance to become Ready and report what did not.
#   scripts/wait-rollouts.sh <instance-slug> [timeout-seconds]
set -euo pipefail

slug="${1:?usage: wait-rollouts.sh <instance-slug> [timeout]}"
timeout="${2:-600}"

namespaces=$(kubectl get ns -o name | sed 's|namespace/||' | grep -E "^(${slug}|${slug}-|jc-operators$)" || true)
[ -n "$namespaces" ] || { echo "no namespaces for instance '${slug}'" >&2; exit 1; }

echo "waiting up to ${timeout}s for rollouts in: $(echo "$namespaces" | tr '\n' ' ')"
deadline=$(( $(date +%s) + timeout ))
for ns in $namespaces; do
	for res in $(kubectl get deploy,statefulset,daemonset -n "$ns" -o name 2>/dev/null); do
		left=$(( deadline - $(date +%s) ))
		[ "$left" -gt 0 ] || { left=1; }
		kubectl rollout status "$res" -n "$ns" --timeout="${left}s" || true
	done
done

# CloudNativePG clusters are not rollouts; wait for the operator to report them ready.
for ns in $namespaces; do
	for cl in $(kubectl get cluster.postgresql.cnpg.io -n "$ns" -o name 2>/dev/null || true); do
		left=$(( deadline - $(date +%s) )); [ "$left" -gt 0 ] || left=1
		kubectl wait "$cl" -n "$ns" --for=condition=Ready --timeout="${left}s" || true
	done
done

failed=0
for ns in $namespaces; do
	while read -r pod; do
		[ -n "$pod" ] || continue
		failed=1
		echo "--- not ready: ${ns}/${pod}"
		kubectl get pod "$pod" -n "$ns" -o wide
		kubectl get events -n "$ns" --field-selector "involvedObject.name=${pod}" \
			--sort-by=.lastTimestamp -o wide 2>/dev/null | tail -5
	done < <(kubectl get pods -n "$ns" --no-headers 2>/dev/null | awk '
		$3 == "Completed" || $3 == "Succeeded" { next }        # finished Jobs, not workloads
		$3 == "Terminating" { next }                           # the old pod of a rollout that already succeeded
		{ split($2, ready, "/"); if ($3 != "Running" || ready[1] != ready[2]) print $1 }')
done

[ "$failed" -eq 0 ] && echo "all workloads ready in: $(echo "$namespaces" | tr '\n' ' ')"
exit "$failed"
