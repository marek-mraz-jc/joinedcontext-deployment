"""The harvest of outside catalogues into CKAN (T-4152): BBSK's ArcGIS Hub into `bbsk`.

`charts/ckan/files/harvest-hub.py` runs over answers of the region's Hub recorded on 2026-10-15
(`fixtures/bbsk-hub/`, eight of its 103 items, descriptions shortened) and writes into a CKAN
that answers the action API in-process. The render cases check what the CronJob may reach.
"""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures/bbsk-hub"

spec = importlib.util.spec_from_file_location("harvest", ROOT / "charts/ckan/files/harvest-hub.py")
harvest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvest)

APS = "b5486911cb0342e48d475130d1d5e960"
OBCE, OKRESY = "40138c783eaa46cd8cd3c8e09ab67127", "04e229d8b39b415497081c63a74c94f9"
CULTURE = "2f936202febe4340a72c1b7224a664d9"
SUPPLIERS = "825cd0cb3b0f46759d14f3bb0d328b59"


def dev_source():
    values = (ROOT / "components/ckan/values/catalogue/development-values.yaml.gotmpl").read_text()
    # The file is a template only for the `{{"{{"}}source{{"}}"}}` in one comment.
    sources = yaml.safe_load(values.replace('{{"{{"}}', "{{").replace('{{"}}"}}', "}}"))["harvest"]["sources"]
    entry = next(s for s in sources if s.get("kind") == "hub")
    # What the chart puts into HARVEST_CONFIG: the entry, keyed `source` by kind and name.
    return {"source": f"hub-{entry['name']}", **{k: v for k, v in entry.items() if k != "name"}}


def items():
    return [f["properties"] for f in json.loads((FIXTURES / "items.json").read_text())["features"]]


def layers_of(item):
    return json.loads((FIXTURES / "layers.json").read_text()).get(item["id"], [])


class FakeCkan:
    """CKAN's action API, as much of it as the harvest calls: the organization, search, create,
    update and delete. Every request must carry the token."""

    def __init__(self):
        self.orgs, self.packages, self.calls = {}, {}, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                action = self.path.rsplit("/", 1)[-1]
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.headers["Authorization"] == "token-1"
                fake.calls.append(action)
                status, answer = fake.answer(action, body)
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.host = f"127.0.0.1:{self.server.server_port}"

    def answer(self, action, body):
        def ok(result):
            return 200, {"success": True, "result": result}

        if action == "organization_show":
            if body["id"] in self.orgs:
                return ok(self.orgs[body["id"]])
            return 404, {"success": False, "error": {"__type": "Not Found Error", "message": "Not found"}}
        if action == "organization_create":
            self.orgs[body["name"]] = body
            return ok(body)
        if action == "package_search":
            org = body["fq"].split(":", 1)[1]
            # CKAN's index drops a deleted dataset (`ckan.search.remove_deleted_packages`).
            found = [p for p in self.packages.values() if p["owner_org"] == org and p["state"] == "active"]
            return ok({"count": len(found), "results": found[body["start"]:body["start"] + body["rows"]]})
        if action == "package_show":
            if body["id"] in self.packages:
                return ok(self.packages[body["id"]])
            return 404, {"success": False, "error": {"__type": "Not Found Error", "message": "Not found"}}
        if action == "package_create":
            assert body["name"] not in {p["name"] for p in self.packages.values()}, "name already in use"
            assert body["id"] not in self.packages
            package = dict(body, state="active")
            self.packages[package["id"]] = package
            return ok(package)
        if action == "package_update":
            self.packages[body["id"]] = dict(body)
            return ok(body)
        if action == "package_delete":
            self.packages[body["id"]]["state"] = "deleted"
            return ok(None)
        return 400, {"success": False, "error": {"__type": "Bad request", "message": f"Action name not known: {action}"}}

    def active(self):
        return {harvest.extra(p, "source_id"): p for p in self.packages.values() if p["state"] == "active"}


@pytest.fixture
def ckan():
    fake = FakeCkan()
    yield fake
    fake.server.shutdown()


def test_the_selection_keeps_open_licences_and_names_why_each_other_item_is_out():
    kept, skipped = harvest.select(items(), dev_source())
    assert sorted(item["id"] for item, _ in kept) == sorted([OBCE, OKRESY, CULTURE, SUPPLIERS])
    reasons = {ident: reason for ident, _, reason in skipped}
    assert reasons[APS].startswith("personal data")
    assert sorted(r for r in reasons.values() if r.startswith("no open licence")) == [
        "no open licence (CC-BY-NC-4.0)", "no open licence (none)", "no open licence (none)"]
    # The okres and the obec census layer share a title at the source and are two datasets here.
    titles = {item["id"]: title for item, title in kept}
    assert titles[OBCE] == "Obyvateľstvo podľa rodinného stavu (2021), obce"
    assert titles[OKRESY] == "Obyvateľstvo podľa rodinného stavu (2021), okresy"
    assert titles[SUPPLIERS] == "Dodávatelia", "the source's trailing space survived"
    assert all("Bystrinská" not in title for _, title, _ in skipped)


def test_a_repeated_title_keeps_the_newest_copy_and_names_the_other_as_its_duplicate():
    source = dict(dev_source(), titles={})
    kept, skipped = harvest.select(items(), source)
    newer = max((i for i in items() if i["id"] in (OBCE, OKRESY)), key=lambda i: i["modified"])
    older = OKRESY if newer["id"] == OBCE else OBCE
    assert newer["id"] in [item["id"] for item, _ in kept]
    assert (older, "Obyvateľstvo podľa rodinného stavu (2021)", f"duplicate of {newer['id']}") in skipped


def test_a_dataset_carries_licence_publisher_and_one_csv_and_geojson_per_layer():
    item = next(i for i in items() if i["id"] == CULTURE)
    package = harvest.dataset(item, item["title"], layers_of(item), dev_source())
    assert package["owner_org"] == "bbsk" and package["license_id"] == "cc-by"
    extras = {e["key"]: e["value"] for e in package["extras"]}
    assert extras["publisher_name"] == "Banskobystrický samosprávny kraj"
    assert extras["publisher_uri"].endswith("/37828100")
    assert extras["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert extras["source_id"] == CULTURE and extras["modified"].endswith("Z")
    assert [r["format"] for r in package["resources"]] == ["CSV", "GeoJSON"] * 3 + ["Esri REST"]
    assert package["resources"][0]["url"] == (
        f"https://opendata.bbsk.sk/api/download/v1/items/{CULTURE}/csv?layers=7")
    assert package["resources"][0]["name"] == "Kultúrne inštitúcie CSV"
    assert "<" not in package["notes"] and "style=" not in package["notes"]
    assert len(package["name"]) <= 100 and package["name"].startswith("bbsk-kulturne-institucie")


def test_a_table_has_no_geojson_and_a_link_off_the_allowed_hosts_is_dropped():
    item = next(i for i in items() if i["id"] == SUPPLIERS)
    package = harvest.dataset(item, "Dodávatelia", layers_of(item), dev_source())
    assert [r["format"] for r in package["resources"]] == ["CSV", "Esri REST"]
    moved = dict(item, url="http://evil.example/arcgis/rest/services/x/FeatureServer")
    package = harvest.dataset(moved, "Dodávatelia", layers_of(item), dev_source())
    assert [r["format"] for r in package["resources"]] == ["CSV"]


def test_html_in_a_description_becomes_text_and_never_markup():
    text = harvest.plain_text("<p style='x'>Prvý&nbsp;odsek</p><p>Druhý <a href='https://x'>odkaz</a>"
                              "<script>alert(1)</script></p>")
    assert text == "Prvý odsek\n\nDruhý odkazalert(1)"
    assert harvest.plain_text(None) == ""


def test_the_harvest_creates_then_leaves_alone_then_withdraws_only_its_own(ckan):
    client = harvest.Ckan(ckan.host, "token-1")
    source = dev_source()
    ckan.packages["hand"] = {"id": "hand", "name": "rucny", "owner_org": "bbsk", "state": "active",
                             "extras": []}

    warmed = []
    counts, kept, _ = harvest.harvest(client, source, items(), layers_of, warmed.append)
    assert counts == {"created": 4, "updated": 0, "unchanged": 0, "withdrawn": 0}
    assert len(warmed) == 4
    assert ckan.orgs["bbsk"]["title"] == "Banskobystrický samosprávny kraj"
    assert set(ckan.active()) == {None, OBCE, OKRESY, CULTURE, SUPPLIERS}

    counts, _, _ = harvest.harvest(client, source, items(), layers_of, warmed.append)
    assert counts == {"created": 0, "updated": 0, "unchanged": 4, "withdrawn": 0}
    assert len(warmed) == 4, "an unchanged dataset's downloads were requested again"
    assert "organization_create" not in ckan.calls[ckan.calls.index("package_create") + 1:]

    renamed = [dict(i, title="Kultúrne inštitúcie") if i["id"] == CULTURE else i
               for i in items() if i["id"] != SUPPLIERS]
    name_before = ckan.active()[CULTURE]["name"]
    counts, _, _ = harvest.harvest(client, source, renamed, layers_of)
    assert counts == {"created": 0, "updated": 1, "unchanged": 2, "withdrawn": 1}
    assert ckan.active()[CULTURE]["name"] == name_before, "a retitled dataset changed its URL"
    assert SUPPLIERS not in ckan.active()
    assert ckan.packages["hand"]["state"] == "active", "a dataset the harvest did not make was withdrawn"

    counts, _, _ = harvest.harvest(client, source, items(), layers_of)
    assert counts["updated"] == 2 and SUPPLIERS in ckan.active(), "a returning dataset stayed deleted"


def test_a_source_that_fails_halfway_withdraws_nothing(ckan):
    client = harvest.Ckan(ckan.host, "token-1")
    harvest.harvest(client, dev_source(), items(), layers_of)

    def broken(item):
        if item["id"] == CULTURE:
            raise harvest.SourceError("services-eu1.arcgis.com: timed out")
        return layers_of(item)

    with pytest.raises(harvest.SourceError):
        harvest.harvest(client, dev_source(), [i for i in items() if i["id"] != SUPPLIERS], broken)
    assert SUPPLIERS in ckan.active()


def test_a_short_read_of_the_hub_is_an_error_not_an_empty_catalogue(monkeypatch):
    page = json.loads((FIXTURES / "items.json").read_text())
    monkeypatch.setattr(harvest, "fetch_json", lambda url, hosts: dict(page, numberMatched=103))
    with pytest.raises(harvest.SourceError, match="read 8 of 103"):
        harvest.hub_items(dev_source())


def test_a_next_page_off_the_hub_is_refused(monkeypatch):
    page = json.loads((FIXTURES / "items.json").read_text())
    page["links"] = [{"rel": "next", "href": "https://evil.example/items?startindex=9"}]
    monkeypatch.setattr(harvest, "fetch_json", lambda url, hosts: page)
    with pytest.raises(harvest.SourceError, match="outside the hub"):
        harvest.hub_items(dev_source())


def test_a_ckan_refusal_is_raised_with_its_reason_and_never_the_token(ckan):
    client = harvest.Ckan(ckan.host, "token-1")
    with pytest.raises(RuntimeError) as error:
        client.call("package_purge", {"id": "x"})
    assert "token-1" not in str(error.value)


def by_name(docs, kind, name):
    match = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert match, f"{kind}/{name} is not in the render"
    return match[0]


def test_the_cronjob_runs_the_catalogue_image_with_the_token_by_reference(rendered):
    docs = rendered("dev")
    job = by_name(docs, "CronJob", "ckan-harvest-bbsk")
    pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert job["spec"]["concurrencyPolicy"] == "Forbid"
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    catalogue = by_name(docs, "Deployment", "ckan")["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == catalogue["image"] and "@sha256:" in container["image"]
    env = {e["name"]: e for e in container["env"]}
    assert env["CKAN_API_TOKEN"]["valueFrom"]["secretKeyRef"] == {"name": "ckan-api-token", "key": "token"}
    config = json.loads(env["HARVEST_CONFIG"]["value"])
    assert (config["source"], config["organization"], config["kind"]) == ("hub-bbsk", "bbsk", "hub")
    assert "def warm_downloads(package):" in container["args"][0], "the hub source runs another script"
    assert "def main():" in container["args"][0]


def test_the_harvest_reaches_dns_the_catalogue_and_https_only(rendered):
    docs = rendered("dev")
    policy = by_name(docs, "NetworkPolicy", "ckan-harvest")["spec"]
    assert not policy.get("ingress")
    assert sorted(p["port"] for rule in policy["egress"] for p in rule["ports"]) == [53, 53, 443, 5000]


def test_an_empty_or_closed_hub_answer_withdraws_nothing(ckan):
    """Integrator review 2026-10-15: an outage that lists nothing must not empty `bbsk`."""
    client = harvest.Ckan(ckan.host, "token-1")
    harvest.harvest(client, dev_source(), items(), layers_of)
    before = set(ckan.active())
    closed = [dict(i, license="none") for i in items()]
    for answer in ([], closed):
        with pytest.raises(harvest.SourceError, match="nothing is withdrawn"):
            harvest.harvest(client, dev_source(), answer, layers_of)
        assert set(ckan.active()) == before
    assert "package_delete" not in ckan.calls


def test_a_service_off_the_allowed_hosts_is_skipped_and_never_fetched():
    moved = [dict(i, url="https://evil.example/arcgis/rest/services/x/FeatureServer")
             if i["id"] == CULTURE else i for i in items()]
    kept, skipped = harvest.select(moved, dev_source())
    assert CULTURE not in [item["id"] for item, _ in kept]
    assert (CULTURE, "its service is not on an allowed host") in [(i, r) for i, _, r in skipped]
    with pytest.raises(harvest.SourceError, match="not an allowed host"):
        harvest.item_layers(moved[[i["id"] for i in moved].index(CULTURE)], {"opendata.bbsk.sk"})


def test_a_fetch_is_refused_off_the_allowed_hosts_and_so_is_a_redirect_there():
    with pytest.raises(harvest.SourceError, match="not an allowed host"):
        harvest.fetch_json("https://evil.example/x.json", {"opendata.bbsk.sk"})
    with pytest.raises(harvest.SourceError, match="not an allowed host"):
        harvest.fetch_json("http://opendata.bbsk.sk/x.json", {"opendata.bbsk.sk"})
    handler = harvest._CheckedRedirects({"opendata.bbsk.sk"})
    request = harvest.urllib.request.Request("https://opendata.bbsk.sk/a")
    with pytest.raises(harvest.SourceError, match="redirect to 169.254.169.254"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://169.254.169.254/latest/")
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://opendata.bbsk.sk/b") is not None
