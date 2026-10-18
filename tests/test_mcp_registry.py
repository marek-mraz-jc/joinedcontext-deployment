"""T-4633: the official MCP Registry listing of the open-data MCP. The file names our domain's
namespace and the production host alone, and carries nothing secret; `mcp-publisher validate`
(the README) checks it against the registry's schema."""

import json
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "components/context-gateway/mcp-registry/server.json"


def test_the_listing_names_our_namespace_and_the_production_host_alone():
    server = json.loads(SERVER.read_text())
    assert server["name"] == "com.joinedcontext/open-data"
    assert server["$schema"].startswith("https://static.modelcontextprotocol.io/schemas/")
    assert len(server["description"]) <= 100
    assert server["remotes"] == [{"type": "streamable-http", "url": "https://api.joinedcontext.com/api/mcp"}]
    text = SERVER.read_text()
    assert "dev." not in text and "packages" not in server, "prod only, and no package to run"
    assert not any(word in text.lower() for word in ("secret", "token", "key", "password")), "nothing secret"
