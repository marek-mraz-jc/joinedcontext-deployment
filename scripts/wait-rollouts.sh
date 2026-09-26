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
	# A pod already being deleted belongs to a rollout that finished; once its containers exit it
	# shows Error or Completed rather than Terminating, so skip it by its deletionTimestamp.
	deleting=$(kubectl get pods -n "$ns" -o jsonpath='{range .items[?(@.metadata.deletionTimestamp)]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
	# A Job's pod in Error is one attempt; the Job retries it and removes it (a CronJob's pod
	# did, mid-apply). Only a Job whose `Failed` condition is True is a failure of the apply.
	owners=$(kubectl get pods -n "$ns" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.ownerReferences[?(@.kind=="Job")].name}{"\n"}{end}' 2>/dev/null || true)
	failed_jobs=$(kubectl get jobs -n "$ns" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.conditions[?(@.type=="Failed")].status}{"\n"}{end}' 2>/dev/null | awk '$2 == "True" {print $1}' || true)
	while read -r pod; do
		[ -n "$pod" ] || continue
		grep -qxF "$pod" <<<"$deleting" && continue
		job=$(awk -v pod="$pod" '$1 == pod {print $2}' <<<"$owners")
		if [ -n "$job" ] && ! grep -qxF "$job" <<<"$failed_jobs"; then continue; fi
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
