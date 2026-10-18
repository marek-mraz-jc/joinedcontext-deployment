"""No two public Endpoints of one organization share a title in one language (T-4568, EP-27).

A public Endpoint's title is its Dataset's title in the open-data catalogue and in the hub's
search. Two that read alike leave a person and an agent to guess which one holds what: dev had two
"Air quality in Banská Bystrica", the EEA readings and the city's map. A seed directory under
`components/context-gateway/seed/` is one organization.
"""

from collections import defaultdict
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components" / "context-gateway" / "seed"


def public_titles(organization: Path):
    """(language, title, endpoint) for every public Endpoint of one organization's seed."""
    for path in sorted(organization.rglob("*.yaml")):
        try:
            documents = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        for document in documents:
            if not isinstance(document, dict) or document.get("kind") != "Endpoint":
                continue
            if (document.get("spec") or {}).get("audience") != "public":
                continue
            metadata = document.get("metadata") or {}
            title = metadata.get("title")
            titles = title if isinstance(title, dict) else {"": title} if isinstance(title, str) else {}
            for language, text in titles.items():
                yield language, " ".join(str(text).split()).casefold(), f"{path.relative_to(organization)}: {metadata.get('name')}"


def shared_titles(organization: Path) -> list[str]:
    held = defaultdict(list)
    for language, title, endpoint in public_titles(organization):
        held[(language, title)].append(endpoint)
    return [f"{organization.name} [{language}] '{title}': {', '.join(endpoints)}" for (language, title), endpoints in sorted(held.items()) if len(endpoints) > 1]


def test_no_two_public_datasets_of_one_organization_share_a_title():
    organizations = [path for path in sorted(SEED.iterdir()) if path.is_dir()]
    assert len(organizations) >= 5, organizations
    shared = [line for organization in organizations for line in shared_titles(organization)]
    assert shared == [], f"give each public Endpoint a title naming its source (T-4568): {shared}"


def endpoint(name: str, title: dict, audience: str = "public") -> str:
    return yaml.safe_dump({"apiVersion": "joinedcontext.com/v1alpha1", "kind": "Endpoint", "metadata": {"name": name, "title": title}, "spec": {"audience": audience}})


def test_a_seeded_pair_with_one_title_is_refused(tmp_path):
    organization = tmp_path / "mesto"
    organization.mkdir()
    (organization / "a.yaml").write_text(endpoint("eea", {"en": "Air quality in Banská Bystrica", "sk": "Kvalita ovzdušia"}))
    (organization / "b.yaml").write_text(endpoint("app", {"en": "Air  quality in banská Bystrica", "sk": "Mapa ovzdušia"}))
    # An internal Endpoint is no Dataset of the catalogue, and another organization may reuse it.
    (organization / "c.yaml").write_text(endpoint("inner", {"en": "Air quality in Banská Bystrica"}, audience="organization"))
    other = tmp_path / "kraj"
    other.mkdir()
    (other / "a.yaml").write_text(endpoint("eea", {"en": "Air quality in Banská Bystrica"}))
    assert shared_titles(organization) == ["mesto [en] 'air quality in banská bystrica': a.yaml: eea, b.yaml: app"]
    assert shared_titles(other) == []
