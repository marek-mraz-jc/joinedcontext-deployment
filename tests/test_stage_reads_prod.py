"""Stage reads prod's public Endpoints through ContextSourceRegistrations (T-6545).

Owner 2026-11-03: the same data on dev, stage and prod, and a registration from prod to stage.
Every registration here is read only (auxiliary, retrieve operations), names a public prod
Endpoint the seed declares without personal data, and reaches stage alone: dev keeps its own data
and prod never registers itself.
"""

import yaml
from conftest import PROJECT_ROOT, seed_configmap

FOLDER = PROJECT_ROOT / "components/context-gateway/seed/stage-reads-prod"
PROD = "https://api.smartcity.joinedcontext.com/api/endpoint/"
READS = {"retrieveOps", "retrieveEntity", "queryEntity"}


def registrations():
    index = yaml.safe_load((FOLDER / "index.yaml").read_text())
    return {path: yaml.safe_load((FOLDER / file).read_text()) for file, path in index.items()}


def seed_endpoints():
    found = {}
    for path in (PROJECT_ROOT / "components/context-gateway/seed").rglob("*.yaml"):
        if path.parent == FOLDER:
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == "Endpoint":
                found[doc["spec"]["slug"]] = doc
    return found


def space_name(ref):
    return ref["name"] if isinstance(ref, dict) else ref


def test_every_stage_registration_reads_a_public_prod_endpoint_and_nothing_else():
    endpoints = seed_endpoints()
    found = registrations()
    assert found, "no registration in the folder"
    for path, csr in found.items():
        spec, meta = csr["spec"], csr["metadata"]
        assert csr["kind"] == "ContextSourceRegistration", path
        assert path == (
            f"projects/{meta['namespace']}/spaces/{spec['contextSpaceRef']}/registrations/{meta['name']}.yaml"
        ), path
        # Read only: the broker forwards no write to an auxiliary source and keeps its own rows.
        assert spec["mode"] == "auxiliary", path
        assert set(spec["operations"]) <= READS and spec["operations"], path
        # Only prod's public edge, and only a slug the seed declares public without personal data.
        assert spec["endpoint"].startswith(PROD), path
        slug = spec["endpoint"].removeprefix(PROD)
        endpoint = endpoints.get(slug)
        assert endpoint, f"{path}: {slug} is no seeded Endpoint"
        assert endpoint["spec"]["audience"] == "public", path
        assert endpoint["spec"].get("catalog", {}).get("personalData", "does-not-contain") == "does-not-contain", path
        # The source Endpoint lives in the space the registration fills, so prod's rows land
        # where stage's own Pipeline writes the same type.
        assert endpoint["metadata"]["namespace"] == meta["namespace"], path
        assert space_name(endpoint["spec"]["contextSpaceRef"]) == spec["contextSpaceRef"], path
        # No credential and no account: prod answers stage as any anonymous reader.
        assert spec["federation"] == {"identity": "caller"}, path
        assert "endpointRef" not in spec, path
        assert all(set(e) == {"type"} for info in spec["information"] for e in info["entities"]), path


def test_one_registration_per_space_and_type():
    seen = {}
    for path, csr in registrations().items():
        for info in csr["spec"]["information"]:
            for entity in info["entities"]:
                key = (csr["metadata"]["namespace"], csr["spec"]["contextSpaceRef"], entity["type"])
                assert key not in seen, f"{key} is registered by {seen[key]} and {path}"
                seen[key] = path


def test_no_environment_lists_the_folder_while_the_gateway_refuses_it():
    """Paused (T-6545 reopened): the gateway answers 501 on every Endpoint of a space holding an
    `identity: caller` registration to an address outside the platform."""
    environments = PROJECT_ROOT / ".ci/example-deployments/environments"
    listing = {
        env.name
        for env in environments.iterdir()
        for values in env.glob("*.yaml.gotmpl")
        if any(line.strip() == "- context-gateway/seed/stage-reads-prod" for line in values.read_text().splitlines())
    }
    assert listing == set(), listing


def test_no_seed_carries_the_registrations_while_paused(rendered):
    paths = {path.replace("/", "__") for path in registrations()}
    for env in ("stage", "smartcity", "dev"):
        assert not paths & set(seed_configmap(rendered(env))["data"]), env


def test_the_cadastral_parcels_and_council_votes_are_registered():
    """The two types T-6545's Done when names: stage held none, prod about 20k and 73k."""
    types = {
        (csr["spec"]["contextSpaceRef"], e["type"])
        for csr in registrations().values()
        for info in csr["spec"]["information"]
        for e in info["entities"]
    }
    assert ("banskabystrica-verejne", "CadastralParcel") in types
    assert ("bbsk-otvorene-data", "CouncilVote") in types


def test_the_folder_holds_no_file_the_index_leaves_out():
    index = yaml.safe_load((FOLDER / "index.yaml").read_text())
    files = {p.name for p in FOLDER.glob("*.yaml")} - {"index.yaml"}
    assert files == set(index), files ^ set(index)

