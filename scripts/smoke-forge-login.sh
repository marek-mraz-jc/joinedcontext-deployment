#!/usr/bin/env bash
# Sign in to the forge through Keycloak the way a browser does, then read the configuration
# repository and download every application repository (T-1422, T-2601, PF-51, PF-79, AP-78). A login only a person could see broken is the defect
# this catches: the forge's Keycloak button failed on every login for weeks behind a green smoke.
#   scripts/smoke-forge-login.sh <base-url>
# Passwords come from the Secrets keycloak-user-<name>, are sent on stdin and never printed.
set -uo pipefail

base="${1:?usage: smoke-forge-login.sh <base-url>}"
slug="${JC_INSTANCE:-${JC_REALM:-dev}}"
org="${JC_SMOKE_ORG:-$(kubectl get deploy context-gateway -n "$slug" \
	-o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="JC_GATEWAY_ORG_DOMAIN")].value}' 2>/dev/null || true)}"
org="${org:-hel.fi}"
forge_org="${JC_FORGE_ORG:-joinedcontext}"
folder="$base/git/$forge_org/configuration/src/branch/main/projects/${JC_SMOKE_PROJECT:-helsinki}"
signed=""

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0
ok() { printf '  ok    %s\n' "$1"; }
ko() { printf '  FAIL  %s\n' "$1"; fail=1; }

# The first message Keycloak or the forge shows a person, or nothing.
error_of() {
	tr '\n' ' ' < "$1" \
		| grep -o -E '(input-error|kc-error-message|kc-feedback-text|flash-error)[^>]*>([[:space:]]*<[^>]*>)*[^<]+' \
		| head -1 | sed -e 's/.*>//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# The project folder lists its manifest; a login page or a 404 does not.
lists_files() { grep -q 'project\.yaml' "$1"; }

code=$(curl -sS -o "$work/anonymous" -w '%{http_code}' --max-time 20 "$folder" 2>/dev/null)
if [ "$code" = 200 ] && lists_files "$work/anonymous"; then
	ko "an anonymous visitor reads the configuration repository"
else
	ok "an anonymous visitor does not read the configuration repository ($code)"
fi

login() {
	local user="$1" password jar action page after landed code
	password=$(kubectl get secret "keycloak-user-${user//./-}" -n "$slug" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)
	if [ -z "$password" ]; then
		ko "$user: no password in Secret keycloak-user-${user//./-} (development profile not applied?)"
		return
	fi
	jar="$work/$user.jar" page="$work/$user.form" after="$work/$user.after"

	curl -sS -L --max-time 30 -c "$jar" -b "$jar" -o "$page" "$base/git/user/oauth2/keycloak" 2>/dev/null
	action=$(tr '\n' ' ' < "$page" | sed -n 's/.*id="kc-form-login"[^>]*action="\([^"]*\)".*/\1/p' | sed 's/&amp;/\&/g')
	if [ -z "$action" ]; then
		ko "$user: the forge's Keycloak button reaches no login form: $(error_of "$page")"
		return
	fi

	landed=$(printf '%s' "$password" | curl -sS -L --max-time 30 -c "$jar" -b "$jar" -o "$after" \
		-w '%{url_effective}' --data-urlencode "username=$user@$org" --data-urlencode "password@-" "$action" 2>/dev/null)
	case "$landed" in
		"$base/git/"*) ;;
		*) ko "$user: the login did not come back to the forge: $(error_of "$after")"; return ;;
	esac
	if [ -n "$(error_of "$after")" ] || grep -q 'id="kc-form-login"' "$after"; then
		ko "$user: the forge refused the login: $(error_of "$after")"
		return
	fi

	code=$(curl -sS -b "$jar" -o "$work/$user.folder" -w '%{http_code}' --max-time 20 "$folder" 2>/dev/null)
	if [ "$code" = 200 ] && lists_files "$work/$user.folder"; then
		ok "$user signs in to the forge through Keycloak and reads the configuration repository"
	elif [ "$code" = 404 ]; then
		ko "$user: signed in, but the configuration repository answers 404: the groups claim maps to no forge team (gitea.forge.groupTeams)"
		return
	else
		ko "$user: signed in, but the configuration repository answers $code"
		return
	fi
	# The team the `groups` claim maps onto (PF-79): the forge shows an organization's team only
	# to its members, so a 404 here is a person the map landed nowhere.
	code=$(curl -sS -b "$jar" -o /dev/null -w '%{http_code}' --max-time 20 "$base/git/org/$forge_org/teams/readers" 2>/dev/null)
	if [ "$code" = 200 ]; then
		ok "$user is in the forge team readers"
	else
		ko "$user is not in the forge team readers ($code)"
	fi
	signed="$signed $user"
	# Every write goes through a Change (CC-41). Gitea links "Add file" for everyone; to a
	# person without write it is the "fork to propose changes" notice, to a writer the commit
	# form, so the form is what gives write access away.
	curl -sS -b "$jar" -o "$work/$user.editor" --max-time 20 "${folder/\/src\/branch\//\/_new\/}" 2>/dev/null
	if grep -q 'name="commit_choice"' "$work/$user.editor"; then
		ko "$user may commit to the configuration repository in the forge"
	else
		ok "$user reads the configuration repository without write access"
	fi
	# Nor a copy of it (T-1461): the forge refuses a reader's fork, which would outlive their
	# group membership. The fork page carries the form's token and the person's own id.
	local repo="${folder%%/src/branch/*}" fork_page="$work/$user.fork" token uid
	curl -sS -b "$jar" -c "$jar" -o "$fork_page" --max-time 20 "$repo/fork" 2>/dev/null
	token=$(sed -n 's/.*name="_csrf" value="\([^"]*\)".*/\1/p' "$fork_page" | head -1)
	uid=$(sed -n 's/.*name="uid"[^>]*value="\([0-9]*\)".*/\1/p' "$fork_page" | head -1)
	curl -sS -b "$jar" -c "$jar" -o /dev/null --max-time 30 -X POST "$repo/fork" \
		--data-urlencode "_csrf=$token" --data-urlencode "uid=$uid" \
		--data-urlencode "repo_name=configuration" 2>/dev/null
	code=$(curl -sS -b "$jar" -o /dev/null -w '%{http_code}' --max-time 20 "$base/git/$user/configuration" 2>/dev/null)
	if [ "$code" = 200 ]; then
		ko "$user forked the configuration repository into $base/git/$user/configuration"
	else
		ok "$user cannot fork the configuration repository ($code)"
	fi
}

for user in ${JC_SMOKE_FORGE_USERS:-demo.steward demo.viewer}; do
	login "$user"
done

# The application repositories (T-2601, PF-79, AP-78): `readers` holds every repository of the
# organization, so each one the organization page lists opens and downloads with its source for a
# person who only reads, and for nobody signed out. The list is every person's together: a
# repository one of them misses is the defect, not a reason to skip it.
apps=$(for user in $signed; do
	curl -sS -b "$work/$user.jar" --max-time 20 "$base/git/$forge_org" 2>/dev/null \
		| grep -o "href=\"/git/$forge_org/[A-Za-z0-9._-]*\"" | sed -e 's/.*\///' -e 's/"$//'
done | grep -vx configuration | sort -u)
if [ -n "$signed" ] && [ -z "$apps" ]; then
	ok "the forge holds no application repository yet"
fi
for app in $apps; do
	repo="$base/git/$forge_org/$app"
	code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$repo" 2>/dev/null)
	if [ "$code" = 404 ]; then
		ok "an anonymous visitor does not read $app (404)"
	else
		ko "an anonymous visitor reads $app ($code)"
	fi
	for user in $signed; do
		code=$(curl -sS -b "$work/$user.jar" -o "$work/$user.app" -w '%{http_code}' --max-time 20 "$repo" 2>/dev/null)
		if [ "$code" != 200 ]; then
			ko "$user: application repository $app answers $code"
			continue
		fi
		if ! grep -q "/git/$forge_org/$app/src/branch/" "$work/$user.app"; then
			ko "$user: application repository $app lists no files (empty repository?)"
			continue
		fi
		code=$(curl -sS -b "$work/$user.jar" -o "$work/$user.tgz" -w '%{http_code}' --max-time 60 "$repo/archive/main.tar.gz" 2>/dev/null)
		files=$( { tar tzf "$work/$user.tgz" 2>/dev/null || true; } | grep -vc '/$' || true)
		if [ "$code" = 200 ] && [ "${files:-0}" -gt 0 ]; then
			ok "$user reads and downloads application repository $app ($files files)"
		else
			ko "$user: downloading $app answers $code with ${files:-0} files"
		fi
	done
done
exit "$fail"
