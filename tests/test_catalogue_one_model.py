"""One catalogue dataset is one Smart Data Model type, or a group of types that reference each other
(T-4344, owner 2026-10-16). Every seeded Endpoint that publishes to CKAN serves only types joined by
relationships, serves every mandatory surface (EP-118), and is narrowed to types the space already
grants the public, under the public role, so a split exposes nothing new."""

from functools import cache
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"

# Which type references which, read from dev's public NGSI-LD on 2026-10-16 (the Relationship
# attributes of up to 100 entities per type of each published Endpoint):
#   GET /api/endpoint/{slug}/ngsi-ld/v1/entities?type={T}&limit=100
# TransitRoute carries no Relationship: it is HSL's stops of one line, keyed by the GtfsRoute's id.
# GtfsShape has no entity on dev yet; GTFS draws a shape for the trips of one route.
REFERENCES = {
    "WasteContainer": {"WasteContainerIsle"},
    "WasteContainerIsle": {"CityDistrict"},
    "GtfsRoute": {"GtfsAgency"},
    "GtfsStop": {"GtfsStation"},
    "TransitRoute": {"GtfsRoute"},
    "GtfsShape": {"GtfsRoute"},
    "Vehicle": {"GtfsStop"},
    "Alert": {"GtfsStop", "GtfsRoute"},
    "OffStreetParking": {"GtfsStation"},
    "WaterQualityObserved": {"PointOfInterest"},
    "PublicAreaPermit": {"CityDistrict"},
}
# What the bundles served before the split; none of them may be a dataset again.
BUNDLES = {"praha-mesto", "helsinki-all", "banskabystrica-verejne", "zilina-verejne", "bbsk-registre"}
MANDATORY = {"ngsi-ld", "mcp", "websocket", "csv", "json"}
# GeoJSON and OGC API Features are mandatory when the data has a location (EP-118); these types have none.
UNLOCATED = {"KeyPerformanceIndicator", "BudgetLine", "NewsArticle", "CreativeWork", "GtfsAgency"}


@cache
def docs(kind: str) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted(SEED.glob("*/*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == kind:
                found.append((path, doc))
    return found


def space_of(spec: dict) -> str:
    ref = spec["contextSpaceRef"]
    return ref["name"] if isinstance(ref, dict) else ref


@cache
def public_policies() -> dict[tuple[str, str], dict[str, dict]]:
    """The public role's Policies, by (project, space), then by name."""
    out: dict[tuple[str, str], dict[str, dict]] = {}
    for _, doc in docs("Policy"):
        spec = doc["spec"]
        if spec["assignee"] == {"kind": "role", "id": "public"}:
            out.setdefault((doc["metadata"]["namespace"], space_of(spec)), {})[doc["metadata"]["name"]] = spec
    return out


def types_of(policy: dict) -> set[str]:
    return {e["type"] for info in policy.get("information", []) for e in info.get("entities", [])}


def published() -> list[tuple[Path, dict, dict[str, dict]]]:
    """Each CKAN-published Endpoint with the public Policies it binds, as the gateway binds them:
    its policyRef's one Policy, else every Policy of its space (store.rs `bound_policy`)."""
    policies = public_policies()
    out = []
    for path, doc in docs("Endpoint"):
        spec = doc["spec"]
        if not spec.get("publish", {}).get("ckan"):
            continue
        of_space = policies.get((doc["metadata"]["namespace"], space_of(spec)), {})
        ref = spec.get("policyRef")
        bound = {n: p for n, p in of_space.items() if ref is None or n == ref.rsplit(":", 1)[1]}
        out.append((path, doc, bound))
    return out


def connected(types: set[str]) -> bool:
    if not types:
        return False
    edges = {t: set() for t in types}
    for a, refs in REFERENCES.items():
        for b in refs:
            if a in types and b in types:
                edges[a].add(b)
                edges[b].add(a)
    seen, todo = set(), [next(iter(types))]
    while todo:
        t = todo.pop()
        if t not in seen:
            seen.add(t)
            todo.extend(edges[t] - seen)
    return seen == types


def test_relationship_check_tells_a_group_from_a_bundle():
    assert connected({"WasteContainerIsle", "WasteContainer"})
    assert connected({"GtfsAgency", "GtfsRoute", "GtfsStop", "GtfsStation", "Vehicle", "Alert", "OffStreetParking", "TransitRoute"})
    assert connected({"BudgetLine"})
    assert not connected({"AirQualityObserved", "Event", "School", "WeatherObserved"})
    assert not connected({"Hospital", "Bridge"})
    assert not connected(set())


def test_every_published_dataset_serves_one_model_or_a_referencing_group():
    rows = published()
    assert len(rows) >= 30
    for path, doc, bound in rows:
        assert bound, f"{path.name}: publishes but binds no public Policy"
        types = set().union(*(types_of(p) for p in bound.values()))
        assert connected(types), f"{path.name}: {sorted(types)} are unrelated types in one dataset"


def test_no_bundle_is_published_any_more():
    names = {doc["metadata"]["name"] for _, doc, _ in published()}
    assert not names & BUNDLES


def test_every_published_dataset_serves_every_mandatory_surface():
    for path, doc, bound in published():
        served = set(doc["spec"]["enabledRepresentations"])
        types = set().union(*(types_of(p) for p in bound.values()))
        mandatory = MANDATORY if types <= UNLOCATED else MANDATORY | {"geojson", "ogc-features"}
        assert mandatory <= served, f"{path.name} lacks {sorted(mandatory - served)}"
        assert "zip" not in served, path.name
        assert doc["spec"]["audience"] == "public", path.name


def test_a_split_policy_grants_nothing_its_space_did_not_grant_the_public():
    policies = public_policies()
    split = [(path, doc) for path, doc in docs("Policy") if "(T-4344)" in path.read_text()]
    assert len(split) >= 24
    for path, doc in split:
        spec = doc["spec"]
        assert spec["assignee"] == {"kind": "role", "id": "public"}, path.name
        assert not spec.get("constraints"), path.name
        others = policies[(doc["metadata"]["namespace"], space_of(spec))]
        wider = set().union(*(types_of(p) for n, p in others.items() if n != doc["metadata"]["name"]))
        assert types_of(spec) <= wider, f"{path.name}: {sorted(types_of(spec) - wider)} were not public"


def test_a_helsinki_part_hides_the_contact_line_as_the_bundle_does():
    for path, doc, _ in published():
        if doc["metadata"]["namespace"] == "helsinki" and doc["spec"].get("projection") is not None:
            assert "contactPoint" in doc["spec"]["projection"]["hiddenAttributes"], path.name
    for path, doc in docs("Endpoint"):
        if path.name.startswith("helsinki-endpoint-") and doc["spec"].get("publish") and doc["spec"].get("policyRef"):
            types = types_of(public_policies()[("helsinki", "helsinki")][doc["spec"]["policyRef"].rsplit(":", 1)[1]])
            if types & {"PointOfInterest", "Event", "BikeHireDockingStation", "PublicAreaPermit", "CityDistrict",
                        "ParkingArea", "ParkingZone", "WaterQualityObserved", "Vehicle", "GtfsStop"}:
                assert "contactPoint" in doc["spec"].get("projection", {}).get("hiddenAttributes", []), path.name


def test_every_endpoint_and_policy_of_the_split_is_in_its_seed_index():
    for path, doc, bound in published():
        index = (path.parent / "index.yaml").read_text()
        assert f"\n{path.name}:" in index, path.name
