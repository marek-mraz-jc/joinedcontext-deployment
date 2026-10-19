#!/bin/sh
# The monthly restore drill (OPS-11, OPS-12, T-0046). Restores the latest base backup and WAL
# of $SOURCE into the throwaway Cluster $DRILL, compares every database's row count with the
# source, measures RTO and RPO, records the result and deletes the copy. Every number in the
# result is read from the clusters; none is typed here.
set -u
# SOURCE, DRILL, RESULT, BACKUPS_ENABLED, TOLERANCE_PERCENT, MIN_MEM_MIB and TIMEOUT_MINUTES
# come from the CronJob.

started=$(date +%s)
verdict=failed
detail=""
rto=""
rpo=""

# The result goes two ways: one JSON line in this pod's log, and the ConfigMap $RESULT that an
# operator or a check reads without the log.
record() {
  at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"event\":\"dr-drill\",\"cluster\":\"$SOURCE\",\"result\":\"$verdict\",\"rtoSeconds\":\"$rto\",\"rpoSeconds\":\"$rpo\",\"at\":\"$at\",\"detail\":\"$detail\"}"
  kubectl patch configmap "$RESULT" --type merge -p "{\"data\":{\"result\":\"$verdict\",\"rtoSeconds\":\"$rto\",\"rpoSeconds\":\"$rpo\",\"at\":\"$at\",\"detail\":\"$detail\"}}" >/dev/null ||
    echo "the result could not be written to configmap/$RESULT" >&2
}

finish() {
  record
  [ "$verdict" = passed ] || [ "$verdict" = no-backup ]
  exit $?
}

if [ "$BACKUPS_ENABLED" != true ]; then
  verdict=no-backup
  detail="no off-site backup to drill: postgres.cluster.backups is off"
  finish
fi

# The node is shared: a restore beside a full node evicts the platform, so the drill waits for
# room and gives up visibly rather than squeezing in.
deadline=$((started + TIMEOUT_MINUTES * 60))
while :; do
  free=$(awk '/^MemAvailable:/ { print int($2 / 1024) }' "${MEMINFO:-/proc/meminfo}")
  [ "${free:-0}" -ge "$MIN_MEM_MIB" ] && break
  if [ "$(date +%s)" -ge "$deadline" ]; then
    verdict=skipped
    detail="the node had ${free:-0} MiB available, under ${MIN_MEM_MIB} MiB, for ${TIMEOUT_MINUTES} minutes"
    finish
  fi
  sleep "${POLL_SECONDS:-60}"
done

# A copy a crashed drill left behind goes first, and this one goes however the drill ends.
kubectl delete cluster "$DRILL" --ignore-not-found --wait=true >/dev/null
trap 'kubectl delete cluster "$DRILL" --ignore-not-found --wait=false >/dev/null' EXIT

restore_start=$(date +%s)
if ! kubectl apply -f /opt/drill/cluster.yaml >/dev/null; then
  detail="the throwaway cluster was refused"
  finish
fi
left=$((deadline - restore_start))
[ "$left" -gt 60 ] || left=60
if ! kubectl wait "cluster/$DRILL" --for=condition=Ready --timeout="${left}s" >/dev/null; then
  detail="the restore did not become ready within ${TIMEOUT_MINUTES} minutes"
  finish
fi
rto=$(($(date +%s) - restore_start))

sql() { # pod database query
  kubectl exec "$1" -c postgres -- psql -X -At -d "$2" -c "$3"
}
primary=$(kubectl get cluster "$SOURCE" -o jsonpath='{.status.currentPrimary}')
copy="$DRILL-1"

# The last transaction the archive held: how much the restore lost against now.
rpo=$(sql "$copy" postgres "SELECT coalesce(round(extract(epoch FROM now() - pg_last_xact_replay_timestamp()))::text, '')")

ROWS="SELECT coalesce(sum((xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, relname), false, true, '')))[1]::text::bigint), 0) FROM pg_stat_user_tables"
databases=$(sql "$primary" postgres "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1") || {
  detail="the source's databases could not be listed"
  finish
}
short=""
for db in $databases; do
  want=$(sql "$primary" "$db" "$ROWS") || want=""
  got=$(sql "$copy" "$db" "$ROWS" 2>/dev/null) || got=""
  if [ -z "$want" ]; then
    short="$short $db(source unreadable)"
  elif [ -z "$got" ]; then
    short="$short $db(missing)"
  elif [ $((got * 100)) -lt $((want * (100 - TOLERANCE_PERCENT))) ]; then
    short="$short $db($got of $want rows)"
  fi
  detail="$detail $db=$got/$want"
done
detail="${detail# }"
if [ -n "$short" ]; then
  detail="short:$short; $detail"
else
  verdict=passed
fi
finish
