"""The open-data catalogue: what the render has to prove before anyone applies it.

T-0315 puts CKAN, its Solr and its Redis on the dev cluster; T-0341 and T-0342 say every
name, colour and logo a visitor sees comes from one `global.branding` block and never from
the chart. Both are decidable from a render, which is where they are decided: a wrong
DataStore role or a Solr open to the namespace is not visible until someone reads a private
dataset out of it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import set_global

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHART = PROJECT_ROOT / "charts/ckan"

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")
requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

DEV_DOMAIN = "dev.joinedcontext.com"
CATALOGUE_HOST = f"data.{DEV_DOMAIN}"


def by_name(docs, kind, name):
    match = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert match, f"{kind}/{name} is not in the render"
    return match[0]


def ckan_container(docs):
    deployment = by_name(docs, "Deployment", "ckan")
    return deployment["spec"]["template"]["spec"]["containers"][0]


def env_of(container):
    return {e["name"]: e.get("value") for e in container.get("env", [])}


@requires_helmfile
def test_the_whole_stack_renders_on_dev(rendered):
    """The catalogue is three workloads and two claims, not one Deployment: CKAN cannot index
    without Solr and will not hold a session without Redis."""
    docs = rendered("dev")
    by_name(docs, "Deployment", "ckan")
    by_name(docs, "Deployment", "ckan-redis")
    by_name(docs, "StatefulSet", "ckan-solr")
    for service in ("ckan", "ckan-solr", "ckan-redis"):
        by_name(docs, "Service", service)
    by_name(docs, "PersistentVolumeClaim", "ckan-storage")


@requires_helmfile
def test_every_catalogue_image_is_pinned_by_digest(rendered):
    """An unpinned tag is a different image on the next pull, and CKAN, Solr and the theme
    only work as a matched set (OPS-27)."""
    docs = rendered("dev")
    workloads = [
        by_name(docs, "Deployment", "ckan"),
        by_name(docs, "Deployment", "ckan-redis"),
        by_name(docs, "StatefulSet", "ckan-solr"),
    ]
    for workload in workloads:
        for container in workload["spec"]["template"]["spec"]["containers"]:
            assert "@sha256:" in container["image"], (
                f"{workload['metadata']['name']} runs {container['image']}, which is not pinned"
            )


@requires_helmfile
def test_the_datastore_read_connection_is_a_different_role_than_the_write_one(rendered):
    """`datastore_search_sql` runs SQL the caller wrote on the read connection. Sharing the
    write role there turns the public catalogue into an arbitrary-SQL surface on the same
    database, and CKAN refuses to start rather than allow it (EP-65)."""
    env = env_of(ckan_container(rendered("dev")))
    read, write = env["CKAN_DATASTORE_READ_URL"], env["CKAN_DATASTORE_WRITE_URL"]
    assert read.split("://", 1)[1].split(":", 1)[0] != write.split("://", 1)[1].split(":", 1)[0], (
        "the DataStore read and write URLs use the same database role"
    )
    assert read.rsplit("/", 1)[1] == write.rsplit("/", 1)[1], "both URLs must name the same database"
    assert env["CKAN_SQLALCHEMY_URL"].rsplit("/", 1)[1] != read.rsplit("/", 1)[1], (
        "the catalogue database and the DataStore database must be different (EP-65)"
    )


@requires_helmfile
def test_no_credential_is_a_literal_in_the_pod(rendered):
    """Every password reaches the container as a `secretKeyRef` and a `$(VAR)` reference in
    the URL beside it; a literal here would be a credential in Git (CC-06, MF-24)."""
    container = ckan_container(rendered("dev"))
    referenced = {e["name"] for e in container["env"] if "valueFrom" in e}
    for name, value in env_of(container).items():
        if value is None:
            continue
        if "://" in value and "@" in value:
            secret = value.split("://", 1)[1].split("@", 1)[0]
            assert ":$(" in secret, f"{name} carries a literal password"
            assert secret.split(":$(", 1)[1].rstrip(")") in referenced


@requires_helmfile
def test_solr_and_redis_answer_the_catalogue_and_nothing_else(rendered):
    """An unauthenticated Solr reachable from the namespace is a full-text dump of every
    private dataset; Redis holds the sessions. Both accept CKAN only (OPS-38)."""
    docs = rendered("dev")
    for policy_name, port in (("ckan-solr", 8983), ("ckan-redis", 6379)):
        policy = by_name(docs, "NetworkPolicy", policy_name)["spec"]
        assert policy["policyTypes"] == ["Ingress", "Egress"]
        peers = [p for rule in policy["ingress"] for p in rule["from"]]
        assert len(peers) == 1
        labels = peers[0]["podSelector"]["matchLabels"]
        assert labels["app.kubernetes.io/component"] == "ckan"
        # The namespace is named rather than implied: a peer carrying only a podSelector
        # keeps validating after the workload it was written for has moved somewhere else.
        namespace = peers[0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        assert namespace == by_name(docs, "NetworkPolicy", policy_name)["metadata"]["namespace"]
        assert [p["port"] for rule in policy["ingress"] for p in rule["ports"]] == [port]


@requires_helmfile
def test_the_catalogue_is_reached_through_the_edge_and_nothing_else(rendered):
    """CKAN has no authentication in front of its own write API beyond its session, so the
    only door is APISIX, where the header sanitisation and the rate limit are."""
    policy = by_name(rendered("dev"), "NetworkPolicy", "ckan")["spec"]
    peers = [p for rule in policy["ingress"] for p in rule["from"]]
    # The edge, and the API token Job that signs in on the Service (T-0493); nobody else.
    assert [p["podSelector"]["matchLabels"].get("app.kubernetes.io/component",
                                                p["podSelector"]["matchLabels"]["app.kubernetes.io/name"])
            for p in peers] == ["apisix", "api-token"]
    assert [p["port"] for rule in policy["ingress"] for p in rule["ports"]] == [5000, 5000]
    # Egress is a closed list: DNS, the database, Solr, Redis. No 443, because nothing in
    # this configuration fetches a remote URL — turning SSO on adds it, and this test with it.
    assert "Egress" in policy["policyTypes"]
    for rule in policy["egress"]:
        for peer in rule["to"]:
            assert "ipBlock" not in peer, "the catalogue must not be able to dial the internet"


@requires_helmfile
def test_the_catalogue_host_is_served_and_covered_by_the_certificate(rendered):
    """`data.{host}` is derived from the route's `subDomain`, so the Ingress rule and the SAN
    list follow from the same map. A host on neither is a browser warning or a 404."""
    docs = rendered("dev")
    ingress = by_name(docs, "Ingress", "apisix")
    assert CATALOGUE_HOST in {rule["host"] for rule in ingress["spec"]["rules"]}
    certificate = next(
        d for d in docs
        if d.get("kind") == "Certificate" and d["spec"].get("secretName") == "apisix-edge-tls"
    )
    assert CATALOGUE_HOST in certificate["spec"]["dnsNames"]

    config = by_name(docs, "ConfigMap", "apisix-standalone-base")["data"]["apisix.yaml"]
    routes = {r["id"]: r for r in yaml.safe_load(config)["routes"]}
    assert routes["ckan"]["host"] == CATALOGUE_HOST
    # The one path on the primary host answers a redirect rather than proxying: CKAN builds
    # every link from its site URL, so a proxied /ckan page would link off the prefix anyway.
    plugins = {p["id"]: p["plugins"] for p in yaml.safe_load(config)["plugin_configs"]}
    assert plugins["ckan-redirect"]["redirect"]["uri"] == f"https://{CATALOGUE_HOST}/"
    assert routes["ckan-redirect"]["host"] == DEV_DOMAIN
    assert routes["ckan-redirect"]["priority"] > routes["portal-ui"]["priority"]


@requires_helmfile
def test_the_instance_branding_reaches_both_the_catalogue_and_the_portal(rendered):
    """One block, two consumers (OPS-46, OPS-47, T-0340, T-0342): the Portal reads a YAML
    file it is handed by name, the CKAN theme reads the JSON beside its templates. Neither
    image carries a city literal, so a rebrand is this block and an apply."""
    docs = rendered("dev")
    branding = json.loads(by_name(docs, "ConfigMap", "ckan-theme")["data"]["branding.json"])
    assert branding["instanceName"] == "joinedcontext"
    assert branding["colours"]["primary"] == "#0000bf"
    # English only for now: the Portal ships no Finnish bundle yet, and a default the UI cannot
    # render made the shell fall back to another language (T-0342 follow-up).
    assert branding["languages"] == {"default": "en", "offered": ["en"]}
    # The logo travels as a file beside the block, never inlined into it.
    assert "logoSvg" not in branding
    assert by_name(docs, "ConfigMap", "ckan-theme")["data"]["logo.svg"].lstrip().startswith("<svg")

    portal_branding = yaml.safe_load(by_name(docs, "ConfigMap", "portal-branding")["data"]["branding.yaml"])
    assert portal_branding == branding, "the two consumers must be served the same block"
    portal = by_name(docs, "Deployment", "portal")
    portal_env = env_of(portal["spec"]["template"]["spec"]["containers"][0])
    assert portal_env["JC_BRANDING_FILE"] == "/etc/jc/branding/branding.yaml"


# The chart has no image defaults on purpose (an accidental default is an unreviewed image
# in production), so a standalone render supplies what the component's values file supplies.
CHART_BASE_VALUES = {
    "siteUrl": "https://data.example.test",
    "ckan": {"image": {"repository": "ckan/ckan-base", "tag": "2.11.3", "digest": "sha256:" + "0" * 64}},
    "solr": {"image": {"repository": "ckan/ckan-solr", "tag": "2.11-solr9", "digest": "sha256:" + "1" * 64}},
    "redis": {"image": {"repository": "redis", "tag": "7-alpine", "digest": "sha256:" + "2" * 64}},
}


def render_chart(tmp_path: Path, values: dict) -> list[dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    values = CHART_BASE_VALUES | values
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.dump(values))
    result = subprocess.run(
        ["helm", "template", "ckan-catalogue", str(CHART), "-f", str(values_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if isinstance(d, dict)]


@requires_helm
def test_a_second_installation_changes_the_block_and_not_one_template(tmp_path):
    """The point of T-0341: a city that is not Helsinki edits values and nothing else. If a
    branding change moved a single byte of the theme's Python or HTML, the theme would be a
    per-city fork instead of a parameter."""
    def theme(name: str, branding: dict) -> dict:
        docs = render_chart(tmp_path / name, {"branding": branding})
        return by_name(docs, "ConfigMap", "ckan-theme")["data"]

    first = theme("first", {
        "instanceName": "Helsinki Region Context",
        "colours": {"primary": "#0000bf"},
        "languages": {"default": "fi"},
    })
    second = theme("second", {
        "instanceName": "Banská Bystrica Context",
        "colours": {"primary": "#cc3026"},
        "languages": {"default": "sk"},
    })

    assert json.loads(first["branding.json"]) != json.loads(second["branding.json"])
    assert json.loads(second["branding.json"])["instanceName"] == "Banská Bystrica Context"
    for key in ("plugin.py", "__init__.py", "header.html", "footer.html", "entry_points.txt", "METADATA"):
        assert first[key] == second[key], f"{key} changed with the branding — the theme is not a parameter"


@requires_helm
def test_an_installation_that_configured_no_branding_still_renders(tmp_path):
    """A missing block is a plain catalogue, not a broken one: the theme reads its own
    defaults, the same way the Portal does."""
    docs = render_chart(tmp_path / "empty", {"branding": {}})
    assert json.loads(by_name(docs, "ConfigMap", "ckan-theme")["data"]["branding.json"]) == {}
    assert "logo.svg" not in by_name(docs, "ConfigMap", "ckan-theme")["data"]


@requires_helmfile
def test_the_config_the_entrypoint_edits_is_put_there_before_ckan_starts(rendered):
    """`start_ckan.sh` edits `$CKAN_INI` with `ckan config-tool`; it never creates it.

    The file the image ships is `/srv/app/ckan.ini`, on the read-only root filesystem, so
    `CKAN_INI` has to point at a writable volume — and something has to put the shipped file
    there before the entrypoint runs. Without it CKAN starts with no application loaded and
    answers 500 to its own probe until the kubelet restarts it, which is a crash loop with no
    line in it naming the cause.
    """
    docs = rendered("dev")
    pod = by_name(docs, "Deployment", "ckan")["spec"]["template"]["spec"]
    container = ckan_container(docs)
    ini = env_of(container)["CKAN_INI"]

    writable = {
        mount["mountPath"]
        for mount in container["volumeMounts"]
        if next(v for v in pod["volumes"] if v["name"] == mount["name"]).get("emptyDir") is not None
    }
    assert str(Path(ini).parent) in writable, f"{ini} is not on a writable volume"

    seeded = [
        init for init in pod.get("initContainers", [])
        if ini in init.get("command", []) + init.get("args", [])
    ]
    assert seeded, f"nothing writes {ini} before the entrypoint edits it"
    assert seeded[0]["image"] == container["image"], (
        "seed the config from the image that ships it, or the node pulls a second one"
    )


@requires_helmfile
def test_the_secret_key_survives_a_restart(rendered):
    """CKAN signs the session cookie, the CSRF token and every API token with `SECRET_KEY`.

    `start_ckan.sh` mints one when the ini has none, and the branch it guards that with reads
    the pristine `ckan.ini` in the image rather than the copy on the emptyDir, so it fires on
    every start. Without something writing a stable value afterwards, every pod restart logs
    every user out and invalidates every API token, silently (T-0436).

    The env var alone cannot do it: CKAN 2.11 has no `CKAN___<OPTION>` override, so a value in
    `[app:main]` — which is what the entrypoint just wrote — wins over anything from the
    environment. `/docker-entrypoint.d` is sourced after that branch, which is why the script
    lives there.
    """
    docs = rendered("dev")
    pod = by_name(docs, "Deployment", "ckan")["spec"]["template"]["spec"]
    container = ckan_container(docs)

    mount = next(
        (m for m in container["volumeMounts"] if m["mountPath"] == "/docker-entrypoint.d"),
        None,
    )
    assert mount, "nothing is mounted where the entrypoint sources its startup scripts"
    assert "subPath" not in mount, "the entrypoint globs the directory, so it must be a directory"

    volume = next(v for v in pod["volumes"] if v["name"] == mount["name"])
    scripts = by_name(docs, "ConfigMap", volume["configMap"]["name"])["data"]
    body = "\n".join(scripts.values())
    assert scripts, "the startup ConfigMap is empty"
    assert all(name.endswith(".sh") for name in scripts), (
        f"the entrypoint only runs .sh and .py files: {sorted(scripts)}"
    )

    for option in (
        "SECRET_KEY=",
        "WTF_CSRF_SECRET_KEY=",
        "api_token.jwt.encode.secret=string:",
        "api_token.jwt.decode.secret=string:",
    ):
        assert option in body, f"{option} is not pinned, so it stays whatever the entrypoint minted"
    # The file the entrypoint is editing, named the way the entrypoint names it, so the two
    # cannot drift apart if the copy on the emptyDir ever moves.
    assert env_of(container)["CKAN_INI"], "the pod does not say which ini CKAN reads"
    assert '"$CKAN_INI"' in body, "the script edits some file of its own rather than $CKAN_INI"
    # A pod that cannot pin the key must not serve with the per-restart one instead.
    assert "exit 1" in body


@requires_helmfile
def test_the_secret_key_is_never_a_literal_and_never_read_as_a_ckan_env_var(rendered):
    """The value comes from the Secret the cluster generated, under a name CKAN does not read.

    Every `CKAN_*` variable in the environment becomes a config default under its own literal
    name, so a variable called `CKAN_SECRET_KEY` would put a key named `CKAN_SECRET_KEY` in the
    config and change nothing (CC-06).
    """
    docs = rendered("dev")
    container = ckan_container(docs)
    pinned = [e for e in container["env"] if "JC_CKAN_SECRET_KEY" == e["name"]]
    assert pinned, "the pod carries no secret key to pin"
    assert "value" not in pinned[0], "the secret key is a literal in the pod"
    assert pinned[0]["valueFrom"]["secretKeyRef"]["name"] == "ckan-session"

    # Nothing prints it. A pod log is read by more people than a Secret is.
    scripts = by_name(docs, "ConfigMap", "ckan-startup")["data"]
    for name, body in scripts.items():
        for line in body.splitlines():
            printing = line.lstrip().startswith(("echo", "printf", "set -x"))
            expanded = "$JC_CKAN_SECRET_KEY" in line or "${JC_CKAN_SECRET_KEY}" in line
            assert not (printing and expanded), (
                f"{name} prints the secret key: {line.strip()}"
            )


@requires_helmfile
def test_the_session_cookies_are_secure_on_an_https_catalogue(rendered):
    """The image's ini ships `SESSION_COOKIE_SECURE = false` and `REMEMBER_COOKIE_SECURE =
    false`, so dev's `ckan` cookie went out without `Secure` (T-3017). The startup ConfigMap
    carries the script that marks both, and dev's site URL is the https one it acts on."""
    docs = rendered("dev")
    assert env_of(ckan_container(docs))["CKAN_SITE_URL"].startswith("https://")
    scripts = by_name(docs, "ConfigMap", "ckan-startup")["data"]
    assert "02-secure-cookies.sh" in scripts, sorted(scripts)
    script = scripts["02-secure-cookies.sh"]
    for option in ("SESSION_COOKIE_SECURE=true", "REMEMBER_COOKIE_SECURE=true"):
        assert option in script
    # Sourced, not executed: an `exit 0` would stop the entrypoint before uWSGI.
    assert "exit 0" not in script


@pytest.mark.parametrize(
    ("site_url", "written"),
    [
        ("https://data.dev.joinedcontext.com", ["SESSION_COOKIE_SECURE=true", "REMEMBER_COOKIE_SECURE=true"]),
        ("http://data.localhost", None),
        ("", None),
    ],
)
def test_the_cookie_script_marks_secure_only_behind_https(tmp_path, site_url, written):
    """Sourced the way `start_ckan.sh` sources it, against a `ckan` that records its arguments:
    an https catalogue writes both options into $CKAN_INI; a plain-http one keeps the image's
    default, where a `Secure` cookie would never come back and nobody could sign in."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    fake = bin_dir / "ckan"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {calls}\n')
    fake.chmod(0o755)
    script = CHART / "files/startup/02-secure-cookies.sh"
    result = subprocess.run(
        ["sh", "-c", f'. "{script}"; echo sourced-to-the-end'],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CKAN_INI": "/tmp/ckan.ini", "CKAN_SITE_URL": site_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "sourced-to-the-end" in result.stdout, "the script ended the entrypoint"
    if written is None:
        assert not calls.exists(), calls.read_text()
    else:
        assert calls.read_text().split() == ["config-tool", "/tmp/ckan.ini", *written]


def test_the_cookie_script_stops_the_pod_when_the_ini_cannot_be_written(tmp_path):
    """A catalogue that could not mark its cookies must not serve with the insecure ones."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "ckan"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    script = CHART / "files/startup/02-secure-cookies.sh"
    result = subprocess.run(
        ["sh", "-c", f'. "{script}"; echo served'],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CKAN_INI": "/tmp/ckan.ini", "CKAN_SITE_URL": "https://data.example"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "served" not in result.stdout
    assert "could not mark the session cookies Secure" in result.stderr


@requires_helmfile
def test_the_api_token_job_writes_one_secret_and_reaches_two_things(rendered):
    """T-0493: the token is minted at run time, so a Job writes it; its Role names the one Secret
    it may read and replace, its image is the catalogue's pinned one, and its egress is the
    catalogue and the API server (EP-62, SEC-GAP-03)."""
    docs = rendered("dev")
    job = by_name(docs, "Job", "ckan-api-token")
    assert job["metadata"]["annotations"]["helm.sh/hook"] == "post-install,post-upgrade"
    pod = job["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert "@sha256:" in container["image"]
    assert container["image"] == ckan_container(docs)["image"]
    env = {e["name"]: e for e in container["env"]}
    assert env["TOKEN_SECRET"]["value"] == "ckan-api-token"
    assert "value" not in env["ADMIN_PASSWORD"], "the administrator password is a literal"
    assert env["CATALOGUE"]["value"].startswith("ckan.")
    assert "def main():" in container["args"][0]

    role = by_name(docs, "Role", "ckan-api-token")
    named = [r for r in role["rules"] if r.get("resourceNames")]
    assert named == [{"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["ckan-api-token"],
                      "verbs": ["get", "update"]}]
    unnamed = [r for r in role["rules"] if not r.get("resourceNames")]
    assert [r["verbs"] for r in unnamed] == [["create"]], "the Job may do more than create its Secret"

    policy = by_name(docs, "NetworkPolicy", "ckan-api-token")["spec"]
    assert "ingress" not in policy or policy["ingress"] == []
    ports = sorted(p["port"] for rule in policy["egress"] for p in rule["ports"])
    assert ports == [53, 53, 443, 5000, 6443]


# --- Keycloak login (T-0403, OPS-26) -------------------------------------------------------

SSO_ISSUER = "https://idm.example.test/realms/helsinki"


def with_sso(**overrides):
    """The chart's CKAN block with the login on, and the images a standalone render needs."""
    ckan = dict(CHART_BASE_VALUES["ckan"])
    ckan["sso"] = {
        "enabled": True,
        "clientId": "ckan",
        "issuer": SSO_ISSUER,
        "scope": "openid email profile",
    } | overrides
    return {"ckan": ckan, "siteUrl": "https://data.example.test"}


@requires_helm
def test_the_catalogue_carries_no_login_configuration_while_sso_is_off(tmp_path):
    """The stock image has no OIDC authenticator, and CKAN exits on a plugin it cannot import.
    So with the flag off nothing of the login may be rendered — not the plugin, not the
    endpoints, not the client."""
    docs = render_chart(tmp_path / "off", {})
    env = env_of(ckan_container(docs))
    assert [name for name in env if "OIDC" in name] == []
    assert "oidc_pkce" not in env["CKAN__PLUGINS"]


@requires_helm
def test_the_login_names_the_plugin_and_the_realm_when_sso_is_on(tmp_path):
    """One flag has to carry the whole thing: a plugin CKAN loads, a host the extension calls,
    and the realm path the ini gets its four endpoints from."""
    docs = render_chart(tmp_path / "on", with_sso())
    env = env_of(ckan_container(docs))
    assert env["CKAN__PLUGINS"].split()[-1] == "oidc_pkce"
    # The extension reads these two from the environment itself; the host is what it prefixes
    # every endpoint with, so the realm path must not be part of it.
    assert env["CKANEXT_OIDC_PKCE_BASE_URL"] == "https://idm.example.test"
    assert env["CKANEXT_OIDC_PKCE_CLIENT_ID"] == "ckan"
    # Declared required by the extension, so CKAN 2.11 exits without them as config options,
    # which ckanext-envvars builds from the double-underscore names (dev, 2026-09-25).
    assert env["CKANEXT__OIDC_PKCE__BASE_URL"] == env["CKANEXT_OIDC_PKCE_BASE_URL"]
    assert env["CKANEXT__OIDC_PKCE__CLIENT_ID"] == "ckan"
    assert "CKANEXT__OIDC_PKCE__CLIENT_SECRET" not in env
    assert env["JC_OIDC_REALM_PATH"] == "/realms/helsinki"


@requires_helm
def test_the_client_secret_only_ever_arrives_by_reference(tmp_path):
    """The client is confidential (CC-05). A secret that is a value in the Deployment is a
    secret in the render, in the golden file and in `kubectl get deploy -o yaml`."""
    docs = render_chart(tmp_path / "secret", with_sso())
    secret_env = [
        e for e in ckan_container(docs)["env"]
        if e["name"] == "CKANEXT_OIDC_PKCE_CLIENT_SECRET"
    ]
    assert len(secret_env) == 1, "the extension gets no client secret"
    assert "value" not in secret_env[0]
    ref = secret_env[0]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "keycloak-client-ckan", "key": "client-secret"}


@requires_helm
def test_the_realm_endpoints_are_written_into_the_ini_and_not_left_at_okta_defaults(tmp_path):
    """`ckanext-oidc-pkce` reads its paths through `tk.config`, and ships Okta's. Against
    Keycloak an unpatched path is a 404 at the first click on Log in, so the startup script
    writes all four and the pod carries what it needs to build them."""
    docs = render_chart(tmp_path / "ini", with_sso())
    script = by_name(docs, "ConfigMap", "ckan-startup")["data"]["01-oidc.sh"]
    for option in ("auth_path", "token_path", "userinfo_path", "logout_path"):
        assert f"ckanext.oidc_pkce.{option}=" in script
    assert "protocol/openid-connect/auth" in script
    # T-2888: the callback redirects to `ckan.route_after_login` (the extension's name, not
    # 2.11's `ckan.auth.…`); left unset it lands on `activity.dashboard`, a 500 without the
    # activity plugin, so a sign-in that worked ended on an error page.
    assert "ckan.route_after_login=dashboard.datasets" in script
    # Sourced, not executed: an `exit` on the nothing-to-do path would stop the entrypoint
    # before uWSGI and the pod would come up "Completed" with no CKAN in it.
    assert "exit 0" not in script


@requires_helmfile
def test_the_plugin_list_and_the_image_cannot_disagree(rendered):
    """Both halves come from one flag on purpose. A render that names the plugin while the
    image is the stock one is a CKAN that does not start at all, and that is decidable here
    rather than in a CrashLoopBackOff."""
    container = ckan_container(rendered("dev"))
    if "oidc_pkce" in env_of(container)["CKAN__PLUGINS"]:
        assert "joinedcontext-ckan" in container["image"], (
            f"the login is on against {container['image']}, which carries no OIDC authenticator"
        )


@requires_helmfile
def test_the_realm_egress_is_the_login_s_and_closes_with_it(rendered, rendered_variant):
    """The catalogue dials nothing else on the internet. The login needs the realm's public host
    — the `iss` claim carries it, so the in-cluster Service is no substitute — and that is the
    entire hole: 443, 8443 for the DNAT a request to the cluster's own public address takes, and
    no third port. The flag opens the hole and closes it; dev runs with it on (T-0403)."""
    on = rendered("dev")
    policy = by_name(on, "NetworkPolicy", "ckan-sso")
    assert policy["spec"]["policyTypes"] == ["Egress"]
    assert policy["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == "ckan"
    assert [(p["protocol"], p["port"]) for rule in policy["spec"]["egress"] for p in rule["ports"]] == [
        ("TCP", 443), ("TCP", 8443),
    ]
    container = ckan_container(on)
    assert "oidc_pkce" in env_of(container)["CKAN__PLUGINS"]
    assert container["image"].startswith("ghcr.io/marek-mraz-jc/joinedcontext-ckan:2.11.6@sha256:")

    # With the login off, nothing of it is rendered either: no policy, no plugin.
    off = rendered_variant("dev", lambda tree: set_global(tree, "ckan.sso", False))
    assert [d for d in off if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "ckan-sso"] == []
    assert "oidc_pkce" not in env_of(ckan_container(off))["CKAN__PLUGINS"]
