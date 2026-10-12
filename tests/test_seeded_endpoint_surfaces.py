"""Every hand-written seeded Endpoint serves WebSocket notifications and OGC API Features, and every
Policy a person or the public reads through grants the subscription operations a WebSocket needs
(T-4073, EP-104, EP-106). No entity write rides along: a reader keeps the entity operations it had.

App Endpoints (`generated-by: portal/app-reconciler`) are compiled from their App's dataNeeds and
are left to the App (T-4074): a subscription operation is a write there (AP-09)."""

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


def manifests(kind: str) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted(SEED.glob("*/*.yaml")):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if isinstance(doc, dict) and doc.get("kind") == kind:
                generated = doc["metadata"].get("annotations", {}).get("joinedcontext.com/generated-by")
                if generated != "portal/app-reconciler":
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
