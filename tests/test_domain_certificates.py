"""Certificates per origin group (T-7002, evidence/T-6991/design.md §8, §9; T-6975 §6).

The configuration chart of components/apisix renders, for `jc.server.organizations` (T-7005's
shape: host labels under `domain`), a Certificate per host that resolves (or one per Organization
once all do) and `<org>.<domain>` for `host: auto`, all HTTP-01: no Organization gets a wildcard
(owner rule), the validation zone (global.ingress.dns01) serves the installation's Apps wildcard
alone. Each setup of §9 (1, 2, 3 and 5 records, and `auto`) is rendered with and without a
validation zone, and every render passes kubeconform; the refusals fail the render with a message
naming the value.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import load_yaml_all

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "components/apisix/charts/configuration"
DOMAIN = "city.example"
INSTALLATION = [DOMAIN, f"api.{DOMAIN}", f"idm.{DOMAIN}", f"opendata.{DOMAIN}"]
ZONE = {"validationZone": "acme.city.example", "provider": "cloudflare",
        "secretRef": {"name": "validation-zone", "key": "token"}}

# Labels under the customer's `domain: bbsk.sk`; setup 5 adds the Apps records, whose hosts get a
# certificate each by HTTP-01 (global.ingress.appHosts), none from an Organization.
HOSTS = {
    1: {"portal": "smartcity"},
    2: {"portal": "smartcity", "opendata": "opendata"},
    3: {"portal": "smartcity", "opendata": "opendata", "api": "api"},
    5: {"portal": "smartcity", "opendata": "opendata", "api": "api", "mcp": "mcp"},
}


def bbsk(hosts, **rest):
    return {"name": "bbsk", "domain": "bbsk.sk", "hosts": hosts, **rest}


def values(organizations, dns01=None, **edge):
    return {
        "domain": DOMAIN,
        "realm": "city",
        "edge": {
            "enabled": True,
            "clusterIssuer": "letsencrypt-prod",
            "ingressClass": "traefik",
            "hosts": INSTALLATION,
            "untrustedHosts": [f"embed.{DOMAIN}", f"tiles.{DOMAIN}"],
            "loginHost": f"idm.{DOMAIN}",
            "organizations": organizations,
            "dns01": dns01 or {},
            **edge,
        },
    }


def helm(tmp_path, vals) -> subprocess.CompletedProcess:
    if shutil.which("helm") is None:
        pytest.skip("helm not installed")
    file = tmp_path / "values.yaml"
    file.write_text(yaml.safe_dump(vals))
    return subprocess.run(["helm", "template", "x", str(CHART), "-n", "jc-prod", "-f", str(file)],
                          capture_output=True, text=True, check=False)


def render(tmp_path, vals) -> list[dict]:
    result = helm(tmp_path, vals)
    assert result.returncode == 0, result.stderr
    (tmp_path / "render.yaml").write_text(result.stdout)
    return [d for d in load_yaml_all(result.stdout) if isinstance(d, dict)]


def refused(tmp_path, vals) -> str:
    result = helm(tmp_path, vals)
    assert result.returncode != 0, "the render should have failed"
    return result.stderr


def certificates(docs) -> dict[str, dict]:
    return {d["metadata"]["name"]: d["spec"] for d in docs if d.get("kind") == "Certificate"}


def kubeconform(path: Path):
    if shutil.which("kubeconform") is None:
        pytest.skip("kubeconform not installed")
    tools = dict(line.split("=", 1) for line in (ROOT / "tools.env").read_text().split()
                 if "=" in line and not line.startswith("#"))
    catalog = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/"
               f"{tools['CRDS_CATALOG_COMMIT']}/{{{{.Group}}}}/{{{{.ResourceKind}}}}_{{{{.ResourceAPIVersion}}}}.json")
    result = subprocess.run(
        ["kubeconform", "-strict", "-summary", "-kubernetes-version", tools["KUBERNETES_VERSION"],
         "-schema-location", "default", "-schema-location", catalog, str(path)],
        capture_output=True, text=True, check=False, env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("dns01", [False, True], ids=["http01-only", "dns01"])
@pytest.mark.parametrize("setup", [1, 2, 3, 5])
def test_each_setup_gets_a_certificate_per_resolving_host(tmp_path, setup, dns01):
    labels = list(HOSTS[setup].values())
    docs = render(tmp_path, values([bbsk(HOSTS[setup], resolved=labels)], ZONE if dns01 else None))
    certs = certificates(docs)
    org = {n: s for n, s in certs.items() if n.startswith("jc-org-")}
    assert sorted(org) == sorted(f"jc-org-{label}-bbsk-sk" for label in labels)
    for label in labels:
        spec = org[f"jc-org-{label}-bbsk-sk"]
        assert spec["dnsNames"] == [f"{label}.bbsk.sk"]
        assert spec["issuerRef"] == {"name": "letsencrypt-prod", "kind": "ClusterIssuer"}
        assert spec["secretName"] == f"jc-org-{label}-bbsk-sk-tls"
    # Never a wildcard for an Organization, with or without a validation zone.
    assert not any("*" in n for s in org.values() for n in s["dnsNames"])
    # The installation's names never ride on an Organization's certificate, nor the reverse.
    assert certs["apisix-edge"]["dnsNames"] == INSTALLATION
    assert certs["apisix-edge-untrusted"]["dnsNames"] == [f"embed.{DOMAIN}", f"tiles.{DOMAIN}"]
    kubeconform(tmp_path / "render.yaml")


@pytest.mark.parametrize("dns01", [False, True], ids=["http01-only", "dns01"])
def test_auto_takes_one_host_under_the_domain_and_the_shared_ones_stay_the_installations(tmp_path, dns01):
    docs = render(tmp_path, values([{"name": "zilina", "host": "auto"}], ZONE if dns01 else None))
    certs = certificates(docs)
    org = {name: spec for name, spec in certs.items() if name.startswith("jc-org-")}
    assert list(org) == ["jc-org-zilina"]
    assert org["jc-org-zilina"]["dnsNames"] == [f"zilina.{DOMAIN}"]
    assert f"opendata.{DOMAIN}" in certs["apisix-edge"]["dnsNames"]
    assert f"api.{DOMAIN}" in certs["apisix-edge"]["dnsNames"]
    kubeconform(tmp_path / "render.yaml")


def test_a_host_whose_record_is_missing_blocks_only_itself(tmp_path):
    docs = render(tmp_path, values([bbsk(HOSTS[3], resolved=["smartcity"])]))
    org = [n for n in certificates(docs) if n.startswith("jc-org-")]
    assert org == ["jc-org-smartcity-bbsk-sk"]


def test_labels_under_the_installation_domain_keep_the_route_names(tmp_path):
    """jc-dev's form (T-7005): no `domain`, no `resolved`: every host, named like its edge route."""
    docs = render(tmp_path, values([{"name": "bbsk", "catalogueId": "c", "hosts": {
        "portal": "smartcity.bbsk", "opendata": "opendata.bbsk", "api": "api.bbsk", "mcp": "mcp.bbsk",
        "idm": "idm.bbsk"}}]))
    org = {n: s["dnsNames"] for n, s in certificates(docs).items() if n.startswith("jc-org-")}
    labels = ("smartcity", "opendata", "api", "mcp", "idm")
    assert org == {f"jc-org-{r}-bbsk": [f"{r}.bbsk.{DOMAIN}"] for r in labels}


def test_one_certificate_per_organization_once_every_host_resolves(tmp_path):
    labels = list(HOSTS[5].values())
    docs = render(tmp_path, values([bbsk(HOSTS[5], resolved=labels, certificate="organization")]))
    org = {n: s for n, s in certificates(docs).items() if n.startswith("jc-org-")}
    assert list(org) == ["jc-org-bbsk"]
    assert org["jc-org-bbsk"]["dnsNames"] == [f"{label}.bbsk.sk" for label in labels]


def test_dns01_issuer_reads_its_token_from_the_operators_secret_and_follows_the_cname(tmp_path):
    docs = render(tmp_path, values([bbsk(HOSTS[5], resolved=[])], ZONE))
    issuer = next(d for d in docs if d.get("kind") == "ClusterIssuer")
    assert issuer["metadata"]["name"] == "jc-dns01-jc-prod"
    solver = issuer["spec"]["acme"]["solvers"][0]["dns01"]
    assert solver["cnameStrategy"] == "Follow"
    assert solver["cloudflare"] == {"apiTokenSecretRef": {"name": "validation-zone", "key": "token"}}
    rfc = {**ZONE, "provider": "rfc2136", "rfc2136": {"nameserver": "ns.acme.example:53", "tsigKeyName": "jc"}}
    docs = render(tmp_path, values([], rfc))
    solver = next(d for d in docs if d.get("kind") == "ClusterIssuer")["spec"]["acme"]["solvers"][0]["dns01"]
    assert solver["rfc2136"]["tsigSecretSecretRef"] == {"name": "validation-zone", "key": "token"}
    assert solver["rfc2136"]["tsigAlgorithm"] == "HMACSHA256"


def test_the_installation_wildcard_moves_to_the_validation_zone_when_one_is_set(tmp_path):
    docs = render(tmp_path, values([], ZONE, appsWildcard=f"*.apps.{DOMAIN}"))
    assert certificates(docs)["apisix-apps-wildcard"]["issuerRef"] == {"name": "jc-dns01-jc-prod", "kind": "ClusterIssuer"}
    assert not [d for d in docs if d.get("kind") == "Issuer" and d["metadata"]["name"] == "letsencrypt-dns01"]
    docs = render(tmp_path, values([], None, appsWildcard=f"*.apps.{DOMAIN}"))
    assert certificates(docs)["apisix-apps-wildcard"]["issuerRef"] == {"name": "letsencrypt-dns01", "kind": "Issuer"}


@pytest.mark.parametrize("organizations, message", [
    # An Organization's host that is already the installation's (the sign-in host, a shared one).
    ([{"name": "bbsk", "hosts": {"portal": "idm"}}], "is already the installation's"),
    # `auto` named like an installation host label (T-6974's reserved labels at the edge).
    ([{"name": "api", "host": "auto"}], "is already the installation's"),
    # Two Organizations on one host.
    ([bbsk({"portal": "x"}), {**bbsk({"portal": "x"}), "name": "b"}], "is already bbsk's"),
    ([bbsk(HOSTS[2], resolved=["smartcity"], certificate="organization")], "\"opendata\" is not in resolved"),
    ([{"name": f"o{i}", "host": "auto"} for i in range(11)], "11 new Certificates in one apply"),
    # A wildcard typed as a label is no host name.
    ([bbsk({"portal": "*.apps"})], "/edge/organizations/0/hosts/portal"),
], ids=["installation-host", "auto-reserved", "twice", "organization-unresolved", "staged", "wildcard"])
def test_refusals(tmp_path, organizations, message):
    assert message in refused(tmp_path, values(organizations))


def test_issued_certificates_do_not_count_against_the_stage(tmp_path):
    orgs = [{"name": f"o{i}", "host": "auto"} for i in range(11)]
    render(tmp_path, values(orgs, issuedCertificates=["jc-org-o0"]))
    render(tmp_path, values(orgs, certificateStage=11))


@pytest.mark.parametrize("dns01, message", [
    ({**ZONE, "provider": "route53"}, "/edge/dns01/provider': value must be one of"),
    ({**ZONE, "secretRef": {"name": "", "key": ""}}, "the zone's token never sits in values"),
    ({**ZONE, "provider": "rfc2136"}, "nameserver and tsigKeyName are required"),
    # A credential typed into the values is refused by the schema, never rendered.
    ({**ZONE, "apiToken": "x"}, "additional properties"),
], ids=["provider", "no-secret", "rfc2136", "inline-token"])
def test_dns01_refusals(tmp_path, dns01, message):
    assert message in refused(tmp_path, values([], dns01))


def test_the_sign_in_host_must_be_on_the_edge(tmp_path):
    assert "jc.server.loginHost" in refused(tmp_path, values([], loginHost=f"login.{DOMAIN}"))


def test_jc_prod_orders_no_new_certificate_while_its_dns_points_elsewhere(rendered):
    """jc-prod's names still resolve to the dev node (edgeAddress): tiles. and viz. stay on
    apisix-edge, no untrusted certificate and no Organization certificate is ordered."""
    docs = rendered("jc-prod")
    certs = certificates(docs)
    domain = "smartcity.joinedcontext.com"
    assert {f"tiles.{domain}", f"viz.{domain}"} <= set(certs["apisix-edge"]["dnsNames"])
    assert "apisix-edge-untrusted" not in certs
    assert not [n for n in certs if n.startswith("jc-org-")]
    # The Ingress serves them from the Secret apisix-edge writes, never from one nobody fills.
    ingress = next(d for d in docs if d.get("kind") == "Ingress" and d["metadata"]["name"] == "apisix")
    tls = {t["secretName"]: t["hosts"] for t in ingress["spec"]["tls"]}
    assert "apisix-edge-untrusted-tls" not in tls
    assert {f"tiles.{domain}", f"viz.{domain}"} <= set(tls["apisix-edge-tls"])


def test_dev_keeps_untrusted_content_apart(rendered):
    docs = rendered("dev")
    certs = certificates(docs)
    edge, untrusted = certs["apisix-edge"]["dnsNames"], certs["apisix-edge-untrusted"]["dnsNames"]
    assert untrusted and all(h.split(".")[0] in ("embed", "tiles", "viz") for h in untrusted)
    assert not set(untrusted) & set(edge)
    ingress = next(d for d in docs if d.get("kind") == "Ingress" and d["metadata"]["name"] == "apisix")
    tls = {t["secretName"]: t["hosts"] for t in ingress["spec"]["tls"]}
    assert sorted(tls["apisix-edge-untrusted-tls"]) == sorted(untrusted)
    assert set(tls["apisix-edge-tls"]) == set(edge)


def test_jc_devs_organization_routes_name_the_secrets_their_certificates_write(rendered):
    """One shape (T-7005 + T-7002): each Organization host's Ingress TLS entry names the Secret of
    the organization-tls.yaml Certificate for that host, and no host has two Certificates: eight
    Organizations of five hosts each (T-7001 adds `idm.`; T-7009 batch 1 adds barcelona and zilina)."""
    docs = rendered("jc-dev")
    certs = {s["secretName"]: s["dnsNames"] for s in certificates(docs).values()}
    ingress = next(d for d in docs if d.get("kind") == "Ingress" and d["metadata"]["name"] == "apisix")
    org_tls = {t["secretName"]: t["hosts"] for t in ingress["spec"]["tls"] if t["secretName"].startswith("jc-org-")}
    assert len(org_tls) == 40 and all(certs[s] == h for s, h in org_tls.items()), org_tls
    names = [n for h in certs.values() for n in h]
    assert len(names) == len(set(names))
