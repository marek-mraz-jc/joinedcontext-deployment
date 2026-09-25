"""T-2873: no demo work and no city dataset is refused by a quota (owner, 2026-09-25, PF-73).

The praha project on dev refused its pipelines at a resident quota of one. Every Project and
Organization the seed ships allows at least 100 context spaces, pipelines, public endpoints and
apps, and runtime ceilings a city dataset does not reach. The quota stays as the mechanism:
each dimension is still set, so a project the Portal opens later still has one to raise.
"""

from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"

FLOORS = {
    "contextSpaces": 100,
    "residentPipelines": 100,
    "publicEndpoints": 100,
    "apps": 100,
    "ingestEventsPerSecond": 500,
    "agentRunsPerDay": 2000,
    "entitiesPerSpace": 1_000_000,
    "requestsPerMinute": 6000,
}


def seeded_quotas() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(SEED.rglob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "Project" and "quotas" in doc.get("spec", {}):
                found.append((path.relative_to(SEED).as_posix(), doc["spec"]["quotas"]))
            elif doc.get("kind") == "Organization" and "quota" in doc.get("spec", {}).get("projects", {}):
                found.append((path.relative_to(SEED).as_posix(), doc["spec"]["projects"]["quota"]))
    return found


def short_of_the_floor(quota: dict) -> list[str]:
    return [
        f"{dimension} is {quota.get(dimension)!r}, below {floor}"
        for dimension, floor in FLOORS.items()
        if not isinstance(quota.get(dimension), int) or quota[dimension] < floor
    ]


def test_every_seeded_quota_leaves_room_for_the_demo():
    quotas = seeded_quotas()
    # praha, the two Bystrica projects, helsinki-mobility and the helsinki organization.
    assert len(quotas) >= 5, quotas
    problems = [f"{path}: {p}" for path, quota in quotas for p in short_of_the_floor(quota)]
    assert not problems, "\n".join(problems)


def test_a_quota_as_small_as_the_one_that_refused_praha_is_named():
    refused_on_dev = dict(FLOORS, residentPipelines=1)
    assert short_of_the_floor(refused_on_dev) == ["residentPipelines is 1, below 100"]
    assert short_of_the_floor({k: v for k, v in FLOORS.items() if k != "apps"}) == [
        "apps is None, below 100"
    ]
