"""Every hand-written seeded Endpoint serves WebSocket notifications and OGC API Features, and every
Policy a person or the public reads through grants the subscription operations a WebSocket needs
(T-4073, EP-104, EP-106). No entity write rides along: a reader keeps the entity operations it had.

App Endpoints (`generated-by: portal/app-reconciler`) are compiled from their App's dataNeeds: they
serve `ogc-features` too (T-4074), and `websocket` only where the App asks, since a subscription
operation is a write for an App (AP-09)."""

from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
SUBSCRIPTIONS = {"createSubscription", "retrieveSubscription", "updateSubscription", "deleteSubscription"}
READS = {"retrieveOps", "queryEntity", "retrieveEntity"}
# The only entity write a reader Policy holds: a steward's correction of a docking station.
READER_WRITES = {"updateAttrs"}
ENTITY_WRITES = {
    "createEntity", "updateEntity", "appendAttrs", "updateAttrs", "deleteAttrs", "deleteEntity", "createBatch",
    "upsertBatch", "updateBatch", "deleteBatch", "mergeEntity", "replaceEntity", "replaceAttrs", "mergeBatch",
    "purgeEntity", "upsertTemporal", "appendAttrsTemporal", "deleteAttrsTemporal", "updateAttrInstanceTemporal",
    "deleteAttrInstanceTemporal", "deleteTemporal", "writeOps",
}
# The open-data catalogue is no dataset (Architecture/21 §10, T-4525): its door serves NGSI-LD and
# MCP for an agent's first call, no WebSocket or OGC Features, so its public reader holds no
# subscription operation; its one writer is the Portal reconciler, which lists what it wrote and
# so holds retrieveOps beside its batch writes. These three files, and only these, are outside
# the dataset rules below.
CATALOGUE = {
    "slovensko-endpoint-catalog.yaml",
    "slovensko-policy-catalog-public-read.yaml",
    "slovensko-policy-catalog-portal-write.yaml",
}


def manifests(kind: str, generated: bool = False) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted(SEED.glob("*/*.yaml")):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if isinstance(doc, dict) and doc.get("kind") == kind:
                by = doc["metadata"].get("annotations", {}).get("joinedcontext.com/generated-by")
                if (by == "portal/app-reconciler") == generated and path.name not in CATALOGUE:
                    found.append((path, doc))
    return found


def readers() -> list[tuple[Path, dict]]:
    return [(path, doc) for path, doc in manifests("Policy")
            if doc["spec"]["assignee"]["kind"] != "serviceAccount" and READS & set(doc["spec"]["operations"])]


def test_every_seeded_endpoint_serves_websocket_and_ogc_features():
    endpoints = manifests("Endpoint")
    assert len(endpoints) >= 23
    for path, doc in endpoints:
        assert {"websocket", "ogc-features"} <= set(doc["spec"]["enabledRepresentations"]), path.name


def test_every_reader_policy_grants_the_subscription_operations():
    policies = readers()
    assert len(policies) >= 23
    for path, doc in policies:
        assert SUBSCRIPTIONS <= set(doc["spec"]["operations"]), path.name


def test_an_endpoint_naming_its_policy_names_a_reader_that_subscribes():
    by_urn = {}
    for _, doc in manifests("Policy"):
        meta = doc["metadata"]
        by_urn[meta["name"]] = doc
    named = [(path, doc) for path, doc in manifests("Endpoint") if doc["spec"].get("policyRef")]
    assert named
    for path, doc in named:
        policy = by_urn[doc["spec"]["policyRef"].rsplit(":", 1)[1]]
        assert SUBSCRIPTIONS <= set(policy["spec"]["operations"]), path.name


def test_no_reader_policy_gains_an_entity_write():
    for path, doc in readers():
        spec = doc["spec"]
        writes = ENTITY_WRITES & set(spec["operations"])
        assert writes <= READER_WRITES, path.name
        if writes:
            assert spec["assignee"]["kind"] == "user", path.name


def test_every_app_endpoint_serves_ogc_features():
    endpoints = manifests("Endpoint", generated=True)
    assert len(endpoints) >= 18
    for path, doc in endpoints:
        assert "ogc-features" in doc["spec"]["enabledRepresentations"], path.name


def test_the_catalogue_exception_names_files_that_exist():
    assert {path.name for path in SEED.glob("*/*.yaml")} >= CATALOGUE


# The file representations an Endpoint no longer publishes: file.csv and the APIs stay (owner
# 2026-10-18, T-4597, T-4601). The gateway refuses a manifest naming one.
REMOVED = {"xlsx", "parquet", "json", "zip", "geojson"}
APPS = SEED.parent.parent / "gitea/apps"


def test_no_seed_or_app_names_a_removed_representation():
    found = []
    for path in sorted([*SEED.rglob("*.yaml"), *APPS.rglob("*.yaml")]):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        stack = [d for d in docs if d is not None]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("enabledRepresentations", "disabledRepresentations", "representations") \
                            and isinstance(value, list):
                        found += [f"{path.relative_to(SEED.parent.parent)}: {key} {v}" for v in value if v in REMOVED]
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    assert len(list(APPS.rglob("app.yaml"))) > 0
    assert not found, found
