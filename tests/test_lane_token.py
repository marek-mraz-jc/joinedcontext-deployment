"""The build lane's token as the Actions organization secret JC_LANE_TOKEN (T-2636, AP-73,
AP-80, ADR-N-028 §5).

Nothing provisioned it, so every `propose` job failed with "JC_LANE_TOKEN is not set" and no
App on dev ever got `status.build`. The lane is a confidential client with one audience and a
short token, a Role that writes `status.build` alone, and a CronJob that mints the token and
writes the one secret. These read the dev render, and run the CronJob's script against a curl
stub, as `test_forge_bootstrap.py` does for the bootstrap Job.
"""

import base64
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/helsinki"
# A token-shaped fixture, built from parts so the secret scan does not read it as one (T-0542).
JWT = ".".join(
    base64.urlsafe_b64encode(json.dumps(part, separators=(",", ":")).encode()).decode().rstrip("=")
    for part in ({"alg": "ES256"}, {"azp": "jc-build-lane"})
) + ".c2lnbmF0dXJl"


def one(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


@pytest.fixture(scope="module")
def lane_client(dev):
    realm_secret = next(
        d for d in dev if d.get("kind") == "Secret" and d["metadata"]["name"].endswith("config-cli-config-realms")
    )
    realm = json.loads(base64.b64decode(next(iter(realm_secret["data"].values()))))
    realm = realm[0] if isinstance(realm, list) else realm
    return next(c for c in realm["clients"] if c["clientId"] == "jc-build-lane")


@pytest.fixture(scope="module")
def cronjob(dev):
    return one(dev, "CronJob", "gitea-lane-token")


def test_the_lane_client_mints_short_portal_api_tokens_and_nothing_else(lane_client):
    assert lane_client["serviceAccountsEnabled"] is True
    assert lane_client["publicClient"] is False
    for flow in ("standardFlowEnabled", "implicitFlowEnabled", "directAccessGrantsEnabled"):
        assert lane_client[flow] is False, flow
    audiences = {
        m["config"].get("included.client.audience") or m["config"].get("included.custom.audience")
        for m in lane_client["protocolMappers"]
        if m["protocolMapper"] == "oidc-audience-mapper"
    }
    assert audiences == {"portal-api"}, "the gateway and the internal listener refuse its token"
    assert lane_client["attributes"]["access.token.lifespan"] == "900"


def test_the_refresher_holds_the_two_secrets_as_files_and_no_kubernetes_token(dev, cronjob):
    job = cronjob["spec"]["jobTemplate"]["spec"]
    pod = job["template"]["spec"]
    assert cronjob["spec"]["schedule"] == "*/5 * * * *", "every 5 minutes, a token lives 15"
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert pod["automountServiceAccountToken"] is False
    secrets = {v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v}
    assert secrets == {"keycloak-client-jc-build-lane", "gitea-token-lane-secret"}
    container = pod["containers"][0]
    assert not any("valueFrom" in e for e in container["env"]), "no secret in the environment"
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["SECRET_NAME"] == "JC_LANE_TOKEN"
    assert env["TOKEN_URL"].startswith("http://keycloak-app-keycloakx-http.")
    assert env["TOKEN_URL"].endswith("/protocol/openid-connect/token")
    bootstrap = one(dev, "Job", "gitea-bootstrap")["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == bootstrap["image"], "the forge's own pinned image"
    lane = {e["name"]: e.get("value") for e in bootstrap["env"]}
    assert json.loads(lane["LANE_SCOPES"]) == ["write:organization"]
    assert lane["LANE_NAMESPACES"]


def test_the_refresher_reaches_keycloak_and_the_forge_alone(dev):
    policy = one(dev, "NetworkPolicy", "gitea-lane-token")["spec"]
    assert policy["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "lane-token"}
    assert policy.get("ingress", []) == []
    peers = {
        (json.dumps(rule["to"][0].get("podSelector", {}), sort_keys=True), rule["ports"][0]["port"])
        for rule in policy["egress"]
    }
    assert len(peers) == 3, peers
    assert any('"keycloak-app"' in peer and port == 8080 for peer, port in peers)
    assert any('"gitea-forge"' in peer and port == 3000 for peer, port in peers)
    for rule in policy["egress"]:
        assert all("ipBlock" not in peer for peer in rule["to"]), "no address range"


def test_the_seed_binds_the_lane_account_to_a_role_that_writes_status_build_alone():
    role = yaml.safe_load((SEED / "helsinki-role-build-lane.yaml").read_text())
    assert role["spec"]["rules"] == [
        {"kinds": ["App"], "verbs": ["propose"], "constraints": [{"field": "status.build"}]}
    ]
    binding = yaml.safe_load((SEED / "helsinki-rolebinding-build-lane.yaml").read_text())
    assert binding["spec"]["subjects"] == [{"user": "service-account-jc-build-lane"}]
    assert binding["spec"]["role"] == "build-lane"
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    assert index["helsinki-role-build-lane.yaml"] == "users/roles/build-lane.yaml"
    assert index["helsinki-rolebinding-build-lane.yaml"] == "users/assignments/build-lane.yaml"


CURL = r'''#!/usr/bin/env python3
"""A curl for the refresher's script: records each call, answers from the environment."""
import json, os, sys
args = sys.argv[1:]
out, method, url, headers, data = None, "GET", None, [], []
i = 0
while i < len(args):
    a = args[i]
    if a in ("-o", "-w", "-X", "-H", "--data", "--data-urlencode"):
        value = args[i + 1]
        if a == "-o": out = value
        elif a == "-X": method = value
        elif a == "-H":
            headers.append(open(value[1:]).read().strip() if value.startswith("@") else value)
        elif a == "--data": data.append(open(value[1:]).read() if value.startswith("@") else value)
        elif a == "--data-urlencode":
            name, _, rest = value.partition("@") if "@" in value and "=" not in value.split("@")[0] else (value, "", "")
            data.append(f"{name}=<{rest}>" if rest else value)
        i += 2
        continue
    if not a.startswith("-"): url = a
    i += 1
with open(os.environ["FAKE_CALLS"], "a") as log:
    log.write(json.dumps({"method": method, "url": url, "headers": headers, "data": data}) + "\n")
token = url == os.environ["TOKEN_URL"]
code = os.environ["FAKE_TOKEN_CODE" if token else "FAKE_FORGE_CODE"]
if out and out != "/dev/null":
    open(out, "w").write(os.environ.get("FAKE_TOKEN_BODY", "") if token else "")
sys.stdout.write(code)
'''


def run_refresher(cronjob, tmp_path, token_code="200", forge_code="201", body=None):
    script = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(CURL)
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    for folder, name, value in (("lane", "client-secret", "the-lane-client-secret"), ("forge", "token", "f" * 40)):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_text(value)
    (tmp_path / "work").mkdir()
    calls = tmp_path / "calls.log"
    calls.write_text("")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WORK": str(tmp_path / "work"),
        "LANE_DIR": str(tmp_path / "lane"),
        "FORGE_DIR": str(tmp_path / "forge"),
        "GITEA_URL": "http://forge.test",
        "ORG": "joinedcontext",
        "TOKEN_URL": "http://keycloak.test/realms/jc/protocol/openid-connect/token",
        "CLIENT_ID": "jc-build-lane",
        "SECRET_NAME": "JC_LANE_TOKEN",
        "FAKE_CALLS": str(calls),
        "FAKE_TOKEN_CODE": token_code,
        "FAKE_FORGE_CODE": forge_code,
        "FAKE_TOKEN_BODY": body if body is not None else json.dumps({"access_token": JWT, "expires_in": 900}),
    }
    result = subprocess.run(["sh", "-c", script], env=environment, capture_output=True, text=True)
    return result, [json.loads(line) for line in calls.read_text().splitlines()], tmp_path / "work"


def test_a_run_writes_the_fresh_token_as_the_one_org_secret_and_prints_no_secret(cronjob, tmp_path):
    result, calls, work = run_refresher(cronjob, tmp_path)
    assert result.returncode == 0, result.stderr
    assert [c["method"] for c in calls] == ["POST", "PUT"]
    assert "client_secret=<" in " ".join(calls[0]["data"]), "the client secret goes in from its file"
    assert "the-lane-client-secret" not in json.dumps(calls[0]), "never on a command line"
    assert calls[1]["url"] == "http://forge.test/api/v1/orgs/joinedcontext/actions/secrets/JC_LANE_TOKEN"
    assert json.loads(calls[1]["data"][0]) == {"data": JWT}
    assert calls[1]["headers"][0] == "Authorization: token " + "f" * 40
    output = result.stdout + result.stderr
    for secret in (JWT, "the-lane-client-secret", "f" * 40):
        assert secret not in output
    assert list(work.iterdir()) == [], "nothing of the token stays behind"


@pytest.mark.parametrize(
    ("token_code", "forge_code", "body", "says"),
    [
        ("401", "201", "", "the realm answered 401"),
        ("200", "201", json.dumps({"error": "no token"}), "no access token"),
        ("200", "201", json.dumps({"access_token": "not a jwt"}), "no access token"),
        ("200", "403", None, "the forge answered 403"),
    ],
)
def test_a_refusal_fails_the_run_and_writes_nothing_it_did_not_mint(cronjob, tmp_path, token_code, forge_code, body, says):
    result, calls, _ = run_refresher(cronjob, tmp_path, token_code, forge_code, body)
    assert result.returncode == 1
    assert says in result.stderr, result.stderr
    if token_code != "200" or "no access token" in says:
        assert [c["method"] for c in calls] == ["POST"], "no secret is written without a token"
    assert JWT not in result.stdout + result.stderr
