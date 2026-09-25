"""Tests for the APISIX plugin chain and the public edge TLS configuration.

docs/Deployment/10-edge-routing-apisix.md section 4 (plugin chain) and
docs/Deployment/08-security-hardening.md section 2, layer 9 (edge TLS).
"""

import re

import pytest
import yaml

# Headers a client must never be able to set: each one is either a tenancy or authorization
# claim the platform trusts internally, or a proxy hint APISIX sets itself. One list, shared
# with the walk over the component sources: two copies of it drifted once already (T-1672).
from conftest import set_global
from test_edge_attack_surface import TRUSTED_HEADERS as FORGED_HEADERS

UI_CONFIGS = ("portal-ui", "portal-public", "apps-surface", "keycloak", "gitea-forge")
# The routes the Portal itself answers; their headers are the Portal's own (T-1732).
PORTAL_CONFIGS = (
    "portal-ui",
    "portal-public",
    "portal-api",
    "portal-well-known",
    "portal-metrics",
    "apps-surface",
    "portal-redirect",
)
# Pages and app bundles a browser may cache; every other route is `no-store`.
CACHEABLE_CONFIGS = ("portal-ui", "portal-public", "apps-surface")
API_CONFIGS = ("portal-api", "context-space", "context-endpoint")
GATEWAY_UPSTREAMS = ("context-space", "context-endpoint")
# The gateway answers these too, and sets their Cache-Control itself (EP-84: the DCAT-AP feed).
GATEWAY_ANSWERED = (*GATEWAY_UPSTREAMS, "catalog-feed")
# BSI TR-02102-2: no CBC, no 3DES, no static RSA key exchange, no anonymous suites.
FORBIDDEN_CIPHER_MARKERS = ("_CBC_", "3DES", "TLS_RSA_", "_anon_", "RC4")


@pytest.fixture(scope="module")
def plugin_configs(rendered):
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-base"
    )
    parsed = yaml.safe_load(cm["data"]["apisix.yaml"])
    return {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}


@pytest.fixture(scope="module")
def upstreams(rendered):
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-base"
    )
    parsed = yaml.safe_load(cm["data"]["apisix.yaml"])
    return {u["id"]: u for u in parsed["upstreams"]}


def test_every_route_clears_every_forged_header(plugin_configs):
    """T-0026: header sanitization runs on every route, not only the authenticated ones."""
    for config_id, plugins in plugin_configs.items():
        sanitizer = plugins.get("serverless-pre-function")
        assert sanitizer, f"{config_id} has no serverless-pre-function"
        assert sanitizer["phase"] == "rewrite"
        lua = "\n".join(sanitizer["functions"])
        for header in FORGED_HEADERS:
            assert header in lua, f"{config_id} does not clear {header}"
        assert "ngx.req.clear_header" in lua


def test_x_forwarded_for_survives_sanitization(plugin_configs):
    """It is the client-IP audit trail and the rate-limit key; nginx maintains it itself."""
    for config_id, plugins in plugin_configs.items():
        lua = "\n".join(plugins["serverless-pre-function"]["functions"])
        assert '"X-Forwarded-For"' not in lua, f"{config_id} clears X-Forwarded-For"


def test_the_trace_context_crosses_the_edge(plugin_configs):
    """OPS-17: APISIX neither clears nor rewrites `traceparent`/`tracestate`, so a trace a client
    starts reaches the gateway, which relays it to the broker (platform
    `space_surface_tests::the_trace_context_reaches_the_broker_unchanged`)."""
    for config_id, plugins in plugin_configs.items():
        lua = "\n".join(plugins["serverless-pre-function"]["functions"]).lower()
        rewrite = plugins.get("proxy-rewrite", {}).get("headers", {})
        touched = [
            name.lower()
            for section in ("set", "add", "remove")
            for name in (rewrite.get(section) or [])
        ]
        for header in ("traceparent", "tracestate"):
            assert f'"{header}"' not in lua, f"{config_id} clears {header}"
            assert header not in touched, f"{config_id} rewrites {header}"


def test_security_response_headers_on_every_route(plugin_configs):
    """T-0028, OPS-34: HSTS, nosniff, referrer policy everywhere; framing and caching by route class."""
    for config_id, plugins in plugin_configs.items():
        headers = plugins["response-rewrite"]["headers"]["set"]
        assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains; preload"
        assert headers["X-Content-Type-Options"] == "nosniff"
        # The Portal answers `no-referrer` itself, and the edge sets the header on every
        # response including the ones it writes (the login redirect), so the Portal's own routes
        # say the same thing on both sides and no request carries a Portal path to another
        # origin. The upstreams that are somebody else's application keep the wider value: Gitea
        # and Keycloak check the `Referer` on some form posts, and taking it away breaks a login.
        # security.txt is answered by the edge itself (T-1721): no upstream reads a `Referer`.
        narrow = PORTAL_CONFIGS + ("security-txt",)
        expected_referrer = "no-referrer" if config_id in narrow else "strict-origin-when-cross-origin"
        assert headers["Referrer-Policy"] == expected_referrer, config_id
        expected_frame = "SAMEORIGIN" if config_id in UI_CONFIGS else "DENY"
        assert headers["X-Frame-Options"] == expected_frame, config_id
        if config_id.removesuffix("-portal").removesuffix("-apps") in GATEWAY_ANSWERED:
            # T-2262, EP-51: the gateway sets Cache-Control on every answer itself (`private`,
            # `no-store`, or `no-cache` with an ETag on a schema artifact); the edge leaves it be.
            assert "Cache-Control" not in headers, config_id
        elif config_id not in CACHEABLE_CONFIGS:
            assert headers["Cache-Control"] == "no-store, no-cache, must-revalidate", config_id


def test_rate_limit_classes(plugin_configs):
    """T-0029: one class per route, keyed on the strongest identity that route carries."""
    for config_id in ("portal-ui", "apps-surface", "portal-redirect"):
        ui = plugin_configs[config_id]["limit-count"]
        assert (ui["count"], ui["time_window"], ui["key"]) == (300, 60, "remote_addr"), config_id

    for config_id in ("portal-api", "context-space"):
        api = plugin_configs[config_id]["limit-count"]
        assert (api["count"], api["time_window"]) == (1200, 60), config_id
        assert "authorization" in api["key"], config_id
    # T-2669: a browser carries the edge session, which openid-connect turns into X-Access-Token;
    # keyed on the bearer alone, every session behind one address shared one bucket.
    portal = plugin_configs["portal-api"]["limit-count"]
    assert portal["key_type"] == "var_combination"
    assert portal["key"].split() == ["$http_authorization", "$http_x_access_token", "$remote_addr"]
    assert "X-Access-Token" in plugin_configs["portal-api"]["serverless-pre-function"]["functions"][0]

    stream = plugin_configs["context-endpoint"]["limit-count"]
    assert (stream["count"], stream["time_window"]) == (5000, 60)
    bulk = plugin_configs["context-endpoint"]["limit-conn"]
    assert bulk["conn"] == 10
    # The endpoint surface passes anonymous requests through, so the bucket cannot be keyed
    # on the bearer token alone — every anonymous caller would share one.
    assert bulk["key_type"] == "var_combination"
    assert "remote_addr" in bulk["key"]


# ADR-N-035: each chain the Organization tunes, its class, and the catalog default helm renders.
RATE_CLASSES = {
    "portal-ui": ("web", 300),
    "portal-public": ("web", 300),
    "apps-surface": ("web", 300),
    "portal-redirect": ("web", 300),
    "portal-api": ("api", 1200),
    "context-endpoint": ("publicEndpoint", 5000),
    "context-endpoint-portal": ("publicEndpoint", 5000),
}


def test_the_organization_tunes_each_class_by_its_label(rendered):
    """T-2892: the Portal replaces the count of a chain labelled `jc-rate-class` with the
    Organization's rate; helm renders the default, and every other chain keeps its own."""
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-base"
    )
    configs = yaml.safe_load(cm["data"]["apisix.yaml"])["plugin_configs"]
    labelled = {
        pc["id"]: (pc["labels"]["jc-rate-class"], pc["plugins"]["limit-count"]["count"])
        for pc in configs
        if "jc-rate-class" in (pc.get("labels") or {})
    }
    assert labelled == RATE_CLASSES
    for pc in configs:
        assert "labels" not in pc or pc["id"] in RATE_CLASSES, pc["id"]


def test_every_rate_limit_rejects_with_429(plugin_configs):
    for config_id, plugins in plugin_configs.items():
        for plugin in ("limit-count", "limit-conn"):
            if plugin in plugins:
                assert plugins[plugin]["rejected_code"] == 429, f"{config_id}/{plugin}"


def test_gateway_upstreams_carry_streaming_timeouts(upstreams):
    """T-0030: five minutes to read, and a pool sized for long-lived connections."""
    for upstream_id in GATEWAY_UPSTREAMS:
        upstream = upstreams[upstream_id]
        assert upstream["timeout"] == {"connect": 6, "send": 60, "read": 300}, upstream_id
        assert upstream["keepalive_pool"]["size"] == 320, upstream_id


def test_gateway_routes_stream_unbuffered(plugin_configs):
    """A 300 s read timeout is pointless if nginx buffers the whole response first."""
    for config_id in GATEWAY_UPSTREAMS:
        assert plugin_configs[config_id]["proxy-buffering"]["disable_proxy_buffering"] is True


def test_endpoint_surface_restricts_cors_to_the_platform_domain(plugin_configs):
    cors = plugin_configs["context-endpoint"]["cors"]
    assert "allow_origins" not in cors, "a wildcard origin would hand responses to any page"
    # The dots of the domain are a character class, not a bare `.`: see
    # tests/test_foreign_origin.py for what an unescaped one lets through (T-1679).
    assert cors["allow_origins_by_regex"] == [r"^https://[^@/]+\.joinedcontext[.]test$"]
    assert cors["allow_credential"] is False


def test_every_config_variable_is_declared_for_the_nginx_workers(rendered):
    """An undeclared ${{VAR}} costs a whole rule file, silently.

    APISIX resolves them with `os.getenv` inside an nginx worker, and a worker sees only the
    variables nginx.conf declares. An undeclared one makes APISIX reject the entire
    apisix.yaml and keep serving the last file that parsed, so route changes appear to be
    ignored while the ConfigMap looks perfectly correct.
    """
    docs = rendered("local")
    configmaps = {d["metadata"]["name"]: d["data"] for d in docs if d.get("kind") == "ConfigMap"}
    referenced = set(re.findall(r"\$\{\{(\w+)\}\}", configmaps["apisix-standalone-base"]["apisix.yaml"]))
    declared = set(yaml.safe_load(configmaps["apisix"]["config.yaml"])["nginx_config"]["envs"])
    assert referenced <= declared, f"not declared in apisix.nginx.envs: {sorted(referenced - declared)}"
    # The edge login needs both (ADR-N-019): the client secret and the session key.
    assert {"EDGE_CLIENT_SECRET", "OIDC_SESSION_SECRET"} <= referenced


def test_the_edge_client_secret_reaches_apisix_from_a_secret_only(rendered):
    """AP-27: the `edge` client's secret is an environment variable from the Secret the
    secrets component generates for the client, in the gateway's namespace; it appears
    nowhere in the rule file (the rule file carries the `${{VAR}}` reference)."""
    docs = rendered("local")
    deployment = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "apisix")
    env = {e["name"]: e for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    ref = env["EDGE_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "keycloak-client-edge", "key": "client-secret"}
    namespace = deployment["metadata"]["namespace"]
    assert any(
        d.get("kind") == "Secret" and d["metadata"]["name"] == "keycloak-client-edge"
        and d["metadata"]["namespace"] == namespace
        for d in docs
    ), f"no keycloak-client-edge Secret rendered in {namespace}"
    # The plugin dials the PUBLIC issuer host, the same hairpin the Portal makes (T-0400): a
    # meshed pod needs 443 out of the outbound redirect, and the NetworkPolicy needs the port.
    annotations = deployment["spec"]["template"]["metadata"]["annotations"]
    assert "443" in annotations["config.linkerd.io/skip-outbound-ports"].split(",")
    policy = next(d for d in docs if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "apisix")
    internet = [
        {p["port"] for p in rule["ports"]}
        for rule in policy["spec"]["egress"]
        if any("ipBlock" in to for to in rule.get("to", []))
    ]
    assert internet and {443, 8443} <= internet[0], internet



def test_apisix_serves_the_composed_secret_and_helm_seeds_it_with_the_base(rendered):
    """ADR-N-030, AP-112: the rule file APISIX mounts is the Secret the Portal composes, never a
    ConfigMap, since it carries every App's client secret. Helm renders the base as a ConfigMap
    and seeds the Secret with the same file, kept across syncs once the Portal owns it."""
    docs = rendered("local")
    deployment = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "apisix")
    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"]["volumes"]}
    assert volumes["apisix-admin"] == {
        "name": "apisix-admin",
        "secret": {"secretName": "apisix-standalone-config"},
    }
    mounts = {m["name"]: m for m in deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]}
    assert mounts["apisix-admin"]["mountPath"] == "/apisix-config"
    assert "subPath" not in mounts["apisix-admin"], "a subPath mount never sees the reconciler's writes"

    namespace = deployment["metadata"]["namespace"]
    by_kind = {(d["kind"], d["metadata"]["name"]): d for d in docs if d["metadata"].get("namespace") == namespace}
    assert ("ConfigMap", "apisix-standalone-config") not in by_kind
    base = by_kind[("ConfigMap", "apisix-standalone-base")]["data"]["apisix.yaml"]
    seed = by_kind[("Secret", "apisix-standalone-config")]
    assert seed["stringData"]["apisix.yaml"] == base
    assert base.rstrip().endswith("#END")
    assert seed["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"


def test_the_portal_may_read_the_base_and_update_the_served_file_and_nothing_else(rendered):
    """ADR-N-030: the Portal's ServiceAccount gets read on the base ConfigMap and read/update on
    the one Secret in the APISIX namespace, each by name. ADR-N-037: it also makes and retires
    each App's Ingress and Certificate there; no update or patch on either, no other object."""
    docs = rendered("local")
    role = next(d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "edge-file-composer")
    assert role["rules"] == [
        {"apiGroups": [""], "resources": ["configmaps"], "resourceNames": ["apisix-standalone-base"], "verbs": ["get"]},
        {"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["apisix-standalone-config"], "verbs": ["get", "update"]},
        {"apiGroups": ["networking.k8s.io"], "resources": ["ingresses"], "verbs": ["get", "list", "create", "delete"]},
        {"apiGroups": ["cert-manager.io"], "resources": ["certificates"], "verbs": ["get", "list", "create", "delete"]},
    ]
    binding = next(d for d in docs if d.get("kind") == "RoleBinding" and d["metadata"]["name"] == "edge-file-composer")
    portal = next(
        d for d in docs
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "portal"
    )
    assert binding["metadata"]["namespace"] == role["metadata"]["namespace"]
    assert binding["subjects"] == [{
        "kind": "ServiceAccount",
        "name": portal["spec"]["template"]["spec"]["serviceAccountName"],
        "namespace": portal["metadata"]["namespace"],
    }]


def edge_objects(docs: list[dict]) -> dict[str, dict]:
    kinds = ("Certificate", "TLSOption", "Ingress")
    return {
        d["kind"]: d
        for d in docs
        if d.get("kind") in kinds and d["metadata"]["name"] != "apisix-edge-staging"
    }


def staging_objects(docs: list[dict]) -> dict[str, dict]:
    return {
        d["kind"]: d
        for d in docs
        if d.get("kind") in ("Issuer", "Certificate", "ClusterIssuer")
        and d["metadata"]["name"] in ("letsencrypt-staging", "apisix-edge-staging")
    }


def test_new_hostnames_are_proven_on_the_staging_issuer_first(rendered, rendered_variant):
    """T-2806, OPS-35: a new domain meets Let's Encrypt STAGING before production carries it.

    HTTP-01 per hostname (no DNS API exists for the zone, so no DNS-01 and no wildcard), a
    namespaced Issuer so nothing cluster-wide changes, and a Secret nothing serves.
    """
    # dev proved dev.joinedcontext.com this way on 2026-09-24 before `domain` moved to it; a
    # next move sets stagingDomain the same way.
    docs = rendered_variant("dev", lambda tree: set_global(tree, "ingress.stagingDomain", "next.example.org"))
    objects = staging_objects(docs)
    assert "ClusterIssuer" not in objects
    issuer = objects["Issuer"]["spec"]["acme"]
    assert issuer["server"] == "https://acme-staging-v02.api.letsencrypt.org/directory"
    assert issuer["solvers"] == [{"http01": {"ingress": {"ingressClassName": "traefik"}}}]
    assert "email" not in issuer, "no personal address in Git; the ACME account needs none"

    certificate = objects["Certificate"]["spec"]
    assert certificate["issuerRef"] == {"name": "letsencrypt-staging", "kind": "Issuer"}
    assert certificate["secretName"] == "apisix-edge-staging-tls"
    assert certificate["dnsNames"] == [
        "next.example.org",
        "data.next.example.org",
        "idm.next.example.org",
        "portal.next.example.org",
    ]
    assert not any("*" in name for name in certificate["dnsNames"]), "no wildcard over HTTP-01"

    served = edge_objects(docs)["Ingress"]["spec"]["tls"][0]["secretName"]
    assert served != certificate["secretName"], "a staging certificate is never served"


def test_no_staging_objects_without_a_staging_domain(rendered):
    """Production, and dev once its domain moved, render no staging Issuer or Certificate."""
    assert staging_objects(rendered("production")) == {}
    assert staging_objects(rendered("dev")) == {}


def test_certificate_covers_the_apex_and_every_routed_subdomain(rendered):
    """T-0045: the SAN list is explicit in Git, not inferred by cert-manager's ingress-shim."""
    objects = edge_objects(rendered("dev"))
    certificate = objects["Certificate"]
    assert certificate["spec"]["secretName"] == "apisix-edge-tls"
    assert certificate["spec"]["issuerRef"] == {"name": "letsencrypt-prod", "kind": "ClusterIssuer"}
    # One entry per hostname: the Portal's three routes share `portal` and must not put it
    # on the certificate three times (ADR-N-019).
    assert certificate["spec"]["dnsNames"] == [
        "dev.joinedcontext.com",
        "data.dev.joinedcontext.com",
        "idm.dev.joinedcontext.com",
        "portal.dev.joinedcontext.com",
    ]

    ingress = objects["Ingress"]
    hosts = [rule["host"] for rule in ingress["spec"]["rules"]]
    assert hosts == certificate["spec"]["dnsNames"], "the apex must be routed, not only certified"
    assert ingress["spec"]["tls"][0]["hosts"] == certificate["spec"]["dnsNames"]
    assert ingress["spec"]["tls"][0]["secretName"] == certificate["spec"]["secretName"]
    # Two owners of one Secret means two ACME orders for the same names.
    assert "cert-manager.io/cluster-issuer" not in ingress["metadata"]["annotations"]


def test_traefik_listener_enforces_tr_02102(rendered):
    """T-0044, OPS-36: TLS 1.2 floor, AEAD suites only (BSI TR-02102)."""
    objects = edge_objects(rendered("dev"))
    options = objects["TLSOption"]["spec"]
    assert options["minVersion"] == "VersionTLS12"
    assert options["maxVersion"] == "VersionTLS13"
    for suite in options["cipherSuites"]:
        assert suite.startswith("TLS_ECDHE_"), suite
        assert all(marker not in suite for marker in FORBIDDEN_CIPHER_MARKERS), suite

    annotations = objects["Ingress"]["metadata"]["annotations"]
    assert annotations["traefik.ingress.kubernetes.io/router.tls.options"] == "dev-bsi-tr-02102@kubernetescrd"


def test_nginx_listener_carries_the_same_cipher_policy(rendered):
    """OPS-36: the nginx branch of the same requirement; no TLSOption CRD exists there."""
    objects = edge_objects(rendered("production"))
    assert "TLSOption" not in objects
    annotations = objects["Ingress"]["metadata"]["annotations"]
    ciphers = annotations["nginx.ingress.kubernetes.io/ssl-ciphers"].split(":")
    assert ciphers, "no cipher list configured"
    for cipher in ciphers:
        assert cipher.startswith("ECDHE-"), cipher
        assert "CBC" not in cipher and "3DES" not in cipher, cipher
    assert annotations["nginx.ingress.kubernetes.io/ssl-prefer-server-ciphers"] == "true"


def test_the_proxy_server_names_its_own_body_ceiling(rendered):
    """T-2263: with the inherited `client_max_body_size 0` the edge answers 413 to every
    chunked request body.

    For a body with a `Content-Length` nginx reads `0` as "no limit", but its chunked filter
    compares `content_length_n + chunk` against the same number without a zero guard, so a
    streamed body of any size is over the limit — measured on dev as `client intended to send
    too large chunked body: 0+435 bytes` on a Portal write. The ceiling therefore has to be a
    number, and it has to be set in the proxy server block: APISIX's own
    `client_max_body_size 0` already sits in the http block, and nginx refuses to start on a
    duplicate there.
    """
    docs = rendered("local")
    nginx = yaml.safe_load(
        next(
            d for d in docs
            if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix"
        )["data"]["config.yaml"]
    )["nginx_config"]
    server = nginx.get("http_server_configuration_snippet", "")
    found = re.findall(r"^\s*client_max_body_size\s+(\S+?);", server, re.MULTILINE)
    assert found, f"the proxy server block sets no client_max_body_size: {server!r}"
    assert found[0] != "0", "0 makes nginx refuse every chunked body"
    assert re.fullmatch(r"\d+[km]?", found[0], re.IGNORECASE), found[0]
    # A service is the authority over its own bodies: the largest one a service accepts is
    # the 11 MB of the Portal's pipeline test, so the edge must not cut below that.
    assert found[0].lower().endswith("m") and int(found[0][:-1]) >= 12, (
        f"the edge ceiling {found[0]} is below what a service already accepts"
    )
    assert "client_max_body_size" not in nginx.get("http_configuration_snippet", ""), (
        "a second client_max_body_size in the http block makes nginx refuse to start"
    )
