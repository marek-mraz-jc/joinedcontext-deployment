"""Tests asserting APISIX standalone route table and plugin configurations render correctly."""

import base64
import json
import re
import shutil

import pytest
import yaml

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")

# docs/Deployment/10-edge-routing-apisix.md section 2. The host constraint is part of
# the contract: an unbound `/*` route outranks the identity route on idm.{host}. The Portal
# lives on portal.{host} behind the edge login and the apex keeps the shared surfaces and
# redirects the rest (ADR-N-019).
LOCAL_DOMAIN = "joinedcontext.test"
PORTAL_HOST = f"portal.{LOCAL_DOMAIN}"
EXPECTED_ROUTES = {
    "portal-ui": {"uri": "/*", "priority": 1, "upstream_id": "portal-ui", "host": PORTAL_HOST},
    "portal-api": {"uri": "/api/v1/*", "priority": 10, "upstream_id": "portal-api", "host": PORTAL_HOST},
    "portal-metrics": {"uri": "/metrics", "priority": 5, "upstream_id": "portal-metrics", "host": PORTAL_HOST},
    "apps-surface": {"uri": "/apps/*", "priority": 25, "upstream_id": "apps-surface", "host": LOCAL_DOMAIN},
    "portal-redirect": {"uri": "/*", "priority": 1, "upstream_id": "portal-redirect", "host": LOCAL_DOMAIN},
    "context-space": {"uri": "/cs/*", "priority": 15, "upstream_id": "context-space", "host": LOCAL_DOMAIN},
    "context-endpoint": {"uri": "/api/endpoint/*", "priority": 20, "upstream_id": "context-endpoint", "host": LOCAL_DOMAIN},
    # AP-108: the forge's container registry at the apex's root, where a node pulls App images.
    "gitea-registry": {"uri": "/v2/*", "priority": 10, "upstream_id": "gitea-registry", "host": LOCAL_DOMAIN},
    # containerd's OAuth POST to the token realm, which Gitea answers 404 so it falls back to GET.
    "gitea-registry-token": {
        "uri": "/v2/token", "priority": 11, "upstream_id": "gitea-registry-token", "host": LOCAL_DOMAIN,
    },
    "context-endpoint-portal": {
        "uri": "/api/endpoint/*", "priority": 20, "upstream_id": "context-endpoint-portal", "host": PORTAL_HOST,
    },
    # T-2670: a static app's data calls, under its own path where the apps session cookie reaches.
    "context-endpoint-apps": {
        "uri": "/apps/*", "priority": 35, "upstream_id": "context-endpoint-apps", "host": LOCAL_DOMAIN,
    },
}


def hosts_of(route):
    """A route binds one `host` or a `hosts` list; either way, the hosts it answers on."""
    return route.get("hosts") or [route.get("host")]
AUTHENTICATED_ROUTES = ("portal-api", "context-space", "context-endpoint")
# The routes the edge login sits on, and what each one does with a visitor who has no session
# (ADR-N-019 §3.3, AP-26, AP-28).
EDGE_LOGIN_ROUTES = {
    "portal-ui": {"unauth_action": "auth", "cookie_path": "/", "callback": f"https://{PORTAL_HOST}/callback"},
    "portal-api": {"unauth_action": "pass", "cookie_path": "/", "callback": f"https://{PORTAL_HOST}/callback"},
    "apps-surface": {
        "unauth_action": "auth", "cookie_path": "/apps/", "callback": f"https://{LOCAL_DOMAIN}/apps/callback",
    },
    # The endpoint surface on the Portal host: the session becomes the bearer the gateway
    # verifies, and a visitor without one is passed through as anonymous, never redirected. The
    # gateway reads the bearer only, so the userinfo header is not minted for it.
    "context-endpoint-portal": {
        "unauth_action": "pass", "cookie_path": "/", "callback": f"https://{PORTAL_HOST}/callback", "userinfo": False,
    },
    # And the space surface on the same host, for the same reason: the Portal UI reads a space
    # from its own origin (`sdk/src/grid/source.ts`), so the session has to become the bearer
    # there too. Anonymous is passed through, never redirected (T-2454).
    "context-space-portal": {
        "unauth_action": "pass", "cookie_path": "/", "callback": f"https://{PORTAL_HOST}/callback", "userinfo": False,
    },
    # A static app's data calls read the session apps-surface made, on its cookie path, and
    # pass an anonymous visitor of a public app through (T-2670).
    "context-endpoint-apps": {
        "unauth_action": "pass", "cookie_path": "/apps/", "callback": f"https://{LOCAL_DOMAIN}/apps/callback",
        "userinfo": False,
    },
}


@pytest.fixture(scope="module")
def apisix_config(rendered):
    docs = rendered("local")
    cm = next(
        (d for d in docs if d.get("kind") == "ConfigMap" and d.get("metadata", {}).get("name") == "apisix-standalone-config"),
        None,
    )
    assert cm is not None, "apisix-standalone-config ConfigMap not found in rendered output"
    raw = cm["data"]["apisix.yaml"]
    return raw, yaml.safe_load(raw)


@requires_helmfile
def test_expected_routes_exist_with_properties(apisix_config):
    _, parsed = apisix_config
    routes_by_id = {r["id"]: r for r in parsed.get("routes", [])}
    for route_id, expected in EXPECTED_ROUTES.items():
        assert route_id in routes_by_id, f"Route {route_id} missing from apisix.yaml"
        route = routes_by_id[route_id]
        assert route.get("uri") == expected["uri"]
        assert route.get("priority") == expected["priority"]
        assert route.get("upstream_id") == expected["upstream_id"]
        assert hosts_of(route) == hosts_of(expected)


@requires_helmfile
def test_routes_have_plugin_config_with_request_id(apisix_config):
    _, parsed = apisix_config
    routes_by_id = {r["id"]: r for r in parsed.get("routes", [])}
    plugin_configs = {pc["id"]: pc.get("plugins", {}) for pc in parsed.get("plugin_configs", [])}
    for route_id in EXPECTED_ROUTES:
        route = routes_by_id[route_id]
        plugin_config_id = route.get("plugin_config_id")
        assert plugin_config_id is not None, f"Route {route_id} missing plugin_config_id"
        assert plugin_config_id in plugin_configs, f"Plugin config {plugin_config_id} not found"
        plugins = plugin_configs[plugin_config_id]
        assert plugins.get("request-id", {}).get("include_in_response") is True


def realm_of(rendered):
    for doc in rendered("local"):
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            return json.loads(base64.b64decode(next(iter(doc["data"].values()))))
    pytest.fail("no keycloak-config-cli realm Secret in the local render")


@requires_helmfile
def test_the_edge_login_sits_on_the_portal_and_apps_routes_only(apisix_config):
    """ADR-N-019: the openid-connect plugin in session mode is the one login front, on the
    Portal routes and the apps surface, with the confidential `edge` client; no other route
    carries it (the context surfaces and the forge stay bearer-only or anonymous)."""
    _, parsed = apisix_config
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    carrying = {config_id for config_id, p in plugins.items() if "openid-connect" in p}
    assert carrying == set(EDGE_LOGIN_ROUTES), carrying
    for route in parsed["routes"]:
        assert "openid-connect" not in route.get("plugins", {}), route["id"]
    for config_id, expected in EDGE_LOGIN_ROUTES.items():
        oidc = plugins[config_id]["openid-connect"]
        assert oidc["client_id"] == "edge", config_id
        assert oidc["client_secret"] == "${{EDGE_CLIENT_SECRET}}", "the secret is an env var from a Secret (AP-27)"
        assert oidc["discovery"] == (
            f"https://idm.{LOCAL_DOMAIN}/realms/local/.well-known/openid-configuration"
        ), config_id
        assert oidc["bearer_only"] is False, "session mode"
        assert oidc["unauth_action"] == expected["unauth_action"], config_id
        assert oidc["redirect_uri"] == expected["callback"], "the callback is under the route it belongs to"
        assert oidc["use_pkce"] is True, "the realm demands S256 from every browser client"
        assert oidc["ssl_verify"] is True, config_id
        assert oidc["set_userinfo_header"] is expected.get("userinfo", True), config_id
        assert oidc["set_access_token_header"] is True, config_id
        assert oidc["set_id_token_header"] is False and oidc["set_refresh_token_header"] is False, config_id
        assert oidc["session"]["secret"] == "${{OIDC_SESSION_SECRET}}", config_id
        assert oidc["session"]["cookie_path"] == expected["cookie_path"], config_id


@requires_helmfile
def test_a_presented_bearer_is_never_verified_at_the_edge(apisix_config):
    """T-0252 still holds: the realm signs ES256 and lua-resty-openidc verifies RS/HS only. With
    `use_jwks`, a `public_key` or an `introspection_endpoint` the plugin would verify a bearer
    it finds and answer 401 before `unauth_action` is consulted, and every CLI call would die at
    the edge. The upstream verifies bearer tokens (docs Deployment/10 §4, OPS-33)."""
    _, parsed = apisix_config
    for pc in parsed["plugin_configs"]:
        oidc = pc.get("plugins", {}).get("openid-connect")
        if not oidc:
            continue
        assert oidc.get("use_jwks", False) is False, pc["id"]
        assert "public_key" not in oidc and "introspection_endpoint" not in oidc, pc["id"]


@requires_helmfile
def test_the_session_cookie_is_scoped_and_bounded_by_the_realm(apisix_config, rendered):
    """AP-29: `Secure`, `HttpOnly`, `SameSite=Lax`, host-only, a path per surface, a name per
    surface so a browser never presents one surface's session to another, and a lifetime that
    never outlives the realm's SSO idle time or max lifespan. The keys are the flat
    lua-resty-session 4 ones APISIX 3.17 validates: a nested `cookie.path` is accepted and
    ignored, and the cookie would land on `/`."""
    _, parsed = apisix_config
    realm = realm_of(rendered)
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    names = {}
    for config_id in EDGE_LOGIN_ROUTES:
        session = plugins[config_id]["openid-connect"]["session"]
        assert "cookie" not in session, f"{config_id}: nested lua-resty-session 3 keys are ignored by APISIX 3.17"
        assert session["cookie_secure"] is True and session["cookie_http_only"] is True, config_id
        assert session["cookie_same_site"] == "Lax", config_id
        assert "cookie_domain" not in session, f"{config_id}: the cookie must not leak across hosts"
        assert session["idling_timeout"] <= realm["ssoSessionIdleTimeout"], config_id
        assert session["rolling_timeout"] <= realm["ssoSessionIdleTimeout"], config_id
        assert session["absolute_timeout"] <= realm["ssoSessionMaxLifespan"], config_id
        names[config_id] = session["cookie_name"]
    # The two Portal routes share one session; the apps surface has its own.
    assert names["portal-ui"] == names["portal-api"]
    assert names["apps-surface"] != names["portal-ui"]


@requires_helmfile
def test_the_apex_redirects_to_the_portal_below_every_other_apex_route(apisix_config):
    """ADR-N-019 §3.1: the apex answers `/` with a redirect to the Portal host, keeping the path
    so links that predate the move still open the same page. It is the lowest-priority apex
    route, so the shared surfaces (/apps, /git, /cs, /api/endpoint) are never shadowed."""
    _, parsed = apisix_config
    routes = {r["id"]: r for r in parsed["routes"]}
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    redirect = plugins["portal-redirect"]["redirect"]
    assert redirect == {"uri": f"https://{PORTAL_HOST}$uri", "append_query_string": True, "ret_code": 302}
    assert "openid-connect" not in plugins["portal-redirect"]
    apex = {r_id: r for r_id, r in routes.items() if LOCAL_DOMAIN in hosts_of(r)}
    assert "portal-redirect" in apex
    for r_id, route in apex.items():
        if r_id != "portal-redirect":
            assert route["priority"] > routes["portal-redirect"]["priority"], r_id
    # Nothing on the apex proxies the Portal UI any more; the apps surface is the one apex
    # route with the Portal as upstream, and it is behind the login.
    portal_upstreams = {
        u["id"] for u in parsed["upstreams"] if any(n.startswith("portal.") for n in u["nodes"])
    }
    assert {r_id for r_id in apex if r_id in portal_upstreams} == {"apps-surface", "portal-redirect"}


@requires_helmfile
def test_the_endpoint_surface_answers_on_the_portal_host_too(apisix_config):
    """The Portal UI builds endpoint links and its access fetches from its own origin, so
    `portal.{host}/api/endpoint/*` must reach the gateway instead of falling through to
    portal-ui's `/*`, which answers with the edge login and then the Portal's 404 (EP-01,
    EP-27). A second route serves the Portal host, same upstream and priority, with the edge
    session turned into the bearer (ADR-N-019); the apex route stays anonymous-or-bearer."""
    _, parsed = apisix_config
    routes = {r["id"]: r for r in parsed["routes"]}
    apex, portal = routes["context-endpoint"], routes["context-endpoint-portal"]
    assert hosts_of(apex) == [LOCAL_DOMAIN] and hosts_of(portal) == [PORTAL_HOST]
    for endpoint in (apex, portal):
        assert endpoint["uri"] == "/api/endpoint/*"
        assert endpoint["priority"] > routes["portal-ui"]["priority"]
        upstream = next(u for u in parsed["upstreams"] if u["id"] == endpoint["upstream_id"])
        assert all(node.startswith("context-gateway.") for node in upstream["nodes"])
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    assert "openid-connect" not in plugins[apex["plugin_config_id"]]
    assert plugins[portal["plugin_config_id"]]["openid-connect"]["unauth_action"] == "pass"


@requires_helmfile
def test_a_static_apps_data_calls_carry_the_apps_session_to_the_gateway(apisix_config):
    """T-2670, AP-29, GW10: the apps session cookie lives on /apps/, so a static app calls its
    endpoint under /apps/{name}/api/endpoint/…; this route reads that same session as the bearer,
    strips the prefix to the gateway's own path, outranks apps-surface, and refuses the egress
    path as the other endpoint routes do."""
    _, parsed = apisix_config
    routes = {r["id"]: r for r in parsed["routes"]}
    apps = routes["context-endpoint-apps"]
    assert apps["priority"] > routes["apps-surface"]["priority"]
    # radixtree_host_uri reads `:name` literally (it matched nothing on dev), so the route is
    # /apps/* narrowed by a regex on the normalised path.
    [(var, op, regex)] = apps["vars"]
    assert (var, op) == ("uri", "~~")
    assert re.match(regex, "/apps/bikes/api/endpoint/abc/ngsi-ld/v1/entities")
    for other in ("/apps/bikes/", "/apps/bikes/assets/api/endpoint.js", "/apps/bikes/api/functions/sum"):
        assert not re.match(regex, other), other
    upstream = next(u for u in parsed["upstreams"] if u["id"] == apps["upstream_id"])
    assert all(node.startswith("context-gateway.") for node in upstream["nodes"])
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    mine, surface = plugins[apps["plugin_config_id"]], plugins[routes["apps-surface"]["plugin_config_id"]]
    oidc = mine["openid-connect"]
    assert oidc["access_token_in_authorization_header"] is True
    for key in ("cookie_name", "cookie_path", "secret"):
        assert oidc["session"][key] == surface["openid-connect"]["session"][key], key
    pattern, target = mine["proxy-rewrite"]["regex_uri"]
    assert re.sub(pattern, target.replace("$1", r"\1"), "/apps/bikes/api/endpoint/abc/ngsi-ld/v1/entities") == (
        "/api/endpoint/abc/ngsi-ld/v1/entities"
    )
    guard = mine["serverless-pre-function"]["functions"][0]
    assert "^/apps/[^/]+/api/endpoint/[^/]+/egress/" in guard and "X-Access-Token" in guard


@requires_helmfile
def test_apisix_yaml_ends_with_end_marker_and_has_no_raw_tokens(apisix_config):
    raw, _ = apisix_config
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    assert lines[-1] == "#END", "apisix.yaml must end with exact #END marker"
    assert "${DOMAIN}" not in raw, "Unsubstituted ${DOMAIN} found in apisix.yaml"
    assert "${REALM}" not in raw, "Unsubstituted ${REALM} found in apisix.yaml"


# --- T-0025: the Linkerd Server scoping the public data-plane port -----------------


def servers(docs: list[dict]) -> dict[str, dict]:
    return {
        d["metadata"]["name"]: d
        for d in docs
        if d.get("kind") == "Server" and d.get("apiVersion") == "policy.linkerd.io/v1beta3"
    }


@requires_helmfile
def test_data_plane_port_is_scoped_by_a_linkerd_server(rendered):
    """Without a Server on 9080 the namespace's mandatory-mTLS default policy governs the
    public port, and every request from an unmeshed ingress controller is refused."""
    server = servers(rendered("production"))["apisix-configuration-apisix-gateway"]
    assert server["spec"]["port"] == 9080
    assert server["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "apisix"
    assert server["spec"]["proxyProtocol"] == "HTTP/1"


@requires_helmfile
def test_access_policy_follows_whether_the_ingress_edge_is_meshed(rendered):
    """`allowUnauthenticatedIngress` is the only thing that may open the port to plaintext,
    and only 9080: every other APISIX port stays on the namespace default."""
    production = servers(rendered("production"))["apisix-configuration-apisix-gateway"]
    assert production["spec"]["accessPolicy"] == "all-authenticated"

    # dev runs behind the kit's Traefik, which has no mesh identity.
    dev = servers(rendered("dev"))["apisix-configuration-apisix-gateway"]
    assert dev["spec"]["accessPolicy"] == "all-unauthenticated"

    ports = {s["spec"]["port"] for s in servers(rendered("production")).values()}
    assert 9091 not in ports and 9092 not in ports and 9180 not in ports


def selects(policy: dict, labels: dict) -> bool:
    match = policy["spec"]["podSelector"].get("matchLabels", {})
    return bool(match) and all(labels.get(k) == v for k, v in match.items())


@requires_helmfile
def test_every_route_upstream_is_a_pod_apisix_is_allowed_to_reach(rendered):
    """A route the egress policy does not name resolves and is then dropped on the way out.

    APISIX runs under a default-deny egress, so each upstream in the standalone rule file
    needs a NetworkPolicy line naming that pod and that port — and, on a meshed cluster, the
    peer's inbound proxy port too, because that is where the outbound proxy actually connects.
    Neither is visible in a render of the route table alone: the edge answers 504 with the
    upstream 2/2 and healthy, which reads as an application fault and is not one.
    """
    docs = rendered("dev")
    config = yaml.safe_load(next(
        d for d in docs
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-config"
    )["data"]["apisix.yaml"])

    apisix_labels = {
        "app.kubernetes.io/name": "apisix",
        "app.kubernetes.io/instance": "apisix-apisix",
    }
    # A peer selector is a subset of the pod's labels, not the whole set: the policy that
    # names only `app.kubernetes.io/name` still selects a pod the Service picks by two labels.
    allowed = [
        (frozenset(peer["podSelector"]["matchLabels"].items()), port["port"])
        for policy in docs
        if policy.get("kind") == "NetworkPolicy" and selects(policy, apisix_labels)
        for rule in policy["spec"].get("egress", [])
        for peer in rule.get("to", []) if "podSelector" in peer
        for port in rule.get("ports", [])
    ]
    services = {
        (d["metadata"]["name"], d["metadata"]["namespace"]): d
        for d in docs if d.get("kind") == "Service"
    }
    # A NetworkPolicy port is the port on the wire, and kube-proxy has already rewritten the
    # Service port to the target one by then. `targetPort` is usually a name, so it is
    # resolved against the container that carries it rather than assumed equal to the port.
    container_ports = {
        (port["name"], frozenset(workload["spec"]["selector"]["matchLabels"].items())): port["containerPort"]
        for workload in docs if workload.get("kind") in ("Deployment", "StatefulSet")
        for container in workload["spec"]["template"]["spec"]["containers"]
        for port in container.get("ports", []) if "name" in port
    }

    for upstream in config.get("upstreams", []):
        for node in upstream["nodes"]:
            host, _, port = node.rpartition(":")
            if not host.endswith(".svc.cluster.local"):
                continue
            name, namespace = host.split(".")[:2]
            service = services.get((name, namespace))
            assert service, f"upstream {host} names no Service in the render"
            selector = frozenset(service["spec"]["selector"].items())
            target = next(
                p.get("targetPort", p["port"]) for p in service["spec"]["ports"]
                if p["port"] == int(port)
            )
            if isinstance(target, str):
                target = container_ports[(target, selector)]
            for allowed_port, why in ((target, "the upstream port"), (4143, "the peer's inbound proxy")):
                assert any(
                    peer <= selector and port_of == allowed_port for peer, port_of in allowed
                ), (
                    f"apisix has no egress rule to {name} on {allowed_port} ({why}); "
                    f"route upstream {node} will time out at the edge"
                )


# The paths under the endpoint surface that must keep working, and the one that must not
# reach the gateway from outside (T-0458, R46). The delivery path carries no token — the
# broker calling it holds none — so it is reached in-cluster, where the NetworkPolicy of
# T-0429 governs who may, and refused here, where a NetworkPolicy can say nothing.
ENDPOINT_PATHS = {
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/ngsi-ld/v1/entities": True,
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/ngsi-ld/v1/subscriptions": True,
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/ogc/features/collections": True,
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/sta/v1.1/Things": True,
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/access": True,
    "/api/endpoint/n4t8xq2vhm6zc9wrb5sdj3kfp7/egress/notifications": False,
    "/api/endpoint/other-slug/egress/notifications?to=http%3A%2F%2Fx": False,
}


def endpoint_guard(parsed):
    """The path guard of the endpoint route, as the regex it actually applies."""
    config = next(p for p in parsed["plugin_configs"] if p["id"] == "context-endpoint")
    lua = config["plugins"]["serverless-pre-function"]["functions"][0]
    pattern = re.search(r"ngx\.re\.find\(ngx\.var\.uri, \[\[(?P<re>.+?)\]\]", lua)
    assert pattern, f"the endpoint route applies no path guard:\n{lua}"
    assert "ngx.exit(403)" in lua, "the guard matches a path and then lets it through"
    return re.compile(pattern.group("re"))


@requires_helmfile
def test_the_unauthenticated_delivery_path_is_refused_at_the_edge(apisix_config):
    """The route stays as it is — it is the whole public representation surface — and one
    path under it is refused. Asserted by running the guard's own expression, so what is
    tested is which paths it refuses rather than that a guard is present."""
    _, parsed = apisix_config
    guard = endpoint_guard(parsed)
    refused = {path: bool(guard.search(path)) for path in ENDPOINT_PATHS}
    assert refused == {path: not allowed for path, allowed in ENDPOINT_PATHS.items()}


@requires_helmfile
def test_the_space_surface_needs_no_such_guard(apisix_config):
    """`/cs/*` is the tenant-member surface and carries no egress path at all; a guard there
    would be a rule nobody can explain in a year."""
    _, parsed = apisix_config
    config = next(p for p in parsed["plugin_configs"] if p["id"] == "context-space")
    assert "egress" not in config["plugins"]["serverless-pre-function"]["functions"][0]


@requires_helmfile
def test_the_broker_dials_the_service_and_not_the_edge(rendered):
    """The other half, and the half that has to land first: with the egress base left at the
    public URL the broker would dial the path the guard above refuses, and every notification
    would stop (R46, T-0457)."""
    deployment = next(
        d for d in rendered("local")
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "context-gateway"
    )
    env = {
        e["name"]: e.get("value")
        for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["JC_GATEWAY_EGRESS_URL"].startswith("http://context-gateway.")
    assert env["JC_GATEWAY_EGRESS_URL"].endswith(".svc.cluster.local:8080")
    assert env["JC_GATEWAY_PUBLIC_URL"] == f"https://{LOCAL_DOMAIN}"


@requires_helmfile
def test_the_portal_scrape_path_is_refused_at_the_edge(apisix_config):
    """OPS-16: the Portal serves /metrics on the port APISIX publishes it on, so the edge is
    what keeps the series inside the cluster. The route terminates at APISIX and never dials
    the upstream; the ServiceMonitor reaches the pod directly and does not pass through here.
    """
    _, parsed = apisix_config
    routes = {r["id"]: r for r in parsed.get("routes", [])}
    plugins = {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}
    abort = plugins["portal-metrics"]["fault-injection"]["abort"]
    assert abort["http_status"] == 404, abort
    # Above the UI's catch-all, or `/*` answers first and proxies the scrape to the Portal.
    assert routes["portal-metrics"]["priority"] > routes["portal-ui"]["priority"]
