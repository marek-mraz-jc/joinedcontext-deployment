#!/bin/sh
# The monthly restore drill (OPS-11, OPS-12, T-0046, T-5101). Restores $SOURCE twice into the
# throwaway Cluster $DRILL, one after the other: first the latest base backup and WAL, then a
# point in time, the instant the drill counted every table of the source. It compares row
# counts (per database for the latest, per table for the point in time), checks the realm and
# the Portal's schema in the copy, measures RTO and RPO, records the result and deletes the
# copy. With the nightly local dump on (LOCAL_BACKUP, T-5556) it first restores the newest dump
# into a throwaway Postgres pod and compares its tables with the counts the dump job took. Every
# number in the result is read from the clusters; none is typed here.
set -u
# SOURCE, DRILL, RESULT, BACKUPS_ENABLED, LOCAL_BACKUP, TOLERANCE_PERCENT, MIN_MEM_MIB and
# TIMEOUT_MINUTES come from the CronJob.

started=$(date +%s)
verdict=failed
detail=""
rto=""
rpo=""
pitr_target=""
pitr_rto=""
pitr_detail=""
local_dump=off
[ "$LOCAL_BACKUP" != true ] || local_dump=not-run
local_rto=""
local_bytes=""
local_detail=""

# The result goes two ways: one JSON line in this pod's log, and the ConfigMap $RESULT that an
# operator or a check reads without the log.
record() {
  at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  fields="\"result\":\"$verdict\",\"rtoSeconds\":\"$rto\",\"rpoSeconds\":\"$rpo\",\"pitrTarget\":\"$pitr_target\",\"pitrRtoSeconds\":\"$pitr_rto\",\"pitrDetail\":\"$pitr_detail\",\"localDump\":\"$local_dump\",\"localDumpRtoSeconds\":\"$local_rto\",\"localDumpBytes\":\"$local_bytes\",\"localDumpDetail\":\"$local_detail\",\"at\":\"$at\",\"detail\":\"$detail\""
  echo "{\"event\":\"dr-drill\",\"cluster\":\"$SOURCE\",$fields}"
  kubectl patch configmap "$RESULT" --type merge -p "{\"data\":{$fields}}" >/dev/null ||
    echo "the result could not be written to configmap/$RESULT" >&2
}

finish() {
  # A dump that does not restore fails the drill whatever the archive's restores said.
  [ "$local_dump" != failed ] || verdict=failed
  record
  [ "$verdict" = passed ] || [ "$verdict" = no-backup ]
  exit $?
}

if [ "$BACKUPS_ENABLED" != true ] && [ "$LOCAL_BACKUP" != true ]; then
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

sql() { # pod database query
  kubectl exec "$1" -c postgres -- psql -X -At -d "$2" -c "$3"
}
# Foreground deletion returns once the copy's volume is gone too, so the next restore under the
# same name starts on an empty disk.
drop() {
  kubectl delete cluster "$DRILL" --ignore-not-found --cascade=foreground --wait=true >/dev/null
}
work=$(mktemp -d)
dump="$DRILL-dump"
# A copy a crashed drill left behind goes first, and this one goes however the drill ends.
drop
drop_dump() {
  [ "$LOCAL_BACKUP" != true ] || kubectl delete pod "$dump" --ignore-not-found "$@" >/dev/null
}
drop_dump --wait=true
trap 'kubectl delete cluster "$DRILL" --ignore-not-found --wait=false >/dev/null; drop_dump --wait=false; rm -rf "$work"' EXIT

# Every table of a database as `database.schema.table|rows`, the line the dump job writes too.
TABLES="SELECT schemaname || '.' || relname, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, relname), false, true, '')))[1]::text FROM pg_stat_user_tables ORDER BY 1"
count_tables() { # pod database file
  rows=$(sql "$1" "$2" "$TABLES" 2>/dev/null) || return 1
  [ -z "$rows" ] || printf '%s\n' "$rows" | sed "s|^|$2.|" >>"$3"
}
# The tables of the second file that differ from the first: missing, or apart by more than the
# tolerance in percent of the first's count, and at least one row.
compare() { # want got
  awk -F'|' -v tol="$TOLERANCE_PERCENT" '
    NR == FNR { want[$1] = $2; next }
    { got[$1] = $2 }
    END {
      for (t in want) {
        if (!(t in got)) { print t "(missing)"; continue }
        d = got[t] - want[t]; if (d < 0) d = -d
        lim = want[t] * tol / 100; if (lim < 1) lim = 1
        if (d > lim) print t "(" got[t] " of " want[t] ")"
      }
    }' "$1" "$2" | sort | tr '\n' ' '
}

# 0. The nightly dump: the newest .sql.gz restored with psql into a pod of the cluster's image,
# on an emptyDir, listening on no port, the dump volume read-only. Its tables are held to the
# counts the dump job took just before pg_dumpall, written beside the dump.
local_stage() {
  begin=$(date +%s)
  if ! kubectl create -f /opt/drill/dump-pod.yaml >/dev/null; then
    local_detail="the restore pod was refused"
    return 1
  fi
  left=$((deadline - begin))
  [ "$left" -gt 60 ] || left=60
  if ! kubectl wait "pod/$dump" --for=condition=Ready --timeout="${left}s" >/dev/null; then
    local_detail="the restore pod did not become ready within ${TIMEOUT_MINUTES} minutes"
    return 1
  fi
  newest=$(kubectl exec "$dump" -c postgres -- sh -c "f=\$(ls -1 /backup/*.sql.gz 2>/dev/null | tail -n 1) && [ -n \"\$f\" ] && echo \"\$f|\$(wc -c <\"\$f\")\"" newest) || newest=""
  file=${newest%|*}
  if [ -z "$newest" ]; then
    local_detail="no dump on the volume"
    return 1
  fi
  local_bytes=${newest##*|}
  if ! kubectl exec "$dump" -c postgres -- sh -c "cat \"\$1.counts\"" counts "$file" >"$work/dumped" || [ ! -s "$work/dumped" ]; then
    local_detail="no table counts beside ${file##*/}"
    return 1
  fi
  # gzip -t reads the whole file first: a truncated dump fails here, not halfway through psql.
  if ! kubectl exec "$dump" -c postgres -- sh -c "gzip -t \"\$1\" && gunzip -c \"\$1\" | psql -X -q -v ON_ERROR_STOP=1 -d postgres >/dev/null" restore "$file" 2>"$work/restore.err"; then
    # The first error, cut at its first quote: a quoted value may be a row of the dump.
    local_detail="${file##*/} did not restore: $(grep -m 1 -E 'ERROR|gzip:' "$work/restore.err" | sed 's/".*//' | tr -d '\134')"
    return 1
  fi
  local_rto=$(($(date +%s) - begin))
  cut -d. -f1 "$work/dumped" | sort -u | while read -r db; do
    count_tables "$dump" "$db" "$work/restored" || :
  done
  touch "$work/restored"
  off=$(compare "$work/dumped" "$work/restored")
  if [ -n "$off" ]; then
    local_detail="${file##*/} short: ${off% }"
    return 1
  fi
  local_detail="${file##*/}: $(wc -l <"$work/dumped" | tr -d ' ') tables match"
}
if [ "$LOCAL_BACKUP" = true ]; then
  if local_stage; then local_dump=local-dump-passed; else local_dump=failed; fi
  drop_dump --wait=false
fi
if [ "$BACKUPS_ENABLED" != true ]; then
  verdict=no-backup
  detail="no off-site backup to drill: postgres.cluster.backups is off"
  finish
fi

primary=$(kubectl get cluster "$SOURCE" -o jsonpath='{.status.currentPrimary}')
copy="$DRILL-1"
databases=$(sql "$primary" postgres "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1") || {
  detail="the source's databases could not be listed"
  finish
}

# Every table's count on the source, then the instant after the last count: the point the
# second restore goes back to. The WAL switch sends the segment holding that instant to the
# archive now rather than at the next archive timeout.
for db in $databases; do
  count_tables "$primary" "$db" "$work/source" || {
    detail="the source's tables in $db could not be counted"
    finish
  }
done
pitr_target=$(sql "$primary" postgres "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), pg_switch_wal()" | cut -d'|' -f1)
case "$pitr_target" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
  *)
    detail="the source's clock could not be read for the point in time"
    finish
    ;;
esac
# A commit at the target's own second lands on either side of it.
sleep "${TARGET_SETTLE_SECONDS:-2}"

restore() { # manifest → $took, or the reason in $why
  why=""
  begin=$(date +%s)
  if ! kubectl create -f "$1" >/dev/null; then
    why="the throwaway cluster was refused"
    return 1
  fi
  left=$((deadline - begin))
  [ "$left" -gt 60 ] || left=60
  if ! kubectl wait "cluster/$DRILL" --for=condition=Ready --timeout="${left}s" >/dev/null; then
    why="the restore did not become ready within ${TIMEOUT_MINUTES} minutes"
    return 1
  fi
  took=$(($(date +%s) - begin))
}

# What a working copy holds besides rows: the realm's realms and people (a login reads them),
# and the Portal's schema at the source's migration (the Portal starts only on its own schema).
key_checks() {
  bad=""
  for db in $databases; do
    case "$db" in
      keycloak)
        people=$(sql "$copy" keycloak "SELECT count(*) FROM realm r JOIN user_entity u ON u.realm_id = r.id WHERE r.enabled AND u.enabled" 2>/dev/null) || people=""
        [ "${people:-0}" -gt 0 ] || bad="$bad keycloak(no enabled person in an enabled realm)"
        ;;
      portal)
        q="SELECT coalesce(max(version)::text, '') FROM _sqlx_migrations WHERE success"
        want=$(sql "$primary" portal "$q") || want=""
        got=$(sql "$copy" portal "$q" 2>/dev/null) || got=""
        [ -n "$got" ] && [ "$got" = "$want" ] || bad="$bad portal(schema ${got:-none} of ${want:-unreadable})"
        ;;
    esac
  done
  echo "${bad# }"
}

# 1. The latest: everything the archive holds, as an incident on the source would restore it.
if ! restore /opt/drill/cluster.yaml; then
  detail="$why"
  finish
fi
rto=$took
# The last transaction the archive held: how much the restore lost against now.
rpo=$(sql "$copy" postgres "SELECT coalesce(round(extract(epoch FROM now() - pg_last_xact_replay_timestamp()))::text, '')")

ROWS="SELECT coalesce(sum((xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, relname), false, true, '')))[1]::text::bigint), 0) FROM pg_stat_user_tables"
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
keys=$(key_checks)
[ -z "$keys" ] || short="$short $keys"
if [ -n "$short" ]; then
  detail="short:$short; $detail"
  finish
fi

# 2. The point in time: the same copy again, replayed only to the instant of the counts above.
drop
sed "s|__TARGET_TIME__|$pitr_target|" /opt/drill/cluster-pitr.yaml >"$work/pitr.yaml"
if ! restore "$work/pitr.yaml"; then
  pitr_detail="$why"
  finish
fi
pitr_rto=$took
for db in $databases; do
  count_tables "$copy" "$db" "$work/copy" || :
done
# A table may differ by what was committed between its count and the target.
off=$(compare "$work/source" "$work/copy")
tables=$(wc -l <"$work/source" | tr -d ' ')
keys=$(key_checks)
if [ -n "$off$keys" ]; then
  pitr_detail="short: ${off}${keys}"
  pitr_detail="${pitr_detail% }"
else
  pitr_detail="$tables tables match"
  verdict=passed
fi
finish
