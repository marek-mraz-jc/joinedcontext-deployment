"""dev's seed follows the identity contract (CC-82, PF-84, PL-57, EP-77; T-1449).

Every space that predates rendered segments pins today's segment, so no entity id changes;
a mapping reads its space from `env("JC_SPACE")`; Helsinki's policies name the organization as
`did:web:{orgDomain}`; a reference inside the organization names its Endpoint, not its slug.
"""

import re
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"


def documents(path: Path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if isinstance(doc, dict)]


def manifests(kind: str):
    for path in sorted(SEED.glob("*/*.yaml")):
        if path.name.endswith("-bento.yaml") or path.name == "index.yaml":
            continue
        for doc in documents(path):
            if doc.get("kind") == kind:
                yield path, doc


def test_every_space_pins_the_segment_its_ids_carry_today():
    spaces = list(manifests("ContextSpace"))
    assert spaces, "the seed holds spaces"
    for path, space in spaces:
        assert space["spec"].get("urnSegment") == space["metadata"]["name"], path.name


def test_no_mapping_types_its_space_or_project_in():
    segments = {doc["spec"]["urnSegment"] for _, doc in manifests("ContextSpace")}
    projects = {doc["metadata"]["name"] for _, doc in manifests("Project")}
    literal = re.compile(r'"(%s)"' % "|".join(map(re.escape, sorted(segments | projects))))
    bentos = sorted(SEED.glob("*/*-bento.yaml"))
    assert bentos, "the seed holds mappings"
    minted = 0
    for path in bentos:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.lstrip()
            # `let source_url` is the publisher's own address, and one of them lives under
            # `egov.banskabystrica.sk`: a host that happens to contain a project's org domain
            # is not this mapping typing its project in (T-2305).
            if stripped.startswith("#") or stripped.startswith("let source_url ="):
                continue
            assert not literal.search(line), f"{path.name}:{number}: {stripped}"
        minted += 'env("JC_SPACE")' in path.read_text()
    # Every mapping that mints an id reads its space from the environment. The one exception is
    # named rather than counted around: the vehicles reaper writes nothing, it deletes buses
    # whose position went stale, so it has no id to mint.
    silent = {p.name for p in bentos if 'env("JC_SPACE")' not in p.read_text()}
    assert silent == {"helsinki-pipeline-vehicles-reaper-bento.yaml"}, silent
    assert minted == len(bentos) - 1


def test_helsinki_policies_name_the_organization_by_placeholder():
    policies = [(p, d) for p, d in manifests("Policy") if p.parent.name == "helsinki"]
    assert len(policies) == 12
    for path, policy in policies:
        assert policy["spec"]["assigner"] == "did:web:{orgDomain}", path.name


def test_a_reference_inside_the_organization_names_its_endpoint():
    endpoints = {
        (doc["metadata"]["namespace"], doc["metadata"]["name"]) for _, doc in manifests("Endpoint")
    }
    references = list(manifests("SharedSpaceReference"))
    assert references
    for path, reference in references:
        spec = reference["spec"]
        assert "endpointSlug" not in spec, path.name
        target = (spec["endpointRef"]["project"], spec["endpointRef"]["name"])
        assert target in endpoints, f"{path.name} names {target}, which the seed does not hold"
