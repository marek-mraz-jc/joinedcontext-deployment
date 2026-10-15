"""The public MCP connectors of Banská Bystrica and BBSK (T-4141, ADR-N-043, EP-92..EP-96).

One named `McpServer` per publisher, `/api/mcp/{project}/otvorene-data`, over that publisher's
public Endpoints only: what a person pastes into Claude, ChatGPT or any MCP client reaches the
city's or the region's open data and nothing of another organization. These cases read the seed;
what the gateway serves from it is the outside-client transcript in the task.
"""

from pathlib import Path

import pytest
import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
SERVERS = {
    # project: (seed folder, members)
    "banskabystrica": ("banskabystrica", {"banskabystrica-verejne"}),
    "bbsk": ("bbsk", {"bbsk-registre", "bbsk-kraj-verejne", "bbsk-kpi"}),
}
# What an anonymous Policy of a member may grant: reads, and the subscriptions a WebSocket
# needs (T-4073), which the gateway hides from anonymous MCP callers (T-4168). No entity write.
ANONYMOUS_OPERATIONS = {"retrieveOps", "createSubscription", "retrieveSubscription", "updateSubscription", "deleteSubscription"}


def manifests(folder: Path):
    for path in sorted(folder.glob("*.yaml")):
        if path.name == "index.yaml" or path.name.endswith("-bento.yaml"):
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and "kind" in doc:
                yield path, doc


def server(project: str):
    folder = SEED / SERVERS[project][0]
    found = [(p, d) for p, d in manifests(folder) if d["kind"] == "McpServer"]
    assert len(found) == 1, f"{folder.name} holds {len(found)} McpServer manifests"
    return found[0]


@pytest.mark.parametrize("project", SERVERS)
def test_the_server_is_public_and_placed_where_the_gateway_reads_it(project):
    path, doc = server(project)
    assert doc["apiVersion"] == "joinedcontext.com/v1alpha1"
    assert doc["metadata"] == doc["metadata"] | {"name": "otvorene-data", "namespace": project}
    assert doc["spec"]["audience"] == "public"
    assert "allowedProjects" not in doc["spec"]
    # The AI client reads the English text as its instructions (EP-92), the Portal the Slovak.
    for text in ("title", "description"):
        assert set(doc["metadata"][text]) == {"sk", "en"}
    index = yaml.safe_load((path.parent / "index.yaml").read_text())
    # jc-core McpServerSpec::PROJECT_PATH_TEMPLATE
    assert index[path.name] == f"projects/{project}/mcp/otvorene-data.yaml"


@pytest.mark.parametrize("project", SERVERS)
def test_the_members_are_the_publishers_own_public_endpoints(project):
    folder, expected = SERVERS[project]
    _, doc = server(project)
    members = doc["spec"]["members"]
    assert 1 <= len(members) <= 10
    assert all(m["kind"] == "Endpoint" and m.get("namespace", project) == project for m in members), members
    assert {m["name"] for m in members} == expected
    endpoints = {d["metadata"]["name"]: d for _, d in manifests(SEED / folder) if d["kind"] == "Endpoint"}
    for name in expected:
        assert endpoints[name]["spec"]["audience"] == "public", name
        assert endpoints[name]["spec"].get("mcp") is not False, f"{name} turns its MCP off"


@pytest.mark.parametrize("project", SERVERS)
def test_an_anonymous_caller_of_a_member_may_read_and_never_write(project):
    folder, expected = SERVERS[project]
    docs = [d for _, d in manifests(SEED / folder)]
    spaces = {
        d["metadata"]["name"]: d["spec"]["contextSpaceRef"]
        for d in docs
        if d["kind"] == "Endpoint" and d["metadata"]["name"] in expected
    }
    for member, space in spaces.items():
        anonymous = [
            d["spec"]
            for d in docs
            if d["kind"] == "Policy"
            and d["spec"]["assignee"] == {"kind": "role", "id": "public"}
            and d["spec"]["contextSpaceRef"]["name"] == space
        ]
        assert anonymous, f"{member}: no anonymous Policy on {space}, the public server would answer nothing"
        for policy in anonymous:
            assert set(policy["operations"]) <= ANONYMOUS_OPERATIONS, (member, policy["operations"])


def test_the_conformance_endpoint_is_no_member():
    """`public-air` holds what the smoke run and the ETSI suite write; it is no open data."""
    _, doc = server("banskabystrica")
    assert "public-air" not in {m["name"] for m in doc["spec"]["members"]}
