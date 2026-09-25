"""The region's own registers in `bbsk-registre` (T-2783, PL-03, DM-01, DM-61, PF-84).

Bento runs each committed mapping over a recorded answer of the URL its DataSource declares,
fetched on 2026-09-25 from the region's ArcGIS FeatureServer and trimmed to a few records
(`fixtures/bbsk/`), and every entity it writes is checked against the space's generated JSON
Schema, which the gateway enforces. The edge cases are those same answers edited in the one place
they name, never an invented feed. The ŠÚ SR cubes of the region are in test_bystrica_pipelines.

Without a container runtime the Bento cases skip; the seed cases do not.
"""

import json
import re
import shutil
import urllib.parse
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-bbsk-open-data")

ROOT = Path(__file__).resolve().parent.parent
BBSK = ROOT / "components/context-gateway/seed/bbsk"
FIXTURES = Path(__file__).resolve().parent / "fixtures/bbsk"
SPACE = "bbsk-registre"

# pipeline -> (the type it writes, how many entities the recording holds)
FEEDS = {
    "okresy": ("AdministrativeArea", 2),
    "obce": ("AdministrativeArea", 3),
    "organizacie": ("PublicOrganization", 4),
    "nemocnice": ("Hospital", 3),
    # Seven rows: one service the register lists three times, identically, is one entity.
    "socialne-sluzby": ("SocialService", 5),
    "mosty": ("Bridge", 6),
}

# Columns of the region's layers that name or reach a person. No DataSource asks for them and no
# mapping reads them, so a value put there never reaches the space.
PERSONAL = {
    "nemocnice": ("Odborný_zástupca", "Telefón_zariadenia_verejný", "E_mail_zariadenia"),
    "socialne-sluzby": ("Email_sociálnej_služby", "Telefón_sociálnej_služby"),
}


def recorded(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def run(pipeline: str, document: bytes) -> list[dict]:
    return open_data.run(BBSK / f"bbsk-pipeline-{pipeline}-bento.yaml", document, SPACE)


def schema_errors(entity: dict) -> list[str]:
    return open_data.schema_errors(BBSK / "bbsk-registre.v1.schema.json", entity)


def edited(name: str, edit) -> bytes:
    document = json.loads(recorded(name))
    edit(document)
    return json.dumps(document, ensure_ascii=False).encode()


def manifest(name: str) -> dict:
    return yaml.safe_load((BBSK / name).read_text())


@pytest.fixture(scope="module")
def written():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(name, recorded(name)) for name in FEEDS}


@requires_docker
def test_every_feed_writes_its_one_type_and_every_record_it_can(written):
    for name, (kind, count) in FEEDS.items():
        assert {e["type"] for e in written[name]} == {kind}, name
        assert len(written[name]) == count, name


@requires_docker
def test_every_entity_is_one_the_gateway_accepts(written):
    for name, entities in written.items():
        for entity in entities:
            assert not schema_errors(entity), (name, entity["id"], schema_errors(entity))


@requires_docker
def test_every_id_is_the_four_segment_urn_of_the_space_and_unique(written):
    for name, entities in written.items():
        ids = [e["id"] for e in entities]
        assert len(ids) == len(set(ids)), name
        for entity in entities:
            assert re.fullmatch(rf"urn:ngsi-ld:{entity['type']}:hel\.fi:{SPACE}:[A-Za-z0-9-]+", entity["id"]), entity["id"]


@requires_docker
def test_every_entity_credits_the_region_and_its_licence(written):
    for entities in written.values():
        for entity in entities:
            assert "Banskobystrický samosprávny kraj" in entity["dataProvider"]["value"], entity["id"]
            assert "CC BY-SA 4.0" in entity["dataProvider"]["value"], entity["id"]
            assert entity["source"]["value"] == "https://opendata.bbsk.sk/", entity["id"]


@requires_docker
def test_an_area_is_keyed_by_the_code_the_statistical_cubes_carry(written):
    """A figure of `bbsk-kraj` has `refArea` `SK0321`; the district it counts is the entity whose
    localId is that code, so an application joins the two without a lookup table."""
    districts = {e["areaCode"]["value"]: e for e in written["okresy"]}
    assert set(districts) == {"SK0321", "SK0323"}
    assert districts["SK0321"]["id"] == f"urn:ngsi-ld:AdministrativeArea:hel.fi:{SPACE}:SK0321"
    assert districts["SK0321"]["name"]["languageMap"] == {"sk": "Okres Banská Bystrica"}
    assert districts["SK0321"]["surfaceArea"] == {"type": "Property", "value": 809438509, "unitCode": "MTK"}
    capital = next(e for e in written["obce"] if e["areaCode"]["value"] == "SK0321508438")
    assert capital["refParentArea"]["object"] == districts["SK0321"]["id"]
    assert {e["location"]["value"]["type"] for e in written["obce"]} == {"Polygon", "MultiPolygon"}


@requires_docker
def test_an_organisation_points_at_its_municipality_and_says_its_field(written):
    categories = {e["organizationCategory"]["value"] for e in written["organizacie"]}
    assert categories == {"school", "socialCare", "culture", "office"}
    for entity in written["organizacie"]:
        assert entity["id"].endswith(":" + entity["legalId"]["value"])
        assert re.fullmatch(rf"urn:ngsi-ld:AdministrativeArea:hel\.fi:{SPACE}:SK032[1-9A-D]\d{{6}}", entity["refMunicipality"]["object"])
        assert entity["location"]["value"]["type"] == "Point"


@requires_docker
def test_a_category_the_model_does_not_know_is_left_out_rather_than_guessed():
    def edit(d):
        d["features"][0]["properties"]["kategória"] = "zdravotníctvo"
    assert len(run("organizacie", edited("organizacie", edit))) == 3


@requires_docker
def test_a_hospital_is_named_by_itself_or_by_its_operator(written):
    by_id = {e["id"].rsplit(":", 1)[1]: e for e in written["nemocnice"]}
    assert {e["hospitalKind"]["value"] for e in by_id.values()} == {"general", "specialised"}
    # GEMERCLINIC registers no name of its own, so the operator's is the one a reader knows.
    gemer = by_id["66-45736987-A0001"]
    assert gemer["name"]["languageMap"]["sk"] == gemer["operatorName"]["value"] == "GEMERCLINIC, n.o."
    assert gemer["address"]["value"] == "Jesenského 102/19, 98101 Hnúšťa"


@requires_docker
def test_a_facility_that_is_no_hospital_is_dropped():
    def edit(d):
        d["features"][0]["properties"]["Druh_zariadenia"] = "ambulancia"
    assert len(run("nemocnice", edited("nemocnice", edit))) == 2


@requires_docker
@pytest.mark.parametrize("name", sorted(PERSONAL))
def test_a_persons_name_telephone_or_e_mail_never_reaches_the_space(name):
    """The DataSource does not ask for these columns; if the layer sent them anyway, the mapping
    still would not read them. The values put there are the shapes a real one has."""
    def edit(d):
        for feature in d["features"]:
            for column in PERSONAL[name]:
                feature["properties"][column] = {
                    "Odborný_zástupca": "MUDr. Jana Testová",
                }.get(column, "+421 900 000 000" if "Telef" in column else "jana.testova@example.sk")
    text = json.dumps(run(name, edited(name, edit)), ensure_ascii=False)
    for value in ("Testová", "+421 900", "jana.testova"):
        assert value not in text, value


@requires_docker
def test_a_service_listed_twice_identically_is_one_entity_and_two_different_ones_are_two(written):
    badan = [e for e in written["socialne-sluzby"] if e["legalId"]["value"] == "00320480"]
    # One outpatient community centre at an address and one field service with none: two.
    assert sorted(e["serviceForm"]["value"] for e in badan) == ["field", "outpatient"]
    assert len({e["id"] for e in badan}) == 2
    kinds = {e["providerKind"]["value"] for e in written["socialne-sluzby"]}
    assert kinds == {"municipality", "municipalityFounded", "regionFounded"}
    assert any(e.get("serviceForm", {}).get("value") == "remote" for e in written["socialne-sluzby"])


@requires_docker
def test_a_service_id_does_not_move_when_the_register_reorders_its_rows():
    def reverse(d):
        d["features"].reverse()
    first = {e["id"] for e in run("socialne-sluzby", recorded("socialne-sluzby"))}
    assert {e["id"] for e in run("socialne-sluzby", edited("socialne-sluzby", reverse))} == first


@requires_docker
def test_a_private_provider_or_a_row_without_an_ico_is_dropped():
    def edit(d):
        d["features"][4]["properties"]["Typ_poskytovateľa"] = "neverejný poskytovateľ"
        d["features"][5]["properties"]["IČO"] = None
    assert len(run("socialne-sluzby", edited("socialne-sluzby", edit))) == 3


@requires_docker
def test_a_bridge_keeps_what_the_databank_states_and_leaves_out_what_it_does_not(written):
    by_code = {e["bridgeCode"]["value"]: e for e in written["mosty"]}
    assert by_code["M529"]["heritageStatus"]["value"] == "cultural"
    assert by_code["M2297"]["heritageStatus"]["value"] == "culturalAndTechnical"
    assert by_code["M9673"]["spanCount"]["value"] == 6
    assert by_code["M9673"]["bridgedLength"] == {"type": "Property", "value": 216.5, "unitCode": "MTR"}
    assert by_code["M9673"]["roadClass"]["value"] == "firstClass"
    # M9609 states no number of openings and no heritage status: neither is written as a guess.
    assert "spanCount" not in by_code["M9609"] and "heritageStatus" not in by_code["M9609"]
    assert by_code["M9609"]["location"]["value"]["type"] == "MultiLineString"
    assert "notListed" in {e.get("heritageStatus", {}).get("value") for e in written["mosty"]}


@requires_docker
def test_an_unknown_road_class_is_left_out_and_a_bridge_without_a_number_is_dropped():
    def edit(d):
        d["features"][0]["properties"]["Trieda_PK"] = "lesná cesta"
        d["features"][1]["properties"]["ID_mosta"] = None
    bridges = run("mosty", edited("mosty", edit))
    assert len(bridges) == 5
    first = next(e for e in bridges if e["bridgeCode"]["value"] == "M529")
    assert "roadClass" not in first and not schema_errors(first)


@requires_docker
def test_an_empty_answer_writes_nothing():
    for name in FEEDS:
        assert run(name, b'{"type": "FeatureCollection", "features": []}') == [], name


def test_a_value_outside_the_model_is_refused_by_the_schema():
    area = {
        "id": f"urn:ngsi-ld:AdministrativeArea:hel.fi:{SPACE}:SK0321",
        "type": "AdministrativeArea",
        "areaCode": {"type": "Property", "value": "SK0421"},
        "divisionLevel": {"type": "Property", "value": "district"},
    }
    assert schema_errors(area), "a code outside the region passed"
    area["areaCode"]["value"] = "SK0321"
    assert not schema_errors(area)
    area["divisionLevel"]["value"] = "region"
    assert schema_errors(area)


def test_every_feed_is_seeded_as_a_datasource_a_pipeline_and_a_mapping():
    index = yaml.safe_load((BBSK / "index.yaml").read_text())
    model = manifest("bbsk-datamodel-registre.yaml")
    public = manifest("bbsk-policy-registre-read.yaml")
    write = manifest("bbsk-policy-registre-pipelines-write.yaml")
    readable = {e["type"] for rule in public["spec"]["information"] for e in rule["entities"]}
    writable = {e["type"] for rule in write["spec"]["information"] for e in rule["entities"]}
    for name, (kind, _) in FEEDS.items():
        pipeline = manifest(f"bbsk-pipeline-{name}.yaml")
        datasource = manifest(f"bbsk-datasource-{name}.yaml")
        assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == datasource["metadata"]["name"]
        assert pipeline["spec"]["output"] == {"type": kind, "mode": "upsert"}
        assert pipeline["spec"]["targetEndpoint"] == "urn:ngsi-ld:Endpoint:bbsk.sk:bbsk-registre:bbsk-registre"
        assert pipeline["spec"]["quotas"]["maxMemoryMb"] <= 256
        assert kind in model["spec"]["classes"] and kind in readable and kind in writable
        for seeded in (f"bbsk-datasource-{name}.yaml", f"bbsk-pipeline-{name}.yaml", f"bbsk-pipeline-{name}-bento.yaml"):
            assert seeded in index, seeded


def test_every_query_names_its_columns_and_none_of_them_reaches_a_person():
    """`outFields=*` would take whatever column the region adds next, a telephone included."""
    for name in FEEDS:
        url = manifest(f"bbsk-datasource-{name}.yaml")["spec"]["http"]["url"]
        assert url.startswith("https://services-eu1.arcgis.com/ODrCBoJHlKVMl3Cg/"), name
        assert url.isascii(), f"{name}: the URL is not percent-encoded"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        fields = query["outFields"][0].split(",")
        assert "*" not in fields, name
        for column in fields:
            assert not re.search(r"(?i)telef|mail|zástupca|štatutár|meno_osoby", column), (name, column)
        assert query["f"] == ["geojson"], name
        if query.get("returnGeometry") != ["false"]:
            assert query["outSR"] == ["4326"], name
    assert "Druh_zariadenia IN" in urllib.parse.unquote(manifest("bbsk-datasource-nemocnice.yaml")["spec"]["http"]["url"])
    assert "neverejný poskytovateľ" in urllib.parse.unquote(manifest("bbsk-datasource-socialne-sluzby.yaml")["spec"]["http"]["url"])


def test_every_register_is_polled_weekly_and_never_resident():
    for name in FEEDS:
        spec = manifest(f"bbsk-pipeline-{name}.yaml")["spec"]
        # PL-26: 30 s or longer is scheduled.
        assert spec["period"] == "168h", name
        assert re.fullmatch(r"\d+ \d+ \* \* 1", spec["schedule"]), name
    schedules = [manifest(f"bbsk-pipeline-{name}.yaml")["spec"]["schedule"] for name in FEEDS]
    assert len(set(schedules)) == len(schedules), "two registers are fetched in the same minute"


def test_the_space_is_public_and_published_under_the_regions_share_alike_licence():
    endpoint = manifest("bbsk-endpoint-registre.yaml")
    space = manifest("bbsk-space-registre.yaml")
    assert endpoint["spec"]["audience"] == "public"
    assert endpoint["spec"]["publish"]["ckan"]["license"] == "cc-by-sa"
    assert endpoint["spec"]["publish"]["ckan"]["instanceRef"]["name"] == "bbsk"
    assert space["spec"]["urnSegment"] == SPACE
    assert space["spec"]["dataModelRef"] == {"kind": "DataModel", "name": "bbsk-registre"}
    for text in (space["metadata"]["description"]["en"], endpoint["metadata"]["description"]["en"]):
        assert "CC BY-SA 4.0" in text and "opendata.bbsk.sk" in text


def test_the_pipelines_client_may_write_the_new_space():
    clients = yaml.safe_load((ROOT / "components/pipeline-runner/keycloak-clients.yaml").read_text())
    audiences = {
        mapper["config"]["included.custom.audience"]
        for mapper in clients["bbsk-pipelines"]["rawValues"]["protocolMappers"]
    }
    assert manifest("bbsk-endpoint-registre.yaml")["spec"]["slug"] in audiences
    roles = manifest("bbsk-serviceaccount-pipelines.yaml")["spec"]["roles"]
    assert {"role": "space-writer", "scope": {"contextSpace": SPACE}} in roles


def test_the_model_classes_and_the_manifest_agree():
    linkml = yaml.safe_load((BBSK / "bbsk-registre.linkml.yaml").read_text())
    model = manifest("bbsk-datamodel-registre.yaml")
    assert linkml["name"] == model["metadata"]["name"]
    assert set(model["spec"]["classes"]) == set(linkml["classes"])
