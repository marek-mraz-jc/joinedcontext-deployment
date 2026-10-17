"""The NGSI-LD open-data catalogue's seed (T-4525, T-4500): one Endpoint named `catalog` on the
space named `catalog`, read by anyone, written only by the Portal reconciler; and a place on
every space whose Dataset the catalogue locates."""

from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
WRITES = {"create", "update", "upsert", "delete", "append", "merge", "replace", "purge"}


def manifests():
    for path in SEED.rglob("*.yaml"):
        if path.name == "index.yaml" or path.name.endswith(".linkml.yaml"):
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and "kind" in doc:
                yield path, doc


def space_of(spec):
    ref = spec.get("contextSpaceRef")
    return ref.get("name") if isinstance(ref, dict) else ref


def test_one_catalog_endpoint_public_on_the_catalog_space_and_placed_in_the_index():
    doors = [(p, d) for p, d in manifests() if d["kind"] == "Endpoint" and d["metadata"]["name"] == "catalog"]
    assert len(doors) == 1, [str(p) for p, _ in doors]
    path, door = doors[0]
    assert space_of(door["spec"]) == "catalog" and door["spec"]["audience"] == "public"
    assert {"ngsi-ld", "mcp"} <= set(door["spec"]["enabledRepresentations"])
    index = yaml.safe_load((path.parent / "index.yaml").read_text())
    placed = {name for name in index if "catalog" in name}
    assert {p.name for p, d in manifests() if d.get("metadata", {}).get("namespace") == "slovensko"
            and ("catalog" in d["metadata"]["name"])} <= placed


def test_anyone_reads_the_catalogue_and_only_the_portal_reconciler_writes_it():
    policies = [d for _, d in manifests() if d["kind"] == "Policy" and space_of(d["spec"]) == "catalog"]
    writers = {(d["spec"]["assignee"]["kind"], d["spec"]["assignee"]["id"]) for d in policies
               if any(any(w in op.lower() for w in WRITES) for op in d["spec"]["operations"])}
    assert writers == {("user", "service-account-portal-reconciler")}
    public = [d for d in policies if d["spec"]["assignee"] == {"kind": "role", "id": "public"}]
    assert public and all(op.startswith("retrieve") for d in public for op in d["spec"]["operations"])
    for d in policies:
        assert {e["type"] for i in d["spec"]["information"] for e in i["entities"]} == {"Dataset", "DataService"}


def test_every_placed_space_has_one_area_in_wgs84():
    placed = {space_of(d["spec"]) for _, d in manifests() if d["kind"] == "Endpoint" and d["spec"].get("audience") == "public"}
    areas = {}
    for _, d in manifests():
        if d["kind"] == "ContextSpace":
            for rule in d["spec"].get("quality") or []:
                if rule["kind"] == "area":
                    areas.setdefault(d["metadata"]["name"], rule["bbox"])
    for name in ["ovzdusie", "banskabystrica-verejne", "banskabystrica-otvorene-data", "bbsk-otvorene-data",
                 "bbsk-registre", "praha-mesto", "ovzdusie-sk", "zilina-verejne", "helsinki"]:
        assert name in placed and name in areas, name
    for name, (w, s, e, n) in areas.items():
        assert -180 <= w < e <= 180 and -90 <= s < n <= 90, name
    # The bb air Dataset's station sits inside its space's area (georel=near around 19.146, 48.736).
    w, s, e, n = areas["ovzdusie"]
    assert w <= 19.146 <= e and s <= 48.736 <= n
