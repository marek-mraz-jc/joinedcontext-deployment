"""Every mapped Banská Bystrica and BBSK dataset, seeded by one generator (T-4255).

`scripts/open-data/generate.py` writes the `{project}-od-*` files of the two project folders from
the T-4254 mapping. The seed has to equal what it writes, so a hand edit of a generated file or a
mapping change without a regeneration fails here. Bento runs the generated mappings over recorded
answers of the sources their DataSources name (`fixtures/open-data/`, fetched on 2026-10-16 and
trimmed to a few rows), and every entity is checked against the generated space's JSON Schema,
which the gateway enforces. Without a container runtime the Bento cases skip; the others do not.
"""

import http.server
import importlib.util
import json
import re
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-open-data-seed")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures/open-data"
SCRIPT = ROOT / "scripts/open-data/generate.py"

spec = importlib.util.spec_from_file_location("generate", SCRIPT)
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)

MAPPING = yaml.safe_load(generate.MAPPING.read_text())
SEEDED = [e for e in MAPPING["datasets"] if e["status"] == "mapped" and (e.get("existing") or {}).get("covers") != "whole"]
SLUGS = generate.slugs(SEEDED)


def files(project: str, kind: str) -> list[Path]:
    return sorted(p for p in (SEED / project).glob(f"{project}-od-{kind}-*.yaml") if not p.name.endswith("-bento.yaml"))


def entry(name: str) -> dict:
    return next(e for e in SEEDED if e["name"] == name)


def run(project: str, slug: str, fixture: str) -> list[dict]:
    mapping = SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml"
    return open_data.run_all(mapping, (FIXTURES / f"{fixture}.json").read_bytes(), f"{project}-otvorene-data",
                             generate.PROJECTS[project]["domain"])


def run_bytes(project: str, slug: str, document: bytes) -> list[dict]:
    mapping = SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml"
    return open_data.run_all(mapping, document, f"{project}-otvorene-data", generate.PROJECTS[project]["domain"])


def schema_errors(project: str, entity: dict) -> list[str]:
    return open_data.schema_errors(SEED / project / f"{project}-otvorene-data.v1.schema.json", entity)


# --- the seed is the generator's output ---

def test_the_committed_seed_is_what_the_mapping_generates():
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_mapped_dataset_has_its_pipeline_unless_a_seed_reads_it_whole():
    mapped = [e for e in MAPPING["datasets"] if e["status"] == "mapped"]
    whole = [e for e in mapped if (e.get("existing") or {}).get("covers") == "whole"]
    pipelines = {p.name for project in generate.PROJECTS for p in files(project, "pipeline")}
    assert len(pipelines) == len(mapped) - len(whole) == len(SEEDED)
    for e in SEEDED:
        assert f"{e['org']}-od-pipeline-{SLUGS[e['name']]}.yaml" in pipelines, e["name"]


def test_the_model_classes_and_both_policies_name_every_type_the_pipelines_write():
    for project in generate.PROJECTS:
        written = {yaml.safe_load(p.read_text())["spec"]["output"]["type"] for p in files(project, "pipeline")}
        model = yaml.safe_load((SEED / project / f"{project}-od-datamodel.yaml").read_text())
        schema = json.loads((SEED / project / f"{project}-otvorene-data.v1.schema.json").read_text())
        assert set(model["spec"]["classes"]) == written
        assert written <= set(schema["definitions"]), "regenerate the artifacts: generate.py --artifacts"
        for policy in ("read", "pipelines-write"):
            doc = yaml.safe_load((SEED / project / f"{project}-od-policy-{policy}.yaml").read_text())
            assert {e["type"] for e in doc["spec"]["information"][0]["entities"]} == written


def test_the_index_places_every_generated_file_once():
    for project in generate.PROJECTS:
        index = yaml.safe_load((SEED / project / "index.yaml").read_text())
        generated = {p.name for p in (SEED / project).glob(f"{project}-od-*")} | {
            p.name for p in (SEED / project).glob(f"{project}-otvorene-data.*") if not p.name.endswith((".md", ".example.jsonld"))}
        assert generated <= set(index), sorted(generated - set(index))
        targets = list(index.values())
        assert len(targets) == len(set(targets))


def test_the_new_spaces_are_writable_by_the_pipelines_and_reachable_by_the_public_mcp_server():
    for project, sa, mcp in (("bbsk", "bbsk-serviceaccount-pipelines.yaml", "bbsk-mcp-otvorene-data.yaml"),
                             ("banskabystrica", "serviceaccount-pipelines.yaml", "banskabystrica-mcp-otvorene-data.yaml")):
        space = f"{project}-otvorene-data"
        roles = yaml.safe_load((SEED / project / sa).read_text())["spec"]["roles"]
        assert {"role": "space-writer", "scope": {"contextSpace": space}} in roles
        members = yaml.safe_load((SEED / project / mcp).read_text())["spec"]["members"]
        assert {"kind": "Endpoint", "name": space} in members
        endpoint = yaml.safe_load((SEED / project / f"{project}-od-endpoint.yaml").read_text())["spec"]
        assert endpoint["audience"] == "public" and "mcp" in endpoint["enabledRepresentations"]
        assert re.fullmatch(r"[a-z2-7]{26,}", endpoint["slug"])


def test_every_open_data_endpoint_serves_each_standard_and_the_catalogue_lists_each_converted_dataset():
    """T-4279: one list of representations for both spaces, and the harvests' mapping names every
    converted dataset once, with the Endpoint of its own project."""
    assert "xlsx" in generate.REPRESENTATIONS and "sta" not in generate.REPRESENTATIONS
    slugs = {}
    for project in ("bbsk", "banskabystrica"):
        endpoint = yaml.safe_load((SEED / project / f"{project}-od-endpoint.yaml").read_text())["spec"]
        assert endpoint["enabledRepresentations"] == generate.REPRESENTATIONS
        slugs[project] = endpoint["slug"]
    rows = json.loads(generate.DISTRIBUTIONS.read_text())
    # A dataset another seed reads whole keeps that seed's Endpoint, which this mapping does not name.
    assert len(rows) == len({e["dataset"] for e in SEEDED})
    for e in SEEDED:
        row = rows[e["dataset"].rsplit("/", 1)[1]]
        assert (row["endpoint"], row["type"], row["dataset"]) == (slugs[e["org"]], e["type"], e["dataset"])


# --- the generator's own rules ---

def test_names_are_dns_labels_unique_and_short_enough_for_a_principal():
    assert len(set(SLUGS.values())) == len(SLUGS)
    for slug in SLUGS.values():
        # `od-` and the reconciler's `pl-` prefix stay inside a 63-character label.
        assert re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", slug) and len(slug) <= 40, slug
    assert generate.slugs([{"name": "bbsk-x-abcdef"}, {"name": "bb-x"}, {"name": "bb-y-1996-2024"}]) == {
        "bbsk-x-abcdef": "x", "bb-x": "x-2", "bb-y-1996-2024": "y"}
    assert not any(re.search(r"-[0-9]{4}$", s) for s in SLUGS.values()), "the janitor would sweep it"


def test_one_range_per_attribute_across_the_model():
    entries = [{"properties": {"rok": {"column": "Rok", "range": "integer"}, "kod": {"column": "Kod", "range": "integer"}}},
               {"properties": {"rok": {"column": "Rok", "range": "float"}, "kod": {"column": "Kod", "range": "string"}}}]
    assert generate.ranges(entries) == {"rok": "float", "kod": "string"}


def test_a_column_named_like_the_attribution_keeps_its_value_under_another_name():
    assert generate.attribute("source") == "columnSource"
    assert generate.attribute("location") == "columnLocation"
    assert generate.attribute("rok") == "rok"


def test_schedules_are_valid_cron_and_follow_the_refresh():
    for project in generate.PROJECTS:
        for p in files(project, "pipeline"):
            spec = yaml.safe_load(p.read_text())["spec"]
            fields = spec["schedule"].split()
            assert len(fields) == 5 and 0 <= int(fields[0]) < 60 and 1 <= int(fields[1]) <= 5, p.name
    daily = next(e for e in SEEDED if e["refresh"] == "P1D")
    assert generate.schedule(daily, 3).endswith("* * *")
    assert generate.schedule({"refresh": "P1M"}, 30).split()[2] == "3"


# --- Security: public sources only, no personal column, the row filters at the source ---

def test_every_source_is_public_https_without_a_credential():
    for project in generate.PROJECTS:
        for p in files(project, "datasource"):
            spec = yaml.safe_load(p.read_text())["spec"]
            url = urllib.parse.urlsplit(spec["http"]["url"])
            assert url.scheme == "https" and url.hostname in {"services-eu1.arcgis.com", "data.dev.joinedcontext.com",
                                                               "www.banskabystrica.sk"}, p.name
            assert set(spec["http"]) == {"url", "verb", "headers", "timeout"} and "Authorization" not in spec["http"]["headers"]


def test_no_dropped_column_is_asked_for_or_read():
    dropped = [e for e in SEEDED if e.get("dropped")]
    assert dropped, "the mapping drops personal columns; this test must see them"
    for e in dropped:
        slug, project = SLUGS[e["name"]], e["org"]
        url = yaml.safe_load((SEED / project / f"{project}-od-datasource-{slug}.yaml").read_text())["spec"]["http"]["url"]
        out_fields = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["outFields"][0].split(",")
        bento = (SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml").read_text()
        for column in e["dropped"]["columns"]:
            assert column not in out_fields, (e["name"], column)
            assert json.dumps(column, ensure_ascii=False) not in bento, (e["name"], column)


def test_every_request_fits_the_url_length_arcgis_answers():
    """ArcGIS Online answers a query URL past about 2 kB with an IIS 404: the BBSK religion layers
    asked for 50 columns by name and failed live (T-4255). Such a layer asks for `*`."""
    starred = 0
    for e in SEEDED:
        slug, project = SLUGS[e["name"]], e["org"]
        url = yaml.safe_load((SEED / project / f"{project}-od-datasource-{slug}.yaml").read_text())["spec"]["http"]["url"]
        bento = (SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml").read_text()
        for u in [url, *re.findall(r'url: "([^"]+)"', bento)]:
            assert len(u) <= 2000, (e["name"], len(u))
            if urllib.parse.parse_qs(urllib.parse.urlsplit(u).query).get("outFields") == ["*"]:
                assert not e.get("dropped"), e["name"]
                starred += 1
    assert starred, "no layer asks for * any more: drop the fallback in generate.py and this test"


def test_a_row_filter_travels_with_every_request_of_its_layer():
    filtered = [e for e in SEEDED if (e.get("rowFilter") or {}).get("where")]
    assert filtered, "the mapping filters rows; this test must see them"
    for e in filtered:
        slug, project = SLUGS[e["name"]], e["org"]
        url = yaml.safe_load((SEED / project / f"{project}-od-datasource-{slug}.yaml").read_text())["spec"]["http"]["url"]
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["where"] == [e["rowFilter"]["where"]]
        bento = (SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml").read_text()
        for page_url in re.findall(r'url: "([^"]+)"', bento):
            assert urllib.parse.parse_qs(urllib.parse.urlsplit(page_url).query)["where"] == [e["rowFilter"]["where"]]


# --- the mappings over recorded answers ---

@requires_docker
def test_a_layer_with_a_key_writes_one_point_per_row_under_its_key():
    entities = run("bbsk", "zoznam-lekarni-v-bbk", "lekarne")
    rows = json.loads((FIXTURES / "lekarne.json").read_text())["features"]
    assert [e["id"] for e in entities] == [
        f"urn:ngsi-ld:PointOfInterest:bbsk.sk:bbsk-otvorene-data:zoznam-lekarni-v-bbk-{r['properties']['IdZZ']}" for r in rows]
    for e, r in zip(entities, rows):
        assert e["location"] == {"type": "GeoProperty", "value": r["geometry"]}
        assert e["dataset"]["value"] == entry("bbsk-zoznam-lekarni-v-bbk-c564de")["dataset"]
        assert "CC BY-SA 4.0" in e["dataProvider"]["value"]
        assert schema_errors("bbsk", e) == []


@requires_docker
def test_a_key_with_its_year_and_a_polygon():
    entities = run("bbsk", "pohyb-obyvatelstva-v-okresoch", "pohyb-okresy")
    rows = json.loads((FIXTURES / "pohyb-okresy.json").read_text())["features"]
    assert len(entities) == len(rows) == 2
    for e, r in zip(entities, rows):
        assert e["id"].endswith(f"-{r['properties']['IDN3']}-{r['properties']['Rok']}")
        assert e["location"]["value"]["type"] == "Polygon"
        assert schema_errors("bbsk", e) == []


@requires_docker
def test_a_table_without_a_key_takes_a_stable_row_hash():
    first = run("bbsk", "zmluvy", "zmluvy")
    again = run("bbsk", "zmluvy", "zmluvy")
    assert [e["id"] for e in first] == [e["id"] for e in again]
    assert len({e["id"] for e in first}) == 3
    assert all("location" not in e and schema_errors("bbsk", e) == [] for e in first)
    # One changed value is another row, so another id.
    doc = json.loads((FIXTURES / "zmluvy.json").read_text())
    doc["features"][0]["properties"]["Suma_v_EUR"] = 1.5
    changed = run_bytes("bbsk", "zmluvy", json.dumps(doc).encode())
    assert changed[0]["id"] != first[0]["id"] and changed[1]["id"] == first[1]["id"]


@requires_docker
def test_a_name_where_the_ico_belongs_keeps_the_row_out():
    """The BBSK IČO columns also hold surnames padded to eight characters (`0000BIBA`), which name
    natural persons and pass the layer's `IS NOT NULL` filter (T-4255): the mapping drops them."""
    doc = json.loads((FIXTURES / "zmluvy.json").read_text())
    kept = [f["properties"]["IČO_dodávateľa"] for f in doc["features"][1:]]
    doc["features"][0]["properties"]["IČO_dodávateľa"] = "0000BIBA"
    entities = run_bytes("bbsk", "zmluvy", json.dumps(doc).encode())
    assert len(entities) == len(kept) == 2
    assert sorted(e["iCODodavatela"]["value"] for e in entities) == sorted(v.strip() for v in kept)
    doc["features"][1]["properties"]["IČO_dodávateľa"] = "00177431 0006"
    assert len(run_bytes("bbsk", "zmluvy", json.dumps(doc).encode())) == 2


@requires_docker
def test_a_contract_with_a_party_without_an_ico_stays_out():
    """The city's contracts name a social-service client as a party (T-4255): a contract stays only
    when every party line of `Zmluvné_strany_s_údajom_IČO` carries an IČO."""
    company = "IČO: 00165549 Fakultná nemocnica s poliklinikou F.D. Roosevelta Banská Bystrica"
    records = [
        {"Centrálne_číslo_zmluvy": "1", "Rok": 2024, "Zmluvné_strany_s_údajom_IČO": company},
        {"Centrálne_číslo_zmluvy": "2", "Rok": 2024, "Zmluvné_strany_s_údajom_IČO": "Adam Gašpar"},
        {"Centrálne_číslo_zmluvy": "3", "Rok": 2024, "Zmluvné_strany_s_údajom_IČO": f"{company},\rNatália Tretinová"},
        {"Centrálne_číslo_zmluvy": "4", "Rok": 2024,
         "Zmluvné_strany_s_údajom_IČO": f"{company},\rIČO: 30232295 Univerzita Mateja Bela"},
        {"Centrálne_číslo_zmluvy": "5", "Rok": 2024, "Zmluvné_strany_s_údajom_IČO": None},
    ]
    doc = json.dumps({"success": True, "result": {"records": records}}).encode()
    entities = run_bytes("banskabystrica", "zmluvy-bb", doc)
    assert len(entities) == 2
    assert not any("Gašpar" in json.dumps(e, ensure_ascii=False) or "Tretinová" in json.dumps(e, ensure_ascii=False)
                   for e in entities)


@requires_docker
def test_a_catalogue_table_reads_its_records_with_their_types():
    entities = run("banskabystrica", "objednavky-bb", "objednavky-bb")
    rows = json.loads((FIXTURES / "objednavky-bb.json").read_text())["result"]["records"]
    assert len(entities) == len(rows) == 3
    for e, r in zip(entities, rows):
        assert e["id"].endswith(f"objednavky-bb-{r['Číslo_objednávky']}")
        assert e["cisloObjednavky"]["value"] == r["Číslo_objednávky"]
        assert schema_errors("banskabystrica", e) == []


@requires_docker
def test_a_wordpress_post_is_its_id_title_link_and_text_without_markup():
    entities = run("banskabystrica", "aktuality", "aktuality")
    posts = json.loads((FIXTURES / "aktuality.json").read_text())
    assert [e["sourceId"]["value"] for e in entities] == [p["id"] for p in posts]
    for e in entities:
        assert "<" not in e["content"]["value"] and e["title"]["value"] and e["dateGmt"]["value"].endswith("Z")
        assert schema_errors("banskabystrica", e) == []


def offline(project: str, slug: str, document: bytes, pages: dict[int, bytes | None]) -> subprocess.CompletedProcess:
    """The mapping over `document`, its further pages answered on this machine by `resultOffset`:
    `pages[offset]` is the answer, None a 500, and an offset it does not name an empty page."""
    class Layer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            offset = int(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["resultOffset"][0])
            body = pages.get(offset, b'{"type": "FeatureCollection", "features": []}')
            self.send_response(500 if body is None else 200)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Layer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        text = (SEED / project / f"{project}-od-pipeline-{slug}-bento.yaml").read_text()
        text = text.replace("https://services-eu1.arcgis.com", f"http://127.0.0.1:{server.server_port}")
        config = {
            "input": {"stdin": {"scanner": {"to_the_end": {}}}},
            "pipeline": yaml.safe_load(text)["pipeline"],
            "rate_limit_resources": [{"label": "pipeline_egress", "local": {"count": 100, "interval": "1s"}}],
            "output": {"stdout": {"codec": "lines"}},
            "logger": {"level": "error"},
        }
        return subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "host", "-e", "JC_ORG_DOMAIN=bbsk.sk",
             "-e", f"JC_SPACE={project}-otvorene-data", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh",
             open_data.BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
            input=document, capture_output=True, timeout=180,
        )
    finally:
        server.shutdown()


def written(result: subprocess.CompletedProcess) -> list[dict]:
    assert result.returncode == 0, result.stderr.decode()
    out = []
    for line in result.stdout.decode().splitlines():
        if line.strip():
            message = json.loads(line)
            out.extend(message if isinstance(message, list) else [message])
    return out


@requires_docker
def test_a_layer_over_one_page_is_read_page_by_page_with_its_filter():
    page0 = json.loads((FIXTURES / "zmluvy.json").read_text())
    rows = page0["features"]
    first = {**page0, "features": rows[:2], "properties": {"exceededTransferLimit": True}}
    second = json.dumps({**page0, "features": rows[2:]}).encode()
    entities = written(offline("bbsk", "zmluvy", json.dumps(first).encode(), {1000: second}))
    assert len({e["id"] for e in entities}) == 3, "both rows of page 0 and the row of page 1000"
    assert all(schema_errors("bbsk", e) == [] for e in entities)
    # Without the flag the layer said it was whole: nothing else is asked for.
    assert len(written(offline("bbsk", "zmluvy", json.dumps({**page0, "features": rows[:2]}).encode(), {1000: None}))) == 2


@requires_docker
def test_an_empty_layer_writes_nothing_and_a_failure_fails_the_run_where_it_shows():
    assert written(offline("bbsk", "peticie", b'{"type": "FeatureCollection", "features": []}', {})) == []
    error = offline("bbsk", "peticie", b'{"error": {"code": 400, "message": "Invalid query"}}', {})
    assert b"the layer answered no features: Invalid query" in error.stdout + error.stderr
    page0 = json.loads((FIXTURES / "zmluvy.json").read_text())
    missing = offline("bbsk", "zmluvy", json.dumps({**page0, "properties": {"exceededTransferLimit": True}}).encode(), {2000: None})
    assert b"the page at 2000 did not come" in missing.stdout + missing.stderr
    table = offline("banskabystrica", "objednavky-bb", b'{"success": false}', {})
    assert b"the catalogue answered no table" in table.stdout + table.stderr
