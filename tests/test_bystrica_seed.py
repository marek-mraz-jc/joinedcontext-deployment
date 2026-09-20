"""The two Banská Bystrica projects are two separate publishers (T-2305, T-2310, PF-54, PF-84, EP-15).

The region and the city publish separately and answer for their own numbers separately, so the
seed keeps them apart: two projects, a raw space and an indicator space each, neither writing
into the other's, and what crosses crosses as a named share that grants reads and nothing else.
These cases read the seed manifests directly; what the cluster does with them is `dev-smoke`'s.
"""

import json
from pathlib import Path

import pytest
import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
REGION = SEED / "bbsk"
CITY = SEED / "banskabystrica"
DOCS = "joinedcontext-docs/Development/10-banska-bystrica-contract.md"

# The artifacts of one LinkML source, committed once per space because a DataModel's artifacts
# sit beside its manifest. The example names its own space and is therefore not in this list.
SHARED_MODEL_FILES = (
    "statistical-observation.linkml.yaml",
    "statistical-observation.v1.schema.json",
    "statistical-observation.v1.context.jsonld",
    "statistical-observation.v1.md",
)


def documents(path: Path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if isinstance(doc, dict)]


def manifests(folder: Path, kind: str):
    for path in sorted(folder.glob("*.yaml")):
        if path.name.endswith("-bento.yaml") or path.name == "index.yaml":
            continue
        for doc in documents(path):
            if doc.get("kind") == kind:
                yield path, doc


def one(folder: Path, kind: str, name: str):
    for path, doc in manifests(folder, kind):
        if doc["metadata"]["name"] == name:
            return doc
    raise AssertionError(f"{folder.name} holds no {kind} named {name}")


def test_the_region_is_its_own_project_and_the_city_says_it_is_the_city():
    region = one(REGION, "Project", "bbsk")
    city = one(CITY, "Project", "banskabystrica")
    assert region["metadata"]["namespace"] == "org"
    # The region has roughly eight times the city's population; a title that does not say which
    # body it is is the error a dashboard cannot show.
    assert region["metadata"]["title"]["sk"] == "Banskobystrický samosprávny kraj"
    assert city["metadata"]["title"]["sk"] == "Mesto Banská Bystrica"
    assert region["spec"]["organizationRef"] == city["spec"]["organizationRef"] == "hel"


def test_each_projects_quotas_hold_exactly_what_it_declares():
    for folder, project, spaces, public in (
        (REGION, "bbsk", ["bbsk-kraj", "bbsk-kpi"], 1),
        (CITY, "banskabystrica", ["ovzdusie", "banskabystrica-mesto", "banskabystrica-kpi"], 1),
    ):
        quotas = one(folder, "Project", project)["spec"]["quotas"]
        declared = {doc["metadata"]["name"] for _, doc in manifests(folder, "ContextSpace")}
        assert declared == set(spaces), folder.name
        assert quotas["contextSpaces"] == len(spaces), folder.name
        endpoints = [doc for _, doc in manifests(folder, "Endpoint")]
        assert sum(e["spec"]["audience"] == "public" for e in endpoints) == public, folder.name
        assert quotas["publicEndpoints"] == public, folder.name


def test_every_new_space_pins_the_segment_its_ids_carry():
    # PF-84: the `{space}` segment is rendered as `{project}-{name}` unless it is pinned, and
    # every space in this seed pins it, so an id cannot change under anyone.
    for folder in (REGION, CITY):
        for path, space in manifests(folder, "ContextSpace"):
            assert space["spec"]["urnSegment"] == space["metadata"]["name"], path.name


def test_the_raw_spaces_are_not_public_and_the_indicators_of_the_region_are():
    assert one(REGION, "Endpoint", "bbsk-kraj")["spec"]["audience"] == "organization"
    assert one(CITY, "Endpoint", "banskabystrica-mesto")["spec"]["audience"] == "organization"
    assert one(REGION, "Endpoint", "bbsk-kpi")["spec"]["audience"] == "public"


def test_the_citys_indicators_reach_the_region_by_a_named_share_and_nothing_wider():
    endpoint = one(CITY, "Endpoint", "banskabystrica-kpi")
    assert endpoint["spec"]["audience"] == "project-list"
    assert endpoint["spec"]["allowedProjects"] == ["bbsk"]

    share = one(REGION, "SharedSpaceReference", "mesto-kpi")
    assert "endpointSlug" not in share["spec"], "inside one organization a share names its endpoint (EP-77)"
    assert share["spec"]["endpointRef"] == {"project": "banskabystrica", "name": "banskabystrica-kpi"}

    # Read and nothing else: the region cannot write a city number.
    grant = one(CITY, "Policy", "kpi-shared-read")
    assert grant["spec"]["assignee"] == {"kind": "group", "id": "bbsk"}
    assert grant["spec"]["operations"] == ["retrieveOps"]
    assert grant["spec"]["information"][0]["entities"] == [{"type": "KeyPerformanceIndicator"}]


def test_no_service_account_can_write_into_the_other_bodys_space():
    for folder, project, own in (
        (REGION, "bbsk", {"bbsk-kraj", "bbsk-kpi"}),
        (CITY, "banskabystrica", {"banskabystrica-mesto", "banskabystrica-kpi"}),
    ):
        account = one(folder, "ServiceAccount", "pipelines")
        scopes = {role["scope"]["contextSpace"] for role in account["spec"]["roles"]}
        assert scopes == own, f"{project} writes only its own spaces"
        for path, policy in manifests(folder, "Policy"):
            if policy["spec"].get("assignee", {}).get("kind") != "serviceAccount":
                continue
            assert policy["spec"]["contextSpaceRef"]["name"] in own | {"ovzdusie"}, path.name


def test_every_endpoint_slug_is_unguessable_and_unique():
    slugs = [
        (path.name, doc["spec"]["slug"])
        for folder in (REGION, CITY, SEED / "helsinki")
        for path, doc in manifests(folder, "Endpoint")
        if "slug" in doc["spec"]
    ]
    for name, slug in slugs:
        # EP-02: at least 128 bits, lowercase RFC 4648 base32 without padding.
        assert len(slug) >= 26, name
        assert set(slug) <= set("abcdefghijklmnopqrstuvwxyz234567"), name
    assert len({slug for _, slug in slugs}) == len(slugs), "two endpoints share a slug"


def test_the_indicator_spaces_grant_only_the_indicator_type():
    for folder, names in ((REGION, ["kpi-pipelines-write", "kpi-read"]),
                          (CITY, ["kpi-pipelines-write", "kpi-shared-read"])):
        for name in names:
            policy = one(folder, "Policy", name)
            assert policy["spec"]["information"][0]["entities"] == [
                {"type": "KeyPerformanceIndicator"}
            ], f"{folder.name}/{name}"


def test_both_copies_of_the_statistical_model_are_the_same_file():
    # One LinkML source, two spaces, so two committed copies of its artifacts. They are copied
    # rather than generated twice, and this is what stops them drifting.
    for name in SHARED_MODEL_FILES:
        assert (REGION / name).read_bytes() == (CITY / name).read_bytes(), name


def test_each_example_entity_names_its_own_space_and_the_contract_url_shape():
    for folder, space, domain in ((REGION, "bbsk-kraj", "bbsk.sk"),
                                  (CITY, "banskabystrica-mesto", "banskabystrica.sk")):
        example = json.loads((folder / "statistical-observation.v1.example.jsonld").read_text())
        assert example["type"] == "StatisticalObservation"
        segments = example["id"].split(":")
        assert segments[:5] == ["urn", "ngsi-ld", "StatisticalObservation", domain, space], folder.name
        assert len(segments) == 6, f"{DOCS} fixes four segments after the scheme"
        # The localId is the publisher's own key: cube, territory, period, indicator.
        cube, area, period, indicator = segments[5].split("-")[:4]
        assert example["dataSet"]["value"] == cube
        assert example["refArea"]["value"] == area
        assert example["refPeriod"]["value"] == period
        assert example["indicator"]["value"] == indicator
        # A row that cannot be fetched again is not a row.
        assert example["source"]["value"].startswith("https://")
        assert cube in example["source"]["value"]


def key_values(entity: dict) -> dict:
    """The entity as `keyValues`, which is the shape the generated JSON Schema describes.

    The committed example is normalised NGSI-LD, one object per attribute; the LinkML generator
    renders the simplified projection. Reducing the one to the other is what makes the two
    comparable, and it is the same reduction the gateway serves under `options=keyValues`.
    """
    out = {}
    for name, attribute in entity.items():
        if not isinstance(attribute, dict) or "type" not in attribute:
            out[name] = attribute
        elif attribute["type"] == "Relationship":
            out[name] = attribute["object"]
        else:
            out[name] = attribute["value"]
    return out


def test_every_example_validates_against_the_model_it_was_generated_from():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REGION / "statistical-observation.v1.schema.json").read_text())
    validator = jsonschema.Draft7Validator(schema["definitions"]["StatisticalObservation"])
    for folder in (REGION, CITY):
        example = json.loads((folder / "statistical-observation.v1.example.jsonld").read_text())
        # The wire carries `@context`; the model describes the entity inside it.
        del example["@context"]
        errors = sorted(validator.iter_errors(key_values(example)), key=str)
        assert not errors, f"{folder.name}: {[e.message for e in errors]}"


def test_an_attribute_the_model_does_not_declare_is_refused():
    # The model closes the object, which is what keeps an invented column out of a raw space.
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REGION / "statistical-observation.v1.schema.json").read_text())
    example = json.loads((REGION / "statistical-observation.v1.example.jsonld").read_text())
    del example["@context"]
    invented = key_values(example) | {"territory": "kraj"}
    errors = list(jsonschema.Draft7Validator(schema["definitions"]["StatisticalObservation"]).iter_errors(invented))
    assert errors and "territory" in errors[0].message


def test_the_seed_index_lists_every_file_beside_it():
    for folder in (REGION, CITY):
        index = yaml.safe_load((folder / "index.yaml").read_text())
        listed = set(index)
        on_disk = {
            path.name
            for path in folder.iterdir()
            if path.is_file() and path.name not in {"index.yaml", "README.md"}
        }
        assert listed == on_disk, f"{folder.name}: {listed ^ on_disk}"
        assert len(set(index.values())) == len(index), f"{folder.name}: two files share a path"
