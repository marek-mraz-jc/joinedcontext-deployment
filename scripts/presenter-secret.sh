#!/usr/bin/env bash
# Load the presenter's password and TOTP seed into one cluster (T-6542).
#
#   SOPS_AGE_KEY_FILE=.secrets/age-<instance>.key \
#   KUBECONFIG=.secrets/kubeconfig-<instance>.yaml \
#       scripts/presenter-secret.sh --instance <instance> --realm <realm>
#   scripts/presenter-secret.sh ... --dry-run     # decrypts and prints the plan, changes nothing
#
# The presenter (components/keycloak/presenter.yaml) signs in with one password and one TOTP seed
# on dev, stage and prod. Both are the owner's and live in components/keycloak/presenter.enc.yaml,
# encrypted to the three instances' age keys (.sops.yaml); the owner reads them with `sops -d`.
# Every render generates Secret keycloak-user-presenter like any demo person's, so CI and an apply
# need no key; this script replaces the generated values with the owner's, once per instance:
#
#   1. decrypts both values into memory (never printed; only their lengths),
#   2. applies the Secret's generator release, which makes the Secret where it is missing,
#   3. writes both values into every copy (the generator reuses a value it finds, so later applies
#      keep them),
#   4. deletes the presenter's TOTP credential in the realm if one exists: keycloak-config-cli
#      skips a credential whose fixed id it already holds, so a changed seed lands only this way,
#   5. applies keycloak-people and keycloak-config, which create the person and push both values.
#
# Running it again changes nothing the owner sees: same values, the credential written again.
set -uo pipefail

instance=""
realm=""
dry_run=0
secret="keycloak-user-presenter"
username="presenter@hel.fi"
sops_file="components/keycloak/presenter.enc.yaml"
helmfile_file="deployment/helmfile.yaml"

die() { printf 'presenter-secret: %s\n' "$1" >&2; exit 2; }
say() { printf 'presenter-secret: %s\n' "$1"; }

while [ $# -gt 0 ]; do
	case "$1" in
	--instance) instance="${2:?}"; shift 2 ;;
	--realm) realm="${2:?}"; shift 2 ;;
	--dry-run) dry_run=1; shift ;;
	*) die "unknown argument $1 (see the header of this script)" ;;
	esac
done
[ -n "$instance" ] || die "--instance is required"
[ -n "$realm" ] || die "--realm is required (the instance's global.instanceSlug)"
case "$realm" in *[!a-z0-9-]*) die "--realm takes lowercase letters, digits and dashes" ;; esac
[ -n "${SOPS_AGE_KEY_FILE:-}${SOPS_AGE_KEY:-}" ] || die "set SOPS_AGE_KEY_FILE to this instance's age key"
[ -f "$sops_file" ] || die "run from the deployment repository root: $sops_file not found"

password=$(sops -d --extract '["password"]' "$sops_file") || die "cannot decrypt the password from $sops_file"
totp=$(sops -d --extract '["totp"]' "$sops_file") || die "cannot decrypt the TOTP seed from $sops_file"
[ "${#password}" -ge 32 ] || die "the password in $sops_file is shorter than 32 characters"
[ "${#totp}" -ge 32 ] || die "the TOTP seed in $sops_file is shorter than 32 characters"
say "decrypted a ${#password}-character password and a ${#totp}-character TOTP seed"

if [ "$dry_run" = 1 ]; then
	say "would apply the generator release of $secret, write both values into every copy,"
	say "delete the TOTP credential of $username in realm $realm and apply keycloak-people and keycloak-config"
	exit 0
fi

helmfile -f "$helmfile_file" -e "$instance" -l "secret-name=$secret" sync >/dev/null || die "the generator release of $secret did not apply"
namespaces=$(kubectl get secret -A --field-selector "metadata.name=$secret" \
	-o 'jsonpath={range .items[*]}{.metadata.namespace}{"\n"}{end}') || die "cannot list Secrets named $secret"
[ -n "$namespaces" ] || die "no Secret named $secret after its generator release: is global.presenterUserId set for $instance?"

# The patch goes through stdin, so neither value reaches a command line or a file.
patch=$(printf '{"data":{"password":"%s","totp":"%s"}}' "$(printf '%s' "$password" | base64 -w0)" "$(printf '%s' "$totp" | base64 -w0)")
for ns in $namespaces; do
	printf '%s' "$patch" | kubectl -n "$ns" patch secret "$secret" --type merge --patch-file /dev/stdin >/dev/null \
		|| die "cannot write $secret in namespace $ns"
	say "wrote $secret in namespace $ns"
done
unset patch password totp

# The admin password is the first line of stdin inside the Keycloak pod (as scripts/preview.sh).
pod=$(kubectl get pod -A -l app.kubernetes.io/name=keycloakx,app.kubernetes.io/instance=keycloak-app \
	-o 'jsonpath={.items[0].metadata.namespace}/{.items[0].metadata.name}') || die "cannot find the Keycloak pod"
[ "$pod" != "/" ] || die "no Keycloak pod in the cluster"
kc_ns=${pod%%/*}
# shellcheck disable=SC2016 # the script runs inside the pod, which expands it
{
	kubectl -n "$kc_ns" get secret keycloak-admin-user -o 'jsonpath={.data.password}' | base64 -d
	echo
} | kubectl -n "$kc_ns" exec -i "${pod#*/}" -c keycloak -- sh -c '
set -eu
kc() { /opt/keycloak/bin/kcadm.sh "$@" --config /tmp/kcadm-presenter.config; }
trap "rm -f /tmp/kcadm-presenter.config" EXIT
IFS= read -r password
kc config credentials --server http://localhost:8080 --realm master --user admin --password "$password" >/dev/null
id=$(kc get users -r "$1" -q exact=true -q username="$2" --fields id --format csv --noquotes)
[ -n "$id" ] || { echo "presenter-secret: $2 is not in realm $1 yet"; exit 0; }
for cred in $(kc get "users/$id/credentials" -r "$1" --fields id,type --format csv --noquotes | sed -n "s/,otp$//p"); do
	kc delete "users/$id/credentials/$cred" -r "$1"
	echo "presenter-secret: deleted the TOTP credential of $2 so the new seed lands"
done
' sh "$realm" "$username" || die "cannot reach the realm $realm through kcadm"

for release in keycloak-people keycloak-config; do
	helmfile -f "$helmfile_file" -e "$instance" -l "release=$release" sync >/dev/null || die "release $release did not apply"
	say "applied $release"
done
say "done: $username signs in on $instance with the password and TOTP seed of $sops_file"
