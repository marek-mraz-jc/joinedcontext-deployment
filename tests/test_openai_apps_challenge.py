"""T-4315: the ChatGPT app directory's domain check, answered by the edge.

The token is served as plain text at `/.well-known/openai-apps-challenge` on every host, from
`global.openaiAppsChallenge`; with none set the path answers 404. Nothing per token is code.
"""

import shutil

import pytest
import yaml

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")

ROUTE = "openai-apps-challenge"


def answer_lua(docs: list[dict]) -> str:
    config = yaml.safe_load(next(
        d for d in docs
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "apisix-standalone-base"
    )["data"]["apisix.yaml"])
    route = next(r for r in config["routes"] if r["id"] == ROUTE)
    assert route["uri"] == "/.well-known/openai-apps-challenge"
    assert "host" not in route and "hosts" not in route, "the MCP host must answer it"
    plugins = next(p for p in config["plugin_configs"] if p["id"] == route["plugin_config_id"])["plugins"]
    return plugins["serverless-pre-function"]["functions"][-1]


def with_token(token: str):
    def edit(tree):
        path = tree / "defaults/environment/global.yaml"
        path.write_text(path.read_text().replace('openaiAppsChallenge: ""', f'openaiAppsChallenge: "{token}"'))
    return edit


@requires_helmfile
def test_without_a_token_the_path_answers_404(rendered):
    lua = answer_lua(rendered("dev"))
    assert 'local token = ""' in lua and "ngx.exit(404)" in lua, lua


@requires_helmfile
def test_the_configured_token_is_answered_as_it_is(rendered_variant):
    lua = answer_lua(rendered_variant("dev", with_token("abc-123_X.y")))
    assert 'local token = "abc-123_X.y"' in lua, lua
    assert "ngx.print(token)" in lua and "text/plain" in lua, lua


@requires_helmfile
def test_a_token_that_could_break_out_of_the_lua_stops_the_render(rendered_variant):
    with pytest.raises(AssertionError, match="openaiAppsChallenge"):
        rendered_variant("dev", with_token('x\\" ngx.say(1) --'))
