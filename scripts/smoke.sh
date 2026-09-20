#!/usr/bin/env bash
# Smoke-test a deployed instance from outside the cluster.
#   scripts/smoke.sh <base-url> <idm-url>
# e.g. scripts/smoke.sh https://2.28.67.127.sslip.io https://idm.2.28.67.127.sslip.io
#
# Every check asserts an exact HTTP status over a *valid* TLS chain (no -k), so an
# expired or missing certificate fails the run. Cluster-side checks (workload
# readiness) use the current kube context.
set -uo pipefail

base="${1:?usage: smoke.sh <base-url> <idm-url>}"
idm="${2:?usage: smoke.sh <base-url> <idm-url>}"
realm="${JC_REALM:-dev}"
slug="${JC_INSTANCE:-$realm}"
# The Portal has a host of its own behind the edge login (ADR-N-019), derived the way the
# route derives it; the apex keeps the shared surfaces and redirects the rest there.
portal="${JC_PORTAL_URL:-https://portal.${base#https://}}"

pass=0
fail=0
skipped=0

ok() { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
ko() { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }
# A check whose subject is not deployed in this instance. Not a pass: it never ran.
skip() { printf '  skip  %s\n' "$1"; skipped=$((skipped + 1)); }

# The entity type an endpoint grants this caller, from its own access document (EP-55).
#
# A read names a type (GW33), and these grants are `retrieveOps`, which is `retrieveEntity` and
# `queryEntity` and nothing else (CIM 009 Table 4.20-2) — the type list is `federationOps`, so
# asking an endpoint what types it has is a 403 by design. The access document is how a client
# learns the type, and what a probe reads for the same reason.
type_of() {
	curl -sS --max-time 20 -H 'Accept: application/json' "$base/api/endpoint/$1/access" 2>/dev/null |
		python3 -c 'import json,sys
try:
    document = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for permission in document.get("permissions", []):
    entity_type = (permission.get("resource") or {}).get("type")
    if entity_type:
        print(entity_type)
        break'
}

# The gateway routes are only configured for the components this instance deploys, so the
# suite asks APISIX itself what exists instead of assuming a fixed platform.
routes=$(kubectl get configmap apisix-standalone-config -n "$slug" -o jsonpath='{.data.apisix\.yaml}' 2>/dev/null || true)
has_route() { printf '%s' "$routes" | grep -q "^  - id: $1\$"; }

# status <expected> <description> <curl args...>
status() {
	local expected="$1" desc="$2"; shift 2
	local got
	got=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$@" 2>/dev/null) || got="curl-error"
	if [ "$got" = "$expected" ]; then ok "$desc ($got)"; else ko "$desc (expected $expected, got $got)"; fi
}

echo "smoke: $base (realm $realm)"

echo "workloads"
if scripts/wait-rollouts.sh "$slug" "${JC_ROLLOUT_TIMEOUT:-120}" >/tmp/smoke-rollouts.log 2>&1; then
	ok "all workloads ready"
else
	ko "workloads not ready"; tail -20 /tmp/smoke-rollouts.log
fi

echo "identity"
status 200 "keycloak OIDC discovery over valid TLS" "$idm/realms/$realm/.well-known/openid-configuration"
if curl -sS --max-time 20 "$idm/realms/$realm/.well-known/openid-configuration" 2>/dev/null |
	grep -q '"jwks_uri"'; then ok "realm $realm publishes a JWKS uri"; else ko "realm $realm has no JWKS uri"; fi
status 200 "keycloak JWKS over valid TLS" "$idm/realms/$realm/protocol/openid-connect/certs"

echo "gateway"
# Everything reaches the platform through APISIX; the identity host is the route that
# exists in every instance, even before the portal and the gateway are deployed.
if curl -sSI --max-time 20 "$idm/realms/$realm/" 2>/dev/null | grep -qi '^server: *APISIX'; then
	ok "traffic is served by APISIX, not by the ingress controller"
else
	ko "no APISIX Server header on $idm — the route is not going through the gateway"
fi

echo "edge"
# The Portal host is the DEMO entry: a missing Ingress rule for it fails silently as a 404
# from the ingress controller, and a missing SAN as a handshake error. Unauthenticated, the
# edge login answers a 302 to the realm's authorization endpoint with the `edge` client and
# the callback that client lists (ADR-N-019, AP-27); anything else means the openid-connect
# plugin is not in front of the Portal or points at a client Keycloak will refuse.
if has_route portal-ui; then
	edge_callback=$(printf '%s' "$portal/callback" | sed 's,:,%3A,g; s,/,%2F,g')
	location=$(curl -sS -o /dev/null -w '%{redirect_url}' --max-time 20 "$portal/" 2>/dev/null || true)
	# The query parameters come in whatever order the plugin builds them.
	case "$location" in
		"$idm/realms/$realm/protocol/openid-connect/auth?"*) ;;
		*) location="" ;;
	esac
	if [ -n "$location" ] && printf '%s' "$location" | grep -q "client_id=edge" && printf '%s' "$location" | grep -q "redirect_uri=$edge_callback"; then
		ok "portal host sends an anonymous visitor to the edge login"
	else
		ko "portal host does not redirect to the edge login with client_id=edge and redirect_uri=$edge_callback (got: ${location:-none})"
	fi
	# The apex still answers: `/` goes to the Portal host, so the one hostname people learn
	# first keeps working.
	location=$(curl -sS -o /dev/null -w '%{redirect_url}' --max-time 20 "$base/" 2>/dev/null || true)
	if [ "$location" = "$portal/" ]; then ok "apex redirects to the portal host"; else ko "apex does not redirect to $portal/ (got: ${location:-none})"; fi
else
	skip "portal host (route portal-ui not configured in this instance)"
fi
# A streamed body reaches the application (T-2263). APISIX inherits `client_max_body_size 0`,
# which nginx reads as "no limit" for a body with a Content-Length and as "zero" in its chunked
# filter, so with the default every `Transfer-Encoding: chunked` write is refused with 413 before
# authentication — measured on dev as a 435-byte Portal write. The probe is unauthenticated on
# purpose: what matters is that the answer comes from the application (401 or 403, whichever the
# route's own refusal is) and not the edge's 413.
if has_route portal-api; then
	chunked=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -X PUT \
		-H 'Content-Type: application/json' -H 'Transfer-Encoding: chunked' \
		--data-binary '{"probe":"chunked"}' \
		"$portal/api/v1/projects/helsinki/pipelines/smoke-probe" 2>/dev/null || true)
	case "$chunked" in
		413) ko "the edge refuses a chunked request body (413): client_max_body_size is 0 again" ;;
		4*|2*) ok "a chunked request body reaches the application ($chunked)" ;;
		*) ko "a chunked request body got ${chunked:-no answer}" ;;
	esac
else
	skip "chunked body (route portal-api not configured in this instance)"
fi
headers=$(curl -sSI --max-time 20 "$idm/realms/$realm/" 2>/dev/null)
missing=""
for header in strict-transport-security x-content-type-options x-frame-options referrer-policy; do
	printf '%s' "$headers" | grep -qi "^$header:" || missing="$missing $header"
done
if [ -z "$missing" ]; then ok "security response headers present"; else ko "response headers missing:$missing"; fi
# BSI TR-02102: TLS 1.2 is the floor and the CBC suites are out. Both are asserted against
# the live listener, because the policy that produces them lives in the ingress controller
# and never appears in this repo's rendered output.
if curl -sS -o /dev/null --max-time 20 --tls-max 1.1 "$idm/realms/$realm/" >/dev/null 2>&1; then
	ko "the edge negotiated TLS 1.1"
else
	ok "the edge refuses TLS 1.1"
fi
if command -v openssl >/dev/null 2>&1; then
	host=${idm#https://}; host=${host%%/*}
	# The output is captured before it is matched: a refused handshake makes openssl exit
	# non-zero, and under `pipefail` that would sink the whole pipeline even though the grep
	# found exactly what this check wants to see.
	handshake=$(echo | openssl s_client -connect "$host:443" -servername "$host" -tls1_2 \
		-cipher 'ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:DES-CBC3-SHA' 2>&1 || true)
	if printf '%s' "$handshake" | grep -qF 'Cipher is (NONE)'; then
		ok "the edge refuses CBC and 3DES suites"
	else
		ko "the edge negotiated a CBC or 3DES suite"
	fi
else
	skip "cipher suite check (openssl not installed)"
fi

echo "token"
# The client secret is never in the repo: CI passes it in, otherwise it is read from the
# cluster the kubeconfig already grants access to.
client_id="${JC_SMOKE_CLIENT_ID:-apisix-gateway}"
client_secret="${JC_SMOKE_CLIENT_SECRET:-$(kubectl get secret "keycloak-client-$client_id" -n "$slug" -o jsonpath='{.data.client-secret}' 2>/dev/null | base64 -d 2>/dev/null || true)}"
token=""
if [ -z "$client_secret" ]; then
	ko "no client secret for $client_id (set JC_SMOKE_CLIENT_SECRET or point KUBECONFIG at the instance)"
else
	token=$(curl -sS --max-time 20 -d grant_type=client_credentials -d "client_id=$client_id" \
		--data-urlencode "client_secret=$client_secret" \
		"$idm/realms/$realm/protocol/openid-connect/token" 2>/dev/null |
		sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
	if [ -n "$token" ]; then ok "client_credentials token from realm $realm"; else ko "no access_token for $client_id in realm $realm"; fi
fi

# DEMO.md step 1 is a human login. The development profile seeds demo.steward and
# demo.viewer with per-cluster passwords (Secret keycloak-user-<name>); a password grant
# through the smoke's confidential client proves the user, the credential and the realm
# policy agree. An instance without the seed (production) has nothing to prove: skip.
demo_user="${JC_SMOKE_DEMO_USER:-demo.viewer}"
demo_password="${JC_SMOKE_DEMO_PASSWORD:-$(kubectl get secret "keycloak-user-${demo_user//./-}" -n "$slug" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)}"
# The Secret is named after the short name; the realm stores the email as the username
# (registrationEmailAsUsername), so that is what a password grant has to send.
# The organization's domain is the users' email domain and every URN's second segment; the
# gateway is deployed with it, so it is read from there rather than written here.
org="${JC_SMOKE_ORG:-$(kubectl get deploy context-gateway -n "$slug" \
	-o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="JC_GATEWAY_ORG_DOMAIN")].value}' 2>/dev/null || true)}"
org="${org:-hel.fi}"
demo_login="${demo_user}@${org}"
demo_token=""
if [ -z "$demo_password" ]; then
	skip "demo user login (no demo users seeded in this instance)"
elif [ -z "$client_secret" ]; then
	ko "demo user login needs the $client_id client secret"
else
	demo_token=$(curl -sS --max-time 20 -d grant_type=password \
		-d "client_id=$client_id" --data-urlencode "client_secret=$client_secret" \
		-d "username=$demo_login" --data-urlencode "password=$demo_password" \
		"$idm/realms/$realm/protocol/openid-connect/token" 2>/dev/null |
		sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
	if [ -n "$demo_token" ]; then ok "demo user $demo_login logs in with a password grant"; else ko "demo user $demo_login cannot log in with a password grant"; fi
fi

echo "edge login"
# The edge (APISIX openid-connect, ADR-N-019) forwards the person's access token and the Portal
# verifies it like a bearer, audience included. A realm whose `edge` client has no audience
# mapper for portal-api mints tokens the Portal refuses: the login page, then a 401, then the
# login page again, for everybody (T-0619). The client's mappers are read through the admin
# API with the instance's own admin secret; direct grants are off for `edge` on purpose, so
# there is no token to inspect from outside.
admin_user="${JC_SMOKE_ADMIN_USER:-admin}"
admin_password="${JC_SMOKE_ADMIN_PASSWORD:-$(kubectl get secret keycloak-admin-user -n "$slug" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)}"
if [ -z "$admin_password" ]; then
	skip "edge client audience (no admin secret: set JC_SMOKE_ADMIN_PASSWORD or point KUBECONFIG at the instance)"
else
	admin_token=$(curl -sS --max-time 20 -d grant_type=password -d client_id=admin-cli \
		-d "username=$admin_user" --data-urlencode "password=$admin_password" \
		"$idm/realms/master/protocol/openid-connect/token" 2>/dev/null |
		sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
	edge_client=$(curl -sS --max-time 20 -H "Authorization: Bearer $admin_token" "$idm/admin/realms/$realm/clients?clientId=edge" 2>/dev/null || true)
	if [ -z "$admin_token" ]; then
		ko "no admin token for $admin_user in realm master"
	elif printf '%s' "$edge_client" | grep -q '"included.client.audience" *: *"portal-api"'; then
		ok "edge client mints tokens with audience portal-api (the Portal verifies aud)"
	else
		ko "edge client has no portal-api audience mapper: every edge login is a 401 (T-0619)"
	fi
	# The agent proxy reads samples through whatever endpoint a run names, including one approved
	# after the realm was written, so its token carries the gateway-wide audience beside the seeded
	# slugs and the Policy decides per endpoint (T-0666, Architecture/12 §5). Without it the kit
	# pass reads a 401 for every type and the generated app has no data.
	if [ -n "$admin_token" ]; then
		proxy_client=$(curl -sS --max-time 20 -H "Authorization: Bearer $admin_token" "$idm/admin/realms/$realm/clients?clientId=helsinki-agent-proxy" 2>/dev/null || true)
		if [ "$proxy_client" = "[]" ]; then
			skip "agent proxy audience (no helsinki-agent-proxy client in realm $realm)"
		elif printf '%s' "$proxy_client" | grep -q '"included.custom.audience" *: *"context-gateway"'; then
			ok "agent proxy client mints tokens with audience context-gateway (reads through any endpoint its Policy grants)"
		else
			ko "agent proxy client has no context-gateway audience: a run reads a 401 through an endpoint approved after the realm (T-0666)"
		fi
	fi
fi

echo "authenticated routes"
if has_route portal-api; then
	# /api/v1/health is public (probes, uptime checks); /api/v1/auth/me is the smallest route
	# behind the Portal's own token verification. The edge passes a call without a session
	# through untouched (`unauth_action: pass`, no bearer verification: ES256 vs
	# lua-resty-openidc, T-0252), so the 401 and the 200 below are the Portal's own answers.
	status 200 "portal API health is public" "$portal/api/v1/health"
	status 401 "portal API rejects an unauthenticated call" "$portal/api/v1/auth/me"
	# The Portal's own code flow, the fallback of an installation without the edge, starts
	# here with a 302 to Keycloak. The redirect_uri it carries must be one the portal-api
	# client lists exactly, or Keycloak answers "Invalid parameter: redirect_uri" and no human
	# can log in; that page is a 400 the status checks never see.
	callback=$(printf '%s' "$portal/api/v1/auth/callback" | sed 's,:,%3A,g; s,/,%2F,g')
	location=$(curl -sS -o /dev/null -w '%{redirect_url}' --max-time 20 "$portal/api/v1/auth/login" 2>/dev/null || true)
	case "$location" in
		"$idm/realms/$realm/protocol/openid-connect/auth?"*"redirect_uri=$callback"*) ok "portal login redirects to keycloak with the callback the client lists" ;;
		*) ko "portal login redirect is not keycloak with redirect_uri=$callback (got: ${location:-none})" ;;
	esac
	if [ -n "$demo_token" ]; then
		spaces=$(curl -sS --max-time 20 -H "Authorization: Bearer $demo_token" "$portal/api/v1/projects/helsinki/spaces" 2>/dev/null || true)
		if printf '%s' "$spaces" | grep -q '"name": *"helsinki"'; then
			ok "portal lists the seeded helsinki space (the configuration repository is seeded)"
		else
			ko "portal does not list the helsinki space: ${spaces:0:160}"
		fi
		# The pipeline test (PL-43): one message through a candidate pipeline on the project's
		# runner, captured on the Portal's internal listener. A 503 here is the runner URL or
		# the capture URL missing from the Portal, or a NetworkPolicy between the two. The viewer
		# may not test a pipeline (403 is the role, not the wiring), so this runs as the steward.
		steward_password="${JC_SMOKE_STEWARD_PASSWORD:-$(kubectl get secret keycloak-user-demo-steward -n "$slug" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)}"
		steward_token=$(curl -sS --max-time 20 -d grant_type=password \
			-d "client_id=$client_id" --data-urlencode "client_secret=$client_secret" \
			-d "username=demo.steward@${org}" --data-urlencode "password=$steward_password" \
			"$idm/realms/$realm/protocol/openid-connect/token" 2>/dev/null |
			sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
		ptest='{"pipeline":{"apiVersion":"joinedcontext.com/v1alpha1","kind":"Pipeline","metadata":{"name":"smoke-test","namespace":"helsinki"},"spec":{"class":"auto","period":"60s","source":{"dataSourceRef":{"kind":"DataSource","name":"hsl-citybikes-gbfs"}},"compute":{"kind":"bloblang","bloblang":"root.id = \"urn:ngsi-ld:SmokeProbe:hel.fi:helsinki:1\"\nroot.type = \"SmokeProbe\""},"output":{"type":"SmokeProbe","mode":"upsert"},"targetEndpoint":"urn:ngsi-ld:Endpoint:hel.fi:helsinki:helsinki-all"}},"sample":{"text":"{\"a\":1}","format":"json"}}'
		status 200 "pipeline test runs a candidate on the runner and captures the output" -X POST -H "Authorization: Bearer $steward_token" \
			-H 'Content-Type: application/json' -d "$ptest" "$portal/api/v1/projects/helsinki/pipelines/test"
		# A Check fetches the URL a person typed on the project's runner (MF-39, T-0752), so an
		# address inside the cluster or the node's metadata service must answer as unreachable:
		# records, a status or a body mean the runner's egress lets a typed URL in. The metadata
		# address goes over 443, which the mesh proxy does not carry, so a refusal is the policy's.
		for inside in "https://kubernetes.default.svc/version" \
			"https://169.254.169.254/hetzner/v1/metadata" \
			"http://keycloak-app-keycloakx-http.${slug}.svc/realms/master" \
			"http://context-broker.${slug}.svc:8080/ngsi-ld/v1/types"; do
			probe=$(curl -sS --max-time 60 -X POST -H "Authorization: Bearer $steward_token" -H 'Content-Type: application/json' \
				-d "{\"apiVersion\":\"joinedcontext.com/v1alpha1\",\"kind\":\"DataSource\",\"metadata\":{\"name\":\"smoke-probe\",\"namespace\":\"helsinki\"},\"spec\":{\"type\":\"http\",\"http\":{\"url\":\"$inside\"}}}" \
				"$portal/api/v1/projects/helsinki/datasources?dryRun=All" 2>/dev/null || true)
			said=$(printf '%s' "$probe" | sed -n 's/.*"skipped": *"\([^"]*\)".*/\1/p')
			case "$said" in
			"the feed could not be reached"* | "the feed did not answer within"* | "the feed answered nothing"*)
				ok "a probe of $inside stays outside the cluster: $said" ;;
			"")
				ko "a probe of $inside answered no refusal: ${probe:0:160}" ;;
			*)
				ko "a probe of $inside reached it: $said" ;;
			esac
		done
		# A take cleans up after itself (T-0667, T-0750): helsinki lists the endpoints, pipelines and
		# spaces its seed commits and at most one more of each (a take in flight); residue of
		# recordings and e2e turns the run red.
		seed=$(kubectl get configmap gitea-bootstrap-seed -n "$slug" -o 'jsonpath={.data}' 2>/dev/null)
		for kind in "endpoints Endpoint projects__helsinki__spaces__[a-z0-9-]*__endpoints__[a-z0-9-]*\.yaml" \
			"pipelines Pipeline projects__helsinki__pipelines__[a-z0-9-]*__pipeline\.yaml" \
			"spaces ContextSpace projects__helsinki__spaces__[a-z0-9-]*__space\.yaml"; do
			set -- $kind
			plural=$1 manifest_kind=$2 seed_pattern=$3
			seeded=$(printf '%s' "$seed" | grep -o "$seed_pattern" | sort -u | wc -l)
			if [ "$seeded" -eq 0 ]; then
				skip "helsinki $plural residue (no Helsinki seed in this instance)"
				continue
			fi
			listed=$(curl -sS --max-time 20 -H "Authorization: Bearer $demo_token" "$portal/api/v1/projects/helsinki/$plural" 2>/dev/null |
				grep -o "\"kind\": *\"$manifest_kind\"" | wc -l)
			if [ "$listed" -eq 0 ]; then
				ko "helsinki lists no $plural for $seeded seeded: the list did not answer"
			elif [ "$listed" -le $((seeded + 1)) ]; then
				ok "helsinki lists $listed $plural for $seeded seeded (no residue)"
			else
				ko "helsinki lists $listed $plural for $seeded seeded: residue of takes or e2e (T-0667)"
			fi
		done
	else
		skip "portal space list (no demo user token)"
	fi
	if [ -n "$token" ]; then
		# A bearer caller (CLI, service account) passes the edge login untouched (AP-28).
		status 200 "portal API answers a bearer call through the edge" -H "Authorization: Bearer $token" "$portal/api/v1/auth/me"
		status 401 "portal API refuses a tampered token" -H "Authorization: Bearer ${token%.*}.forged" "$portal/api/v1/auth/me"
		# header {"alg":"ES256","typ":"JWT"}, payload {"exp":1}: expired and unsigned at once.
		# Built at run time: a JWT-shaped literal in the repo trips gitleaks.
		b64url() { printf '%s' "$1" | base64 | tr -d '\n=' | tr '+/' '-_'; }
		expired="$(b64url '{"alg":"ES256","typ":"JWT"}').$(b64url '{"exp":1}').AAAA"
		status 401 "portal API refuses an expired token" -H "Authorization: Bearer $expired" "$portal/api/v1/auth/me"
	else
		skip "portal API bearer call (no token)"
	fi
else
	skip "portal API (route portal-api not configured in this instance)"
fi

echo "context endpoint"
if has_route context-endpoint; then
	# The slug comes from the Endpoint the forge bootstrap seeds (T-0263/T-0277, T-0278: the
	# gateway serves the forge's checkout), the same way the route table comes from APISIX: a
	# slug written into this script would drift from the seed, and a made-up one cannot exist
	# (slugs are 26+ base32 characters). A seed key is the repository path with `/` as `__`.
	ep="${JC_SMOKE_ENDPOINT:-$(kubectl get configmap gitea-bootstrap-seed -n "$slug" -o jsonpath='{.data.projects__banskabystrica__spaces__ovzdusie__endpoints__public-air\.yaml}' 2>/dev/null | sed -n 's/^ *slug: *//p' | head -1)}"
	# Writes are bound to the conformance ServiceAccount (GW22): its client_credentials token
	# carries the slug as audience and an azp the gateway resolves to the manifest (PF-45, PF-46).
	# The apisix-gateway token above is minted for the Portal and names no account here.
	ep_client="${JC_SMOKE_ENDPOINT_CLIENT_ID:-banskabystrica-conformance}"
	ep_secret="${JC_SMOKE_ENDPOINT_CLIENT_SECRET:-$(kubectl get secret "keycloak-client-$ep_client" -n "$slug" -o jsonpath='{.data.client-secret}' 2>/dev/null | base64 -d 2>/dev/null || true)}"
	ep_token=""
	if [ -z "$ep" ]; then
		skip "endpoint round trip (no Endpoint seeded on the gateway in this instance)"
	elif [ -z "$ep_secret" ]; then
		ko "no client secret for $ep_client (set JC_SMOKE_ENDPOINT_CLIENT_SECRET or point KUBECONFIG at the instance)"
	else
		ep_token=$(curl -sS --max-time 20 -d grant_type=client_credentials -d "client_id=$ep_client" \
			--data-urlencode "client_secret=$ep_secret" \
			"$idm/realms/$realm/protocol/openid-connect/token" 2>/dev/null |
			sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
		if [ -n "$ep_token" ]; then ok "client_credentials token for $ep_client"; else ko "no access_token for $ep_client in realm $realm"; fi
	fi
	if [ -n "$ep_token" ]; then
		# application/json, so the core @context applies; application/ld+json without an @context
		# member is a 400 (CIM 009 6.3.5), which masked every write check as "passing".
		# The first create also creates the tenant on Antares (5.5.10); reads before it are 404.
		urn="urn:ngsi-ld:AirQualityObserved:${org}:ovzdusie:smoke-1"
		body='{"id":"'"$urn"'","type":"AirQualityObserved","dateObserved":{"type":"Property","value":"2026-01-01T00:00:00Z"}}'
		status 201 "entity create through the endpoint" -X POST -H 'Content-Type: application/json' \
			-H "Authorization: Bearer $ep_token" -d "$body" "$base/api/endpoint/$ep/ngsi-ld/v1/entities"
		status 200 "entity read back" -H "Authorization: Bearer $ep_token" "$base/api/endpoint/$ep/ngsi-ld/v1/entities/$urn"
		# A foreign organization prefix must be refused by the gateway, not stored.
		foreign='{"id":"urn:ngsi-ld:AirQualityObserved:someone-else.sk:ovzdusie:smoke-2","type":"AirQualityObserved"}'
		status 400 "write with a foreign URN prefix is refused" -X POST -H 'Content-Type: application/json' \
			-H "Authorization: Bearer $ep_token" -d "$foreign" "$base/api/endpoint/$ep/ngsi-ld/v1/entities"
		status 204 "entity delete" -X DELETE -H "Authorization: Bearer $ep_token" "$base/api/endpoint/$ep/ngsi-ld/v1/entities/$urn"

		# T-0945: what the space lists, the space serves. An entity whose URN carries another
		# organization's domain lists (the broker holds it) and answers 400 on retrieve (the
		# gateway checks the prefix, GW20), so a steward can neither read nor correct it. A
		# round trip of the script's own entity would never see that: the rows that drift are
		# the ones somebody else wrote.
		listed=$(curl -sS --max-time 20 -H "Authorization: Bearer $ep_token" \
			"$base/api/endpoint/$ep/ngsi-ld/v1/entities?type=AirQualityObserved&limit=50" 2>/dev/null |
			tr ',' '\n' | sed -n 's/.*"id":"\(urn:ngsi-ld:[^"]*\)".*/\1/p' | sort -u)
		if [ -z "$listed" ]; then
			skip "every listed entity retrieves by id (the space holds none)"
		else
			unreadable=""
			for one in $listed; do
				got=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
					-H "Authorization: Bearer $ep_token" \
					"$base/api/endpoint/$ep/ngsi-ld/v1/entities/$one" 2>/dev/null) || got="curl-error"
				[ "$got" = "200" ] || unreadable="$unreadable $one($got)"
			done
			if [ -z "$unreadable" ]; then
				ok "every listed entity retrieves by id ($(printf '%s\n' "$listed" | wc -l) of them)"
			else
				ko "listed but not retrievable, so no steward can read or correct them:$unreadable"
			fi
		fi
	fi
else
	skip "endpoint round trip (route context-endpoint not configured in this instance)"
fi

echo "helsinki space"
# DEMO.md steps 3 and 4 on the shared `helsinki` space: four public endpoints over one space,
# three of them bound by policyRef to one entity type, the fourth to everything; every one
# answers NGSI-LD, MCP and the model's LinkML; the streams of the resident runner fill it. The
# slugs come from the forge's seed the way the ovzdusie one does above.
if has_route context-endpoint; then
	slug_of() { kubectl get configmap gitea-bootstrap-seed -n "$slug" -o jsonpath="{.data.projects__helsinki__spaces__helsinki__endpoints__helsinki-$1\.yaml}" 2>/dev/null | sed -n 's/^ *slug: *//p' | head -1; }
	all=$(slug_of all)
	if [ -z "$all" ]; then
		skip "helsinki endpoints (no Helsinki seed on the gateway in this instance)"
	else
		mcp='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
		for name in events bikes transport all; do
			hs=$(slug_of "$name")
			granted=$(type_of "$hs")
			if [ -z "$granted" ]; then
				ko "helsinki-$name names no type in its access document"
				continue
			fi
			status 200 "helsinki-$name serves NGSI-LD" "$base/api/endpoint/$hs/ngsi-ld/v1/entities?type=$granted&limit=1"
			status 200 "helsinki-$name serves the LinkML model" "$base/api/endpoint/$hs/schema/v1/linkml"
			status 200 "helsinki-$name answers its DCAT record on the Portal host" "$portal/api/endpoint/$hs/"
			status 200 "helsinki-$name answers an MCP tools/list" -X POST -H 'Content-Type: application/json' \
				-H 'Accept: application/json, text/event-stream' -d "$mcp" "$base/api/endpoint/$hs/mcp"
		done
		# The slice is real: a type the endpoint's Policy does not grant is an empty answer, not
		# the neighbour's data (EP-14, 404-vs-403 narrowing keeps it a 200).
		body=$(curl -sS --max-time 20 "$base/api/endpoint/$(slug_of bikes)/ngsi-ld/v1/entities?type=Event&limit=1" 2>/dev/null || true)
		if [ "$body" = "[]" ]; then ok "helsinki-bikes does not serve events"; else ko "helsinki-bikes served events: ${body:0:120}"; fi
		# Data flows: the bike feed answers within a minute of the runner starting, the events
		# register at once; the buses depend on HSL's timetable, so their absence is a note.
		flowing() { # type seconds
			deadline=$(( $(date +%s) + $2 ))
			while :; do
				body=$(curl -sS --max-time 20 "$base/api/endpoint/$all/ngsi-ld/v1/entities?type=$1&limit=1" 2>/dev/null || true)
				case "$body" in "[{"*) return 0 ;; esac
				[ "$(date +%s)" -ge "$deadline" ] && return 1
				sleep 10
			done
		}
		if flowing BikeHireDockingStation 120; then ok "city bike stations are flowing into the space"; else ko "no BikeHireDockingStation entity after 120 s"; fi
		if flowing Event 60; then ok "events are flowing into the space"; else ko "no Event entity after 60 s"; fi
		if flowing Vehicle 30; then ok "buses are flowing into the space"; else skip "no Vehicle entity yet (HSL's trunk lines may be off the road at this hour)"; fi
	fi
else
	skip "helsinki endpoints (route context-endpoint not configured in this instance)"
fi

echo "forge"
if has_route gitea-forge; then
	# Gitea listens at the root; a 200 here proves both halves of the prefix — the gateway
	# rewrite that takes /git off, and the ROOT_URL that put it there.
	status 200 "git forge answers under the /git prefix" "$base/git/api/healthz"
	# A person signed in with Keycloak reads the configuration repository (PF-79). Three
	# things make that true and each fails silently: the team exists, it reads, and the
	# forge's OpenID Connect source maps the realm group onto it. Checked with the
	# administrator credential the bootstrap Job already uses, in-cluster.
	forge_admin_user=$(kubectl get secret gitea-admin-credentials -n "$slug" -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || true)
	forge_admin_pw=$(kubectl get secret gitea-admin-credentials -n "$slug" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)
	forge_org=$(kubectl get job gitea-bootstrap -n "$slug" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="ORG")].value}' 2>/dev/null || true)
	forge_org="${forge_org:-joinedcontext}"
	if [ -n "$forge_admin_pw" ]; then
		teams=$(curl -sS --max-time 20 -u "$forge_admin_user:$forge_admin_pw" \
			"$base/git/api/v1/orgs/$forge_org/teams" 2>/dev/null || true)
		if printf '%s' "$teams" | grep -q '"name": *"readers"'; then
			ok "the forge has the readers team a signed-in person lands in"
		else
			ko "the forge has no readers team: every Keycloak login meets a 404 on the private repository"
		fi
		# What a team may do is its unit map: Gitea computes the summary `permission` from
		# it and answers "none" for any map it did not mint itself, so a team that reads
		# the code unit looks unprivileged there (it read "none" on dev while the readers
		# team was reading perfectly well).
		units=$(printf '%s' "$teams" | tr ',' '\n')
		if printf '%s' "$units" | grep -q '"repo.code": *"read"'; then
			ok "a forge team reads the configuration repository (PF-79)"
		else
			ko "no forge team carries read permission"
		fi
		if printf '%s' "$units" | grep -Eq '"repo.code": *"(write|admin)"'; then
			ko "a forge team writes the configuration repository: merging is the Portal's (PF-80)"
		else
			ok "no forge team writes it, so merging stays the Portal's approval (PF-80)"
		fi
	else
		skip "forge teams (no gitea-admin-credentials in $slug)"
	fi
	# The repository stays private: without a session the file is not served (PF-79).
	status 404 "the configuration repository is not readable without a session" \
		"$base/git/$forge_org/configuration/raw/branch/main/platform-settings.yaml"
else
	skip "git forge (route gitea-forge not configured in this instance)"
fi

echo "catalogue"
if has_route ckan; then
	# The catalogue has a host of its own, derived the way the route derives it.
	catalogue="${JC_CATALOGUE_URL:-https://data.${base#https://}}"
	status 200 "catalogue front page over valid TLS" "$catalogue/"
	status 200 "catalogue Action API answers" "$catalogue/api/3/action/status_show"
	# The theme is the whole point of OPS-47: the front page has to carry the instance's
	# own name and its own primary colour, and neither may be a literal in any image.
	name=$(kubectl get configmap portal-branding -n "$slug" \
		-o jsonpath='{.data.branding\.yaml}' 2>/dev/null | sed -n 's/^instanceName: *//p' | tr -d "'\"")
	primary=$(kubectl get configmap portal-branding -n "$slug" \
		-o jsonpath='{.data.branding\.yaml}' 2>/dev/null | sed -n 's/^  primary: *//p' | tr -d "'\"")
	page=$(curl -sS --max-time 20 "$catalogue/" 2>/dev/null || true)
	if [ -n "$name" ] && printf '%s' "$page" | grep -qF "$name"; then
		ok "catalogue front page carries the instance name"
	else
		ko "catalogue front page does not carry the instance name (${name:-<no branding configured>})"
	fi
	if [ -n "$primary" ] && printf '%s' "$page" | grep -qF -- "--jc-primary: $primary"; then
		ok "catalogue front page carries the branded primary colour"
	else
		ko "catalogue front page does not carry the branded primary colour (${primary:-<none>})"
	fi
	# The one path on the primary host that leads to the catalogue.
	status 302 "/ckan on the primary host redirects to the catalogue" "$base/ckan"
	# The publisher's token (T-0493): the catalogue's api-token Job keeps one of the site
	# administrator in `ckan-api-token`. Listing that user's tokens is refused to anonymous, and
	# CKAN reads a token signed with a key it no longer has as anonymous, so a 200 here is a
	# token that survived every restart since it was minted.
	ckan_token=$(kubectl get secret ckan-api-token -n "$slug" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)
	ckan_admin=$(kubectl get secret ckan-admin-credentials -n "$slug" -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || true)
	if [ -z "$ckan_token" ] || [ -z "$ckan_admin" ]; then
		ko "no CKAN API token in Secret ckan-api-token: the catalogue's api-token Job has not written it (T-0493)"
	elif curl -sS --max-time 20 -H "Authorization: $ckan_token" -H 'Content-Type: application/json' \
		-d "{\"user_id\": \"$ckan_admin\"}" "$catalogue/api/3/action/api_token_list" 2>/dev/null |
		grep -q '"success": *true'; then
		ok "the publisher's CKAN API token authenticates as the site administrator"
	else
		ko "the CKAN API token in ckan-api-token no longer authenticates (T-0493)"
	fi
else
	skip "catalogue (route ckan not configured in this instance)"
fi

echo "network policy"
image="docker.io/busybox:1.38@sha256:dc2d74b28e4cf8984fa52af1f39bc7c3d9c73760b41a74d629f5d11b1ab28616"
# One probe pod, parameterised by the command it runs: probe_overrides <pod-name> <command-json>.
# It has to stay OUT of the mesh: a meshed probe only completes a TCP handshake with its
# own outbound proxy on localhost, so `nc -z` reports success no matter what the policy
# does. The opt-out carries the reason the justify-linkerd-inject-opt-out policy asks for.
probe_overrides() {
	cat <<JSON
{
  "metadata": {
    "annotations": {
      "linkerd.io/inject": "disabled",
      "mesh.joinedcontext.com/opt-out-reason": "smoke probe: an unmeshed pod is the point of the NetworkPolicy check"
    }
  },
  "spec": {
    "securityContext": {"runAsNonRoot": true, "runAsUser": 65534, "seccompProfile": {"type": "RuntimeDefault"}},
    "containers": [{
      "name": "$1",
      "image": "$image",
      "command": $2,
      "securityContext": {"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true, "capabilities": {"drop": ["ALL"]}},
      "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"cpu": "100m", "memory": "64Mi"}}
    }]
  }
}
JSON
}

# Ingress: a pod that carries none of the allowed labels must not reach the database at all.
probe="smoke-netpol-$$"
if kubectl run "$probe" -n "$slug" --rm --attach --restart=Never --quiet --timeout=90s \
	--image="$image" \
	--overrides="$(probe_overrides "$probe" '["nc", "-w", "5", "-z", "postgres-cluster-rw", "5432"]')" \
	>/dev/null 2>&1; then
	ko "an unlabelled pod reached postgres-cluster-rw:5432 — the database NetworkPolicy is not holding"
else
	ok "postgres refuses a pod outside the allowed selectors"
fi

# Egress: the other half of the same default-deny, and the half nothing measured until now.
# `podSelector: {}` with both policy types is what the repository renders
# (defaults/environment/networkpolicies.yaml.gotmpl), but a controller that enforces only
# ingress passes every check above while leaving a compromised pod free to call out — which
# is what happened on this cluster long enough for T-0258 to be written against it. The
# rendered manifest cannot tell the two apart: tests/test_networkpolicies.py asserts the same
# YAML either way, so the difference only exists on a running cluster (OPS-38, SEC-GAP-05).
#
# The probe prints one line per destination it reached and one line to prove it ran at all.
# Without that last line a pod that never started looks exactly like a pod the policy stopped,
# and this check would go quietly green the day the image or the namespace changes.
#
# It settles first. The controller programs a NEW pod's egress chains a few seconds after that
# pod is running, so a probe that calls out the instant it starts measures the gap and not the
# policy: measured here, the same pod spec reaches 1.1.1.1:443 immediately and is refused
# twenty-five seconds later. The loop waits for the refusal and reports how long it took, so a
# window that grows is visible rather than silent; if it never comes the measurement below
# runs anyway and fails, which is the case this check exists for. The window itself is real
# and is T-0459 — it is not what this check is about.
egress="smoke-egress-$$"
# nslookup is the discriminating leg: CoreDNS is up, in this cluster, and reachable the moment
# egress stops being enforced. The 1.1.1.1 leg adds the internet, which a firewall outside
# Kubernetes may also be blocking, so it is a second opinion rather than the evidence.
egress_out=$(kubectl run "$egress" -n "$slug" --rm --attach --restart=Never --quiet --timeout=180s \
	--image="$image" \
	--overrides="$(probe_overrides "$egress" '["sh", "-c", "i=0; while [ $i -lt 18 ]; do nc -w 3 -z 1.1.1.1 443 >/dev/null 2>&1 || break; i=$((i+1)); sleep 4; done; echo SETTLED-AFTER=$((i*4))s; timeout 8 nslookup kubernetes.default >/dev/null 2>&1 && echo REACHED-DNS; nc -w 5 -z 1.1.1.1 443 >/dev/null 2>&1 && echo REACHED-NET; echo PROBE-RAN"]')" \
	2>/dev/null)
reached=$(printf '%s' "$egress_out" | sed -n 's/^REACHED-DNS\r*$/CoreDNS/p; s/^REACHED-NET\r*$/1.1.1.1:443/p' | tr '\n' ' ')
if ! printf '%s' "$egress_out" | grep -q PROBE-RAN; then
	ko "the egress probe never ran, so the egress half of the default-deny was not measured"
elif [ -n "$reached" ]; then
	ko "an unlabelled pod reached ${reached}— the egress half of the default-deny is not holding"
else
	ok "an unlabelled pod reaches neither CoreDNS nor the internet ($(printf '%s' "$egress_out" | sed -n 's/^SETTLED-AFTER=\([0-9a-z]*\)\r*$/settled after \1/p'))"
fi

echo "functions"
# jc-functions (SDK-22, SDK-23) takes the Portal alone, so the smoke reaches its Service over a
# port-forward and presents what the Portal presents: portal-api's client_credentials token,
# whose audience jc-functions is the realm's mapper. The one function sent reads a public
# Helsinki endpoint anonymously, so its answer is also the runtime's egress to the gateway.
if ! kubectl get deployment jc-functions -n "$slug" >/dev/null 2>&1; then
	skip "functions (jc-functions is not deployed in this instance)"
else
	fn_port=$((20000 + $$ % 10000))
	kubectl port-forward -n "$slug" svc/jc-functions "$fn_port:8080" >/dev/null 2>&1 &
	fn_forward=$!
	for _ in 1 2 3 4 5 6 7 8 9 10; do
		curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$fn_port/healthz" && break
		sleep 1
	done
	status 401 "jc-functions refuses an invocation without the Portal's token" -X POST \
		-H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$fn_port/invoke"
	fn_secret=$(kubectl get secret keycloak-client-portal-api -n "$slug" -o jsonpath='{.data.client-secret}' 2>/dev/null | base64 -d 2>/dev/null || true)
	fn_token=""
	if [ -n "$fn_secret" ]; then
		fn_token=$(curl -sS --max-time 20 -d grant_type=client_credentials -d client_id=portal-api \
			--data-urlencode "client_secret=$fn_secret" \
			"$idm/realms/$realm/protocol/openid-connect/token" 2>/dev/null |
			sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
	fi
	fn_slug=$(kubectl get configmap gitea-bootstrap-seed -n "$slug" -o jsonpath='{.data.projects__helsinki__spaces__helsinki__endpoints__helsinki-all\.yaml}' 2>/dev/null | sed -n 's/^ *slug: *//p' | head -1)
	if [ -z "$fn_token" ]; then
		ko "no client_credentials token for portal-api, so no function was invoked"
	elif [ -z "$fn_slug" ]; then
		skip "function invocation (no Helsinki seed on the gateway in this instance)"
	else
		# The same rule as the endpoint probes above: a read names a type, and the type comes
		# from the endpoint's access document rather than from this script's memory (GW33).
		fn_type=$(type_of "$fn_slug")
		fn_type=${fn_type:-Event}
		fn_body=$(printf '{"files":{"@app/functions/smoke.ts":"export default async (request, ctx) => { ctx.log(\\"smoke\\"); const r = await ctx.jc.get(\\"/api/endpoint/%s/ngsi-ld/v1/entities?type='"$fn_type"'&limit=1\\"); return { body: { gateway: r.status } }; };","@joinedcontext/sdk/server":"export const createClient = (config, transport) => ({ get: (path) => transport({ method: \\"GET\\", path }) });"},"entry":"@app/functions/smoke.ts","request":{"method":"POST","query":{},"body":null,"user":null},"config":{"slug":"%s","orgDomain":"smoke","space":"helsinki"}}' "$fn_slug" "$fn_slug")
		fn_answer=$(curl -sS --max-time 20 -X POST -H 'Content-Type: application/json' \
			-H "Authorization: Bearer $fn_token" -d "$fn_body" "http://127.0.0.1:$fn_port/invoke" 2>/dev/null)
		case "$fn_answer" in
			*'"body":{"gateway":200}'*) ok "jc-functions runs a function for the Portal's token and the function reads the gateway" ;;
			*) ko "jc-functions did not answer the smoke function with the gateway's 200: ${fn_answer:-no answer}" ;;
		esac
	fi
	kill "$fn_forward" 2>/dev/null
	# Ingress: the Service's address, so neither probe needs DNS. A probe carrying the Portal's
	# label connects (the policy is what decides, not a pod that cannot dial at all) and an
	# unlabelled one does not.
	fn_ip=$(kubectl get service jc-functions -n "$slug" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
	fn_probe="smoke-functions-$$"
	# The controller adds a new pod to the allowed sources a few seconds after it starts (T-0459),
	# so the labelled probe retries for half a minute before it counts as refused.
	fn_retry='["sh", "-c", "i=0; while [ $i -lt 10 ]; do nc -w 3 -z IP 8080 && exit 0; i=$((i+1)); sleep 3; done; exit 1"]'
	portal_probe=$(probe_overrides "$fn_probe-portal" "${fn_retry/IP/$fn_ip}" |
		sed 's/"metadata": {/"metadata": {\n    "labels": {"app.kubernetes.io\/name": "portal-portal"},/')
	if kubectl run "$fn_probe-portal" -n "$slug" --rm --attach --restart=Never --quiet --timeout=90s \
		--image="$image" --overrides="$portal_probe" >/dev/null 2>&1; then
		ok "a pod with the Portal's label reaches jc-functions:8080"
	else
		ko "a pod with the Portal's label cannot reach jc-functions:8080, so the refusal below proves nothing"
	fi
	if kubectl run "$fn_probe" -n "$slug" --rm --attach --restart=Never --quiet --timeout=90s \
		--image="$image" \
		--overrides="$(probe_overrides "$fn_probe" "[\"nc\", \"-w\", \"5\", \"-z\", \"$fn_ip\", \"8080\"]")" \
		>/dev/null 2>&1; then
		ko "an unlabelled pod reached jc-functions:8080 — the functions NetworkPolicy is not holding"
	else
		ok "jc-functions refuses a pod that is not the Portal"
	fi
fi

# Who the edge thinks the caller is (T-0929, EP-20, SP-22). APISIX sits behind the ingress
# controller as a ClusterIP, and its chart trusts only 127.0.0.1 for `X-Real-IP`, so until the
# nginx snippet was added every caller on the internet arrived as the ingress pod: one address in
# the access log, and one `limit-count` bucket the first caller emptied for everybody. The access
# log is where that shows, so that is what this reads.
echo "edge caller"
if ! kubectl get deployment apisix -n "$slug" >/dev/null 2>&1; then
	skip "edge caller (no APISIX in this instance)"
else
	# A fixed path, not a per-run one: the access log is read back through `kubectl logs`,
	# and `tail -1` of the matches is this run's.
	beacon="/smoke-caller"
	curl -s -o /dev/null --max-time 10 "$base$beacon" || true
	logged=$(kubectl logs deployment/apisix -n "$slug" -c apisix --tail=200 2>/dev/null |
		grep -F "$beacon" | tail -1 | awk '{print $1}')
	case "$logged" in
	"")
		skip "edge caller (the request did not reach the edge's access log)"
		;;
	10.42.* | 10.43.*)
		ko "the edge logged the caller as $logged, a pod address: every caller shares one rate-limit bucket"
		;;
	*)
		ok "the edge names the caller, not the hop in front of it ($logged)"
		;;
	esac
fi

# The artifact store's per-organization credentials (PF-32, T-0422, T-0925, T-0933). The Secret
# is the one object that proves the whole path: the reconciler reached the store's admin API with
# the root credential, the store accepted the policy and the user, and the reader was handed to
# the namespace that serves. It was missing for as long as the reconciler's egress named the
# store's service port and not its Linkerd inbound port, and nothing here noticed.
echo "artifact store"
if ! kubectl get statefulset artifact-store -n "$slug" >/dev/null 2>&1; then
	skip "artifact store (the component is not deployed in this instance)"
else
	readers=$(kubectl get secret -n "$slug" -l joinedcontext.com/artifact-store-role=reader \
		-o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}' 2>/dev/null || true)
	if [ -z "$readers" ]; then
		ko "no organization has a reader credential: the reconciler minted none or handed none over"
	else
		missing=""
		for reader in $readers; do
			for key in ACCESS_KEY_ID ACCESS_SECRET_KEY; do
				value=$(kubectl get secret "$reader" -n "$slug" -o "jsonpath={.data.$key}" 2>/dev/null || true)
				[ -n "$value" ] || missing="$missing $reader/$key"
			done
		done
		if [ -n "$missing" ]; then
			ko "a reader Secret is missing a key:$missing"
		else
			ok "every organization has its artifact-store reader credential ($readers)"
		fi
	fi
	# The writer publishes; a Secret carrying it would hand a serving pod the power to replace
	# an artifact, which is the one thing the two roles exist to keep apart.
	writers=$(kubectl get secret -n "$slug" -l joinedcontext.com/artifact-store-role=writer \
		-o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}' 2>/dev/null || true)
	if [ -n "$writers" ]; then
		ko "a writer credential was written into the cluster:$writers"
	else
		ok "no writer credential is written anywhere in the cluster"
	fi
fi

# A pipeline's credential (PL-15, CC-06, T-0927, T-0935). The Portal decrypts every `secretRef`
# of every Pipeline with the backend it was given and writes one `pipeline-secrets` Secret into
# the runner's namespace; the runner takes the whole Secret as environment, so a stream reads
# `${MQTT_PASSWORD}` and nothing else ever holds the value. Two properties are checked here and
# nowhere else: the environment reaches the process, and the plaintext is in no ConfigMap.
echo "pipeline credentials"
if ! kubectl get secret pipeline-secrets -n "$slug" >/dev/null 2>&1; then
	skip "pipeline credentials (no pipeline on this instance declares a secretRef)"
else
	variables=$(kubectl get secret pipeline-secrets -n "$slug" \
		-o go-template='{{range $name, $_ := .data}}{{$name}}{{"\n"}}{{end}}' 2>/dev/null || true)
	if [ -z "$variables" ]; then
		ko "pipeline-secrets is empty: every reference was refused, and the runner has nothing"
	else
		missing=""
		for variable in $variables; do
			# The value is never printed: the test is whether the process has it, not what it is.
			kubectl exec -n "$slug" deploy/pipeline-runner -c pipeline-runner-runner -- \
				sh -c "[ -n \"\$$variable\" ]" >/dev/null 2>&1 || missing="$missing $variable"
		done
		if [ -n "$missing" ]; then
			ko "the runner's environment is missing a resolved credential:$missing"
		else
			ok "the runner reads every resolved credential from its environment ($(echo $variables | tr '\n' ' '))"
		fi
		# The other half: what the Secret holds appears in no ConfigMap of the namespace. A
		# credential copied into a rendered config is a credential in `kubectl get -o yaml`.
		leaked=""
		for variable in $variables; do
			value=$(kubectl get secret pipeline-secrets -n "$slug" -o "jsonpath={.data.$variable}" 2>/dev/null | base64 -d 2>/dev/null || true)
			[ -n "$value" ] || continue
			if kubectl get configmap -n "$slug" -o yaml 2>/dev/null | grep -qF -- "$value"; then
				leaked="$leaked $variable"
			fi
		done
		if [ -n "$leaked" ]; then
			ko "a resolved credential is written in plaintext into a ConfigMap:$leaked"
		else
			ok "no resolved credential appears in any ConfigMap of $slug"
		fi
	fi
fi

printf '\n%s passed, %s failed, %s skipped\n' "$pass" "$fail" "$skipped"
[ "$fail" -eq 0 ]
