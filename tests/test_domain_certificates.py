"""Certificates per origin group (T-7002, evidence/T-6991/design.md §8, §9; T-6975 §6).

The configuration chart of components/apisix renders, for `jc.server.organizations`, a Certificate
per host that resolves (or one per Organization once all do), `<org>.<domain>` for `host: auto`,
and the Apps wildcard through the operator's validation zone (global.ingress.dns01). Each setup of
§9 (1, 2, 3 and 5 records, and `auto`) is rendered with and without a validation zone, and every
render passes kubeconform; the refusals fail the render with a message naming the value.
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

HOSTS = {
    1: {"portal": "smartcity.bbsk.sk"},
    2: {"portal": "smartcity.bbsk.sk", "opendata": "opendata.bbsk.sk"},
    3: {"portal": "smartcity.bbsk.sk", "opendata": "opendata.bbsk.sk", "api": "api.bbsk.sk"},
    5: {"portal": "smartcity.bbsk.sk", "opendata": "opendata.bbsk.sk", "api": "api.bbsk.sk",
        "apps": "apps.bbsk.sk"},
}


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
    hosts = HOSTS[setup]
    named = [h for k, h in hosts.items() if k != "apps"]
    docs = render(tmp_path, values(
        [{"name": "bbsk", "hosts": hosts, "resolved": named}], ZONE if dns01 else None))
    certs = certificates(docs)
    for host in named:
        spec = certs[f"jc-org-bbsk-{host.replace('.', '-')}"]
        assert spec["dnsNames"] == [host]
        assert spec["issuerRef"] == {"name": "letsencrypt-prod", "kind": "ClusterIssuer"}
        assert spec["secretName"] == f"jc-org-bbsk-{host.replace('.', '-')}-tls"
    wildcard = certs.get("jc-org-bbsk-apps")
    if setup == 5 and dns01:
        assert wildcard["dnsNames"] == ["*.apps.bbsk.sk"]
        assert wildcard["issuerRef"] == {"name": "jc-dns01-jc-prod", "kind": "ClusterIssuer"}
    else:
        # No validation zone: no wildcard, every App keeps a certificate of its own by HTTP-01.
        assert wildcard is None
    # The installation's names never ride on an Organization's certificate, nor the reverse.
    assert certs["apisix-edge"]["dnsNames"] == INSTALLATION
    assert certs["apisix-edge-untrusted"]["dnsNames"] == [f"embed.{DOMAIN}", f"tiles.{DOMAIN}"]
    kubeconform(tmp_path / "render.yaml")


@pytest.mark.parametrize("dns01", [False, True], ids=["http01-only", "dns01"])
def test_auto_takes_one_host_under_the_domain_and_the_shared_ones_stay_the_installations(tmp_path, dns01):
    docs = render(tmp_path, values([{"name": "zilina", "host": "auto"}], ZONE if dns01 else None))
    certs = certificates(docs)
    org = {name: spec for name, spec in certs.items() if name.startswith("jc-org-")}
    assert org == {"jc-org-zilina": org["jc-org-zilina"]}
    assert org["jc-org-zilina"]["dnsNames"] == [f"zilina.{DOMAIN}"]
    assert f"opendata.{DOMAIN}" in certs["apisix-edge"]["dnsNames"]
    assert f"api.{DOMAIN}" in certs["apisix-edge"]["dnsNames"]
    kubeconform(tmp_path / "render.yaml")


def test_a_host_whose_record_is_missing_blocks_only_itself(tmp_path):
    docs = render(tmp_path, values([{"name": "bbsk", "hosts": HOSTS[3], "resolved": ["smartcity.bbsk.sk"]}]))
    org = [n for n in certificates(docs) if n.startswith("jc-org-")]
    assert org == ["jc-org-bbsk-smartcity-bbsk-sk"]


def test_one_certificate_per_organization_once_every_host_resolves(tmp_path):
    named = list(HOSTS[3].values()) + ["mobility.bbsk.sk"]
    hosts = {**HOSTS[3], "portals": ["mobility.bbsk.sk"]}
    docs = render(tmp_path, values(
        [{"name": "bbsk", "hosts": hosts, "resolved": named, "certificate": "organization"}]))
    org = {n: s for n, s in certificates(docs).items() if n.startswith("jc-org-")}
    assert list(org) == ["jc-org-bbsk"]
    assert org["jc-org-bbsk"]["dnsNames"] == named


def test_dns01_issuer_reads_its_token_from_the_operators_secret_and_follows_the_cname(tmp_path):
    docs = render(tmp_path, values([{"name": "bbsk", "hosts": HOSTS[5], "resolved": []}], ZONE))
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
    ([{"name": "bbsk", "hosts": {"portal": f"idm.{DOMAIN}"}, "resolved": [f"idm.{DOMAIN}"]}],
     "is already the installation's"),
    # `auto` named like an installation host label (T-6974's reserved labels at the edge).
    ([{"name": "api", "host": "auto"}], "is already the installation's"),
    # Two Organizations on one host.
    ([{"name": "a", "hosts": {"portal": "x.bbsk.sk"}}, {"name": "b", "hosts": {"portal": "x.bbsk.sk"}}],
     "is already a's"),
    ([{"name": "bbsk", "hosts": HOSTS[2], "resolved": ["smartcity.bbsk.sk"], "certificate": "organization"}],
     "opendata.bbsk.sk\" is not in resolved"),
    ([{"name": f"o{i}", "host": "auto"} for i in range(11)], "11 new Certificates in one apply"),
], ids=["installation-host", "auto-reserved", "twice", "organization-unresolved", "staged"])
def test_refusals(tmp_path, organizations, message):
    assert message in refused(tmp_path, values(organizations))


def test_issued_certificates_do_not_count_against_the_stage(tmp_path):
    orgs = [{"name": f"o{i}", "host": "auto"} for i in range(11)]
    render(tmp_path, values(orgs, issuedCertificates=["jc-org-o0"]))


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


def test_jc_prod_signs_in_on_idm_and_keeps_untrusted_content_apart(rendered):
    docs = rendered("jc-prod")
    certs = certificates(docs)
    edge, untrusted = certs["apisix-edge"]["dnsNames"], certs["apisix-edge-untrusted"]["dnsNames"]
    domain = "smartcity.joinedcontext.com"
    assert f"idm.{domain}" in edge
    assert sorted(untrusted) == [f"tiles.{domain}", f"viz.{domain}"]
    assert not set(untrusted) & set(edge)
    ingress = next(d for d in docs if d.get("kind") == "Ingress" and d["metadata"]["name"] == "apisix")
    tls = {t["secretName"]: t["hosts"] for t in ingress["spec"]["tls"]}
    assert sorted(tls["apisix-edge-untrusted-tls"]) == sorted(untrusted)
    assert not set(untrusted) & set(tls["apisix-edge-tls"])
    assert set(tls["apisix-edge-tls"]) == set(edge)
