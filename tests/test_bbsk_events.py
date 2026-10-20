"""The events of Slovakia in one space, the Banská Bystrica Region a view of it (T-4895).

The model fits the iCalendar surface (EP-125: the type Event with `name` and `startDate`
required) and the owner's rule that an event without a name, a start or a GPS point is not
published (2026-10-20); the two Endpoints serve the calendar beside NGSI-LD and OGC Features and
publish Event alone; nobody but the pipelines' account writes. These cases read the seed; the live
feed and the anonymous 403 are `dev-smoke`'s ("events calendar"), the rendering is Antares'
crates/antares-ical/tests/ical.rs.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed/bbsk"
SPACE = "bbsk-podujatia"
ENDPOINTS = {"bbsk-podujatia": "podujatia-kraj-read", "bbsk-podujatia-slovensko": "podujatia-read"}
# EP-125's iCalendar requirement (platform crates/jc-core/src/kinds/endpoint.rs ICAL): the source
# attribute of each RFC 5545 field, and the ones the model must mark required.
ICAL_SOURCES = {"startDate", "name", "endDate", "description", "address", "location", "url"}
ICAL_REQUIRED = {"startDate", "name"}
SLOVAKIA = (16.8, 47.7, 22.6, 49.7)


def manifests():
    for path in sorted(SEED.glob("*.yaml")):
        if path.name.endswith(("-bento.yaml", ".linkml.yaml")) or path.name == "index.yaml":
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and "kind" in doc:
                yield path, doc


def of_space(kind):
    return {d["metadata"]["name"]: d for _, d in manifests() if d["kind"] == kind and space_of(d) == SPACE}


def space_of(doc):
    ref = doc.get("spec", {}).get("contextSpaceRef")
    return ref.get("name") if isinstance(ref, dict) else ref


LINKML = yaml.safe_load((SEED / "bbsk-podujatia.linkml.yaml").read_text())
SCHEMA = json.loads((SEED / "bbsk-podujatia.v1.schema.json").read_text())


def event_schema():
    schema = copy.deepcopy(SCHEMA)
    schema.update({"$ref": "#/definitions/Event"})
    return schema


VALID = jsonschema.Draft7Validator(event_schema())


def event(**changes):
    """A key-values Event as the pipelines write it, with `changes` applied (None drops a member)."""
    e = {
        "id": "urn:ngsi-ld:Event:bbsk-podujatia:3f1c2a9b8d7e6f50",
        "type": "Event",
        "name": "Vianočné trhy na námestí",
        "startDate": "2026-12-05T10:00:00+01:00",
        "endDate": "2026-12-05T20:00:00+01:00",
        "location": {"type": "Point", "coordinates": [19.1462, 48.7363]},
        "venue": "Námestie SNP",
        "address": {"addressLocality": "Banská Bystrica", "addressRegion": "Banskobystrický kraj", "addressCountry": "SK"},
        "eventCategory": "trhy",
        "url": "https://www.banskabystrica.sk/podujatia/vianocne-trhy/",
        "source": "https://www.banskabystrica.sk/wp-json/tribe/events/v1/events",
        "sourceId": "4711",
    }
    for key, value in changes.items():
        if value is None:
            e.pop(key, None)
        else:
            e[key] = value
    return e


def inside_slovakia(e):
    lon, lat = e["location"]["coordinates"]
    return SLOVAKIA[0] <= lon <= SLOVAKIA[2] and SLOVAKIA[1] <= lat <= SLOVAKIA[3]


def test_the_space_names_its_one_model_and_keeps_no_history():
    space = of_space("ContextSpace").get(SPACE) or next(
        d for _, d in manifests() if d["kind"] == "ContextSpace" and d["metadata"]["name"] == SPACE)
    assert space["spec"]["dataModelRef"] == {"kind": "DataModel", "name": SPACE}
    assert space["spec"]["retention"] == [{"entityType": "Event", "history": "off"}]
    [rule] = space["spec"]["quality"]
    assert (rule["entityType"], rule["attribute"], tuple(rule["bbox"])) == ("Event", "location", SLOVAKIA)
    [model] = of_space("DataModel").values()
    assert model["spec"]["classes"] == ["Event"] and model["spec"]["lifecycle"] == "published"


def test_the_event_class_fits_the_ical_surface_and_the_owners_required_fields():
    """EP-125 refuses `ical` on a model whose Event leaves name or startDate optional; the owner
    adds the GPS point (2026-10-20). jcctl validate applies the first rule to the Endpoints."""
    cls = LINKML["classes"]["Event"]
    assert cls["class_uri"] == "schema:Event"
    required = {s for s, u in cls["slot_usage"].items() if u.get("required")}
    assert required == ICAL_REQUIRED | {"location"}
    assert ICAL_SOURCES - {"location"} <= set(cls["slots"]) | {"location"}
    assert set(SCHEMA["definitions"]["Event"]["required"]) == {"id", "type", "name", "startDate", "location"}
    # schema.org names, the ones the surface reads (antares-ical mapping.rs).
    slots = LINKML["slots"]
    assert {slots[s]["slot_uri"] for s in ("name", "startDate", "endDate", "description", "url")} == {
        "schema:name", "schema:startDate", "schema:endDate", "schema:description", "schema:url"}


@pytest.mark.parametrize("fixture", [
    pytest.param(event(), id="timed, Europe/Bratislava offset"),
    pytest.param(event(startDate="2026-07-24", endDate="2026-07-24"), id="all-day"),
    pytest.param(event(startDate="2026-07-24", endDate="2026-07-26"), id="multi-day"),
    pytest.param(event(startDate="2026-03-29T01:30:00+01:00", endDate="2026-03-29T03:30:00+02:00"), id="across the DST change"),
    pytest.param(event(endDate=None), id="missing end"),
    pytest.param(event(endDate=None, venue=None, address=None, url=None, eventCategory=None), id="the three required alone"),
])
def test_an_event_the_calendar_serves_is_valid(fixture):
    assert list(VALID.iter_errors(fixture)) == []
    assert inside_slovakia(fixture)


@pytest.mark.parametrize(("fixture", "why"), [
    pytest.param(event(name=None), "'name' is a required property", id="no name"),
    pytest.param(event(startDate=None), "'startDate' is a required property", id="no start"),
    pytest.param(event(location=None), "'location' is a required property", id="no GPS"),
    pytest.param(event(startDate="5. 12. 2026"), "does not match", id="a start that is no date"),
    pytest.param(event(startDate="2026-12-05T10:00:00"), "does not match", id="a time without its offset"),
    pytest.param(event(startDate="2026-12-05T10:00"), "does not match", id="a time without offset or seconds"),
    pytest.param(event(location={"type": "Point"}), "'coordinates' is a required property", id="a point without coordinates"),
])
def test_an_event_without_a_name_a_start_or_a_point_is_refused(fixture, why):
    errors = [e.message for e in VALID.iter_errors(fixture)]
    assert any(why in m for m in errors), errors


def test_a_point_outside_slovakia_is_flagged():
    assert not inside_slovakia(event(location={"type": "Point", "coordinates": [0.0, 0.0]}))
    assert not inside_slovakia(event(location={"type": "Point", "coordinates": [48.7363, 19.1462]})), "lat/lon swapped"


def test_two_endpoints_serve_the_calendar_and_event_alone():
    endpoints = of_space("Endpoint")
    policies = of_space("Policy")
    assert set(endpoints) == set(ENDPOINTS)
    for name, policy in ENDPOINTS.items():
        spec = endpoints[name]["spec"]
        assert spec["audience"] == "public"
        assert {"ngsi-ld", "ogc-features", "ical"} <= set(spec["enabledRepresentations"])
        assert spec["policyRef"] == f"urn:ngsi-ld:Policy:bbsk.sk:{SPACE}:{policy}"
        read = policies[policy]["spec"]
        assert read["assignee"] == {"kind": "role", "id": "public"}
        assert read["information"] == [{"entities": [{"type": "Event"}]}]
        assert not [op for op in read["operations"] if op.endswith(("Batch", "Entity", "Attrs", "Temporal")) or op == "writeOps"]
    assert {e["spec"]["slug"] for e in endpoints.values()}.isdisjoint(
        {d["spec"].get("slug") for _, d in manifests() if d["kind"] == "Endpoint" and space_of(d) != SPACE})


def test_the_region_is_a_scope_view_of_the_national_space():
    """The events exist once (owner 2026-10-20): the region's dataset narrows by scope."""
    policies = of_space("Policy")
    assert policies["podujatia-kraj-read"]["spec"]["scopeQ"] == "/SK/BB/#"
    assert "scopeQ" not in policies["podujatia-read"]["spec"]


def test_only_the_pipelines_write_and_never_delete():
    writers = {n: p["spec"] for n, p in of_space("Policy").items() if p["spec"]["assignee"]["kind"] != "role"}
    assert list(writers) == ["podujatia-pipelines-write"]
    spec = writers["podujatia-pipelines-write"]
    assert spec["assignee"] == {"kind": "serviceAccount", "id": "pipelines"}
    assert set(spec["operations"]) == {"upsertBatch", "createBatch", "queryBatch"}
    assert spec["information"] == [{"entities": [{"type": "Event"}]}]


def test_every_file_is_placed_by_the_index():
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    ours = sorted(p.name for p in SEED.glob("bbsk-*podujatia*"))
    assert len(ours) == 12
    assert [f for f in ours if f not in index] == []
    assert {index[f].split("/spaces/")[1].split("/")[0] for f in ours} == {SPACE}
