"""Every mapped Banská Bystrica and BBSK dataset, seeded by one generator (T-4255).

`scripts/open-data/generate.py` writes the `{project}-od-*` files of the two project folders from
the T-4254 mapping. The seed has to equal what it writes, so a hand edit of a generated file or a
mapping change without a regeneration fails here. Bento runs the generated mappings over recorded
answers of the sources their DataSources name (`fixtures/open-data/`, fetched on 2026-10-16 and
trimmed to a few rows), and every entity is checked against the generated space's JSON Schema,
which the gateway enforces, and against its FIWARE Smart Data Model's schema.json, vendored in
`scripts/open-data/sdm/` (T-4319). Without a container runtime the Bento cases skip; the others do not.
"""

import http.server
import importlib.util
import json
import re
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime, timezone
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


MAPPED = [e for e in MAPPING["datasets"] if e["status"] == "mapped"]
MODEL = {e["type"]: e["smartDataModel"] for e in MAPPED}
BASE = {e["type"]: e.get("baseModel") for e in MAPPED}
PINS = json.loads((generate.SDM / "pins.json").read_text())


def sdm_errors(entity: dict, model_of: str | None = None) -> list[str]:
    """The entity against its type's vendored Smart Data Model, or the extension the type has (T-4336)."""
    t = model_of or entity["type"]
    if t in generate.SPACE_EXTENSIONS:
        return open_data.sdm_errors(f"extensions/{t}", entity)
    schema = generate.sdm_schema({"name": t, "type": t, "smartDataModel": MODEL[t], "baseModel": BASE[t]})
    return open_data.sdm_errors(str(schema.parent.relative_to(generate.SDM)), entity)


# --- the seed is the generator's output ---

def test_the_committed_seed_is_what_the_mapping_generates():
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_mapped_dataset_has_its_pipeline_unless_a_seed_reads_it_whole():
    mapped = [e for e in MAPPING["datasets"] if e["status"] == "mapped"]
    whole = [e for e in mapped if (e.get("existing") or {}).get("covers") == "whole"]
    pipelines = {p.name for project in generate.PROJECTS for p in files(project, "pipeline")}
    assert len(mapped) - len(whole) == len(SEEDED)
    # A dataset of the city's layers may take several pipelines (generate.parts, T-4317).
    want = {f"{e['org']}-od-pipeline-{slug}.yaml" for e in SEEDED for _, slug in generate.parts(e, SLUGS[e["name"]])}
    assert pipelines == want
    # Each pipeline alone writes its rows, so it replaces them whole and a dropped attribute
    # leaves at the next run (PL-79, T-4407).
    modes = {yaml.safe_load(p.read_text())["spec"]["output"]["mode"] for project in generate.PROJECTS
             for p in files(project, "pipeline")}
    assert modes == {"replace"}


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
    assert {"xlsx", "parquet", "sta"} <= set(generate.REPRESENTATIONS)
    slugs = {}
    for project in ("bbsk", "banskabystrica"):
        endpoint = yaml.safe_load((SEED / project / f"{project}-od-endpoint.yaml").read_text())["spec"]
        assert endpoint["enabledRepresentations"] == generate.REPRESENTATIONS
        slugs[project] = endpoint["slug"]
    rows = json.loads(generate.DISTRIBUTIONS.read_text())
    mapped = [e for e in MAPPING["datasets"] if e["status"] == "mapped"]
    # The susr- rows are scripts/open-data/datacube.py's (T-4390, test_datacube_generator.py).
    assert len([k for k in rows if not k.startswith("susr-")]) == len({e["dataset"] for e in mapped})
    for e in SEEDED:
        row = rows[e["dataset"].rsplit("/", 1)[1]]
        assert (row["endpoint"], row["type"], row["dataset"], row["filtered"]) == (slugs[e["org"]], e["type"], e["dataset"], True)
    # T-4288: SensorThings is listed for the datasets whose numbers carry an instant, and only those.
    series = {name for name, row in rows.items() if row.get("series")}
    assert any(s.startswith("bbsk-pohyb-obyvatelstva-v-okresoch") for s in series), sorted(series)
    assert not any(s.startswith(("bb-adresy", "bbsk-zoznam-lekarni")) for s in series)
    assert series == {e["dataset"].rsplit("/", 1)[1] for e in SEEDED if e.get("observedAt")} - {
        e["dataset"].rsplit("/", 1)[1] for e in SEEDED if not generate.series(e)}
    # T-4291: a dataset another seed reads whole is listed through that seed's public Endpoint, over
    # its whole type, since those rows name no catalogue dataset.
    endpoints = {d["spec"]["slug"]: (f.parent.name, d["spec"]) for f in SEED.glob("*/*.yaml")
                 for d in yaml.safe_load_all(f.read_text()) if isinstance(d, dict) and d.get("kind") == "Endpoint"}
    for e in mapped:
        if (e.get("existing") or {}).get("covers") != "whole":
            continue
        row = rows[e["dataset"].rsplit("/", 1)[1]]
        project, endpoint = endpoints[row["endpoint"]]
        assert (project, endpoint["audience"], row["filtered"]) == (e["org"], "public", False), e["name"]
        assert {"ngsi-ld", "csv", "json", "ogc-features", "odata"} <= set(endpoint["enabledRepresentations"]), e["name"]
    mosty = rows["bbsk-mosty-v-banskobystrickom-kraji-public-view-3b4675"]
    assert (mosty["type"], endpoints[mosty["endpoint"]][1]["policyRef"]) == ("Bridge", "urn:ngsi-ld:Policy:bbsk.sk:bbsk-registre:mosty-read")


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
            # Bento's cron reads a weekday 0-6; a 7 refused the whole stream on dev (T-4347).
            assert fields[4] == "*" or 0 <= int(fields[4]) <= 6, p.name
    daily = next(e for e in SEEDED if e["refresh"] == "P1D")
    assert generate.schedule(daily, 3).endswith("* * *")
    assert generate.schedule({"refresh": "P1M"}, 30).split()[2] == "3"


# --- Security: public sources only, no personal column, the row filters at the source ---

def test_every_source_is_public_https_without_a_credential():
    for project in generate.PROJECTS:
        for p in files(project, "datasource"):
            spec = yaml.safe_load(p.read_text())["spec"]
            url = urllib.parse.urlsplit(spec["http"]["url"])
            # The T-MAPY host is where the city's DTM_BB archives are published (T-4317).
            assert url.scheme == "https" and url.hostname in {"services-eu1.arcgis.com", "data.dev.joinedcontext.com",
                                                               "www.banskabystrica.sk", "dtm-banskabystrica.tmapserver.sk"}, p.name
            assert set(spec["http"]) == {"url", "verb", "headers", "timeout"} and "Authorization" not in spec["http"]["headers"]


def test_no_dropped_column_is_asked_for_or_read():
    dropped = [e for e in SEEDED if e.get("dropped")]
    assert dropped, "the mapping drops personal columns; this test must see them"
    for e in dropped:
        slug, project = SLUGS[e["name"]], e["org"]
        url = yaml.safe_load((SEED / project / f"{project}-od-datasource-{slug}.yaml").read_text())["spec"]["http"]["url"]
        # An archive is read whole, so only the mapping keeps a dropped column out (T-4317).
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        out_fields = query["outFields"][0].split(",") if e["source"]["kind"] == "esri-featureserver" else []
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


# --- Smart Data Models (T-4319): every type is a published model, every entity valid in it ---

def test_every_mapped_type_is_one_vendored_smart_data_model_at_a_pinned_commit():
    assert len(MODEL) == len({(e["type"], e["smartDataModel"]) for e in MAPPED}), "one model per type"
    for e in MAPPED:
        assert generate.sdm_schema(e).is_file()
        official = e.get("baseModel") or e["smartDataModel"]
        assert re.fullmatch(r"[0-9a-f]{40}", PINS[official.split("/")[0]]), official
    assert re.fullmatch(r"[0-9a-f]{40}", PINS["data-models"])
    vendored = {str(p.parent.relative_to(generate.SDM)) for p in generate.SDM.glob("*/*/schema.json")
                if p.parent.parent != generate.EXTENSIONS}
    in_use = {(e.get("baseModel") or e["smartDataModel"]).removeprefix("dataModel.") for e in MAPPED}
    # The folder also serves the city seeds' models (T-4329: Helsinki, Praha), so it holds at
    # least the models this seed uses, the bases of the extensions included, each subject pinned.
    assert vendored >= in_use, "vendor every model in use, the bases of the extensions included"
    assert {f"dataModel.{v.split('/')[0]}" for v in vendored} | {"about", "data-models"} == set(PINS), "a pin per vendored subject"


def test_a_mapped_dataset_without_a_model_or_with_one_not_vendored_is_refused():
    for model in (None, "", "dataModel.Finance/Invoice", "Organization/Organization"):
        with pytest.raises(SystemExit, match="mapped without a vendored Smart Data Model"):
            generate.sdm_schema({"name": "bbsk-x", "smartDataModel": model})
    # An extension names a declared, vendored base and its own type (T-4336).
    for bad in ({"baseModel": None}, {"baseModel": "dataModel.Finance/Ledger"}, {"type": "Other"}):
        with pytest.raises(SystemExit, match="extends no vendored base"):
            generate.sdm_schema({"name": "bbsk-x", "type": "Invoice", "smartDataModel": "extension/Invoice",
                                 "baseModel": "dataModel.CPSV-AP/Cost", **bad})
    assert not [e for e in MAPPING["datasets"] if e["status"] == "removed" and SLUGS.get(e["name"])]
    removed = {e["name"] for e in MAPPING["datasets"] if e["status"] == "removed"}
    for project in generate.PROJECTS:
        for p in files(project, "datasource"):
            assert yaml.safe_load(p.read_text())["metadata"]["title"]["en"] not in {
                e["title"][:120] for e in MAPPING["datasets"] if e["name"] in removed and e["org"] == project}, p.name


def expanded(context: dict, term: str) -> str:
    """The IRI the generated @context gives `term`, its CURIE resolved by the context's own prefixes."""
    iri = context[term]["@id"] if isinstance(context[term], dict) else context[term]
    prefix, _, rest = iri.partition(":")
    return context[prefix] + rest if isinstance(context.get(prefix), str) and not rest.startswith("//") else iri


def test_every_term_a_model_names_expands_to_its_vendored_context_and_a_source_column_stays_jc():
    """T-4328: a client expanding with the Smart Data Model's @context reads the IRIs the broker holds."""
    for project in generate.PROJECTS:
        context = json.loads((SEED / project / f"{project}-otvorene-data.v1.context.jsonld").read_text())["@context"]
        named = 0
        for e in [e for e in SEEDED if e["org"] == project]:
            model = (e.get("baseModel") or e["smartDataModel"]).split("/")[0]
            sdm = json.loads((generate.SDM / model.removeprefix("dataModel.") / "context.jsonld").read_text())["@context"]
            # An extension's type is ours (T-4336); every other term reads as its base names it.
            want = f"https://joinedcontext.com/models/{e['type']}" if e.get("baseModel") else sdm[e["type"]]
            assert expanded(context, e["type"]) == want, e["name"]
            for a in [*generate.COMMON, *map(generate.attribute, e["properties"]), *(e.get("constants") or {})]:
                if isinstance(sdm.get(a), str):
                    assert expanded(context, a) == sdm[a], (e["name"], a)
                    named += 1
                else:
                    assert expanded(context, a) == f"https://joinedcontext.com/models/{a}", (e["name"], a)
        assert named, project
    # A source's own column (BBSK's school statistics) is the organisation's term.
    assert expanded(json.loads((SEED / "bbsk/bbsk-otvorene-data.v1.context.jsonld").read_text())["@context"],
                    "absolventiZaMinulyRokSpol") == "https://joinedcontext.com/models/absolventiZaMinulyRokSpol"


def test_every_context_is_vendored_beside_its_schema_at_the_same_pin():
    for model in {(BASE[t] or m).split("/")[0] for t, m in MODEL.items()}:
        assert (generate.SDM / model.removeprefix("dataModel.") / "context.jsonld").is_file(), model
        assert model in PINS


def test_two_models_naming_one_term_differently_are_refused():
    a = {"name": "x", "type": "PointOfInterest", "smartDataModel": "dataModel.PointOfInterest/PointOfInterest",
         "properties": {"category": {}}}
    b = {**a, "name": "y", "type": "KeyPerformanceIndicator",
         "smartDataModel": "dataModel.KeyPerformanceIndicator/KeyPerformanceIndicator"}
    with pytest.raises(SystemExit, match="`category`"):
        generate.sdm_iris([a, b])


SAMPLE = {"string": "x", "integer": 1, "float": 1.5, "datetime": "2026-01-01T00:00:00Z", "date": "2026-01-01",
          "uri": "https://example.org/a", "string-list": ["x"]}


def test_every_mapping_writes_an_entity_its_model_accepts():
    """Without Bento: the entity each mapping writes when every column holds a value of its range."""
    # The range the Bento writes is the space's: integer and text columns of one name meet as text.
    space = {project: generate.ranges([e for e in SEEDED if e["org"] == project]) for project in generate.PROJECTS}
    for e in MAPPED:
        written = space[e["org"]] if e in SEEDED else {generate.attribute(a): p["range"] for a, p in e["properties"].items()}
        entity = {"id": f"urn:ngsi-ld:{e['type']}:bbsk.sk:s:x-1", "type": e["type"],
                  **{generate.attribute(a): {"type": "Property", "value": SAMPLE[written[generate.attribute(a)]]} for a in e["properties"]},
                  **{a: {"type": "Property", "value": v} for a, v in (e.get("constants") or {}).items()},
                  **{a: {"type": "Property", "value": "https://example.org/s"} for a in ("source", "isPartOf")},
                  "dataProvider": {"type": "Property", "value": "x (CC BY 4.0)"},
                  # The entity's own key where the base requires an identifier no column holds (T-4336).
                  **({"identifier": {"type": "Property", "value": "x-1"}} if e.get("identifierFromId") else {})}
        if e["source"].get("geometry"):
            entity["location"] = {"type": "GeoProperty", "value": {"type": "Point", "coordinates": [19.1, 48.7]}}
        assert sdm_errors(entity) == [], e["name"]
    # A list attribute that came through as text is what the model refuses.
    assert sdm_errors({"id": "urn:ngsi-ld:Address:bb:x", "type": "Address", "thoroughfare": {"type": "Property", "value": "x"}})


# --- the mappings over recorded answers ---

def valid(project: str, entities: list[dict]) -> bool:
    for e in entities:
        assert schema_errors(project, e) == [], e["id"]
        assert sdm_errors(e) == [], e["id"]
    return True


@requires_docker
def test_a_layer_with_a_key_writes_one_point_per_row_under_its_key():
    entities = run("bbsk", "zoznam-lekarni-v-bbk", "lekarne")
    rows = json.loads((FIXTURES / "lekarne.json").read_text())["features"]
    assert [e["id"] for e in entities] == [
        f"urn:ngsi-ld:PointOfInterest:bbsk.sk:bbsk-otvorene-data:zoznam-lekarni-v-bbk-{r['properties']['IdZZ']}" for r in rows]
    for e, r in zip(entities, rows):
        assert e["location"] == {"type": "GeoProperty", "value": r["geometry"]}
        assert e["name"]["value"] == r["properties"]["Názov"].strip()
        assert e["isPartOf"]["value"] == entry("bbsk-zoznam-lekarni-v-bbk-c564de")["dataset"]
        assert "dataset" not in e, "the core @context owns `dataset` (T-4289)"
        assert "CC BY-SA 4.0" in e["dataProvider"]["value"]
    assert valid("bbsk", entities)


@requires_docker
def test_a_key_with_its_year_and_a_polygon():
    entities = run("bbsk", "pohyb-obyvatelstva-v-okresoch", "pohyb-okresy")
    rows = json.loads((FIXTURES / "pohyb-okresy.json").read_text())["features"]
    assert len(entities) == len(rows) == 2
    for e, r in zip(entities, rows):
        assert e["id"].startswith("urn:ngsi-ld:KeyPerformanceIndicator:")
        assert e["id"].endswith(f"-{r['properties']['IDN3']}-{r['properties']['Rok']}")
        assert e["location"]["value"]["type"] == "Polygon"
        # Every number is stamped with its year, so SensorThings charts it; the year itself is not (T-4288).
        numbers = {a: p for a, p in e.items() if isinstance(p, dict) and isinstance(p.get("value"), (int, float))}
        stamped = {a for a, p in numbers.items() if p.get("observedAt") == f"{r['properties']['Rok']}-01-01T00:00:00Z"}
        assert numbers and stamped == set(numbers) - {"rok"}, sorted(set(numbers) - stamped)
        assert "observedAt" not in e.get("rok", {})
    assert valid("bbsk", entities)


@requires_docker
def test_a_corrected_accident_keeps_its_id_and_the_constant_its_model_requires():
    first = run("bbsk", "nehodovost-v-bbk", "nehodovost-v-bbk")
    rows = json.loads((FIXTURES / "nehodovost-v-bbk.json").read_text())["features"]
    assert [e["id"] for e in first] == [
        f"urn:ngsi-ld:RoadAccident:bbsk.sk:bbsk-otvorene-data:nehodovost-v-bbk-{r['properties']['Číslo_nehody']}"
        for r in rows]
    assert all(e["status"]["value"] == "archived" for e in first)
    # An Esri date is the instant every number of the accident was observed at (T-4288).
    for e, r in zip(first, rows):
        at = datetime.fromtimestamp(r["properties"]["Dátum_a_čas"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert {p.get("observedAt") for p in e.values() if isinstance(p, dict) and isinstance(p.get("value"), (int, float))} == {at}
    assert valid("bbsk", first)
    # A corrected value updates the accident instead of adding a second one (T-4332).
    doc = json.loads((FIXTURES / "nehodovost-v-bbk.json").read_text())
    doc["features"][0]["properties"]["Škoda_v_EUR"] = 1.5
    changed = run_bytes("bbsk", "nehodovost-v-bbk", json.dumps(doc).encode())
    assert [e["id"] for e in changed] == [e["id"] for e in first]


@requires_docker
def test_a_table_without_a_key_takes_a_stable_row_hash():
    first = run("banskabystrica", "adresy", "adresy")
    again = run("banskabystrica", "adresy", "adresy")
    assert [e["id"] for e in first] == [e["id"] for e in again]
    assert len({e["id"] for e in first}) == 3
    # One changed value is another row, so another id.
    doc = json.loads((FIXTURES / "adresy.json").read_text())
    doc["result"]["records"][0]["Ulica"] = "Iná ulica"
    changed = run_bytes("banskabystrica", "adresy", json.dumps(doc).encode())
    assert changed[0]["id"] != first[0]["id"] and changed[1]["id"] == first[1]["id"]


@requires_docker
def test_a_list_attribute_is_a_one_item_list_and_an_empty_name_reads_the_next_column():
    doc = json.loads((FIXTURES / "nabijacky-a-zastavky.json").read_text())
    doc["features"][0]["properties"]["PRIM_NAME"] = None
    entities = run_bytes("bbsk", "nabijacky-a-zastavky", json.dumps(doc).encode())
    rows = [f["properties"] for f in doc["features"]]
    assert len(entities) == len(rows) == 3
    assert entities[0]["name"]["value"] == rows[0]["Categ"]
    assert [e["name"]["value"] for e in entities[1:]] == [r["PRIM_NAME"] for r in rows[1:]]
    assert entities[0]["category"]["value"] == [str(rows[0]["category"])]
    assert valid("bbsk", entities)
    spatial = run("bbsk", "prispevkove-rozpoctove-a-ine-organizacie", "prispevkove-rozpoctove-a-ine-organizacie")
    assert [e["spatial"]["value"] for e in spatial] == [[r["properties"]["Obec"]] for r in json.loads(
        (FIXTURES / "prispevkove-rozpoctove-a-ine-organizacie.json").read_text())["features"]]
    assert valid("bbsk", spatial)


@requires_docker
def test_a_name_where_the_ico_belongs_keeps_the_row_out():
    """The BBSK IČO columns also hold surnames padded to eight characters (`0000BIBA`), which name
    natural persons and pass the layer's `IS NOT NULL` filter (T-4255): the mapping drops them."""
    doc = json.loads((FIXTURES / "dodavatelia.json").read_text())
    kept = [f["properties"]["ICO"] for f in doc["features"][1:]]
    doc["features"][0]["properties"]["ICO"] = "0000BIBA"
    entities = run_bytes("bbsk", "dodavatelia", json.dumps(doc).encode())
    assert sorted(e["iCO"]["value"] for e in entities) == sorted(v.strip() for v in kept)
    assert valid("bbsk", entities)
    doc["features"][1]["properties"]["ICO"] = "00177431 0006"
    assert len(run_bytes("bbsk", "dodavatelia", json.dumps(doc).encode())) == 2


@requires_docker
def test_a_catalogue_table_reads_its_records_as_addresses():
    entities = run("banskabystrica", "adresy", "adresy")
    rows = json.loads((FIXTURES / "adresy.json").read_text())["result"]["records"]
    assert len(entities) == len(rows) == 3
    for e, r in zip(entities, rows):
        assert e["id"].startswith("urn:ngsi-ld:Address:banskabystrica.sk:banskabystrica-otvorene-data:adresy-")
        assert (e["thoroughfare"]["value"], e["postName"]["value"]) == ([r["Ulica"]], [r["Obec"]])
    assert valid("banskabystrica", entities)


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
    page0 = json.loads((FIXTURES / "dodavatelia.json").read_text())
    rows = page0["features"]
    first = {**page0, "features": rows[:2], "properties": {"exceededTransferLimit": True}}
    second = json.dumps({**page0, "features": rows[2:]}).encode()
    entities = written(offline("bbsk", "dodavatelia", json.dumps(first).encode(), {1000: second}))
    assert len({e["id"] for e in entities}) == 3, "both rows of page 0 and the row of page 1000"
    assert valid("bbsk", entities)
    # Without the flag the layer said it was whole: nothing else is asked for.
    assert len(written(offline("bbsk", "dodavatelia", json.dumps({**page0, "features": rows[:2]}).encode(), {1000: None}))) == 2


@requires_docker
def test_an_empty_layer_writes_nothing_and_a_failure_fails_the_run_where_it_shows():
    assert written(offline("bbsk", "dodavatelia", b'{"type": "FeatureCollection", "features": []}', {})) == []
    error = offline("bbsk", "dodavatelia", b'{"error": {"code": 400, "message": "Invalid query"}}', {})
    assert b"the layer answered no features: Invalid query" in error.stdout + error.stderr
    page0 = json.loads((FIXTURES / "dodavatelia.json").read_text())
    missing = offline("bbsk", "dodavatelia", json.dumps({**page0, "properties": {"exceededTransferLimit": True}}).encode(), {2000: None})
    assert b"the page at 2000 did not come" in missing.stdout + missing.stderr
    table = offline("banskabystrica", "adresy", b'{"success": false}', {})
    assert b"the catalogue answered no table" in table.stdout + table.stderr


# --- S-JTSK archives (T-4317): the ZIP read whole, its GeoJSON member reprojected to WGS 84 ---

# Control points in S-JTSK (EPSG:5514) and what PROJ 9.5 (GDAL 3.10.0) answers for them with the same
# Helmert shift: `cs2cs +proj=krovak +lat_0=49.5 +lon_0=24.83333333333333 +alpha=30.28813972222222
# +k=0.9999 +x_0=0 +y_0=0 +ellps=bessel +towgs84=485.021,169.465,483.839,7.786342,4.397554,4.102655,0
# +units=m +to +proj=longlat +datum=WGS84`. The first three are vertices of the city's own archives.
CONTROL = [
    ((-417349.9072, -1227405.1559), (19.150454056, 48.745789330)),
    ((-420281.0068, -1222336.9984), (19.105554825, 48.789279679)),
    ((-415867.542, -1226405.1929), (19.169552258, 48.755744569)),
    ((-460000.0, -1250000.0), (18.597394267, 48.513365548)),
    ((-380000.0, -1200000.0), (19.631909576, 49.015474718)),
]


def sjtsk_archive(features: list[dict], extra: dict[str, bytes] | None = None) -> bytes:
    import io
    import zipfile
    doc = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::5514"}},
           "features": features}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (extra or {}).items():
            z.writestr(name, data)
        z.writestr("OE_01_register_adries.geojson", json.dumps(doc, ensure_ascii=False))
    return buf.getvalue()


def near(got: list, want: tuple) -> bool:
    # 2e-7 degrees is under 2 cm: the mapping keeps 7 decimals.
    return abs(got[0] - want[0]) < 2e-7 and abs(got[1] - want[1]) < 2e-7


@requires_docker
def test_an_sjtsk_address_lands_where_proj_puts_it_and_keeps_no_sjtsk_column():
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": list(src)},
              "properties": {"ID": 10170905.0 + i, "ULICA": "Mikuláša Kováča", "OBEC": "Banská Bystrica",
                             "POINT_X": src[0], "POINT_Y": src[1]}} for i, (src, _) in enumerate(CONTROL)]
    entities = run_bytes("banskabystrica", "dtm-bb-register-adries",
                         sjtsk_archive(feats, {"legenda.pdf": b"%PDF-1.4 not data"}))
    assert len(entities) == len(CONTROL), "one address per feature, the PDF beside it read as nothing"
    for e, (_, want) in zip(entities, CONTROL):
        assert e["location"]["value"]["type"] == "Point"
        assert near(e["location"]["value"]["coordinates"], want), e["location"]
        assert e["thoroughfare"]["value"] == ["Mikuláša Kováča"], "CPSV-AP Address (T-4319)"
        assert "pOINTX" not in e and "pOINTY" not in e
        assert schema_errors("banskabystrica", e) == []
    assert len({e["id"] for e in entities}) == len(CONTROL)


@requires_docker
def test_a_line_and_a_polygon_reproject_every_vertex():
    # The street and building registers have no model (T-4319); the address pipeline reprojects
    # whatever geometry an archive's feature has, so it carries the case.
    (a, pa), (b, pb), (c, pc) = CONTROL[:3]
    street = {"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": [[list(a), list(b)]]},
              "properties": {"ID": 1, "ULICA": "Uľanská cesta"}}
    ring = [list(a), list(b), list(c), list(a)]
    house = {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}, "properties": {"ID": 2}}
    out = run_bytes("banskabystrica", "dtm-bb-register-adries", sjtsk_archive([street, house]))
    line, polygon = sorted(out, key=lambda e: e["location"]["value"]["type"])
    assert [[near(p, w) for p, w in zip(x, (pa, pb))] for x in line["location"]["value"]["coordinates"]] == [[True, True]]
    got = polygon["location"]["value"]["coordinates"][0][0]
    assert [near(p, w) for p, w in zip(got, (pa, pb, pc, pa))] == [True] * 4
    assert {e["id"].rsplit("-", 1)[1] for e in out} == {"1", "2"}, [e["id"] for e in out]


@requires_docker
def test_an_archive_without_geojson_writes_nothing():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mapa.pdf", b"%PDF-1.4")
    assert run_bytes("banskabystrica", "dtm-bb-register-adries", buf.getvalue()) == []


def test_an_archive_in_a_crs_no_step_reprojects_stops_the_generator():
    e = {**entry("bb-dtm-bb-register-adries")}
    e["source"] = {**e["source"], "crs": "EPSG:3035"}
    with pytest.raises(SystemExit):
        generate.bento(e, "x", generate.ranges([e]))


# --- the city's ArcGIS layers (T-4317): many layers per dataset, the server answers WGS 84 ---

LAYERED = [e for e in SEEDED if e["source"]["kind"] == "esri-layers"]
PARTS = {e["name"]: generate.parts(e, SLUGS[e["name"]]) for e in LAYERED}
DTM = "https://dtm-banskabystrica.tmapserver.sk/arcgis/rest/services/dtm/DTM_v_1_4_2_3_verejny/MapServer"


def three_layers(rows: tuple[int, int, int]) -> dict:
    """The green areas' entry read from three layers, as a sheet of several layers is."""
    e = entry("bb-dtm-bb-register-verejnej-zelene-1")
    layers = [{"url": f"{DTM}/{n}", "key": f"dtm-{n}", "name": name, "rows": r, "fields": ["typudrzovanezelene"]}
              for n, name, r in zip((57, 23, 26), ("udržiavaná plocha zelene - db", "vodná nádrž - db", "koryto - db"), rows)]
    return {**e, "source": {**e["source"], "layers": layers, "rows": sum(rows)}}


asked: list[tuple[int, int, str]] = []


def layered(text: str, document: bytes, pages: dict[tuple[int, int], bytes | None]) -> subprocess.CompletedProcess:
    """A Bento mapping of an `esri-layers` pipeline over `document`, its further pages answered
    here: `pages[(layer, offset)]` answers, None is a 500, any other page is empty; every request
    is recorded in `asked`."""
    asked.clear()

    class Service(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            layer = int(url.path.rsplit("/", 2)[-2])
            offset = int(urllib.parse.parse_qs(url.query)["resultOffset"][0])
            asked.append((layer, offset, self.headers.get("User-Agent", "")))
            body = pages.get((layer, offset), b'{"type": "FeatureCollection", "features": []}')
            self.send_response(500 if body is None else 200)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        text = text.replace("https://dtm-banskabystrica.tmapserver.sk", f"http://127.0.0.1:{server.server_port}")
        config = {
            "input": {"stdin": {"scanner": {"to_the_end": {}}}},
            "pipeline": yaml.safe_load(text)["pipeline"],
            "rate_limit_resources": [{"label": "pipeline_egress", "local": {"count": 100, "interval": "1s"}}],
            "output": {"stdout": {"codec": "lines"}},
            "logger": {"level": "error"},
        }
        return subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "host", "-e", "JC_ORG_DOMAIN=banskabystrica.sk",
             "-e", "JC_SPACE=banskabystrica-otvorene-data", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh",
             open_data.BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
            input=document, capture_output=True, timeout=300,
        )
    finally:
        server.shutdown()


def generated(e: dict, part: int = 0) -> str:
    one, slug = generate.parts(e, "dtm-bb-register-verejnej-zelene")[part]
    return generate.bento(one, slug, generate.ranges(SEEDED))


def page(features: list[dict], more: bool = False) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features,
                       **({"exceededTransferLimit": True, "properties": {"exceededTransferLimit": True}} if more else {})}).encode()


def test_every_layer_page_asks_wgs84_geojson_of_the_city_host_in_pages_the_server_allows():
    assert sorted(e["name"] for e in LAYERED) == ["bb-dtm-bb-register-statickej-dopravy", "bb-dtm-bb-register-verejnej-zelene-1"]
    for e in LAYERED:
        urls = []
        for part, slug in PARTS[e["name"]]:
            bento = (SEED / e["org"] / f"{e['org']}-od-pipeline-{slug}-bento.yaml").read_text()
            source = yaml.safe_load((SEED / e["org"] / f"{e['org']}-od-datasource-{slug}.yaml").read_text())
            assert source["spec"]["http"]["url"] == generate.source_url(part)
            assert source["spec"]["http"]["headers"]["User-Agent"] == generate.AGENT
            calls = [p["http"] for step in yaml.safe_load(bento)["pipeline"]["processors"] if "switch" in step
                     for case in step["switch"] for p in case["processors"] if "http" in p]
            assert all(c["headers"]["User-Agent"] == generate.AGENT for c in calls)
            urls += [generate.source_url(part), *re.findall(r'"url": "([^"]+)"', bento)]
        assert {u.split("/query?")[0] for u in urls} == {x["url"] for x in e["source"]["layers"]}, e["name"]
        assert len(urls) == len(set(urls)), "no page is read by two pipelines"
        for u in urls:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
            assert u.startswith("https://dtm-banskabystrica.tmapserver.sk/arcgis/rest/services/") and len(u) <= generate.URL_LIMIT
            assert q["outSR"] == ["4326"] and q["f"] == ["geojson"] and int(q["resultRecordCount"][0]) <= 2000
            assert q["outFields"][0].split(",")[0] == "OBJECTID" and q["orderByFields"] == ["OBJECTID"]
        assert not any(c in u.lower() for u in urls for c in ("vkladosoba", "zmenaosoba", "ideditora", "created_user", "last_edited_user"))
    # A sheet with no model names the layers it would read, so it can come back (T-4319).
    removed = next(e for e in MAPPING["datasets"] if e["name"] == "bb-dtm-bb-vyskopis-teran")
    assert removed["status"] == "removed" and f"{DTM}/136" in removed["layers"]


def test_a_large_dataset_is_read_by_several_pipelines_each_under_the_row_bound():
    green = PARTS["bb-dtm-bb-register-verejnej-zelene-1"]  # 8546 rows
    assert [slug for _, slug in green] == ["dtm-bb-register-verejnej-zelene", "dtm-bb-register-verejnej-zelene-p2",
                                           "dtm-bb-register-verejnej-zelene-p3"]
    for e in [*LAYERED, three_layers((22417, 2257, 11388))]:
        parts = generate.parts(e, "x")
        for part, _ in parts:
            pages = part["source"]["pages"]
            held = sum(max(0, min(generate.PAGE, x["rows"] - x["offset"])) for x in pages)
            assert held <= generate.PART_ROWS or len(pages) == 1, (e["name"], held)
        every = [(x["key"], x["offset"]) for part, _ in parts for x in part["source"]["pages"]]
        assert len(every) == len(set(every)) and len(every) == sum(max(1, -(-int(x["rows"] * 1.5) // generate.PAGE))
                                                                   for x in e["source"]["layers"])
    first, second = green[0][0]["source"]["pages"], green[1][0]["source"]["pages"]
    assert (first[0]["offset"], len(first)) == (0, 4) and second[0]["offset"] == 4000
    assert generate.parts(entry("bb-adresy"), "adresy") == [(entry("bb-adresy"), "adresy")]


@requires_docker
def test_a_dataset_of_three_layers_reads_each_layer_and_tags_each_row_with_its_layer():
    fixture = json.loads((FIXTURES / "dtm-vrstevnice.json").read_text())  # 2 rows as the server sent them, more to come
    line = fixture["features"][1]
    reservoir = {"type": "Feature", "id": 1, "geometry": {"type": "Point", "coordinates": [19.15, 48.73]},
                 "properties": {"objectid": 1, "typudrzovanezelene": 2}}
    channel = {**line, "id": 2, "properties": {"objectid": 2}}
    e = three_layers((97, 14, 16))
    entities = written(layered(generated(e), page(fixture["features"], more=True), {(23, 0): page([reservoir]), (26, 0): page([channel])}))
    ids = sorted(x["id"].rsplit(":", 1)[1] for x in entities)
    prefix = "dtm-bb-register-verejnej-zelene-"
    assert ids == [prefix + k for k in ("dtm-23-1", "dtm-26-2", "dtm-57-1", "dtm-57-2")], "object id 1 in two layers, two entities"
    by = {x["id"].rsplit(":", 1)[1]: x for x in entities}
    assert by[prefix + "dtm-23-1"]["typudrzovanezelene"]["value"] == 2
    assert by[prefix + "dtm-23-1"]["vrstva"]["value"] == "vodná nádrž - db"
    assert by[prefix + "dtm-57-2"]["location"]["value"] == line["geometry"], "WGS 84 as the server sent it"
    assert "location" not in by[prefix + "dtm-57-1"], "a row without geometry has no location"
    assert all(schema_errors("banskabystrica", x) == [] for x in entities)
    # The DataSource's page is never asked again; each other layer once, from its first page.
    assert sorted((layer, o) for layer, o, _ in asked) == [(23, 0), (26, 0)]
    assert {agent for _, _, agent in asked} == {generate.AGENT}


@requires_docker
def test_a_part_reads_exactly_its_pages_and_an_empty_one_past_the_end_writes_nothing():
    _, slug = PARTS["bb-dtm-bb-register-verejnej-zelene-1"][1]
    fixture = json.loads((FIXTURES / "dtm-vrstevnice.json").read_text())
    text = (SEED / "banskabystrica" / f"banskabystrica-od-pipeline-{slug}-bento.yaml").read_text()
    entities = written(layered(text, page(fixture["features"][1:]), {}))
    assert len(entities) == 1
    assert sorted(o for layer, o, _ in asked if layer == 57) == [5000, 6000, 7000]


@requires_docker
def test_a_layer_that_fails_or_answers_an_error_fails_the_run():
    fixture = (FIXTURES / "dtm-vrstevnice.json").read_bytes()
    text = generated(three_layers((97, 14, 16)))
    down = layered(text, fixture, {(23, 0): None})
    assert b"did not come" in down.stdout + down.stderr
    error = layered(text, fixture, {(26, 0): b'{"error": {"code": 400, "message": "Invalid query"}}'})
    assert b"the layer dtm-26 answered no features: Invalid query" in error.stdout + error.stderr


@requires_docker
def test_slovak_numbers_and_dates_become_numbers_and_iso_dates(tmp_path):
    """T-4324: the city's tables write "10 700,01" and "29.08.2026". The generated maps read
    them as 10700.01 and 2026-08-29, keep a dotted decimal, and leave text that is no number null."""
    mapping = tmp_path / "maps.yaml"
    probe = "\n".join([
        generate.MAPS,
        'root = this.map_each(kv -> {"float": kv.value.apply("float"), "integer": kv.value.apply("integer"),',
        '                            "date": kv.value.apply("date")})',
    ])
    mapping.write_text(yaml.safe_dump({"pipeline": {"processors": [{"mapping": probe}]}}))
    values = {"price": "10 700,01", "nbsp": "1 234,5", "thousands": "1.234,56", "negative": "-12,5",
              "dotted": "1.5", "number": 12, "text": "abc", "empty": None,
              "signed": "29.08.2026", "spaced": "1. 3. 2024", "iso": "2024-03-01"}
    out = open_data.run(mapping, json.dumps(values).encode(), "s")
    value = lambda key, kind: (out[key][kind] or {}).get("value")
    assert [value(k, "float") for k in ("price", "nbsp", "thousands", "negative", "dotted", "number")] == [
        10700.01, 1234.5, 1234.56, -12.5, 1.5, 12]
    assert value("price", "integer") == 10700
    assert value("text", "float") is None and value("empty", "float") is None and value("signed", "float") is None
    assert [value(k, "date") for k in ("signed", "spaced", "iso")] == ["2026-08-29", "2024-03-01", "2024-03-01"]
    assert value("text", "date") is None


# --- extensions (T-4336): the base whole under allOf, the formalisms beside, the examples valid ---

EXTENDED = {t: e for t, e in (MAPPING.get("extensions") or {}).items() if any(x["type"] == t for x in SEEDED)}
EXTENDED.update(generate.SPACE_EXTENSIONS)  # a city space's own (T-4338), checked the same way


def test_the_mapping_extends_where_no_model_holds_and_refuses_nothing_for_want_of_one():
    # Only the city's DTM sheets (T-4317) still wait for a model; every type T-4319 removed is extended.
    removed = [e["name"] for e in MAPPING["datasets"] if e["status"] == "removed"]
    assert all(n.startswith("bb-dtm-") for n in removed), removed
    assert not [e for e in MAPPING["datasets"] if e["status"] == "removed" and e.get("type") in MAPPING["extensions"]]
    assert {e["type"] for e in MAPPED if e.get("baseModel")} == set(MAPPING["extensions"])
    assert {d.name for d in generate.EXTENSIONS.iterdir()} == set(EXTENDED)


def test_every_extension_keeps_its_base_whole_and_only_renames_the_type():
    for t, ext in EXTENDED.items():
        schema = json.loads((generate.EXTENSIONS / t / "schema.json").read_text())
        base = json.loads((generate.SDM / ext["baseModel"].removeprefix("dataModel.") / "schema.json").read_text())
        whole, added = schema["allOf"]
        kept = {k: v for k, v in base.items() if k not in generate.SDM_HEADER}
        assert json.dumps(whole).replace(f'"enum": ["{t}"]', f'"enum": ["{generate.base_type(base)}"]') == json.dumps(kept), t
        assert set(base.get("required", [])) <= set(whole["required"]), t
        assert added["properties"]["type"]["enum"] == [t]
        assert not set(added["properties"]) - {"type"} & generate.declared(base, json.loads((generate.SDM / "common-schema.json").read_text())["definitions"])


FORMALISMS = ("schema.json", "context.jsonld", "model.linkml.yaml", "model.md", "model.owl.ttl", "model.rdf.ttl",
              "model.shacl.ttl", "examples/example.json", "examples/example-normalized.jsonld")


def test_every_extension_ships_the_seven_formalisms_and_both_examples():
    for t in EXTENDED:
        for f in FORMALISMS:
            path = generate.EXTENSIONS / t / f
            assert path.is_file() and path.stat().st_size > 100, path
        assert f"jc:{t}" in (generate.EXTENSIONS / t / "model.owl.ttl").read_text() or t in (generate.EXTENSIONS / t / "model.owl.ttl").read_text()
        assert "generation_date" not in (generate.EXTENSIONS / t / "model.rdf.ttl").read_text()


def test_every_extension_validates_its_own_examples_and_refuses_a_missing_base_requirement():
    for t, ext in EXTENDED.items():
        example = json.loads((generate.EXTENSIONS / t / "examples/example.json").read_text())
        normalized = {k: v for k, v in json.loads((generate.EXTENSIONS / t / "examples/example-normalized.jsonld").read_text()).items()
                      if k != "@context"}
        assert example["type"] == t and open_data.key_values(normalized) == example, t
        assert sdm_errors(normalized) == [], t
        required = set(json.loads((generate.EXTENSIONS / t / "schema.json").read_text())["allOf"][0]["required"]) - {"id", "type"}
        for a in required:
            assert sdm_errors({k: v for k, v in normalized.items() if k != a}), (t, a)
        base = json.loads((generate.SDM / ext["baseModel"].removeprefix("dataModel.") / "schema.json").read_text())
        assert sdm_errors(dict(normalized, type=generate.base_type(base)), model_of=t), t


@requires_docker
def test_a_grant_without_a_number_takes_its_row_hash_as_the_identifier_its_base_requires():
    """bb-dotacie has no number column; CPSV-AP Cost requires `identifier` (T-4336)."""
    entities = run("banskabystrica", SLUGS["bb-dotacie"], "dotacie")
    assert len(entities) == len({e["id"] for e in entities}) == 3
    for e in entities:
        assert e["type"] == "Grant" and e["id"].endswith(":" + e["identifier"]["value"])
    assert valid("banskabystrica", entities)


# T-4385: what each publisher's catalogue holds once its harvest ran whole. A harvest lists a
# dataset only when od-datasets.json gives its rows an Endpoint (EP-118), one entry per dataset;
# beside them sit the Endpoints the platform publishes itself (`spec.publish.ckan`), into the
# organization of their CkanInstance. dev counted 33 on 2026-10-17 with both harvests dead.
def mapped_rows() -> dict:
    """od-datasets.json less the ŠÚ SR rows, which scripts/open-data/datacube.py writes, not the
    bb-bbsk mapping, and which CKAN lists only once T-4399 publishes them (T-4390)."""
    od = json.loads((ROOT / "charts/ckan/files/od-datasets.json").read_text())
    return {name: row for name, row in od.items() if not name.startswith("susr-")}


def expected_catalogue() -> dict[str, int]:
    od = mapped_rows()
    org_of = {e["name"]: e["org"] for e in MAPPING["datasets"]}
    counts: dict[str, int] = {}
    for name in od:
        counts[org_of[name]] = counts.get(org_of[name], 0) + 1
    # The 45 ŠÚ SR Endpoints publish themselves into slovensko (T-4402, T-4433).
    for path in sorted([*SEED.glob("*/*.yaml"), *SEED.glob("slovensko/susr-*/endpoint.yaml")]):
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == "Endpoint":
                ckan = ((doc.get("spec") or {}).get("publish") or {}).get("ckan")
                if ckan:
                    org = ckan["instanceRef"]["name"]
                    counts[org] = counts.get(org, 0) + 1
    return counts


def test_each_publisher_expects_its_converted_datasets_and_its_endpoints():
    od = mapped_rows()
    mapped = {e["name"] for e in MAPPING["datasets"] if e["status"] == "mapped"}
    assert set(od) <= mapped, "a converted dataset the mapping does not map"
    assert len({entry["dataset"] for entry in od.values()}) == len(od), "one entry per dataset"
    assert expected_catalogue() == {
        "banskabystrica": 13 + 4, "bbsk": 88 + 5, "hel-fi": 11, "praha": 7, "slovensko": 1 + 45, "zilina": 5}


def test_the_rdf_artifacts_are_canonical_whatever_order_a_generator_wrote(tmp_path):
    """T-4437: the same graph, its triples and blank nodes written in two orders as the LinkML
    generators do from run to run, comes out byte-identical, and still the same graph."""
    pytest.importorskip("rdflib")
    from rdflib import Graph
    from rdflib.compare import isomorphic

    one = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/> .
ex:Shape a sh:NodeShape ;
    sh:property [ sh:path ex:b ; sh:maxCount 1 ] , [ sh:path ex:a ; sh:minCount 1 ] .
"""
    two = """@prefix ex: <https://example.org/> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
_:x sh:minCount 1 ; sh:path ex:a .
ex:Shape sh:property _:y , _:x ; a sh:NodeShape .
_:y sh:maxCount 1 ; sh:path ex:b .
"""
    a, b = tmp_path / "a.ttl", tmp_path / "b.ttl"
    a.write_text(one)
    b.write_text(two)
    subprocess.run([sys.executable, "-c", generate.CANONICAL, str(a), str(b)], check=True)
    assert a.read_text() == b.read_text()
    assert isomorphic(Graph().parse(a), Graph().parse(data=one, format="turtle"))
    once = a.read_text()
    subprocess.run([sys.executable, "-c", generate.CANONICAL, str(a)], check=True)
    assert a.read_text() == once
