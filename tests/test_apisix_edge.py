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
from test_edge_attack_surface import TRUSTED_HEADERS as FORGED_HEADERS

UI_CONFIGS = ("portal-ui", "apps-surface", "keycloak", "gitea-forge")
# The routes the Portal itself answers; their headers are the Portal's own (T-1732).
PORTAL_CONFIGS = (
    "portal-ui",
    "portal-api",
    "portal-well-known",
    "portal-metrics",
    "apps-surface",
    "portal-redirect",
)
# Pages and app bundles a browser may cache; every other route is `no-store`.
CACHEABLE_CONFIGS = ("portal-ui", "apps-surface")
API_CONFIGS = ("portal-api", "context-space", "context-endpoint")
GATEWAY_UPSTREAMS = ("context-space", "context-endpoint")
# BSI TR-02102-2: no CBC, no 3DES, no static RSA key exchange, no anonymous suites.
FORBIDDEN_CIPHER_MARKERS = ("_CBC_", "3DES", "TLS_RSA_", "_anon_", "RC4")


@pytest.fixture(scope="module")
def plugin_configs(rendered):
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-config"
    )
    parsed = yaml.safe_load(cm["data"]["apisix.yaml"])
    return {pc["id"]: pc.get("plugins", {}) for pc in parsed["plugin_configs"]}


@pytest.fixture(scope="module")
def upstreams(rendered):
    cm = next(
        d for d in rendered("local")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-config"
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


def test_security_response_headers_on_every_route(plugin_configs):
    """T-0028: HSTS, nosniff, referrer policy everywhere; framing and caching by route class."""
    for config_id, plugins in plugin_configs.items():
        headers = plugins["response-rewrite"]["headers"]["set"]
        assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains; preload"
        assert headers["X-Content-Type-Options"] == "nosniff"
        # The Portal answers `no-referrer` itself, and the edge sets the header on every
        # response including the ones it writes (the login redirect), so the Portal's own routes
        # say the same thing on both sides and no request carries a Portal path to another
        # origin. The upstreams that are somebody else's application keep the wider value: Gitea
        # and Keycloak check the `Referer` on some form posts, and taking it away breaks a login.
        expected_referrer = "no-referrer" if config_id in PORTAL_CONFIGS else "strict-origin-when-cross-origin"
        assert headers["Referrer-Policy"] == expected_referrer, config_id
        expected_frame = "SAMEORIGIN" if config_id in UI_CONFIGS else "DENY"
        assert headers["X-Frame-Options"] == expected_frame, config_id
        if config_id not in CACHEABLE_CONFIGS:
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

    stream = plugin_configs["context-endpoint"]["limit-count"]
    assert (stream["count"], stream["time_window"]) == (5000, 60)
    bulk = plugin_configs["context-endpoint"]["limit-conn"]
    assert bulk["conn"] == 10
    # The endpoint surface passes anonymous requests through, so the bucket cannot be keyed
    # on the bearer token alone — every anonymous caller would share one.
    assert bulk["key_type"] == "var_combination"
    assert "remote_addr" in bulk["key"]


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
    assert cors["allow_origins_by_regex"] == [r"^https://.+\.joinedcontext.test$"]
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
    referenced = set(re.findall(r"\$\{\{(\w+)\}\}", configmaps["apisix-standalone-config"]["apisix.yaml"]))
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


def edge_objects(docs: list[dict]) -> dict[str, dict]:
    kinds = ("Certificate", "TLSOption", "Ingress")
    return {d["kind"]: d for d in docs if d.get("kind") in kinds}


def test_certificate_covers_the_apex_and_every_routed_subdomain(rendered):
    """T-0045: the SAN list is explicit in Git, not inferred by cert-manager's ingress-shim."""
    objects = edge_objects(rendered("dev"))
    certificate = objects["Certificate"]
    assert certificate["spec"]["secretName"] == "apisix-edge-tls"
    assert certificate["spec"]["issuerRef"] == {"name": "letsencrypt-prod", "kind": "ClusterIssuer"}
    # One entry per hostname: the Portal's three routes share `portal` and must not put it
    # on the certificate three times (ADR-N-019).
    assert certificate["spec"]["dnsNames"] == [
        "2.28.67.127.sslip.io",
        "data.2.28.67.127.sslip.io",
        "idm.2.28.67.127.sslip.io",
        "portal.2.28.67.127.sslip.io",
    ]

    ingress = objects["Ingress"]
    hosts = [rule["host"] for rule in ingress["spec"]["rules"]]
    assert hosts == certificate["spec"]["dnsNames"], "the apex must be routed, not only certified"
    assert ingress["spec"]["tls"][0]["hosts"] == certificate["spec"]["dnsNames"]
    assert ingress["spec"]["tls"][0]["secretName"] == certificate["spec"]["secretName"]
    # Two owners of one Secret means two ACME orders for the same names.
    assert "cert-manager.io/cluster-issuer" not in ingress["metadata"]["annotations"]


def test_traefik_listener_enforces_tr_02102(rendered):
    """T-0044: TLS 1.2 floor, AEAD suites only."""
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
    """The nginx branch of the same requirement; no TLSOption CRD exists there."""
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
