"""T-4167 (Architecture/23 §6): the residents' public assistant of Banská Bystrica and its region.

`banskabystrica/banskabystrica` answers anyone on the assistant host and the demo page, so
everything it reads is public and belongs to the city or the region: its web sources crawl
banskabystrica.sk and bbsk.sk alone, its CKAN source lists the two bodies' organizations, its
connectors name public Endpoints of the two projects that serve MCP with read-only tools, and
its limits are T-4149's defaults. Prague, Helsinki and Žilina are unreachable by construction.
"""

from pathlib import Path
from urllib.parse import urlsplit

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
SCOPE = ("banskabystrica", "bbsk")
WEB_HOSTS = {"www.banskabystrica.sk", "www.bbsk.sk"}
# jc-assistant's READ_ONLY_TOOLS (platform crates/assistant/src/chat/mcp.rs), which the data loop
# offers the answering model (T-4294).
READ_ONLY = {"list_types", "get_type", "list_attributes", "query_entities", "get_entity", "get_attribute_value",
             "query_temporal", "retrieve_temporal", "describe_schema", "describe_access"}
ELSEWHERE = ("helsinki", "hel-fi", "hel.fi", "praha", "prague", "zilina", "žilina")


def manifests(kind: str, project: str = "banskabystrica") -> dict[str, dict]:
    found = {}
    for path in sorted((SEED / project).glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == kind:
                found[doc["metadata"]["name"]] = doc
    return found


def deployment() -> dict:
    return manifests("AssistantDeployment")["banskabystrica"]["spec"]


def test_the_deployment_is_public_and_answers_on_its_own_id():
    spec = deployment()
    assert spec["channel"] == "public"
    assert spec["publicId"] == "banskabystrica"
    assert spec.get("enabled", True) is True
    # The internal staff assistant stays as it was.
    assert manifests("AssistantDeployment")["knowledge"]["spec"]["channel"] == "internal"


def test_every_source_is_public_and_of_the_city_or_the_region():
    spec = deployment()
    sources = manifests("KnowledgeSource")
    assert set(spec["sources"]) == {"web", "web-bbsk", "data-portal", "catalogue"}
    hosts = set()
    for name in spec["sources"]:
        source = sources[name]["spec"]
        assert source["visibility"] == "public", name
        if source["source"] == "website":
            hosts |= {urlsplit(url).hostname for url in source["startUrls"]}
        if source["source"] == "ckan":
            assert source["organizations"] and set(source["organizations"]) <= set(SCOPE), name
            instance = manifests("CkanInstance")[source["ckanInstanceRef"]]["spec"]
            assert instance["url"] == "https://data.dev.joinedcontext.com"
    assert hosts == WEB_HOSTS


def test_every_connector_is_a_public_mcp_endpoint_of_the_scope_with_read_only_tools():
    spec = deployment()
    assert spec["scope"]["projects"] == ["bbsk"]
    endpoints = {**manifests("Endpoint"), **manifests("Endpoint", "bbsk")}
    assert spec["connectors"], "the assistant reads live values through connectors"
    for connector in spec["connectors"]:
        # `bbsk/bbsk-registre` names a scoped project's Endpoint (T-4177); a bare name, this project's.
        project, _, name = connector["endpoint"].rpartition("/")
        assert project in ("", *spec["scope"]["projects"]), connector["endpoint"]
        endpoint = endpoints[name]
        assert endpoint["metadata"]["namespace"] == (project or "banskabystrica"), connector["endpoint"]
        assert endpoint["metadata"]["namespace"] in SCOPE, connector["endpoint"]
        assert endpoint["spec"]["audience"] == "public", connector["endpoint"]
        assert "mcp" in endpoint["spec"]["enabledRepresentations"], connector["endpoint"]
        assert set(connector["tools"]) <= READ_ONLY, connector


def test_the_connectors_are_every_public_mcp_endpoint_of_the_two_bodies():
    # T-4256 (owner 2026-10-16): the assistant queries all the open data by default. The public
    # `otvorene-data` servers of its project and scope are the curated read-only set, so every
    # member of them is a connector, and an Endpoint added there joins without a hand edit here.
    spec = deployment()
    own = SCOPE[0]
    members = {
        member["name"] if project == own else f"{project}/{member['name']}"
        for project in (own, *spec["scope"]["projects"])
        for server in manifests("McpServer", project).values()
        if server["spec"]["audience"] == "public"
        for member in server["spec"]["members"]
        if member["kind"] == "Endpoint"
    }
    assert {connector["endpoint"] for connector in spec["connectors"]} == members


def test_the_public_mcp_servers_list_members_that_serve_mcp():
    # The gateway drops a member that does not serve MCP, so a server whose members lack it
    # lists no tool at all (T-4141's `otvorene-data` before T-4167).
    for project in SCOPE:
        endpoints = manifests("Endpoint", project)
        for name, server in manifests("McpServer", project).items():
            for member in server["spec"]["members"]:
                assert "mcp" in endpoints[member["name"]]["spec"]["enabledRepresentations"], (project, name, member)


def test_no_other_body_is_named_and_no_secret_is_carried():
    text = yaml.safe_dump(manifests("AssistantDeployment")["banskabystrica"]).lower()
    for source in deployment()["sources"]:
        text += yaml.safe_dump(manifests("KnowledgeSource")[source]).lower()
    for word in ELSEWHERE:
        assert word not in text, word
    for word in ("secretref", "apikey", "api_key", "token:", "password"):
        assert word not in text, word


def test_it_is_placed_on_the_assistant_host_the_demo_page_and_the_catalogue_with_t4149_limits():
    spec = deployment()
    assert spec["allowedOrigins"] == [
        "https://assistant.dev.joinedcontext.com",
        "https://dev.joinedcontext.com",
        "https://data.dev.joinedcontext.com",
    ]
    limit = spec["rateLimit"]
    assert (limit["perClientPerMinute"], limit["perClientPerHour"], limit["perClientPerDay"], limit["streamsPerClient"]) == (10, 60, 200, 2)
    budget = spec["budget"]
    assert budget["outputTokensPerAnswer"] == 700
    assert budget["messagesPerConversation"] == 30
    assert budget["questionChars"] == 1000
    # The cost cap is the guard; the shared token cap stays above it (T-4286).
    assert budget["costPerDayUsd"] <= 3
    assert budget["tokensPerDay"] <= 5_000_000
    assert budget["tokensPerConversation"] <= budget["tokensPerDay"]
    assert spec["model"]["answer"] and spec["model"]["router"]


def test_the_chat_speaks_slovak_first():
    spec = deployment()
    assert spec["languages"][0] == "sk"
    assert 4 <= len(spec["suggestions"]["sk"]) <= 6
    assert spec["disclaimer"]["sk"] and spec["disclaimer"]["en"]
    assert len(spec["theme"]["greeting"]) <= 500


def test_the_sources_and_the_deployment_are_seeded_at_their_kinds_paths():
    index = yaml.safe_load((SEED / "banskabystrica/index.yaml").read_text())
    assert index["banskabystrica-assistant-public.yaml"] == "projects/banskabystrica/assistant/deployments/banskabystrica.yaml"
    assert index["banskabystrica-knowledge-web-bbsk.yaml"] == "projects/banskabystrica/assistant/sources/web-bbsk.yaml"
    assert index["banskabystrica-knowledge-data-portal.yaml"] == "projects/banskabystrica/assistant/sources/data-portal.yaml"


def test_the_dev_catalogue_widget_is_this_assistant_and_reaches_the_two_bodies_alone():
    # T-4252: every page of data.dev frames the deployment `ckan.catalogue.assistant` names; it is
    # this one, whose project and scope are Banská Bystrica and the region, not Helsinki's.
    values = Path(__file__).resolve().parent.parent / ".ci/example-deployments/environments/dev/ckan.yaml.gotmpl"
    public_id = yaml.safe_load(values.read_text())["ckan"]["catalogue"]["assistant"]
    found = [
        doc
        for project in SEED.iterdir()
        if project.is_dir()
        for doc in manifests("AssistantDeployment", project.name).values()
        if doc["spec"]["publicId"] == public_id
    ]
    assert len(found) == 1, public_id
    doc = found[0]
    assert doc["spec"]["channel"] in ("public", "ckan")
    assert {doc["metadata"]["namespace"], *doc["spec"]["scope"]["projects"]} == set(SCOPE)
    assert "https://data.dev.joinedcontext.com" in doc["spec"]["allowedOrigins"]
