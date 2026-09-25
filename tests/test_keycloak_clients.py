"""T-0270: the portal-api client must list the callback the Portal actually uses;
T-0248: the development profile seeds the DEMO.md users, production seeds none.

The Portal derives its redirect URI as `{JC_PORTAL_PUBLIC_URL}/api/v1/auth/callback`
(portal src/config.rs). Keycloak matches redirect URIs exactly, so a client listing any
other path turns every browser login into "Invalid parameter: redirect_uri".
"""

import base64
import json
import re

import pytest


@pytest.fixture(scope="module")
def realm_clients(rendered):
    for doc in rendered("local"):
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            realm = json.loads(base64.b64decode(doc["data"]["local.json"]))
            return {c["clientId"]: c for c in realm["clients"]}
    pytest.fail("no keycloak-config-cli realm Secret in the local render")


def test_portal_api_redirect_uri_is_the_portal_callback(realm_clients):
    uris = realm_clients["portal-api"]["redirectUris"]
    assert uris, "portal-api lists no redirect URI at all"
    assert all(uri.endswith("/api/v1/auth/callback") for uri in uris), uris


def test_portal_api_redirect_uris_are_exact(realm_clients):
    # Security line of T-0270: exact matches only, no wildcard on a confidential client.
    assert not any("*" in uri for uri in realm_clients["portal-api"]["redirectUris"])


def test_the_portal_clients_live_on_the_portal_host(realm_clients):
    """ADR-N-019: the Portal moved to portal.{host}; its own clients follow, or the fallback
    code flow of the backend and the UI's origin would still name the apex."""
    for client_id in ("portal-ui", "portal-api"):
        client = realm_clients[client_id]
        assert client["rootUrl"] == "https://portal.joinedcontext.test", client_id
        assert all(uri.startswith("https://portal.joinedcontext.test/") for uri in client["redirectUris"]), client_id
        assert client["webOrigins"] == ["https://portal.joinedcontext.test"], client_id


# --- ADR-N-019, AP-27: the `edge` client of the APISIX openid-connect plugin ------------------


def test_the_edge_client_logs_people_in_on_both_hosts(realm_clients):
    """One confidential client for the Portal host and the apps surface of the apex: the
    authorization code flow with PKCE, no service account, no password grant, no browser
    origin (the flow runs inside APISIX)."""
    edge = realm_clients["edge"]
    assert set(edge["redirectUris"]) == {"https://portal.joinedcontext.test/*", "https://joinedcontext.test/apps/*"}
    assert edge["publicClient"] is False and edge["bearerOnly"] is False
    assert edge["standardFlowEnabled"] is True and edge["implicitFlowEnabled"] is False
    assert edge["directAccessGrantsEnabled"] is False and edge["serviceAccountsEnabled"] is False
    assert edge["webOrigins"] == []
    assert edge["attributes"]["pkce.code.challenge.method"] == "S256"
    # "+" = the redirect URIs, so the post-logout landing on the Portal host is accepted.
    assert edge["attributes"]["post.logout.redirect.uris"] == "+"
    assert edge["secret"] == "$(CLIENT_SECRET_EDGE)", "the secret is substituted from the generated Secret"
    # The gateway's own name as an audience: the session reaches an endpoint approved after
    # the login (Architecture/12 §4); the Portal's audience stays beside it.
    audiences = {
        m["config"].get("included.custom.audience") or m["config"].get("included.client.audience")
        for m in edge["protocolMappers"]
        if m["protocolMapper"] == "oidc-audience-mapper"
    }
    assert {"portal-api", "context-gateway"} <= audiences, audiences


def test_only_the_edge_client_is_signed_rs256(realm_clients):
    """lua-resty-openidc verifies RS/HS signatures only, so the edge client's tokens are RS256
    by per-client override; the realm default stays ES256 for everyone else (T-0252, AR-11)."""
    edge = realm_clients["edge"]["attributes"]
    assert edge["access.token.signed.response.alg"] == "RS256"
    assert edge["id.token.signed.response.alg"] == "RS256"
    for client_id, client in realm_clients.items():
        if client_id == "edge":
            continue
        attributes = client.get("attributes") or {}
        assert not any(key.endswith(".signed.response.alg") for key in attributes), client_id


@pytest.mark.parametrize("env", ["local", "production"])
def test_the_rs256_key_is_active_below_the_es256_key(rendered, env):
    """The realm signs ES256 by default and keeps an active RS256 key at a lower priority for
    the one client that asks for it (ADR-N-019); the HS512 key stays disabled."""
    realm = realm_of(rendered, env)
    assert realm["defaultSignatureAlgorithm"] == "ES256"
    keys = {k["name"]: k["config"] for k in realm["components"]["org.keycloak.keys.KeyProvider"]}
    assert keys["ecdsa-generated"]["active"] == ["true"] and keys["ecdsa-generated"]["enabled"] == ["true"]
    assert keys["rsa-generated"]["active"] == ["true"] and keys["rsa-generated"]["enabled"] == ["true"]
    assert keys["rsa-generated"]["algorithm"] == ["RS256"]
    assert int(keys["rsa-generated"]["keySize"][0]) >= 3072, "BSI TR-02102-1: RSA moduli of 3000 bits or more"
    assert int(keys["rsa-generated"]["priority"][0]) < int(keys["ecdsa-generated"]["priority"][0])
    assert keys["hmac-generated"]["active"] == ["false"] and keys["hmac-generated"]["enabled"] == ["false"]


def realm_of(rendered, env):
    for doc in rendered(env):
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            return json.loads(base64.b64decode(next(iter(doc["data"].values()))))
    pytest.fail(f"no keycloak-config-cli realm Secret in the {env} render")


def human_users(realm):
    """The realm users that are people; a service account is a user Keycloak owns."""
    return {
        u["username"]: u
        for u in realm["users"]
        if "serviceAccountClientId" not in u
    }


def test_development_profile_seeds_the_demo_users(rendered):
    realm = realm_of(rendered, "dev")
    users = human_users(realm)
    # A Yellow change needs an approver who is not its author (CC-34), so the demo has two —
    # and a fourth person who proposes and decides nothing, so the plain self-approval refusal
    # can be played by somebody it applies to (T-2231).
    assert set(users) == {
        "demo.steward@hel.fi",
        "demo.viewer@hel.fi",
        "demo.approver@hel.fi",
        "demo.editor@hel.fi",
        "demo.janitor@hel.fi",
    }
    assert users["demo.steward@hel.fi"]["realmRoles"] == ["portal-approver"]
    assert users["demo.approver@hel.fi"]["realmRoles"] == ["portal-approver"]
    assert users["demo.viewer@hel.fi"]["realmRoles"] == [], "demo.viewer is read only"
    assert users["demo.editor@hel.fi"]["realmRoles"] == [], "demo.editor approves nothing"
    # The residue sweep's approver (T-2627): its RoleBinding is what it may do, and no project
    # group admits it to the gateway, so it reads no context data.
    assert users["demo.janitor@hel.fi"]["realmRoles"] == []
    assert not {"/helsinki", "/banskabystrica", "helsinki", "banskabystrica"} & set(
        users["demo.janitor@hel.fi"].get("groups", [])
    )
    assert "portal-approver" in {r["name"] for r in realm["roles"]["realm"]}
    assert realm["registrationEmailAsUsername"] is True
    for user in users.values():
        assert user["email"].endswith("@hel.fi")
        # keycloak-config-cli refuses a user whose username is not the email while the realm
        # uses email as username, and the import aborts before it sets any password (T-0366).
        assert user["username"] == user["email"]
        assert user["requiredActions"] == [], "a required action would block the demo login"
        (credential,) = user["credentials"]
        # Security line of T-0248: the password is a per-cluster Secret substituted at import
        # time, never a literal in the rendered realm.
        assert credential["value"].startswith("$(USER_PASSWORD_") and credential["temporary"] is False


def test_demo_passwords_are_generated_per_cluster(rendered):
    secrets = {d["metadata"]["name"]: d for d in rendered("dev")
               if d.get("kind") == "Secret" and d["metadata"]["name"].startswith("keycloak-user-")}
    assert set(secrets) == {
        "keycloak-user-demo-steward",
        "keycloak-user-demo-viewer",
        "keycloak-user-demo-approver",
        "keycloak-user-demo-editor",
        "keycloak-user-demo-janitor",
    }
    for secret in secrets.values():
        assert secret["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
        assert list(secret["data"]) == ["password"]


def test_production_seeds_no_human_users(rendered):
    assert human_users(realm_of(rendered, "production")) == {}
    assert not [d for d in rendered("production")
                if d.get("kind") == "Secret" and d["metadata"]["name"].startswith("keycloak-user-")]


# T-0411, AP-27: the reconciler creates the confidential client `app-{name}` of every app on
# demand. It authenticates as the service account of the Portal's own client, so that account
# is the one identity in the realm with an Admin API role, and the role is the narrowest one
# Keycloak has for the job.
@pytest.mark.parametrize("env", ["local", "production", "dev"])
def test_the_portal_service_account_may_manage_clients(rendered, env):
    realm = realm_of(rendered, env)
    accounts = {u["serviceAccountClientId"]: u
                for u in realm["users"] if "serviceAccountClientId" in u}
    assert "portal-api" in accounts, "the reconciler could not create an app's client"
    assert accounts["portal-api"]["clientRoles"] == {"realm-management": ["manage-clients"]}
    assert accounts["portal-api"]["username"] == "service-account-portal-api", (
        "keycloak names a service account after its client; another name creates a second user"
    )
    client = {c["clientId"]: c for c in realm["clients"]}["portal-api"]
    assert client["serviceAccountsEnabled"] is True, (
        "the role is mapped onto an account the client does not have"
    )


@pytest.mark.parametrize("env", ["local", "production", "dev"])
def test_no_other_client_holds_an_admin_api_role(rendered, env):
    """Security line of T-0411 and T-0866: only the Portal reaches the Admin API, and each of
    its two clients holds the narrowest role for the one job it does.

    `portal-api` creates an app's client; `portal-reconciler` writes the memberships of the
    groups the repository declares (PF-63) and nothing else — the login client must not gain
    that right. Every other workload is a service account with its own audience-bound token and
    no reason to reach the Admin API; another holder would make the blast radius of any one
    leaked client secret the whole realm."""
    realm = realm_of(rendered, env)
    holders = {
        u["serviceAccountClientId"]: u["clientRoles"]["realm-management"]
        for u in realm["users"]
        if u.get("clientRoles", {}).get("realm-management")
    }
    assert set(holders) == {"portal-api", "portal-reconciler"}, holders
    assert sorted(holders["portal-api"]) == ["manage-clients"], holders
    assert sorted(holders["portal-reconciler"]) == ["manage-users", "query-groups"], holders


@pytest.mark.parametrize("env", ["local", "production", "dev"])
def test_the_group_reconciler_client_has_no_login_flow(rendered, env):
    """PF-63: the credential that writes group memberships logs nobody in — no code flow, no
    password grant, a service account and nothing else."""
    realm = realm_of(rendered, env)
    client = {c["clientId"]: c for c in realm["clients"]}["portal-reconciler"]
    assert client["serviceAccountsEnabled"] is True
    assert client["standardFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["publicClient"] is False


LABEL = re.compile(r"^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$")


@pytest.mark.parametrize("env", ["local", "production", "dev"])
def test_every_rendered_label_value_is_a_valid_label(rendered, env):
    """A digest in `image.tag` reaches `app.kubernetes.io/version`, and the API server
    refuses the upgrade: `@` and `:` are not label characters. helm template and
    kubeconform both accept it, so only this check stands between a digest pin and a
    dev-apply that cannot patch the StatefulSet (T-0368)."""
    for doc in rendered(env):
        for where, labels in (
            (doc.get("metadata", {}).get("name", "?"), doc.get("metadata", {}).get("labels") or {}),
        ):
            for key, value in labels.items():
                assert len(value) <= 63, f"{doc.get('kind')}/{where}: label {key} is longer than 63 characters"
                assert LABEL.match(value), f"{doc.get('kind')}/{where}: label {key}={value!r} is not a valid label value"


def test_mcp_mobile_is_a_public_pkce_client(realm_clients):
    """T-0336 / PF-45: a phone reaching an endpoint's MCP route logs in with this client.

    It lives on a device somebody can lose, so it carries no secret and PKCE S256 is
    mandatory rather than optional; the audience (RFC 8707 `resource`) is what binds a
    token to one endpoint, which is why there is one client and not one per endpoint.
    """
    client = realm_clients["mcp-mobile"]
    assert client["publicClient"] is True
    assert "secret" not in client, "a public client must not carry a secret"
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False


def test_mcp_mobile_lists_only_the_known_mobile_callbacks(realm_clients):
    # Security line of T-0336: dynamic client registration stays off, so this list is the
    # whole set of places an authorization code may be delivered. A wildcard here would let
    # anybody who can host a page collect codes for a client that needs no secret.
    assert set(realm_clients["mcp-mobile"]["redirectUris"]) == {
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://platform.openai.com/chatkit-oauth-callback",
    }


# --- PF-61, PF-79: who the caller is, on every client ----------------------------------------


def test_every_client_carries_the_groups_claim(realm_clients):
    """A `RoleBinding` names a group (`viewers` binds `platform-readers`), so a token without
    the claim makes every signed-in person a stranger: the Portal answers 404 on every list
    (PF-50, PF-61) and the forge lands nobody in its readers team (PF-79). Keycloak adds no
    such claim by default, and it broke silently on the clients nobody looked at."""
    for client_id, client in realm_clients.items():
        mappers = [m for m in client.get("protocolMappers", [])
                   if m["protocolMapper"] == "oidc-group-membership-mapper"]
        assert len(mappers) == 1, f"{client_id} carries {len(mappers)} group mappers"
        config = mappers[0]["config"]
        assert config["claim.name"] == "groups", client_id
        assert config["full.path"] == "false", f"{client_id}: the forge's team map names the group, not its path"
        assert config["access.token.claim"] == "true" and config["id.token.claim"] == "true", client_id


def test_a_clients_own_mappers_survive_the_shared_one(realm_clients):
    """The shared mapper is added to a client's list, never over it: `mergeOverwrite` replaces
    a list wholesale, so writing the default the obvious way drops the audience mappers a
    token is refused without (T-0491, SDK-23)."""
    names = {m["name"] for m in realm_clients["portal-api"]["protocolMappers"]}
    assert {"groups", "realm-roles-in-id-token", "jc-functions-audience"} <= names


# --- T-1420: the forge's client alone skips PKCE until go-gitea/gitea#38202 ships ---------------


def test_the_gitea_client_drops_pkce_and_stays_confidential(realm_clients):
    gitea = realm_clients["gitea"]
    assert gitea["attributes"].get("pkce.code.challenge.method", "") == "", gitea["attributes"]
    assert gitea["attributes"]["post.logout.redirect.uris"] == "+"
    assert gitea["publicClient"] is False and gitea["secret"] == "$(CLIENT_SECRET_GITEA)"
    assert gitea["directAccessGrantsEnabled"] is False and gitea["implicitFlowEnabled"] is False
    uris = gitea["redirectUris"]
    assert all(u.endswith("/git/user/oauth2/keycloak/callback") and "*" not in u for u in uris), uris


def test_every_other_browser_client_still_requires_pkce(realm_clients):
    for client_id, client in realm_clients.items():
        if client_id == "gitea" or not client.get("standardFlowEnabled"):
            continue
        assert client["attributes"]["pkce.code.challenge.method"] == "S256", client_id


# --- T-2420, T-2271 (AG-52, PF-46): the agent proxy's two audiences ----------------------------


@pytest.fixture(scope="module")
def dev_realm_clients(rendered):
    """The realm of an environment that runs the agent runner; `local` leaves that component out."""
    for doc in rendered("dev"):
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            realm = json.loads(base64.b64decode(doc["data"]["dev.json"]))
            return {c["clientId"]: c for c in realm["clients"]}
    pytest.fail("no keycloak-config-cli realm Secret in the dev render")


def test_the_agent_proxy_carries_both_audiences_it_is_refused_without(dev_realm_clients):
    """One client, two doors, and a token is refused at either without its mapper.

    `context-gateway` is how a run reads samples through whichever endpoint it names (T-0666).
    `portal-internal` is how the proxy asks the Portal's internal listener what a run is
    (`authenticate_agent_proxy`, portal `src/auth/internal.rs`): without it the lookup fails,
    `RunResolver::fetch` reports no active run, and the proxy answers every model call of every
    conversation `401 invalid run credentials` — the wording is deliberately the same for four
    different failures (T-2285), so a dropped mapper looks exactly like a forged ticket. The
    live realm is checked by `scripts/smoke.sh`; this is the manifest it is written from.
    """
    proxy = dev_realm_clients["helsinki-agent-proxy"]
    audiences = {
        mapper["config"].get("included.custom.audience")
        for mapper in proxy["protocolMappers"]
        if mapper["protocolMapper"] == "oidc-audience-mapper"
    }
    assert {"context-gateway", "portal-internal"} <= audiences, sorted(a for a in audiences if a)
    # And it stays a workload: client credentials only, no browser flow to phish a token out of.
    assert proxy["serviceAccountsEnabled"] is True
    assert proxy["standardFlowEnabled"] is False and proxy["implicitFlowEnabled"] is False
    assert proxy["directAccessGrantsEnabled"] is False and proxy["publicClient"] is False
