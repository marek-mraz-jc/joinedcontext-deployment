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


def _index_destinations():
    """Every seeded manifest with the repository path its `index.yaml` writes it to."""
    for index in sorted(SEED.glob("*/index.yaml")):
        for source, destination in (yaml.safe_load(index.read_text()) or {}).items():
            path = index.parent / source
            if not path.exists() or not source.endswith((".yaml", ".yml")):
                continue
            docs = documents(path)
            # A multi-document file has no single kind to place; none exists in the seed today.
            if len(docs) != 1 or "kind" not in docs[0]:
                continue
            yield path, docs[0], destination


def _shape(destination: str, name: str) -> str:
    """The destination with its variable segments named, so two manifests of one kind compare."""
    segments = destination.split("/")
    shaped = []
    for position, segment in enumerate(segments):
        previous = segments[position - 1] if position else None
        if previous in {"projects"}:
            shaped.append("{namespace}")
        elif previous in {"spaces"}:
            shaped.append("{space}")
        elif previous in {"pipelines", "blueprints"}:
            shaped.append("{name}")
        elif position == len(segments) - 1 and segment == f"{name}.yaml":
            shaped.append("{name}.yaml")
        else:
            shaped.append(segment)
    return "/".join(shaped)


def test_every_kind_is_seeded_to_one_repository_path():
    """MF-06: a manifest lives at the path its kind declares, or the loader refuses it.

    `jcctl validate --repo-dir` over the rendered seed reported
    `SharedSpaceReference/bbsk/mesto-kpi belongs at projects/bbsk/shared/mesto-kpi.yaml`
    because one `index.yaml` wrote `shares/` where the kind's template says `shared/` (T-1471).
    Comparing the seeded manifests of one kind against each other needs no jcctl in the lane.
    Its ceiling: a kind seeded exactly once has nothing to disagree with.
    """
    shapes: dict[str, dict[str, list[str]]] = {}
    for _path, doc, destination in _index_destinations():
        shape = _shape(destination, doc.get("metadata", {}).get("name"))
        shapes.setdefault(doc["kind"], {}).setdefault(shape, []).append(destination)
    assert shapes, "the seed holds manifests"
    disagreeing = {kind: paths for kind, paths in shapes.items() if len(paths) > 1}
    assert not disagreeing, f"one kind, two repository paths: {disagreeing}"


def test_the_demo_editor_proposes_and_deletes_nothing():
    """CC-34, PF-50, PF-58: dev holds a person whose own change waits for somebody else (T-2231).

    The steward is bound to `steward` and to `org-admin`, so `delete` makes their own change the
    PF-58 administrator exception; the approver holds `approve` and cannot propose; the viewer
    holds `read` and gets the missing-role refusal instead. Without a fourth person the plain
    self-approval refusal cannot be played on dev at all, which is what
    `joinedcontext-portal/ui/e2e/live/roles-refusals.spec.ts` needed.

    The property that journey stands on, read off `ui/src/api/approval.ts:88,100-106`: the editor
    may approve the kind they propose — otherwise the page answers `needsRole` and never reaches
    the self-approval rule — and may delete nothing, which is what `administers` asks for. They
    may also propose a `RoleBinding`, so the grant refusal is about the width of the grant and
    not about their being unable to grant at all (PF-50).
    """
    editor = "demo.editor@hel.fi"
    roles = {doc["metadata"]["name"]: doc for _path, doc in manifests("Role")}
    held = [
        doc["spec"]["role"]
        for _path, doc in manifests("RoleBinding")
        if any(subject.get("user") == editor for subject in doc["spec"]["subjects"])
    ]
    assert held, f"{editor} is bound to no role"
    rules = []
    for name in held:
        assert name in roles, f"{editor} is bound to `{name}`, which the seed does not declare"
        rules.extend(roles[name]["spec"]["rules"])

    def verbs_of(kind: str) -> set[str]:
        return {verb for rule in rules if kind in rule["kinds"] for verb in rule["verbs"]}

    assert "delete" not in {verb for rule in rules for verb in rule["verbs"]}, (
        f"{editor} administers a kind, so their own change would be the PF-58 exception"
    )
    assert {"propose", "approve"} <= verbs_of("ContextSpace"), sorted(verbs_of("ContextSpace"))
    assert verbs_of("RoleBinding") == {"propose"}, sorted(verbs_of("RoleBinding"))

    # And strictly below the steward, who holds `org-admin` beside `steward`.
    steward_kinds = {
        kind
        for name in ("steward", "org-admin")
        for rule in roles[name]["spec"]["rules"]
        for kind in rule["kinds"]
    }
    assert {kind for rule in rules for kind in rule["kinds"]} <= steward_kinds
