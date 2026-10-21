"""The catalogue harvest (T-4151): `charts/ckan/files/harvest-nkod.py` against a fake NKOD, fake
publisher files and a fake CKAN that keep what the real ones decide: `package_update` replaces the resource list,
`package_delete` only marks, and the DataStore is gone (T-5060): the fake refuses every `datastore_*`
action, so a run that copies a row into CKAN fails. The SPARQL rows
and files are shaped like the city's own, fetched on 2026-10-15 (docs
Research/banska-bystrica-open-data-sources.md §6 to §8), and cut to a few rows. Nothing here needs
a cluster or the network.
"""

import importlib.util
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "charts/ckan/files/harvest-nkod.py"
STANDARDS = SCRIPT.with_name("od-standards.py")
EU = "http://publications.europa.eu/resource/authority/"
BY, BYSA = EU + "licence/CC_BY_4_0", EU + "licence/CC_BYSA_4_0"
EGOV = "https://egov.banskabystrica.sk/Default.aspx?NavigationState="
DTM = "https://dtm-banskabystrica.tmapserver.sk/opendata/"
TOKEN = "harvest-test-token"

CONFIG = {
    "source": "nkod-banskabystrica",
    "sparql": "https://data.slovensko.sk/api/sparql",
    "publisher": "https://data.gov.sk/id/legal-subject/00313271",
    "publisherName": "Mesto Banská Bystrica",
    "organization": "banskabystrica",
    "namePrefix": "bb-",
    "allowedHosts": ["egov.banskabystrica.sk", "dtm-banskabystrica.tmapserver.sk", "www.banskabystrica.sk"],
    "rewriteHosts": {"banskabystrica.sk": "www.banskabystrica.sk"},
    "skip": {
        "Ulice": {"state": "mislinked", "reason": "not ingested, link points to Počet občanov podľa dňa narodenia"},
        "Evidencia psov": {"state": "personal", "reason": "not ingested, locates each dog owner"},
    },
}

AGES = [{"Vek": "0", "Počet_občanov_v_danom_veku": "612 ", "Počet_mužov": "301", "Počet_žien": "311"},
        {"Vek": "1", "Počet_občanov_v_danom_veku": "640", "Počet_mužov": "330", "Počet_žien": "310"}]
ORDERS = [{"Číslo_objednávky": "1/2025", "Dodávateľ": "Firma s.r.o.", "IČO": "00313271   "},
          {"Číslo_objednávky": "2/2025", "Dodávateľ": "Ján Novák", "IČO": "   "},
          {"Číslo_objednávky": "3/2025", "Dodávateľ": "Iná a.s.", "IČO": "35677708"}]

# url -> (status, content type, body); a tuple of a redirect target instead redirects.
WEB = {
    EGOV + "920:0::plac1140:_144053_5_8": (200, "application/json", json.dumps(AGES).encode("utf-8-sig")),
    EGOV + "1:orders": (200, "application/json", json.dumps(ORDERS).encode()),
    EGOV + "1100:0:": (200, "text/html; charset=utf-8", b"<!DOCTYPE html><html></html>"),
    "https://egov.banskabystrica.sk/XSD/07.pdf": (200, "application/pdf", b"%PDF-1.4"),
    DTM + "OE_02_register_ulic.zip": (200, "application/zip", b""),
    DTM + "OE_4_DTM_BB_3.0_polohopis_a_v%C3%BD%C5%A1kopis_bodov%C3%A9ho_po%C4%BEa.zip": (200, "application/zip", b""),
    "https://www.banskabystrica.sk/wp-json/wp/v2/events": (200, "application/json", json.dumps([{"id": 1, "title": {"rendered": "Jarmok"}}]).encode()),
    DTM + "gone.zip": (404, "", b""),
}


def dataset(uid, title, *dists, keyword="obcania", modified="2023-11-30T08:26:58Z"):
    """The SPARQL rows NKOD answers for one dataset: one row per distribution, each with its terms."""
    base = {"ds": f"https://data.gov.sk/set/{uid}", "title": title, "description": title,
            "modified": modified, "landing": f"https://data.gov.sk/dataset/{uid}-slug", "keyword": keyword}
    rows = []
    for n, (url, fmt, licence) in enumerate(dists):
        row = dict(base, dist=f"{base['ds']}/resource/{n}", distTitle=title, url=url, format=EU + "file-type/" + fmt)
        if licence:
            row |= {"work": licence, "database": licence, "special": licence}
        rows.append(row)
    return rows or [base]


CATALOGUE = (
    dataset("veku", "Počet občanov podľa veku", (EGOV + "920:0::plac1140:_144053_5_8", "JSON", BY))
    + dataset("ulice", "Ulice", (EGOV + "945:0::plac2174:_144154_5_8", "JSON", BY))
    + dataset("psy", "Evidencia psov", (EGOV + "803:0::plac2114:_272000_5_8", "JSON", BY))
    + dataset("faktury", "Faktúry BB", (EGOV + "1100:0:", "JSON", BY))
    + dataset("pocty", "Počty občanov v jednotlivých rokoch", ("https://egov.banskabystrica.sk/XSD/07.pdf", "JSON", BY))
    + dataset("objednavky", "Objednávky BB", (EGOV + "1:orders", "JSON", BY))
    # The same file twice under one dataset, and a non-ASCII file name.
    + dataset("ulic", "DTM_BB-register-ulic", (DTM + "OE_02_register_ulic.zip", "ZIP", BYSA),
              (DTM + "OE_02_register_ulic.zip", "ZIP", BYSA))
    + dataset("polohopis", "DTM_BB-Polohopis", (DTM + "OE_4_DTM_BB_3.0_polohopis_a_výškopis_bodového_poľa.zip", "ZIP", BYSA))
    # The bare host NKOD records, which the configuration moves to www.
    + dataset("podujatia", "Podujatia", ("https://banskabystrica.sk/wp-json/wp/v2/events", "JSON", BY))
    + dataset("bezlicencie", "Bez licencie", (DTM + "OE_02_register_ulic.zip", "ZIP", None))
    + dataset("mrtvy", "Mŕtvy odkaz", (DTM + "gone.zip", "ZIP", BY))
)


class FakeCkan:
    def __init__(self):
        self.packages, self.organizations, self.calls = {}, set(), []
        self.next_id = 0

    def new_id(self):
        self.next_id += 1
        return f"id-{self.next_id}"

    def __call__(self, action, payload):
        self.calls.append(action)
        assert not action.startswith(("datastore", "resource_view")), f"{action}: CKAN holds no rows (T-5060)"
        return getattr(self, action)(payload)

    def organization_show(self, p):
        return {"name": p["id"]} if p["id"] in self.organizations else None

    def organization_create(self, p):
        self.organizations.add(p["name"])
        return {"name": p["name"]}

    def package_show(self, p):
        return next((v for v in self.packages.values() if p["id"] in (v["id"], v["name"])), None)

    def _resources(self, package_id, resources):
        return [dict(r, id=r.get("id") or self.new_id(), package_id=package_id) for r in resources]

    def package_create(self, p):
        assert p["name"] not in self.packages
        package = dict(p, id=self.new_id(), state="active")
        package["resources"] = self._resources(package["id"], p.get("resources", []))
        self.packages[p["name"]] = package
        return package

    def package_update(self, p):
        package = dict(p, resources=self._resources(p["id"], p["resources"]))
        self.packages[p["name"]] = package
        return package

    def package_delete(self, p):
        self.packages[p["id"]]["state"] = "deleted"

    def package_search(self, p):
        assert 'extras_harvest_source:"nkod-banskabystrica"' in p["fq"]
        names = [v["name"] for v in self.packages.values() if v["state"] == "active" and any(
            e == {"key": "harvest_source", "value": "nkod-banskabystrica"} for e in v.get("extras", []))]
        return {"count": len(names), "results": [{"name": n} for n in names][p["start"]:p["start"] + p["rows"]]}


class Response(io.BytesIO):
    def __init__(self, status, kind, body):
        super().__init__(body)
        self.status, self.headers = status, {"Content-Type": kind}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeWeb:
    def __init__(self, harvest):
        self.harvest, self.requests = harvest, []

    def open(self, request, timeout):
        url = request.full_url
        self.requests.append((request.get_method(), url))
        target = WEB.get(url)
        if target is None:
            raise urllib.error.URLError("no route to host")
        if isinstance(target[0], str):  # a redirect: what the handler checks before following
            self.harvest.allowed(target[0])
            return self.open(type(request)(target[0], method=request.get_method()), timeout)
        status, kind, body = target
        if status != 200:
            raise urllib.error.HTTPError(url, status, "status", {}, io.BytesIO())
        return Response(status, kind, body)


ARTEFACTS = ["context.jsonld", "model.linkml.yaml", "model.md", "model.owl.ttl", "model.rdf.ttl",
             "model.schema.json", "model.shacl.ttl"]


class EveryName(dict):
    """A mapping that converts every dataset, so a run lists them (EP-118); a test that needs one
    unconverted removes it with `unconverted`."""

    def __init__(self):
        super().__init__()
        self.unconverted = set()

    def get(self, name, default=None):
        if name in self.unconverted:
            return default
        return {"endpoint": "ep", "type": "T", "location": False,
                "dataset": f"https://opendata.dev.joinedcontext.com/dataset/{name}"}


def model_index(endpoint):
    return [{"version": 1, "types": ["T", "KeyPerformanceIndicator"],
             "artifacts": {f: {"bytes": 10, "sha256": f"sha-{f}", "type": "text/plain"} for f in ARTEFACTS}}]


def load(monkeypatch, catalogue=CATALOGUE, config=CONFIG, mapped=True):
    monkeypatch.setenv("CATALOGUE", "ckan.ckan.svc.cluster.local")
    monkeypatch.setenv("CKAN_API_TOKEN", TOKEN)
    monkeypatch.setenv("HARVEST_CONFIG", json.dumps(config))
    # What the CronJob runs: od-standards.py, then the script (templates/harvest.yaml).
    spec = importlib.util.spec_from_file_location("harvest_nkod", SCRIPT)
    harvest = importlib.util.module_from_spec(spec)
    exec(compile(STANDARDS.read_text() + "\n" + SCRIPT.read_text(), spec.origin, "exec"), harvest.__dict__)
    harvest.ckan = FakeCkan()
    harvest.OPENER = FakeWeb(harvest)
    harvest.sparql = lambda query: [{k: {"value": v} for k, v in row.items()} for row in catalogue]
    harvest.od_models = model_index
    if mapped:
        # Every dataset's rows are converted unless the test says otherwise (T-4324).
        harvest.OD_DATASETS = EveryName()
        harvest.OD_GATEWAY = "https://api.dev.joinedcontext.com"
    return harvest


def states(out):
    return {line.split(":")[0]: int(line.split(": ")[1]) for line in out.splitlines()
            if line and not line.startswith(" ") and line.split(":")[0].isalpha()}


def test_a_run_ingests_what_the_files_hold_and_lists_every_skip_with_its_reason(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    out = capsys.readouterr().out
    assert states(out) == {"ingested": 5, "mislinked": 1, "personal": 1, "html": 1, "pdf": 1,
                           "licence": 1, "dead": 1}
    assert "  - Ulice: not ingested, link points to Počet občanov podľa dňa narodenia" in out
    assert "  - Faktúry BB: declared JSON, https://egov.banskabystrica.sk/Default.aspx?NavigationState=1100:0: serves an HTML page" in out
    assert "  - Bez licencie: no open licence in legislation:termsOfUse" in out
    assert "  - Mŕtvy odkaz: https://dtm-banskabystrica.tmapserver.sk/opendata/gone.zip answered 404" in out

    fake = harvest.ckan
    assert fake.organizations == {"banskabystrica"}
    assert set(fake.packages) == {"bb-pocet-obcanov-podla-veku", "bb-objednavky-bb", "bb-dtm-bb-register-ulic", "bb-dtm-bb-polohopis",
                                  "bb-podujatia"}
    ages = fake.packages["bb-pocet-obcanov-podla-veku"]
    assert ages["license_id"] == "cc-by" and ages["owner_org"] == "banskabystrica"
    extras = {e["key"]: e["value"] for e in ages["extras"]}
    assert extras["modified"] == "2023-11-30T08:26:58Z"
    assert extras["publisher_name"] == "Mesto Banská Bystrica"
    assert extras["source_uri"] == "https://data.gov.sk/set/veku"
    # T-4765: the Endpoint under the key jcctl's publisher writes, its trailing slash included.
    assert extras["endpoint"] == "https://api.dev.joinedcontext.com/api/endpoint/ep/"
    # EP-118: the platform's distributions and data model, no source link and no copy of the rows.
    assert [r["format"] for r in ages["resources"]] == [
        "NGSI-LD", "CSV", "OData", "MCP", "WebSocket",
        "JSON Schema", "JSON-LD", "LinkML", "Markdown", "OWL", "RDF", "SHACL"]
    assert not any(r["url"].startswith(EGOV) for r in ages["resources"])
    # T-5060: no DataStore action was ever called and no resource is a table.
    assert not [c for c in fake.calls if c.startswith("datastore")]
    assert not any(r.get("url_type") == "datastore" for p in fake.packages.values() for r in p["resources"])

    # The licence of the map data is the stricter one, and no ZIP is listed (EP-118).
    streets = fake.packages["bb-dtm-bb-register-ulic"]
    assert streets["license_id"] == "cc-by-sa"
    assert not any("ZIP" in (r.get("format") or "") or r["url"].endswith(".zip")
                   for p in fake.packages.values() for r in p["resources"])
    # The non-ASCII file name is fetched percent-encoded, and the bare host is moved to www.
    requests = harvest.OPENER.requests
    assert any(url.endswith("v%C3%BD%C5%A1kopis_bodov%C3%A9ho_po%C4%BEa.zip") for _, url in requests)
    assert any(url == "https://www.banskabystrica.sk/wp-json/wp/v2/events" for _, url in requests)
    # A file is fetched at most once per run, and the ZIPs only by HEAD.
    assert len(requests) == len(set(requests))
    assert all(method == "HEAD" for method, url in requests if url.endswith(".zip"))


def test_no_row_of_a_source_is_copied_into_the_catalogue(monkeypatch, capsys):
    """§8 (T-5060): an order without an IČO can name a natural person. CKAN holds no rows at all now,
    so the person is nowhere in it; the Endpoint and its Policy are the only data surface."""
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    assert "Ján Novák" not in json.dumps(harvest.ckan.packages, ensure_ascii=False)
    assert "Firma s.r.o." not in json.dumps(harvest.ckan.packages, ensure_ascii=False)
    assert "vynechané riadky" not in harvest.ckan.packages["bb-objednavky-bb"]["notes"]
    assert not [c for c in harvest.ckan.calls if c.startswith(("datastore", "resource_view"))]


def test_a_second_run_rewrites_the_same_dataset_instead_of_adding_new_ones(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    names = set(harvest.ckan.packages)
    first = len(harvest.ckan.calls)
    grown = AGES + [{"Vek": "2", "Počet_občanov_v_danom_veku": "1", "Počet_mužov": "1", "Počet_žien": "0"}]
    monkeypatch.setitem(WEB, EGOV + "920:0::plac1140:_144053_5_8", (200, "application/json", json.dumps(grown).encode()))
    assert harvest.main() == 0
    assert set(harvest.ckan.packages) == names, "a rerun added or lost a dataset"
    assert "package_create" not in harvest.ckan.calls[first:]
    ages = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [r.get("url_type") for r in ages] == [None] * 12


def test_a_run_over_an_unchanged_source_writes_nothing(monkeypatch, capsys):
    # T-4644: metadata_modified is "Aktualizované"; a run that changed nothing must not move it.
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    first = len(harvest.ckan.calls)
    assert harvest.main() == 0
    writes = [c for c in harvest.ckan.calls[first:] if not c.endswith(("_show", "_search", "_list"))]
    assert writes == [], writes


def test_a_changed_source_updates_in_place_and_keeps_the_dataset_and_its_issued(monkeypatch, capsys):
    """T-5060: CKAN holds no rows, so a changed file alone writes nothing; a newer `modified` in the
    catalogue updates the dataset in place."""
    rows = [dict(r, issued="2019-04-02T10:00:00Z") for r in CATALOGUE]
    harvest = load(monkeypatch, catalogue=rows)
    assert harvest.main() == 0
    fake = harvest.ckan
    identity, first = fake.packages["bb-pocet-obcanov-podla-veku"]["id"], len(fake.calls)
    grown = AGES + [{"Vek": "2", "Počet_občanov_v_danom_veku": "1", "Počet_mužov": "1", "Počet_žien": "0"}]
    monkeypatch.setitem(WEB, EGOV + "920:0::plac1140:_144053_5_8", (200, "application/json", json.dumps(grown).encode()))
    assert harvest.main() == 0
    assert not [c for c in fake.calls[first:] if c in ("package_create", "package_update", "package_delete")]
    newer = [dict(r, modified="2026-10-20T08:00:00Z") if r["title"] == "Počet občanov podľa veku" else r for r in rows]
    harvest = load(monkeypatch, catalogue=newer)
    harvest.ckan = fake
    first = len(fake.calls)
    assert harvest.main() == 0
    calls = fake.calls[first:]
    assert "package_create" not in calls and "package_delete" not in calls and calls.count("package_update") == 1
    ages = fake.packages["bb-pocet-obcanov-podla-veku"]
    assert ages["id"] == identity
    assert {"key": "issued", "value": "2019-04-02T10:00:00Z"} in ages["extras"]
    assert {"key": "modified", "value": "2026-10-20T08:00:00Z"} in ages["extras"]


def test_a_withdrawn_dataset_that_returns_is_updated_never_created_again(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["state"] = "deleted"
    first = len(harvest.ckan.calls)
    assert harvest.main() == 0
    assert "package_create" not in harvest.ckan.calls[first:]
    assert harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["state"] == "active"


def test_a_dataset_the_publisher_no_longer_lists_is_withdrawn(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    fake = harvest.ckan
    harvest = load(monkeypatch, catalogue=[r for r in CATALOGUE if r["title"] != "DTM_BB-register-ulic"])
    harvest.ckan = fake
    assert harvest.main() == 0
    assert fake.packages["bb-dtm-bb-register-ulic"]["state"] == "deleted"
    assert fake.packages["bb-pocet-obcanov-podla-veku"]["state"] == "active"
    assert "  - bb-dtm-bb-register-ulic: no longer ingested from the catalogue" in capsys.readouterr().out


def test_an_empty_catalogue_answer_deletes_nothing(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    fake = harvest.ckan
    harvest = load(monkeypatch, catalogue=[])
    harvest.ckan = fake
    assert harvest.main() == 1
    assert "package_delete" not in fake.calls
    assert "nothing is deleted on an empty answer" in capsys.readouterr().err


def test_a_source_off_the_allowlist_or_on_plain_http_is_never_fetched(monkeypatch, capsys):
    harvest = load(monkeypatch)
    with pytest.raises(harvest.Refused):
        harvest.allowed("http://egov.banskabystrica.sk/x")
    with pytest.raises(harvest.Refused):
        harvest.allowed("https://ckan.ckan.svc.cluster.local:5000/api/3/action/user_list")
    # A redirect off the allowlist is refused before it is followed.
    monkeypatch.setitem(WEB, EGOV + "1:orders", ("https://169.254.169.254/latest/meta-data/",))
    catalogue = (dataset("objednavky", "Objednávky BB", (EGOV + "1:orders", "JSON", BY))
                 + dataset("elsewhere", "Inde", ("https://example.org/data.json", "JSON", BY)))
    harvest = load(monkeypatch, catalogue=catalogue)
    assert harvest.main() == 0
    out = capsys.readouterr().out
    assert states(out) == {"refused": 2}
    assert not any("169.254" in url or "example.org" in url for _, url in harvest.OPENER.requests)
    assert harvest.ckan.packages == {}


def test_the_token_is_never_printed(monkeypatch, capsys):
    harvest = load(monkeypatch)
    harvest.main()
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


def test_two_titles_that_fold_to_one_name_keep_apart(monkeypatch, capsys):
    catalogue = (dataset("aaaaaaaa-1", "Školy", (DTM + "OE_02_register_ulic.zip", "ZIP", BY))
                 + dataset("bbbbbbbb-2", "Skoly", (DTM + "OE_02_register_ulic.zip", "ZIP", BY)))
    harvest = load(monkeypatch, catalogue=catalogue)
    assert harvest.main() == 0
    assert set(harvest.ckan.packages) == {"bb-skoly-aaaaaaaa", "bb-skoly-bbbbbbbb"}


def test_only_a_converted_dataset_is_listed_with_its_apis_and_model(monkeypatch, capsys):
    """T-4279, EP-118 (T-4324): the mapping names the age table only. Its page lists the NGSI-LD
    API and the files filtered to its rows, OData, MCP and the WebSocket for the type, then the data
    model in seven formalisms; no DataStore table (T-5060), no GeoJSON or OGC, the rows have no
    location. Every dataset nobody mapped is not listed, and named so."""
    monkeypatch.setenv("OD_GATEWAY", "https://api.dev.joinedcontext.com/")
    monkeypatch.setenv("OD_DATASETS", json.dumps({"bb-pocet-obcanov-podla-veku": {
        "endpoint": "abc", "type": "KeyPerformanceIndicator", "location": False,
        "dataset": "https://opendata.dev.joinedcontext.com/dataset/bb-pocet-obcanov-podla-veku"}}))
    harvest = load(monkeypatch, mapped=False)
    assert harvest.main() == 0
    out = capsys.readouterr().out
    assert set(harvest.ckan.packages) == {"bb-pocet-obcanov-podla-veku"}
    assert "  - Objednávky BB: not converted to NGSI-LD, so not listed (EP-118)" in out
    ages = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [r["format"] for r in ages] == [
        "NGSI-LD", "CSV", "OData", "MCP", "WebSocket",
        "JSON Schema", "JSON-LD", "LinkML", "Markdown", "OWL", "RDF", "SHACL"]
    assert ages[-1]["format"] == "SHACL" and not any(r.get("url_type") == "datastore" for r in ages)
    assert ages[0]["url"] == ("https://api.dev.joinedcontext.com/api/endpoint/abc/ngsi-ld/v1/entities?type=KeyPerformanceIndicator"
                              "&q=isPartOf%3D%3D%22https%3A%2F%2Fopendata.dev.joinedcontext.com%2Fdataset%2Fbb-pocet-obcanov-podla-veku%22")
    assert ages[0]["conforms_to"].startswith("https://www.etsi.org/")
    assert ages[5]["url"] == "https://api.dev.joinedcontext.com/api/endpoint/abc/schema/v1/model.schema.json"
    assert not any("geojson" in r["url"] or "/ogc/" in r["url"] for r in ages)
    # A second run writes the same list again, nothing doubled.
    harvest.main()
    again = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [(r["name"], r["url"]) for r in again] == [(r["name"], r["url"]) for r in ages]


def test_a_dataset_unmapped_after_a_run_is_withdrawn_and_none_mapped_withdraws_nothing(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    harvest.OD_DATASETS.unconverted.add("bb-objednavky-bb")
    assert harvest.main() == 0
    assert harvest.ckan.packages["bb-objednavky-bb"]["state"] == "deleted"
    assert harvest.ckan.packages["bb-podujatia"]["state"] == "active"
    # Withdrawn means CKAN's state=deleted, never a purge: once the dataset converts again (an
    # extended Smart Data Model, owner 11:40Z), the next run restores the same dataset by its id.
    withdrawn_id = harvest.ckan.packages["bb-objednavky-bb"]["id"]
    harvest.OD_DATASETS.unconverted.discard("bb-objednavky-bb")
    assert harvest.main() == 0
    assert harvest.ckan.packages["bb-objednavky-bb"]["state"] == "active"
    assert harvest.ckan.packages["bb-objednavky-bb"]["id"] == withdrawn_id
    for script in ("harvest-nkod.py", "harvest-hub.py"):
        assert "dataset_purge" not in (SCRIPT.parent / script).read_text(), script
    harvest.OD_GATEWAY = ""
    assert harvest.main() == 1
    assert "nothing is withdrawn" in capsys.readouterr().err
    assert harvest.ckan.packages["bb-podujatia"]["state"] == "active"


def test_a_refused_connection_to_the_catalogue_is_tried_again_and_other_errors_are_not(monkeypatch):
    """A new pod is refused until the network-policy controller admits it (prod demo-bbsk)."""
    harvest = load(monkeypatch)
    # load() fakes the catalogue; run the script again for its real ckan(), urlopen faked below.
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), harvest.__dict__)
    sleeps, calls = [], []
    monkeypatch.setattr(harvest.time, "sleep", sleeps.append)

    def refused_twice(request, timeout):
        calls.append(request.full_url)
        if len(calls) <= 2:
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return io.BytesIO(json.dumps({"result": {"name": "bb"}}).encode())

    monkeypatch.setattr(harvest.urllib.request, "urlopen", refused_twice)
    assert harvest.ckan("organization_show", {"id": "bb"}) == {"name": "bb"}
    assert len(calls) == 3 and sleeps == [3, 3]

    def unreachable(request, timeout):
        raise urllib.error.URLError(OSError(113, "No route to host"))

    calls.clear()
    monkeypatch.setattr(harvest.urllib.request, "urlopen", unreachable)
    with pytest.raises(urllib.error.URLError):
        harvest.ckan("organization_show", {"id": "bb"})


def test_the_harvest_never_calls_a_datastore_or_a_view_action(monkeypatch, capsys):
    """T-5060: a dataset whose files hold no table, one that holds rows and one that holds personal
    data all list the same platform distributions; none gets a table, a table view or a hidden flag."""
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    fake = harvest.ckan
    assert set(fake.calls) <= {"organization_show", "organization_create", "package_show", "package_create",
                               "package_update", "package_search", "package_delete"}, set(fake.calls)
    for name, package in fake.packages.items():
        assert not any(r.get("url_type") == "datastore" for r in package["resources"]), name
    assert not hasattr(harvest, "OD_HIDDEN") and not hasattr(harvest, "od_fields") and not hasattr(harvest, "table")
