"""The platform's own forge identities and the rule on `main` (T-2352, T-2353, PF-104, PF-105).

The Portal's and the gateway's tokens used to be minted on the site administrator, so a leaked
`gitea-token-portal` administered the whole forge, and nothing protected the branch the platform
reads its configuration from. These tests run the bootstrap Job's own rendered script against
`tests/fake_forge.py`, as `test_forge_seed_converges.py` does, and read what it did to the forge.
"""

import base64
import json

import pytest

from test_forge_seed_converges import Forge, requires_helmfile


@pytest.fixture(scope="module")
def script(rendered):
    job = next(
        d
        for d in rendered("local")
        if d.get("kind") == "Job" and d["metadata"]["name"] == "gitea-bootstrap"
    )
    return job["spec"]["template"]["spec"]["containers"][0]["args"][0]


def state(forge: Forge) -> dict:
    return json.loads(forge.state.read_text())


def token_of(forge: Forge, secret: str) -> str:
    return base64.b64decode(forge.secrets[secret]["data"]["token"]).decode()


@requires_helmfile
def test_each_token_is_minted_on_a_machine_user_that_administers_nothing(script, tmp_path):
    """PF-105: two users, neither an administrator nor able to open an organization, each a
    collaborator on the configuration repository with the one verb it needs, and each token
    minted on its own user. The Secret records on whom, so a token of another user is replaced."""
    forge = Forge(tmp_path, {})
    result = forge.run(script)
    assert result.returncode == 0, result.stderr
    held = state(forge)

    assert held["minted"][:2] == ["jc-portal/jc-portal", "jc-gateway/jc-gateway"], held["minted"]
    for user in ("jc-portal", "jc-gateway"):
        assert held["users"][user]["password_set"], "the forge requires one; it is random and dropped"
        patched = held["users"][user]["patched"]
        assert patched["admin"] is False and patched["allow_create_organization"] is False, patched
    assert held["collaborators"]["configuration/jc-portal"] == "write"
    assert held["collaborators"]["configuration/jc-gateway"] == "read"
    for secret, user in (("gitea-token-portal", "jc-portal"), ("gitea-token-gateway", "jc-gateway")):
        owner = base64.b64decode(forge.secrets[secret]["data"]["owner"]).decode()
        assert owner == user, secret
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        assert "password" not in line.lower() or "not-a-real-password" not in line, line


@requires_helmfile
def test_the_administrators_tokens_are_retired_after_their_readers_restart(script, tmp_path):
    """PF-105, T-2353: the forge as it was, both tokens on the administrator and the Secrets
    without an owner. One run mints on the machine users, restarts what read the old tokens at
    start, then deletes the old tokens; the next run changes none of it."""
    forge = Forge(tmp_path, {})
    before = state(forge)
    before["tokens"] = {"forge-admin/jc-portal": True, "forge-admin/jc-gateway": True}
    before["deployments_exist"] = True
    forge.state.write_text(json.dumps(before))

    first = forge.run(script)
    assert first.returncode == 0, first.stderr
    held = state(forge)
    assert held["restarted"] == ["dev/deployments/portal", "dev/deployments/context-gateway"]
    assert "forge-admin/jc-portal" not in held["tokens"] and "forge-admin/jc-gateway" not in held["tokens"]
    order = [line for line in forge.log if "deployments/portal" in line or "forge-admin/tokens/jc-portal" in line]
    assert order[0].startswith("PATCH") and order[-1].startswith("DELETE"), (
        f"the old token went before its reader restarted: {order}"
    )

    second = forge.run(script)
    assert second.returncode == 0, second.stderr
    again = state(forge)
    assert again["restarted"] == held["restarted"], "a token that still authenticates restarted its reader"
    assert again["minted"] == held["minted"]


@requires_helmfile
def test_main_takes_only_the_portals_push_and_merge_never_over_an_outdated_base(script, tmp_path):
    """PF-104, CC-41: one rule on `main`, converged every run. The whitelist names the Portal's
    user alone, stale approvals drop, an outdated branch does not merge, nobody overrides it,
    and no forge approval is asked for because the Verdict is the Portal's."""
    forge = Forge(tmp_path, {})
    assert forge.run(script).returncode == 0
    rule = state(forge)["rules"]["configuration/main"]
    assert rule["push_whitelist_usernames"] == ["jc-portal"] and rule["enable_push_whitelist"] is True
    assert rule["merge_whitelist_usernames"] == ["jc-portal"] and rule["enable_merge_whitelist"] is True
    assert rule["required_approvals"] == 0
    assert rule["dismiss_stale_approvals"] is True
    assert rule["block_on_outdated_branch"] is True
    assert rule["block_admin_merge_override"] is True
    assert rule["enable_bypass_allowlist"] is False and rule["enable_force_push"] is False

    widened = state(forge)
    widened["rules"]["configuration/main"]["push_whitelist_usernames"] = ["jc-portal", "someone"]
    widened["rules"]["configuration/main"]["block_on_outdated_branch"] = False
    forge.state.write_text(json.dumps(widened))
    assert forge.run(script).returncode == 0
    rule = state(forge)["rules"]["configuration/main"]
    assert rule["push_whitelist_usernames"] == ["jc-portal"], "a hand-widened rule stayed wide"
    assert rule["block_on_outdated_branch"] is True


@requires_helmfile
def test_the_seed_commits_as_the_portal_and_never_as_the_administrator(script, tmp_path):
    """PF-104: the rule refuses the administrator's push, so the seed is the Portal's commit."""
    forge = Forge(tmp_path, {})
    forge.put("projects/bbsk/project.yaml", "apiVersion: v1\nkind: Project\nmetadata:\n  name: bbsk\n")
    assert forge.run(script).returncode == 0
    portal = "token:" + token_of(forge, "gitea-token-portal")
    writes = [w for w in state(forge)["writes"] if "/contents/" in w["url"]]
    assert writes, "the seed wrote nothing"
    assert {w["who"] for w in writes} == {portal}, writes


@requires_helmfile
def test_an_application_repository_already_in_the_organization_stays_the_portals(script, tmp_path):
    """AP-75 until the applications move to `{org}-apps`: what the Portal created with the
    administrator's token it still administers, and the configuration repository is not one."""
    forge = Forge(tmp_path, {})
    held = state(forge)
    held["repos"] = {"helsinki_bikes": {"files": {}, "head": "c" * 40}}
    forge.state.write_text(json.dumps(held))
    assert forge.run(script).returncode == 0
    collaborators = state(forge)["collaborators"]
    assert collaborators["helsinki_bikes/jc-portal"] == "admin"
    assert collaborators["configuration/jc-portal"] == "write"
