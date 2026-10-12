"""The public transport endpoint publishes HSL's transport types and nothing else of the space
(T-3895, EP-14): it evaluates its one Policy, and that Policy names exactly these types, read only."""

from pathlib import Path

import yaml

HELSINKI = Path(__file__).resolve().parent.parent / "components/context-gateway/seed/helsinki"

TRANSPORT = {"Vehicle", "GtfsStop", "TransitRoute", "GtfsStation", "GtfsAgency", "GtfsRoute", "GtfsShape",
             "Alert", "OffStreetParking"}


def load(name: str) -> dict:
    return yaml.safe_load((HELSINKI / name).read_text())


def test_a_public_reader_of_the_endpoint_sees_the_transport_types_and_nothing_else():
    endpoint = load("helsinki-endpoint-transport.yaml")["spec"]
    policy = load("helsinki-policy-public-transport.yaml")
    assert endpoint["audience"] == "public"
    assert endpoint["policyRef"] == f"urn:ngsi-ld:Policy:hel.fi:helsinki:{policy['metadata']['name']}"
    spec = policy["spec"]
    assert spec["assignee"] == {"kind": "role", "id": "public"}
    assert spec["operations"] == ["retrieveOps"]
    granted = [entity["type"] for rule in spec["information"] for entity in rule["entities"]]
    assert sorted(granted) == sorted(TRANSPORT)
    # Every granted type is a class of the space's model, so none is a typo that grants nothing.
    model = load("helsinki.linkml.yaml")
    assert TRANSPORT <= set(model["classes"])
    # The rest of the space (events, bikes, weather, permits, districts...) stays out.
    assert {"Event", "BikeHireDockingStation", "WeatherObserved", "PublicAreaPermit", "CityDistrict"} & set(granted) == set()


def test_the_endpoint_projects_no_internal_attribute_and_credits_its_sources():
    endpoint = load("helsinki-endpoint-transport.yaml")["spec"]
    assert "contactPoint" in endpoint["projection"]["hiddenAttributes"]
    catalog = endpoint["catalog"]
    assert catalog["license"] == "CC_BY_4_0"
    assert "Fintraffic" in catalog["attribution"]["en"] and "HSL" in catalog["attribution"]["en"]
    sources = {source["url"] for source in catalog["source"]}
    assert {"https://hsl.fi/en/hsl/open-data", "https://parking.fintraffic.fi/api/v1"} <= sources
