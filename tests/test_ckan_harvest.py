"""The catalogue harvest (T-4151): `charts/ckan/files/harvest-nkod.py` against a fake NKOD, fake
publisher files and a fake CKAN that keep what the real ones decide: a DataStore table belongs to a
resource, `package_update` replaces the resource list, `package_delete` only marks. The SPARQL rows
and files are shaped like the city's own, fetched on 2026-10-15 (docs
Research/banska-bystrica-open-data-sources.md §6 to §8), and cut to a few rows. Nothing here needs
a cluster or the network.
"""

import importlib.util
import io
import json
import urllib.error
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
    "requireColumn": {"Objednávky BB": "IČO"},
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
        self.packages, self.tables, self.organizations, self.calls = {}, {}, set(), []
        self.next_id = 0

    def new_id(self):
        self.next_id += 1
        return f"id-{self.next_id}"

    def __call__(self, action, payload):
        self.calls.append(action)
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
        live = self.package_show({"id": p["id"]})
        kept = {r["id"] for r in p["resources"] if r.get("id")}
        for r in live["resources"]:
            if r["id"] not in kept:
                self.tables.pop(r["id"], None)  # CKAN drops a table with its resource
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

    def datastore_create(self, p):
        assert p["force"] is True
        if "resource" in p:
            package = self.package_show({"id": p["resource"]["package_id"]})
            resource = dict(p["resource"], id=self.new_id(), url_type="datastore", url="https://x/dump")
            package["resources"].append(resource)
            rid = resource["id"]
        else:
            rid = p["resource_id"]
            assert rid not in self.tables, "datastore_create on a live table"
        self.tables[rid] = {"fields": p["fields"], "records": list(p["records"])}
        return {"resource_id": rid}

    def datastore_upsert(self, p):
        self.tables[p["resource_id"]]["records"] += p["records"]

    def datastore_delete(self, p):
        self.tables.pop(p["resource_id"])

    def datastore_search(self, p):
        return {"total": len(self.tables[p["resource_id"]]["records"])}


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


def load(monkeypatch, catalogue=CATALOGUE, config=CONFIG):
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
    assert [r["format"] for r in ages["resources"]] == ["JSON", "CSV"]
    table = fake.tables[ages["resources"][1]["id"]]
    # Trimmed and typed: the count is a number, and the stray space is gone.
    assert table["records"][0]["Počet_občanov_v_danom_veku"] == 612
    assert [f["type"] for f in table["fields"]] == ["int", "int", "int", "int"]

    # The ZIP listed twice is one resource; the licence of the map data is the stricter one.
    streets = fake.packages["bb-dtm-bb-register-ulic"]
    assert len(streets["resources"]) == 1 and streets["license_id"] == "cc-by-sa"
    # The non-ASCII file name is sent percent-encoded, and stored that way.
    assert fake.packages["bb-dtm-bb-polohopis"]["resources"][0]["url"].endswith("v%C3%BD%C5%A1kopis_bodov%C3%A9ho_po%C4%BEa.zip")
    # The bare host is moved to www., and a WordPress answer that is no flat table stays a link.
    events = fake.packages["bb-podujatia"]
    assert [r["url"] for r in events["resources"]] == ["https://www.banskabystrica.sk/wp-json/wp/v2/events"]
    # A file is fetched at most once per run, and the ZIPs only by HEAD.
    requests = harvest.OPENER.requests
    assert len(requests) == len(set(requests))
    assert all(method == "HEAD" for method, url in requests if url.endswith(".zip"))


def test_rows_without_an_identifier_are_not_published_in_any_resource(monkeypatch, capsys):
    """§8: an order without an IČO can name a natural person. The table drops it, the original
    file is not linked (it still holds the row), and the description says how many were left out."""
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    orders = harvest.ckan.packages["bb-objednavky-bb"]
    assert [r["url_type"] for r in orders["resources"]] == ["datastore"]
    records = harvest.ckan.tables[orders["resources"][0]["id"]]["records"]
    assert [r["Dodávateľ"] for r in records] == ["Firma s.r.o.", "Iná a.s."]
    # An IČO keeps its leading zeros: it is an identifier, not a number.
    assert records[0]["IČO"] == "00313271"
    assert "Ján Novák" not in json.dumps(harvest.ckan.packages, ensure_ascii=False)
    assert "vynechané riadky bez údaja IČO (1)" in orders["notes"]


def test_a_second_run_replaces_the_tables_instead_of_adding_new_ones(monkeypatch, capsys):
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    tables = set(harvest.ckan.tables)
    first = len(harvest.ckan.calls)
    grown = AGES + [{"Vek": "2", "Počet_občanov_v_danom_veku": "1", "Počet_mužov": "1", "Počet_žien": "0"}]
    monkeypatch.setitem(WEB, EGOV + "920:0::plac1140:_144053_5_8", (200, "application/json", json.dumps(grown).encode()))
    assert harvest.main() == 0
    assert set(harvest.ckan.tables) == tables, "a rerun added or lost a table"
    assert "package_create" not in harvest.ckan.calls[first:]
    ages = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [r.get("url_type") for r in ages] == [None, "datastore"]
    assert len(harvest.ckan.tables[ages[1]["id"]]["records"]) == 3


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


def test_a_table_that_lost_rows_fails_the_run(monkeypatch, capsys):
    harvest = load(monkeypatch)
    real = harvest.ckan.datastore_search
    harvest.ckan.datastore_search = lambda p: {"total": real(p)["total"] - 1}
    assert harvest.main() == 1
    assert "check failed: Počet občanov podľa veku: table Počet občanov podľa veku (tabuľka) holds 1 rows, 2 expected" \
        in capsys.readouterr().err


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


def test_a_converted_dataset_gains_the_platform_apis_after_its_files_and_tables_stay(monkeypatch, capsys):
    """T-4279: the mapping names the age table, so its page lists the NGSI-LD API and the files
    filtered to its rows, OData and MCP for the type; no GeoJSON or OGC, the rows have no location.
    The orders nobody mapped here gain nothing, and the DataStore table is still the table."""
    monkeypatch.setenv("OD_GATEWAY", "https://dev.joinedcontext.com/")
    monkeypatch.setenv("OD_DATASETS", json.dumps({"bb-pocet-obcanov-podla-veku": {
        "endpoint": "abc", "type": "KeyPerformanceIndicator", "location": False,
        "dataset": "https://data.dev.joinedcontext.com/dataset/bb-pocet-obcanov-podla-veku"}}))
    harvest = load(monkeypatch)
    assert harvest.main() == 0
    ages = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [r["format"] for r in ages] == ["JSON", "JSON-LD", "CSV", "JSON", "XLSX", "JSON", "JSON", "JSON", "CSV"]
    assert ages[-1].get("url_type") == "datastore", "the table moved off the end of the list"
    assert ages[1]["url"] == ("https://dev.joinedcontext.com/api/endpoint/abc/ngsi-ld/v1/entities?type=KeyPerformanceIndicator"
                              "&q=dataset%3D%3D%22https%3A%2F%2Fdata.dev.joinedcontext.com%2Fdataset%2Fbb-pocet-obcanov-podla-veku%22")
    assert ages[1]["conforms_to"].startswith("https://www.etsi.org/")
    assert not any("geojson" in r["url"] or "/ogc/" in r["url"] for r in ages)
    assert not any(r.get("resource_type") == "api" for r in harvest.ckan.packages["bb-objednavky-bb"]["resources"])
    # A second run writes the same list again, nothing doubled.
    harvest.main()
    again = harvest.ckan.packages["bb-pocet-obcanov-podla-veku"]["resources"]
    assert [(r["name"], r["url"]) for r in again] == [(r["name"], r["url"]) for r in ages]
