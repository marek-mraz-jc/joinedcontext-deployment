#!/usr/bin/env bash
# The seeded people under the fixed Keycloak ids the manifests name them by (PF-126, ADR-N-061).
#
# keycloak-config-cli creates a user through the admin API, which drops the `id` it is given, so
# this runs before the realm import and creates each person through the realm's partial import,
# which keeps it. The import then sets their password, second factor, roles and groups as before.
#
# One line per person in $USERS_FILE: `<id> <username> <recreate>`. A person who is missing is
# created; one who holds the id already is left alone; one who holds another id is deleted and
# created again only when `recreate` is true (the demo people of the development profile, whose
# password and second factor the import sets again from their Secrets). Otherwise the Job fails
# and names the id the deployment has to carry: an owner's account is never deleted.
#
# Run on every apply and idempotent. On a fresh installation the realm does not exist yet: it is
# created bare, and the import fills it in.
set -euo pipefail

: "${KEYCLOAK_URL:?the Keycloak base URL}"
: "${KEYCLOAK_USER:?the realm admin}"
: "${KEYCLOAK_PASSWORD:?the realm admin password}"
: "${REALM:?the realm}"
USERS_FILE=${USERS_FILE:-/config/users}

CONFIG=$(mktemp)
BODY=$(mktemp)
trap 'rm -f "$CONFIG" "$BODY"' EXIT
kc() { /opt/keycloak/bin/kcadm.sh "$@" --config "$CONFIG"; }
fail() { echo "user ids: $*" >&2; exit 1; }

kc config credentials --server "$KEYCLOAK_URL" --realm master \
  --user "$KEYCLOAK_USER" --password "$KEYCLOAK_PASSWORD" >/dev/null

if ! kc get "realms/$REALM" --fields realm >/dev/null 2>&1; then
  kc create realms -s realm="$REALM" -s enabled=true
  echo "realm $REALM created; the import fills it in"
fi

# The id a username holds in the realm, or nothing.
id_of() {
  kc get users -r "$REALM" -q username="$1" -q exact=true --fields id --format csv --noquotes
}

UUID='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
while read -r id username recreate; do
  [ -n "$id" ] || continue
  [[ $id =~ $UUID ]] || fail "'$id' is not a lower-case Keycloak user id"
  [[ $username =~ ^[A-Za-z0-9._@+-]+$ ]] || fail "a username of $id holds a character Keycloak refuses"
  held=$(id_of "$username")
  if [ "$held" = "$id" ]; then
    echo "$id is in place"
    continue
  fi
  mode=SKIP
  if [ -n "$held" ]; then
    [ "$recreate" = true ] ||
      fail "the person meant to hold $id holds $held: set that id where the deployment names them (global.initialUserId); nobody was changed"
    mode=OVERWRITE
  fi
  printf '{"ifResourceExists":"%s","users":[{"id":"%s","username":"%s","email":"%s","enabled":true,"emailVerified":true}]}' \
    "$mode" "$id" "$username" "$username" > "$BODY"
  kc create partialImport -r "$REALM" -f "$BODY" >/dev/null
  [ "$(id_of "$username")" = "$id" ] || fail "Keycloak did not create $id"
  echo "$id created${held:+ in place of $held}"
done < "$USERS_FILE"
