#!/usr/bin/env bash
# The Portal's client administration, narrowed to its own clients (T-2725, AP-27, AP-111).
#
# The realm runs Keycloak's fine-grained admin permissions (v2). `portal-api` holds the
# read-only `view-clients` role, so it lists and finds clients, and this script grants it the
# write scopes on every client of the realm and takes them away again on every client that does
# not carry `managed-by: joinedcontext`: the edge client, the platform's own clients and
# Keycloak's built-in ones. The App and workload clients the Portal creates carry the mark, so
# it keeps creating, changing and deleting those.
#
# Run after every realm import and idempotent: it finds its two policies and two permissions by
# name and writes them as they should be, and the deny covers the clients the realm holds now.
# A client somebody adds by hand between two runs is the Portal's to change until the next.
#
# Reading a client's secret stays with `view-clients` (Keycloak 26.6 lists clients with their
# secrets to a caller that may view them): confidential platform clients move off shared
# secrets (T-2868), which is what leaves the list nothing to show.
set -euo pipefail

: "${KEYCLOAK_URL:?the Keycloak base URL}"
: "${KEYCLOAK_USER:?the realm admin}"
: "${KEYCLOAK_PASSWORD:?the realm admin password}"
: "${REALM:?the realm}"
: "${PRINCIPAL:?the client whose service account administers clients}"
MANAGED_KEY=${MANAGED_KEY:-managed-by}
MANAGED_VALUE=${MANAGED_VALUE:-joinedcontext}
# The client scopes of the permissions v2 resource type `Clients` that change something.
WRITE_SCOPES='["manage","map-roles","map-roles-client-scope","map-roles-composite"]'

CONFIG=$(mktemp)
trap 'rm -f "$CONFIG"' EXIT
kc() { /opt/keycloak/bin/kcadm.sh "$@" --config "$CONFIG"; }
fail() { echo "admin permissions: $*" >&2; exit 1; }

kc config credentials --server "$KEYCLOAK_URL" --realm master \
  --user "$KEYCLOAK_USER" --password "$KEYCLOAK_PASSWORD" >/dev/null

client_id() {
  kc get clients -r "$REALM" -q "clientId=$1" --fields id --format csv --noquotes | head -n 1
}

permissions=$(client_id admin-permissions)
[ -n "$permissions" ] || fail "realm $REALM has no admin-permissions client: adminPermissionsEnabled is off"
principal=$(client_id "$PRINCIPAL")
[ -n "$principal" ] || fail "realm $REALM has no client $PRINCIPAL"
server="clients/$permissions/authz/resource-server"

# The id of the policy or permission of that exact name, or nothing. Plain bash: the Keycloak
# image carries no awk, sed or jq.
named() {
  local id name
  while IFS=, read -r id name; do
    if [ "$name" = "$2" ]; then
      echo "$id"
      return
    fi
  done < <(kc get "$server/$1" -r "$REALM" -q "name=$2" --fields id,name --format csv --noquotes)
}

# Creates or rewrites one policy or permission; `$1` is its path under the resource server
# (`policy/client`, `permission/scope`), `$2` its name, the rest its fields.
ensure() {
  local path=$1 name=$2 id
  shift 2
  id=$(named "${path%%/*}" "$name")
  if [ -z "$id" ]; then
    kc create "$server/$path" -r "$REALM" -s "name=$name" "$@" >/dev/null
    echo "created $name"
  else
    kc update "$server/$path/$id" -r "$REALM" -s "id=$id" -s "name=$name" "$@"
    echo "updated $name"
  fi
}

ensure policy/client "$PRINCIPAL" -s logic=POSITIVE -s "clients=[\"$principal\"]"
ensure policy/client "not-$PRINCIPAL" -s logic=NEGATIVE -s "clients=[\"$principal\"]"
granted=$(named policy "$PRINCIPAL")
denied=$(named policy "not-$PRINCIPAL")

# Every client of the realm without the mark, the principal itself included.
unmanaged=""
count=0
while IFS=, read -r id _client mark; do
  if [ -n "$id" ] && [ "$mark" != "$MANAGED_VALUE" ]; then
    unmanaged+="${unmanaged:+,}\"$id\""
    count=$((count + 1))
  fi
done < <(kc get clients -r "$REALM" -q first=0 -q max=100000 \
  --fields "id,clientId,attributes($MANAGED_KEY)" --format csv --noquotes)
[ "$count" -gt 0 ] || fail "realm $REALM lists no client without $MANAGED_KEY: refusing to grant every client"

ensure permission/scope "$PRINCIPAL-manages-clients" -s resourceType=Clients \
  -s "scopes=$WRITE_SCOPES" -s "policies=[\"$granted\"]"
ensure permission/scope "$PRINCIPAL-not-on-unmanaged-clients" -s resourceType=Clients \
  -s "scopes=$WRITE_SCOPES" -s "resources=[$unmanaged]" -s "policies=[\"$denied\"]"
echo "denied $PRINCIPAL the writes on $count clients without $MANAGED_KEY: $MANAGED_VALUE"
