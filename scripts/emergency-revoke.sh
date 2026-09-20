#!/usr/bin/env bash
# Emergency revocation of a compromised credential or policy (OPS-45, R48, PF-38).
#
#   scripts/emergency-revoke.sh --instance dev --policy public-read \
#       [--user jana.kovacova | --service-account banskabystrica-conformance] \
#       [--verify-url https://host/api/endpoint/<slug>/ngsi-ld/v1/entities?type=X] \
#       [--verify-token-file .secrets/compromised-token] [--bound 5]
#
# Three things have to happen, in this order, and the order is the point:
#
#   1. the Policy that grants the compromised subject leaves the gateway's repository,
#      because an access token already in an attacker's hands stays cryptographically
#      valid until it expires — only the PDP can stop honouring it;
#   2. the gateway replicas re-read the repository, which today means a restart: the
#      table is read once at start-up and there is no invalidation endpoint yet
#      (platform T-0177 adds one; until then a restart IS the invalidation);
#   3. Keycloak stops minting new tokens for the subject — sessions logged out for a
#      user, client secret rotated for a service account.
#
# Then the script MEASURES the propagation instead of claiming it: it calls the endpoint
# with the compromised token until the answer is 401 or 403 and fails if that takes longer
# than the bound (5 s per OPS-45).
#
# The script never prints a token, a secret or a password; only lengths and statuses.
set -uo pipefail

instance=""
policy=""
policy_key=""
user=""
service_account=""
verify_url=""
verify_token_file=""
bound=5
namespace=""
deployment="context-gateway-gateway"
configmap="context-gateway"
idm=""

die() { printf 'emergency-revoke: %s\n' "$1" >&2; exit 2; }

while [ $# -gt 0 ]; do
	case "$1" in
	--instance) instance="${2:?}"; shift 2 ;;
	--namespace) namespace="${2:?}"; shift 2 ;;
	--policy) policy="${2:?}"; shift 2 ;;
	--policy-key) policy_key="${2:?}"; shift 2 ;;
	--user) user="${2:?}"; shift 2 ;;
	--service-account) service_account="${2:?}"; shift 2 ;;
	--verify-url) verify_url="${2:?}"; shift 2 ;;
	--verify-token-file) verify_token_file="${2:?}"; shift 2 ;;
	--bound) bound="${2:?}"; shift 2 ;;
	--deployment) deployment="${2:?}"; shift 2 ;;
	--configmap) configmap="${2:?}"; shift 2 ;;
	--idm) idm="${2:?}"; shift 2 ;;
	-h | --help) sed -n '2,25p' "$0"; exit 0 ;;
	*) die "unknown argument: $1" ;;
	esac
done

[ -n "$instance" ] || die "usage: emergency-revoke.sh --instance <slug> [--policy NAME] [--user NAME | --service-account CLIENT]"
[ -n "$policy" ] || [ -n "$user" ] || [ -n "$service_account" ] ||
	die "nothing to revoke: give --policy, --user or --service-account"
namespace="${namespace:-$instance}"
# The seed mounts one file per manifest, so a Policy named `public-read` is the key
# `policy.yaml` unless the operator says otherwise; `--policy-key` covers the rest.
[ -n "$policy" ] && [ -z "$policy_key" ] && policy_key="policy.yaml"

started=$(date +%s)
elapsed() { printf '%ss' "$(($(date +%s) - started))"; }
step() { printf '[%6s] %s\n' "$(elapsed)" "$1"; }
fail=0
ko() { printf '[%6s] FAIL  %s\n' "$(elapsed)" "$1" >&2; fail=1; }

step "revoking on instance $instance (namespace $namespace), bound ${bound}s"

# 1. The Policy leaves the repository the gateway reads.
if [ -n "$policy" ]; then
	if kubectl -n "$namespace" get configmap "$configmap" -o "jsonpath={.data.$policy_key}" 2>/dev/null | grep -q "name: $policy"; then
		# A JSON Patch `remove` on a key that is gone fails loudly, which is what an
		# emergency wants: no silent "revoked" on a repository that still grants.
		if kubectl -n "$namespace" patch configmap "$configmap" \
			--type=json -p "[{\"op\": \"remove\", \"path\": \"/data/${policy_key//\//~1}\"}]" >/dev/null; then
			step "policy $policy removed from configmap $configmap ($policy_key)"
		else
			ko "policy $policy could not be removed from configmap $configmap"
		fi
	else
		ko "policy $policy is not in configmap $configmap under $policy_key — check --policy-key"
	fi
fi

# 2. The replicas re-read the repository. Restart, then wait: an unfinished rollout means
#    old pods are still answering with the old table.
if kubectl -n "$namespace" rollout restart "deployment/$deployment" >/dev/null; then
	step "restarting $deployment"
	if kubectl -n "$namespace" rollout status "deployment/$deployment" --timeout="${bound}s" >/dev/null; then
		step "$deployment is serving the repository without the policy"
	else
		ko "$deployment did not become ready within ${bound}s"
	fi
else
	ko "$deployment could not be restarted"
fi

# 3. Keycloak stops issuing new tokens for the subject. The admin token comes from the
#    environment (KEYCLOAK_ADMIN_TOKEN) or from the master-realm password grant with
#    KEYCLOAK_ADMIN_USER / KEYCLOAK_ADMIN_PASSWORD; neither is ever echoed.
admin_token() {
	if [ -n "${KEYCLOAK_ADMIN_TOKEN:-}" ]; then
		printf '%s' "$KEYCLOAK_ADMIN_TOKEN"
		return 0
	fi
	[ -n "${KEYCLOAK_ADMIN_USER:-}" ] && [ -n "${KEYCLOAK_ADMIN_PASSWORD:-}" ] || return 1
	curl -sS --max-time 10 \
		-d "client_id=admin-cli" -d "grant_type=password" \
		--data-urlencode "username=$KEYCLOAK_ADMIN_USER" \
		--data-urlencode "password=$KEYCLOAK_ADMIN_PASSWORD" \
		"$idm/realms/master/protocol/openid-connect/token" |
		sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
}

if [ -n "$user" ] || [ -n "$service_account" ]; then
	[ -n "$idm" ] || die "--idm <https://idm.host> is needed to reach Keycloak"
	token=$(admin_token)
	if [ -z "$token" ]; then
		ko "no Keycloak admin token: set KEYCLOAK_ADMIN_TOKEN, or KEYCLOAK_ADMIN_USER and KEYCLOAK_ADMIN_PASSWORD"
	else
		api="$idm/admin/realms/$instance"
		if [ -n "$user" ]; then
			id=$(curl -sS --max-time 10 -H "Authorization: Bearer $token" \
				"$api/users?username=$user&exact=true" |
				sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)
			if [ -z "$id" ]; then
				ko "user $user not found in realm $instance"
			else
				code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST \
					-H "Authorization: Bearer $token" "$api/users/$id/logout")
				case "$code" in
				20*) step "sessions of $user logged out" ;;
				*) ko "logout of $user answered $code" ;;
				esac
			fi
		fi
		if [ -n "$service_account" ]; then
			id=$(curl -sS --max-time 10 -H "Authorization: Bearer $token" \
				"$api/clients?clientId=$service_account" |
				sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)
			if [ -z "$id" ]; then
				ko "client $service_account not found in realm $instance"
			else
				# Rotating the secret is what stops the client credentials grant; the
				# new secret is never printed, it is read from Keycloak when needed.
				code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST \
					-H "Authorization: Bearer $token" "$api/clients/$id/client-secret")
				case "$code" in
				20*) step "client secret of $service_account rotated" ;;
				*) ko "secret rotation of $service_account answered $code" ;;
				esac
			fi
		fi
	fi
fi

# 4. Measure what actually happened at the enforcement point (OPS-45: hard 5 s).
if [ -n "$verify_url" ] && [ -n "$verify_token_file" ]; then
	[ -r "$verify_token_file" ] || die "cannot read $verify_token_file"
	deadline=$((started + bound))
	code=""
	while :; do
		code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
			-H "Authorization: Bearer $(cat "$verify_token_file")" "$verify_url" 2>/dev/null) || code="curl-error"
		case "$code" in
		401 | 403) break ;;
		esac
		[ "$(date +%s)" -lt "$deadline" ] || break
		sleep 1
	done
	took=$(($(date +%s) - started))
	case "$code" in
	401 | 403)
		if [ "$took" -le "$bound" ]; then
			step "the compromised credential is refused ($code) after ${took}s, within the ${bound}s bound"
		else
			ko "the compromised credential is refused ($code) only after ${took}s, over the ${bound}s bound (OPS-45)"
		fi
		;;
	*) ko "the compromised credential still answers $code after ${took}s (OPS-45)" ;;
	esac
else
	step "no --verify-url given: revocation is not measured, only performed"
fi

if [ "$fail" -eq 0 ]; then
	step "revocation complete"
	exit 0
fi
printf 'emergency-revoke: revocation did NOT complete cleanly — read the FAIL lines above\n' >&2
exit 1
