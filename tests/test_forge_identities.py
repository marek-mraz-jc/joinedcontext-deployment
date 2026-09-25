"""The platform's own forge identities and the rule on `main` (T-2352, T-2353, PF-105, PF-106).

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
    """PF-106: two users, neither an administrator nor able to open an organization, each a
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
    """PF-106, T-2353: the forge as it was, both tokens on the administrator and the Secrets
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
    """PF-105, CC-41: one rule on `main`, converged every run. The whitelist names the Portal's
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
    """PF-105: the rule refuses the administrator's push, so the seed is the Portal's commit."""
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


@requires_helmfile
def test_the_applications_move_to_their_own_organization_and_machine_user(script, tmp_path):
    """PF-106, T-2856: with an organization for the applications, the Job moves every
    `{project}_{name}` repository there with its history, makes jc-apps their administrator,
    mints the applications', the registry's and the lane's tokens on jc-apps against that
    organization, and takes jc-portal out of the team that may create repositories beside the
    configuration. A second run moves and mints nothing."""
    forge = Forge(tmp_path, {})
    held = state(forge)
    held["repos"] = {"helsinki_bikes": {"files": {}, "head": "c" * 40}, "helsinki": {"files": {}, "head": "d" * 40}}
    forge.state.write_text(json.dumps(held))
    apart = {
        "APPS_ORG": "joinedcontext-apps",
        "APPS_USER": "jc-apps",
        "APPS_SECRET": "gitea-token-apps",
        "APPS_SCOPES": '["write:repository","write:package"]',
        "APPS_NAMESPACES": "dev",
        "APPS_RESTART": "dev/portal",
        "REGISTRY_SECRET": "app-registry",
        "REGISTRY_SCOPES": '["read:package"]',
        "REGISTRY_HOST": "forge.test",
        "REGISTRY_NAMESPACES": "dev-apps",
        "LANE_SECRET": "gitea-token-lane-secret",
        "LANE_SCOPES": '["write:organization"]',
        "LANE_NAMESPACES": "dev",
        "RUNNER_SECRET": "gitea-runner-registration",
        "RUNNER_NAMESPACES": "dev",
    }
    first = forge.run(script, **apart)
    assert first.returncode == 0, first.stderr
    held = state(forge)
    assert held["moved"] == {"helsinki_bikes": "joinedcontext-apps"}, "a project repository moved too"
    assert held["collaborators"]["helsinki_bikes/jc-apps"] == "admin"
    assert "jc-portal" in held["left"], "jc-portal still creates repositories beside the configuration"
    assert held["users"]["jc-apps"]["patched"]["admin"] is False
    minted = [m for m in held["minted"] if not m.startswith(("jc-portal/", "jc-gateway/"))]
    assert minted == ["jc-apps/jc-apps", "jc-apps/jc-registry-pull", "jc-apps/jc-lane-secret"], minted
    pull = json.loads(base64.b64decode(forge.secrets["app-registry"]["data"][".dockerconfigjson"]))
    user = base64.b64decode(pull["auths"]["forge.test"]["auth"]).decode().split(":", 1)[0]
    assert user == "jc-apps", "a node pulls as the applications' user, not the administrator"
    assert "PATCH http://kube.test/apis/apps/v1/namespaces/dev/deployments/portal" in forge.log
    assert any("/orgs/joinedcontext-apps/actions/runners/registration-token" in line for line in forge.log)

    second = forge.run(script, **apart)
    assert second.returncode == 0, second.stderr
    again = state(forge)
    assert again["minted"] == held["minted"] and again["moved"] == held["moved"]


@requires_helmfile
def test_without_an_applications_organization_nothing_moves(script, tmp_path):
    """T-2856: the default keeps the applications beside the configuration, jc-portal creating
    and administering them, and no apps token is minted."""
    forge = Forge(tmp_path, {})
    held = state(forge)
    held["repos"] = {"helsinki_bikes": {"files": {}, "head": "c" * 40}}
    forge.state.write_text(json.dumps(held))
    assert forge.run(script, APPS_ORG="").returncode == 0
    held = state(forge)
    assert not held.get("moved") and not held.get("left")
    assert not any(m.startswith("jc-apps/") for m in held["minted"])


def _portal_env(docs):
    portal = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "portal")
    return {e["name"]: e for e in portal["spec"]["template"]["spec"]["containers"][0]["env"]}


@requires_helmfile
def test_one_value_moves_the_applications_and_the_portal_follows(rendered, rendered_variant):
    """PF-106, T-2856: `gitea.forge.appsOrganization` is the switch. Off by default, so no
    environment moves a repository by surprise; on, the Job gets the organization and the
    Portal the owner and the apps token, by secretRef only."""
    job = next(d for d in rendered("local") if d.get("kind") == "Job" and d["metadata"]["name"] == "gitea-bootstrap")
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["APPS_ORG"] == ""
    assert "JC_GITEA_APPS_OWNER" not in _portal_env(rendered("local"))
    reader = _portal_env(rendered("local"))["JC_GITEA_READER"]["value"]
    assert reader == env["GATEWAY_USER"], "the Portal names another reader than the gateway's user"

    def apart(tree):
        path = tree / "components/gitea/default-environment.yaml.gotmpl"
        text = path.read_text()
        assert '    appsOrganization: ""\n' in text
        path.write_text(text.replace('    appsOrganization: ""\n', "    appsOrganization: joinedcontext-apps\n"))

    docs = rendered_variant("local", apart)
    portal = _portal_env(docs)
    assert portal["JC_GITEA_APPS_OWNER"]["value"] == "joinedcontext-apps"
    token = portal["JC_GITEA_APPS_TOKEN"]
    assert "value" not in token and token["valueFrom"]["secretKeyRef"]["name"] == "gitea-token-apps"
    job = next(d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "gitea-bootstrap")
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["APPS_ORG"] == "joinedcontext-apps"
    assert env["APPS_RESTART"] == "local/portal"
    lane = [d for d in docs if d.get("kind") == "CronJob" and "lane" in d["metadata"]["name"]]
    for cronjob in lane:
        containers = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
        org = next(e["value"] for e in containers[0]["env"] if e["name"] == "ORG")
        assert org == "joinedcontext-apps", "the lane's secret belongs to the organization its builds run in"
