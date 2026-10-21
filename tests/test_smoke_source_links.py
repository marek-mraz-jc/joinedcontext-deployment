"""scripts/smoke-source-links.py against recorded answers (T-4802): the bridges of prod bbsk-demo,
read through the multi-type Registre kraja, link the dataset bbsk-mosty of the Bridge-only
Endpoint over the same space; a type no dataset publishes links nothing."""

import csv
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/smoke-source-links.py"
spec = importlib.util.spec_from_file_location("smoke_source_links", SCRIPT)
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)

DOMAIN = "smartcity.example.org"
API = f"https://api.{DOMAIN}/api/endpoint"
REGISTRE, MOSTY = "lws6dd7o56veegwxsjtvak3goeta4mfn", "omto6qk5sfn5ft7zl5pdiaxunj2ljnae"


def mosty(example):
    base = f"{API}/{MOSTY}"
    return {"name": "bbsk-mosty", "extras": [{"key": "endpoint", "value": f"{base}/"}], "resources": [
        {"url": f"{base}/ngsi-ld/v1/", "description":
            f"The first ten:\n\n    curl '{base}/ngsi-ld/v1/entities?type={example}&limit=10'\n"},
        {"url": f"{base}/odata/v4/", "description": "OData"}]}


def answers(example):
    first = {"Bridge": "urn:ngsi-ld:Bridge:bbsk.sk:bbsk-registre:M1006",
             "PointOfInterest": "urn:ngsi-ld:PointOfInterest:bbsk.sk:bbsk-registre:P1"}
    table = {
        f"https://opendata.{DOMAIN}/api/3/action/package_search?rows=1000&start=0":
            {"result": {"count": 1, "results": [mosty(example)]}},
        f"https://api.{DOMAIN}/catalog.jsonld": {"dcat:dataset": [{"@id": f"{API}/{MOSTY}"}]},
        # The door over the space has no catalogue record: the hub lends it (T-4802).
        f"https://api.{DOMAIN}/api/mcp/bbsk/otvorene-data": {"result": {"content": [{"type": "text", "text":
            "slug | title | space | access | types | domain\n"
            f"{REGISTRE} | Registers of the region | bbsk-registre | public | Bridge,PointOfInterest | x\n"
            "zzzzprivate | Private | bbsk-registre | organization | Bridge | x"}]}},
        f"{API}/{MOSTY}/ngsi-ld/v1/types": {"typeList": ["Bridge"]},
    }
    for slug, kinds in ((REGISTRE, ["Bridge", "PointOfInterest"]), (MOSTY, ["Bridge"])):
        for kind in kinds:
            table[f"{API}/{slug}/ngsi-ld/v1/entities?type={kind}&limit=1&pick=id"] = [{"id": first[kind]}]
    return table


class Recorded:
    def __init__(self, table):
        self.table, self.count, self.asked = table, 0, []

    def fetch(self, url, method="GET", headers=None, body=None, limit=0):
        self.count += 1
        self.asked.append(url)
        if url not in self.table:
            return links.smoke.Answer(404, "application/json", b"{}")
        return links.smoke.Answer(200, "application/json", json.dumps(self.table[url]).encode())


def table(path):
    with path.open(newline="") as handle:
        return {(r["endpoint"], r["type"]): r for r in csv.DictReader(handle, delimiter="\t")}


def test_rows_of_the_space_link_the_dataset_that_names_their_type(tmp_path):
    assert links.run(DOMAIN, "prod", tmp_path, Recorded(answers("Bridge")), now="T") == 0
    rows = table(tmp_path / "smoke-source-links-prod-T.tsv")
    dataset = f"https://opendata.{DOMAIN}/dataset/bbsk-mosty"
    assert rows[(REGISTRE, "Bridge")]["resolved"] == dataset
    assert rows[(MOSTY, "Bridge")]["resolved"] == dataset
    assert rows[(REGISTRE, "PointOfInterest")]["resolved"] == "-"
    assert rows[(REGISTRE, "PointOfInterest")]["expected"] == "-"
    fixture = json.loads((tmp_path / "smoke-source-links-prod-T.json").read_text())
    assert fixture["served"][MOSTY] == ["Bridge"]
    assert fixture["owners"] == {MOSTY: [dataset]}
    assert "zzzzprivate" not in fixture["served"], "a non-public Endpoint is not swept"


def test_a_page_that_names_another_type_is_a_ko(tmp_path, capsys):
    # Prod before T-4802: the page's example named AdministrativeArea, a type MOSTY does not serve.
    assert links.run(DOMAIN, "prod", tmp_path, Recorded(answers("AdministrativeArea")), now="T") == 1
    rows = table(tmp_path / "smoke-source-links-prod-T.tsv")
    assert rows[(REGISTRE, "Bridge")]["verdict"] == "ko"
    assert rows[(MOSTY, "Bridge")]["verdict"] == "ok", "its own Endpoint's one page"
    assert "source link " + REGISTRE + " Bridge" in capsys.readouterr().out


def test_names_that_are_not_plain_never_reach_a_pattern():
    pages = {"https://x/dataset/a": f"{API}/{MOSTY}/odata/v4/Bridge"}
    assert links.resolve(pages, [MOSTY], "Bridge", MOSTY) == "https://x/dataset/a"
    assert links.resolve(pages, [MOSTY], "Br.dge", "other") == ""
    assert links.resolve(pages, ["a|b"], "Bridge", "other") == ""
    assert links.resolve(pages, [MOSTY], "BridgeX", "other") == ""
