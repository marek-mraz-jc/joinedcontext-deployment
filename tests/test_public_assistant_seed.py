"""T-4167, T-4281 (Architecture/23 §6): one public assistant per body, over its own knowledge.

Each of Banská Bystrica (the city), BBSK (the region), Žilina and Prague answers anyone on the
assistant host, the demo page and the data catalogue under its own publicId. Everything it reads
is public and its own body's: its web source crawls the body's site alone, its CKAN source lists
the body's organization alone, its connectors name public Endpoints of its own project that serve
MCP with read-only tools, and its limits are T-4149's with a daily budget per body (T-4281).
No other body's site, organization or Endpoint is reachable from it.
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
READ_ONLY = {"list_types", "query_entities", "get_entity", "get_attribute_value", "retrieve_temporal"}
# publicId: (project, web host, CKAN organization, language first, cost per day)
BODIES = {
    "banskabystrica": ("banskabystrica", "www.banskabystrica.sk", "banskabystrica", "sk", 1),
    "bbsk": ("bbsk", "www.bbsk.sk", "bbsk", "sk", 1),
    "zilina": ("zilina", "www.zilina.sk", "zilina", "sk", 0.5),
    "praha": ("praha", "www.praha.eu", "praha", "cs", 0.5),
}
# Words that name a body, for the check that one body's assistant names no other.
NAMES = {
    "banskabystrica": ("banskabystrica", "banská bystrica"),
    "bbsk": ("bbsk", "samosprávn"),
    "zilina": ("zilina", "žilin"),
    "praha": ("praha", "prague", "prahy"),
}
ORIGINS = [
    "https://assistant.dev.joinedcontext.com",
    "https://dev.joinedcontext.com",
    "https://data.dev.joinedcontext.com",
]


def manifests(kind: str, project: str) -> dict[str, dict]:
    found = {}
    for path in sorted((SEED / project).glob("*.yaml")):
        if path.name == "index.yaml":
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == kind:
                found[doc["metadata"]["name"]] = doc
    return found


def deployment(public_id: str) -> dict:
    project = BODIES[public_id][0]
    found = [d for d in manifests("AssistantDeployment", project).values() if d["spec"]["publicId"] == public_id]
    assert len(found) == 1, public_id
    return found[0]


@pytest.mark.parametrize("public_id", BODIES)
def test_each_body_has_one_public_assistant_on_its_own_id(public_id):
    doc = deployment(public_id)
    spec = doc["spec"]
    assert doc["metadata"]["namespace"] == BODIES[public_id][0]
    assert spec["channel"] == "public"
    assert spec.get("enabled", True) is True
    # Its own project only: no source and no connector of another project (T-4281).
    assert "scope" not in spec
    assert all("/" not in name for name in spec["sources"])
    assert all("/" not in c["endpoint"] for c in spec["connectors"])


@pytest.mark.parametrize("public_id", BODIES)
def test_every_source_is_public_and_the_bodys_own(public_id):
    project, host, organization, _, _ = BODIES[public_id]
    spec = deployment(public_id)["spec"]
    sources = manifests("KnowledgeSource", project)
    assert set(spec["sources"]) == {"web", "data-portal", "catalogue"}
    for name in spec["sources"]:
        source = sources[name]["spec"]
        assert source["visibility"] == "public", name
        if source["source"] == "website":
            assert {urlsplit(url).hostname for url in source["startUrls"]} == {host}
        if source["source"] == "ckan":
            assert source["organizations"] == [organization], name
            instance = manifests("CkanInstance", project)[source["ckanInstanceRef"]]["spec"]
            assert instance["url"] == "https://data.dev.joinedcontext.com"


@pytest.mark.parametrize("public_id", BODIES)
def test_every_connector_is_a_public_mcp_endpoint_of_the_body_with_read_only_tools(public_id):
    project = BODIES[public_id][0]
    spec = deployment(public_id)["spec"]
    endpoints = manifests("Endpoint", project)
    assert spec["connectors"], "the assistant reads live values through connectors"
    for connector in spec["connectors"]:
        endpoint = endpoints[connector["endpoint"]]
        assert endpoint["spec"]["audience"] == "public", connector["endpoint"]
        assert "mcp" in endpoint["spec"]["enabledRepresentations"], connector["endpoint"]
        assert set(connector["tools"]) <= READ_ONLY, connector


@pytest.mark.parametrize("public_id", ["banskabystrica", "bbsk"])
def test_the_connectors_are_every_member_of_the_bodys_public_mcp_server(public_id):
    # T-4256 (owner 2026-10-16): the assistant queries all the open data by default. The public
    # `otvorene-data` server of its project is the curated read-only set, so every member of it
    # is a connector, and an Endpoint added there joins without a hand edit here.
    project = BODIES[public_id][0]
    members = {
        member["name"]
        for server in manifests("McpServer", project).values()
        if server["spec"]["audience"] == "public"
        for member in server["spec"]["members"]
        if member["kind"] == "Endpoint"
    }
    assert {c["endpoint"] for c in deployment(public_id)["spec"]["connectors"]} == members


def test_the_public_mcp_servers_list_members_that_serve_mcp():
    # The gateway drops a member that does not serve MCP, so a server whose members lack it
    # lists no tool at all (T-4141's `otvorene-data` before T-4167).
    for project in ("banskabystrica", "bbsk"):
        endpoints = manifests("Endpoint", project)
        for name, server in manifests("McpServer", project).items():
            for member in server["spec"]["members"]:
                assert "mcp" in endpoints[member["name"]]["spec"]["enabledRepresentations"], (project, name, member)


@pytest.mark.parametrize("public_id", BODIES)
def test_no_other_body_is_named_and_no_secret_is_carried(public_id):
    project = BODIES[public_id][0]
    spec = deployment(public_id)["spec"]
    text = yaml.safe_dump(deployment(public_id)).lower()
    for source in spec["sources"]:
        text += yaml.safe_dump(manifests("KnowledgeSource", project)[source]).lower()
    for other, words in NAMES.items():
        if other == public_id:
            continue
        for word in words:
            assert word not in text, (public_id, word)
    for word in ("hel.fi", "helsinki", "secretref", "apikey", "api_key", "token:", "password"):
        assert word not in text, (public_id, word)


@pytest.mark.parametrize("public_id", BODIES)
def test_it_is_placed_on_the_host_the_demo_page_and_the_catalogue_with_its_own_budget(public_id):
    spec = deployment(public_id)["spec"]
    assert spec["allowedOrigins"] == ORIGINS
    limit = spec["rateLimit"]
    assert (limit["perClientPerMinute"], limit["perClientPerHour"], limit["perClientPerDay"], limit["streamsPerClient"]) == (10, 60, 200, 2)
    budget = spec["budget"]
    assert budget["costPerDayUsd"] == BODIES[public_id][4]
    assert budget["outputTokensPerAnswer"] == 700
    assert budget["messagesPerConversation"] == 30
    assert budget["questionChars"] == 1000
    # The cost cap is the guard; the shared token cap stays above it (T-4286).
    assert budget["tokensPerDay"] <= 5_000_000
    assert budget["tokensPerConversation"] <= budget["tokensPerDay"]
    assert spec["model"]["answer"] and spec["model"]["router"]


def test_the_public_budgets_stay_inside_the_keys_five_dollars():
    assert sum(deployment(p)["spec"]["budget"]["costPerDayUsd"] for p in BODIES) <= 5


@pytest.mark.parametrize("public_id", BODIES)
def test_the_chat_speaks_the_bodys_language_first(public_id):
    spec = deployment(public_id)["spec"]
    first = BODIES[public_id][3]
    assert spec["languages"][0] == first
    assert 3 <= len(spec["suggestions"][first]) <= 6
    assert spec["disclaimer"][first] and spec["disclaimer"]["en"]
    assert len(spec["theme"]["greeting"]) <= 500


@pytest.mark.parametrize("public_id", BODIES)
def test_the_sources_and_the_deployment_are_seeded_at_their_kinds_paths(public_id):
    project = BODIES[public_id][0]
    index = yaml.safe_load((SEED / project / "index.yaml").read_text())
    by_path = {path: name for name, path in index.items()}
    name = deployment(public_id)["metadata"]["name"]
    assert f"projects/{project}/assistant/deployments/{name}.yaml" in by_path
    for source in deployment(public_id)["spec"]["sources"]:
        assert f"projects/{project}/assistant/sources/{source}.yaml" in by_path, source
    for file in by_path.values():
        assert (SEED / project / file).exists(), file


def test_the_region_is_indexed_once():
    # T-4281 item 2: bbsk.sk is crawled in the bbsk project alone; the city's project holds no
    # second copy, and the eval copies read the region's as `bbsk/{source}`.
    for doc in manifests("KnowledgeSource", "banskabystrica").values():
        hosts = {urlsplit(url).hostname for url in doc["spec"].get("startUrls", [])}
        assert "www.bbsk.sk" not in hosts, doc["metadata"]["name"]
        assert "bbsk" not in doc["spec"].get("organizations", []), doc["metadata"]["name"]
    for name in ("bb-eval-haiku", "bb-eval-deepseek", "bb-eval-gemini"):
        spec = manifests("AssistantDeployment", "banskabystrica")[name]["spec"]
        assert {"bbsk/web", "bbsk/data-portal"} <= set(spec["sources"]), name
        assert spec["scope"]["projects"] == ["bbsk"], name


def test_the_catalogue_opens_the_publishers_assistant_and_bbsk_elsewhere():
    # T-4281 item 5: a dataset page frames its publisher's assistant, every other page bbsk's.
    values = Path(__file__).resolve().parent.parent / ".ci/example-deployments/environments/dev/ckan.yaml.gotmpl"
    catalogue = yaml.safe_load(values.read_text())["ckan"]["catalogue"]
    assert catalogue["assistant"] == "bbsk"
    by_organization = catalogue["assistantByOrganization"]
    assert by_organization == {"banskabystrica": "banskabystrica", "bbsk": "bbsk", "zilina": "zilina", "praha": "praha"}
    for organization, public_id in by_organization.items():
        doc = deployment(public_id)
        assert BODIES[public_id][2] == organization
        assert "https://data.dev.joinedcontext.com" in doc["spec"]["allowedOrigins"]


# What 2026-10-16 measured on dev (T-4286): banskabystrica's 56 requests spent 263,512 tokens
# (253,475 in, 10,037 out) for 227,764 micro-dollars, about $0.86 a million tokens.
MEASURED_USD_PER_TOKEN = 227_764e-6 / 263_512


def test_no_anonymous_deployment_runs_out_of_tokens_before_its_cost_cap():
    """T-4286: tokensPerDay 300,000 held the public assistant to about 65 answers a day for
    everyone, and at 08:25Z every visitor read a refusal. The cost cap is the guard: on every
    deployment anonymous visitors reach, the day's tokens at the measured price buy more than
    costPerDayUsd, so the cost cap binds first, and past it the answers are links."""
    checked = 0
    for path in sorted(SEED.glob("*/*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if not (isinstance(doc, dict) and doc.get("kind") == "AssistantDeployment"):
                continue
            spec = doc["spec"]
            if spec["channel"] == "internal":
                continue
            budget = spec["budget"]
            cost = budget.get("costPerDayUsd", 3)
            assert budget["tokensPerDay"] * MEASURED_USD_PER_TOKEN >= cost, (
                f"{path.name}: tokensPerDay {budget['tokensPerDay']} buys about "
                f"${budget['tokensPerDay'] * MEASURED_USD_PER_TOKEN:.2f}, less than costPerDayUsd {cost}"
            )
            checked += 1
    assert checked >= 3, "the public, catalogue and eval deployments are checked"
