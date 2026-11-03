"""T-6542: one presenter, the same login and rights on dev, stage and the production instance.

The owner presents as `presenter@hel.fi` on all three. Each realm seeds the person under one id
with the same realm roles and groups, the forge seeds bind them beside the demo steward and each
other Organization's administrator, and the password and TOTP seed are only in the sops file.
"""

import base64
import json
import re
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENTS = ROOT / ".ci/example-deployments/environments"
KEYCLOAK = ROOT / "components/keycloak"
INSTANCES = ("dev", "stage", "smartcity")
PRESENTER = yaml.safe_load((KEYCLOAK / "presenter.yaml").read_text())
PEOPLE = yaml.safe_load((KEYCLOAK / "demo-users.yaml").read_text())
ADMINS = ("demo.steward", "demo.zilina", "demo.barcelona", "demo.bratislava")


def presenter_id(env: str) -> str | None:
    path = ENVIRONMENTS / env / "global.yaml.gotmpl"
    found = re.findall(r"(?m)^  presenterUserId: (\S+)", path.read_text()) if path.is_file() else []
    return found[0] if found else None


def test_the_three_instances_name_one_presenter_and_no_other_does():
    ids = {env: presenter_id(env) for env in INSTANCES}
    assert len(set(ids.values())) == 1, ids
    [one] = set(ids.values())
    assert uuid.UUID(one).version == 4 and not one.startswith("de300000-"), "a demo id is refused on production"
    others = [p.name for p in ENVIRONMENTS.iterdir() if p.is_dir() and p.name not in INSTANCES and presenter_id(p.name)]
    assert not others, others


def test_the_presenter_holds_the_administrators_rights_and_no_wider_role():
    """Security: what the steward and the other Organizations' administrators hold, plus TOTP."""
    admin_roles = set().union(*(PEOPLE[name]["realmRoles"] for name in ADMINS))
    assert set(PRESENTER["realmRoles"]) == admin_roles | {"mfa-required"}
    assert "platform-admin" not in PRESENTER["realmRoles"]
    assert set(PRESENTER["groups"]) == set().union(*(PEOPLE[name]["groups"] for name in ADMINS))
    assert "id" not in PRESENTER, "the id is per instance values, the same on all three"


def test_the_password_and_totp_seed_are_only_in_the_sops_file():
    encrypted = yaml.safe_load((KEYCLOAK / "presenter.enc.yaml").read_text())
    values = {key: value for key, value in encrypted.items() if key != "sops"}
    assert set(values) == {"username", "password", "totp", "totpUri"}
    assert all(str(value).startswith("ENC[AES256_GCM,") for value in values.values()), "a plain value in Git"


def config_users(docs: list[dict]) -> dict[str, dict]:
    """The realm import's users, from the keycloak-config-cli realm Secret."""
    for doc in docs:
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            realms = [json.loads(base64.b64decode(value)) for value in doc["data"].values()]
            return {user["username"]: user for realm in realms for user in realm.get("users") or []}
    pytest.fail("no keycloak-config-cli realm Secret in the render")


def seed_texts(docs: list[dict]) -> list[str]:
    return [
        text
        for doc in docs
        if doc.get("kind") == "ConfigMap" and doc["metadata"]["name"].startswith(("gitea-", "sample-apps"))
        for text in (doc.get("data") or {}).values()
        if isinstance(text, str)
    ]


@pytest.mark.parametrize("env", INSTANCES)
def test_each_realm_seeds_the_same_person_with_a_second_factor(rendered, env):
    docs = rendered(env)
    user = config_users(docs).get("presenter@hel.fi")
    assert user, f"{env}: the realm import seeds no presenter"
    extra = set(user["realmRoles"]) - set(PRESENTER["realmRoles"])
    assert len(extra) == 1 and extra.pop().startswith("default-roles-"), user["realmRoles"]
    assert set(user["groups"]) == {"/platform-readers"} | {f"/{g}" for g in PRESENTER["groups"]}
    assert {c["type"] for c in user["credentials"]} == {"password", "otp"}
    secrets = [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "keycloak-user-presenter"]
    assert secrets and all({"password", "totp"} <= set(d["data"]) for d in secrets), env


@pytest.mark.parametrize("env", INSTANCES)
def test_the_seeds_bind_the_presenter_beside_every_administrator_once(rendered, env):
    one = presenter_id(env)
    texts = seed_texts(rendered(env))
    bound = [t for t in texts if one in t]
    assert bound, f"{env}: no seed names the presenter"
    for org in ("hel", "zilina", "barcelona", "bratislava"):
        assert any(
            doc.get("kind") == "RoleBinding" and doc["spec"]["role"] == "org-admin"
            and doc["spec"]["scope"] == {"organization": org}
            and {"user": one} in doc["spec"]["subjects"]
            for text in bound for doc in yaml.safe_load_all(text) if isinstance(doc, dict)
        ), f"{env}: the presenter administers no {org}"
    for text in bound:
        for doc in yaml.safe_load_all(text):
            if not isinstance(doc, dict):
                continue
            members = (doc.get("spec") or {}).get("subjects") or (doc.get("spec") or {}).get("members") or []
            assert sum(m == {"user": one} for m in members) <= 1, doc["metadata"]
