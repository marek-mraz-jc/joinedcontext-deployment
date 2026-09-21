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
DEMO_USERS = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "components/keycloak/demo-users.yaml").read_text()
)
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


# The steward's note (T-2434): the one attribute of a published row a person may write, and the
# grants around it. Every figure in these spaces belongs to a publisher and is rewritten by the
# next pipeline run, so an application that offered one for editing would lose what a person
# typed without telling them. The note is what makes the two records applications possible.
NOTE = "stewardNote"

# What the models' own artifacts are, per folder: the LinkML source and the three generated or
# hand-written files that a published DataModel commits beside it (DM-02).
MODEL = "statistical-observation"


def model_slots(folder: Path) -> list[str]:
    """The slots the class declares, in the order the LinkML source lists them."""
    source = yaml.safe_load((folder / f"{MODEL}.linkml.yaml").read_text())
    return list(source["classes"]["StatisticalObservation"]["slots"])


def policies_of(folder: Path, space: str) -> dict[str, dict]:
    return {
        doc["metadata"]["name"]: doc["spec"]
        for _, doc in manifests(folder, "Policy")
        if doc["spec"]["contextSpaceRef"]["name"] == space
    }


RAW = ((REGION, "bbsk-kraj", "kraj"), (CITY, "banskabystrica-mesto", "mesto"))


def test_both_models_declare_the_one_attribute_no_pipeline_writes():
    for folder, _, _ in RAW:
        assert NOTE in model_slots(folder), folder.name
    # A pipeline that wrote it would take the words back on its next run without a word. None
    # does: the mappings produce the publisher's own columns and stop there. The upsert itself
    # is `?options=update` (joinedcontext-portal src/reconciler/streams.rs), so a run that does
    # not mention the note leaves the note where it is.
    for folder in (REGION, CITY):
        for path in sorted(folder.glob("*-bento.yaml")):
            assert NOTE not in path.read_text(), path.name


def test_every_slot_the_model_declares_reaches_the_artifacts_beside_it():
    # The generator's files are committed, not rendered at read time (seed README), so this is
    # what catches a source edited without `gen_json_schema.py` and `gen_context.py` being run.
    for folder, _, _ in RAW:
        schema = json.loads((folder / f"{MODEL}.v1.schema.json").read_text())
        context = json.loads((folder / f"{MODEL}.v1.context.jsonld").read_text())["@context"]
        docs = (folder / f"{MODEL}.v1.md").read_text()
        declared = schema["definitions"]["StatisticalObservation"]["properties"]
        for slot in model_slots(folder):
            assert slot in declared, f"{folder.name}: {slot} is not in the JSON Schema"
            assert slot in context, f"{folder.name}: {slot} is not in the @context"
            assert f"| `{slot}` |" in docs, f"{folder.name}: {slot} is not in the docs page"


def test_the_note_is_optional_and_bounded_and_the_figures_stay_required():
    for folder, _, _ in RAW:
        entity = json.loads((folder / f"{MODEL}.v1.schema.json").read_text())["definitions"][
            "StatisticalObservation"
        ]
        assert NOTE not in entity["required"], "a row exists before anybody annotates it"
        assert "value" in entity["required"], folder.name
        note = entity["properties"][NOTE]
        # The gateway validates every write against this schema (CC-12), so the bound on a
        # free-text attribute is here and not only in the application that offers the field.
        assert note["pattern"] == "^[^<>]{0,500}$", folder.name
        assert note["type"] == ["string", "null"], folder.name


def test_serving_the_note_is_a_minor_version_of_a_published_model():
    for folder, _, _ in RAW:
        model = one(folder, "DataModel", MODEL)
        assert model["spec"]["version"] == "1.1.0", folder.name
        assert model["spec"]["lifecycle"] == "published", folder.name
        # An added optional attribute is backwards compatible, so the major version and the
        # artifact filenames it names do not move.
        assert model["spec"]["artifacts"]["jsonSchema"] == f"./{MODEL}.v1.schema.json", folder.name
        assert f"`{MODEL}` 1.1.0" in (folder / f"{MODEL}.v1.md").read_text(), folder.name


def test_a_person_may_write_the_note_and_may_not_write_a_figure():
    for folder, space, name in RAW:
        grant = policies_of(folder, space)[f"{name}-steward-note"]
        assert grant["operations"] == ["updateAttrs"], f"{folder.name}: one write and no other"
        assert grant["assignee"]["kind"] == "user", folder.name
        assert grant["information"] == [
            {"entities": [{"type": "StatisticalObservation"}], "propertyNames": [NOTE]}
        ], f"{folder.name}: the grant names the attribute, not the type (EP-14, GW16)"


def test_no_grant_in_these_projects_lets_a_person_write_a_published_figure():
    # The property that has to hold however many policies are added later: a human write grant
    # over a raw space reaches the note and nothing else, so `value` cannot be edited by anyone
    # whose typing the next pipeline run would overwrite (AP-62, GW17).
    writes = {"createEntity", "updateEntity", "appendAttrs", "updateAttrs", "deleteAttrs",
              "deleteEntity", "mergeEntity", "replaceEntity", "replaceAttrs", "updateOps",
              "redirectionOps", "createBatch", "upsertBatch", "updateBatch", "deleteBatch"}
    for folder, space, _ in RAW:
        for name, spec in policies_of(folder, space).items():
            if spec["assignee"]["kind"] not in {"user", "group", "role"}:
                continue
            if not writes.intersection(spec["operations"]):
                continue
            granted = [info.get("propertyNames") for info in spec.get("information", [])]
            assert granted == [[NOTE]], f"{folder.name}/{name} grants a person more than the note"


def test_the_steward_reads_the_columns_the_records_application_shows():
    for folder, space, name in RAW:
        grant = policies_of(folder, space)[f"{name}-steward-read"]
        assert grant["operations"] == ["retrieveOps"], f"{folder.name}: reading and nothing else"
        served = grant["information"][0]["propertyNames"]
        # Every column the model declares, because a filter names an attribute and an attribute
        # the grant withholds is a filter the endpoint refuses rather than answers (T-1862).
        assert sorted(served) == sorted(model_slots(folder)), folder.name
        assert grant["information"][0]["entities"] == [{"type": "StatisticalObservation"}]


def test_the_raw_endpoints_stay_closed_to_the_public_while_the_note_opens():
    # The note is a grant on a space, not a wider door: both raw endpoints keep the audience
    # they had, and the city's public air endpoint is still the only public one it has.
    assert one(REGION, "Endpoint", "bbsk-kraj")["spec"]["audience"] == "organization"
    assert one(CITY, "Endpoint", "banskabystrica-mesto")["spec"]["audience"] == "organization"
    assert one(CITY, "Endpoint", "public-air")["spec"]["audience"] == "public"
def test_a_public_endpoint_serves_a_tabular_representation_and_says_what_it_is():
    """T-2432, EP-62..EP-64: what the open-data catalogue needs from a public endpoint.

    A dataset's preview, its filtered API and SQL over its rows are the CKAN DataStore sheet, and
    the sheet is filled by reading the endpoint's own tabular representation as an ordinary
    consumer. An endpoint that serves none can carry links and nothing else. The dataset's title
    and notes are the endpoint's `metadata.title` and `metadata.description`, mapped through its
    DCAT-AP record, so an endpoint without them lands in the catalogue named after its manifest.
    """
    public = [
        (folder.name, path, doc)
        for folder in (REGION, CITY)
        for path, doc in manifests(folder, "Endpoint")
        if doc["spec"].get("audience") == "public"
    ]
    assert public, "neither project has a public endpoint to publish"
    for project, path, doc in public:
        where = f"{project}/{path.name}"
        representations = doc["spec"].get("enabledRepresentations", [])
        assert "csv" in representations, f"{where}: no tabular representation, so no sheet is possible"
        for field in ("title", "description"):
            text = doc["metadata"].get(field)
            assert isinstance(text, dict) and text.get("sk"), f"{where}: no Slovak {field} for the dataset page"
            assert text.get("en"), f"{where}: no English {field} beside the Slovak one"


def test_every_space_is_named_by_a_model_so_the_portal_can_say_what_is_in_it():
    """A space no model names shows a viewer nothing, however full it is (T-2450).

    The Portal's look-inside view lists a space's entity types from the DataModels that name it:
    `DataModel.spec.contextSpaceRef` is the required half of the link, and a space's own
    `dataModelRef` is an optional pointer at the primary one. Both indicator spaces held their
    indicators for a day with no model naming them, so the view said "nothing here" over a full
    space and the demonstration's third step had nothing to show.
    """
    for folder in (REGION, CITY):
        spaces = {doc["metadata"]["name"] for _, doc in manifests(folder, "ContextSpace")}
        named = {doc["spec"]["contextSpaceRef"] for _, doc in manifests(folder, "DataModel")}
        assert spaces, f"{folder.name} declares no ContextSpace"
        assert spaces <= named, f"{folder.name}: no DataModel names {sorted(spaces - named)}"


def test_the_indicator_model_states_the_contract_the_platform_enforces():
    """The published schema closes the object and requires all seven; the model says the same.

    A model that let an indicator carry `state` or `threshold` would describe a document the
    gateway refuses before it is stored, which is worse than no model at all (Development/10 §4).
    """
    required = {"name", "currentValue", "calculationPeriod", "calculationFormula",
                "derivedFrom", "computedBy", "updatedAt"}
    for folder in (REGION, CITY):
        schema = json.loads((folder / "key-performance-indicator.v1.schema.json").read_text())
        entity = (schema.get("$defs") or schema["definitions"])["KeyPerformanceIndicator"]
        assert entity["additionalProperties"] is False, f"{folder.name}: the object is left open"
        assert required <= set(entity["required"]), f"{folder.name}: {sorted(required - set(entity['required']))} not required"
        assert not ({"state", "threshold"} & set(entity["properties"])), \
            f"{folder.name}: the model declares an attribute the gateway refuses"


def test_every_space_the_portal_shows_is_one_its_own_steward_may_read():
    """T-2456: a body's own person reads the body's own space, indicators included.

    `banskabystrica-kpi` had two grants and neither was a human's — the pipelines write and the
    region reads through the share — so the city's steward opened the space in the Portal and got
    `403` for every row of the numbers the city itself publishes. The demonstration walks into
    each of these four spaces, so each one needs a read a signed-in person actually holds.
    """
    for folder in (REGION, CITY):
        for _, space in manifests(folder, "ContextSpace"):
            name = space["metadata"]["name"]
            readers = [
                (policy_name, spec["assignee"])
                for policy_name, spec in policies_of(folder, name).items()
                if "retrieveOps" in spec["operations"]
            ]
            human = [
                policy_name
                for policy_name, assignee in readers
                if assignee["kind"] == "user"
                or (assignee["kind"] == "role" and assignee["id"] == "public")
            ]
            assert human, f"{name} is readable by no signed-in person: {readers}"

            # And the person the grant names gets past the door in front of it. The gateway
            # resolves a human's project out of the `groups` claim and refuses an endpoint whose
            # audience is a list of projects before it reads any Policy at all
            # (context-gateway app.rs, EP-14, EP-15), so a read granted to somebody in no group
            # of the project is a `403` that looks exactly like a missing grant.
            endpoints = [
                spec
                for _, doc in manifests(folder, "Endpoint")
                for spec in [doc["spec"]]
                if spec["contextSpaceRef"] == name
            ]
            for endpoint in endpoints:
                if endpoint["audience"] != "project-list":
                    continue
                admitted = {folder.name, *endpoint.get("allowedProjects", [])}
                for policy_name, assignee in readers:
                    if assignee["kind"] != "user":
                        continue
                    user = assignee["id"].split("@")[0]
                    groups = set(DEMO_USERS.get(user, {}).get("groups", []))
                    assert groups & admitted, (
                        f"{policy_name} grants {user} a read on {name}, whose endpoint admits"
                        f" {sorted(admitted)} and whose groups are {sorted(groups)}"
                    )


def test_the_application_reading_both_bodies_is_a_published_static_app_on_the_regions_space():
    """T-2457: the Portal serves only an App the configuration repository holds, and it configures
    it with the Endpoints on the spaces its dataNeeds name plus those its project's shares name."""
    app = one(REGION, "App", "bbsk-ukazovatele")
    assert app["metadata"]["namespace"] == "bbsk"
    assert app["spec"]["kind"] == "static"
    assert app["spec"]["lifecycle"] == "published"
    spaces = {need["contextSpaceRef"]["name"] for need in app["spec"]["dataNeeds"]}
    assert spaces == {"bbsk-kpi"}
    assert one(REGION, "Endpoint", "bbsk-kpi")["spec"]["contextSpaceRef"] == "bbsk-kpi"
    # It reads and never writes (AP-07).
    operations = {op for need in app["spec"]["dataNeeds"] for op in need["operations"]}
    assert operations <= {"queryEntity", "retrieveEntity"}, operations


# What the city and the region cleared for the open-data catalogue (T-2407, user 2026-09-21):
# these two and nothing else, until the other endpoints are reviewed. `public-air` is held back
# while its space holds Helsinki test stations rather than the city's readings (T-2407 body).
CLEARED = {("banskabystrica", "public-air"), ("bbsk", "bbsk-kpi")}
HELD = {("banskabystrica", "public-air")}


def test_only_the_cleared_endpoints_publish_each_to_its_own_bodys_catalogue():
    """T-2407: a publication is a step past "reachable at a URL", so it is the city's call."""
    published = set()
    for folder in (CITY, REGION):
        instances = {doc["metadata"]["name"]: doc for _, doc in manifests(folder, "CkanInstance")}
        for _, endpoint in manifests(folder, "Endpoint"):
            ckan = endpoint["spec"].get("publish", {}).get("ckan")
            if ckan is None:
                continue
            project = endpoint["metadata"]["namespace"]
            published.add((project, endpoint["metadata"]["name"]))
            assert endpoint["spec"]["audience"] == "public", endpoint["metadata"]["name"]
            instance = instances[ckan["instanceRef"]["name"]]
            # Each body lands in its own organization, never in hel-fi's.
            assert instance["metadata"]["namespace"] == project
            assert ckan.get("organization", instance["spec"]["organizationDefault"]) == project
            # A DataStore sheet is read through a representation the endpoint serves.
            if "datastore" in ckan:
                assert ckan["datastore"]["representation"] in endpoint["spec"]["enabledRepresentations"]
            # The token is a reference, never a value.
            assert set(instance["spec"]["apiTokenRef"]) <= {"name", "key", "envVar"}
    assert published == CLEARED - HELD
