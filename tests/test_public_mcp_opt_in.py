"""Every public Endpoint a seeded named MCP server reads opts in to MCP (T-6761, MF-53, EP-24).

jc-core serves `mcp` on a `public` Endpoint only when it opts in: `mcp: true` or `mcp` listed in
`enabledRepresentations`. A named server reads its members through their MCP surface and the
gateway drops a selected Endpoint that serves no MCP (context-gateway mcp/server.rs `serve`), so
a public seed Endpoint without the opt-in would silently leave the open data connector. These
cases read the seeds, the App grants Gitea serves and both open-data generators.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEEDS = [ROOT / "components/context-gateway/seed", ROOT / "components/gitea/apps"]
GENERATORS = [ROOT / "scripts/open-data/generate.py", ROOT / "scripts/open-data/datacube.py"]


def documents():
    for folder in SEEDS:
        for path in sorted(folder.rglob("*.yaml")):
            try:
                docs = list(yaml.safe_load_all(path.read_text()))
            except yaml.YAMLError:
                continue  # templates and Bento files, never a manifest of these kinds
            for doc in docs:
                if isinstance(doc, dict) and isinstance(doc.get("spec"), dict) and "kind" in doc:
                    yield path.relative_to(ROOT), doc


DOCS = list(documents())
SERVERS = [(p, d) for p, d in DOCS if d["kind"] == "McpServer"]
PUBLIC = [(p, d) for p, d in DOCS if d["kind"] == "Endpoint" and d["spec"].get("audience") == "public"]


def opts_in(spec: dict) -> bool:
    """jc-core `EndpointSpec::mcp_on` plus a listed `mcp`, for a public Endpoint."""
    return spec.get("mcp") is True or "mcp" in (spec.get("enabledRepresentations") or [])


def selects(server: dict, endpoint: dict) -> bool:
    """jc-core `McpServerSpec::selects` over a seed: projects, spaces and access level."""
    select = server["spec"].get("select")
    if not select:
        return False
    project = endpoint["metadata"]["namespace"]
    space = endpoint["spec"]["contextSpaceRef"]
    space = space["name"] if isinstance(space, dict) else space
    return (
        ("projects" not in select or project in select["projects"])
        and ("spaces" not in select or f"{project}/{space}" in select["spaces"])
        and endpoint["spec"]["audience"] in select.get("accessLevel", [endpoint["spec"]["audience"]])
    )


def members(server: dict) -> set:
    namespace = server["metadata"]["namespace"]
    return {
        (m.get("namespace", namespace), m["name"]) for m in server["spec"].get("members") or []
    }


def test_the_seed_holds_named_servers_and_public_endpoints():
    assert len(SERVERS) >= 9, [str(p) for p, _ in SERVERS]
    assert len(PUBLIC) >= 600, len(PUBLIC)


@pytest.mark.parametrize("path,server", SERVERS, ids=[str(p) for p, _ in SERVERS])
def test_every_public_endpoint_a_server_reads_opts_in(path, server):
    read = [
        (p, d) for p, d in PUBLIC
        if selects(server, d) or (d["metadata"]["namespace"], d["metadata"]["name"]) in members(server)
    ]
    assert read, f"{path} reads no public Endpoint"
    closed = [f"{p}: {d['metadata']['name']}" for p, d in read if not opts_in(d["spec"])]
    assert not closed, f"{path} reads public Endpoints that serve no MCP; add `mcp: true`: {closed}"


def test_no_public_endpoint_opts_in_and_out_at_once():
    # jc-core refuses `mcp: false` beside a listed `mcp` (EP-24).
    both = [str(p) for p, d in PUBLIC if d["spec"].get("mcp") is False and "mcp" in (d["spec"].get("enabledRepresentations") or [])]
    assert not both, both


@pytest.mark.parametrize("generator", GENERATORS, ids=lambda p: p.name)
def test_the_open_data_generators_emit_the_opt_in(generator):
    # Both write `enabledRepresentations: REPRESENTATIONS` on the public Endpoint they generate.
    tree = ast.parse(generator.read_text())
    lists = [
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "REPRESENTATIONS" for t in node.targets)
    ]
    assert lists == [lists[0]] and "mcp" in lists[0], lists
    assert re.search(r"enabledRepresentations\W{1,6}(\[\{\"\, \"\.join\()?REPRESENTATIONS", generator.read_text()), (
        "the public Endpoint lists REPRESENTATIONS"
    )
