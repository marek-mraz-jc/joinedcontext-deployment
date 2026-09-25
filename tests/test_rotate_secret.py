"""OPS-45, T-1719: scripts/rotate-secret.sh rotates an in-cluster credential and MEASURES it.

The script talks to a cluster, to helmfile, to Keycloak, to the forge and to PostgreSQL, so
the suite runs it against stubs on PATH that keep one small state file: which value each
copy of the Secret holds, which value the other side still accepts, and every call made. A
test asserts what the script did, in which order, and that no value ever reached a command
line, the output or the log.
"""

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "rotate-secret.sh"

OLD = "old-Value-9f3a*x"
NEW = "new-Value-7c2b~y"

KUBECTL_STUB = r'''#!/usr/bin/env python3
import base64, json, os, sys
state_path = os.environ["STUB_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as log:
    log.write("kubectl " + " ".join(args) + "\n")

def save():
    json.dump(state, open(state_path, "w"))

ns = args[args.index("-n") + 1] if "-n" in args else None
out = next((a for a in args if a.startswith("jsonpath=")), "")
if args[:3] == ["get", "secret", "-A"]:
    print("\n".join(n for n, v in state["copies"].items() if v is not None))
elif "get" in args and "secret" in args and ns is not None:
    value = state["copies"].get(ns)
    if value is None:
        sys.exit(1)
    if out == "jsonpath={.data}":
        sys.stdout.write(json.dumps({"key": base64.b64encode(value.encode()).decode()}))
    elif "release-name" in out:
        sys.stdout.write(state.get("release", ""))
    elif "username" in out:
        sys.stdout.write(base64.b64encode(b"portal").decode())
    else:
        sys.stdout.write(base64.b64encode(value.encode()).decode())
elif "delete" in args and "secret" in args:
    state["copies"][ns] = None
    save()
elif "get" in args and "deployment,statefulset,daemonset" in args:
    print(json.dumps({"items": state.get("workloads", {}).get(ns, [])}))
elif "rollout" in args:
    sys.exit(0)
elif "get" in args and "pod" in args:
    sys.stdout.write(state.get("primary", "/"))
elif "exec" in args:
    password = sys.stdin.readline().rstrip("\n")
    sys.exit(0 if password == state["accepted"] else 2)
else:
    sys.exit(1)
'''

HELMFILE_STUB = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["STUB_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as log:
    log.write("helmfile " + " ".join(args) + "\n")
selector = args[args.index("-l") + 1]
if selector.startswith("secret-name=") or selector == "release=gitea-bootstrap":
    value = state["regenerate"]
    for ns in state["copies"]:
        state["copies"][ns] = value
    # A forge token is deleted in Gitea by the bootstrap itself; a database role follows its Secret.
    if state.get("pushedBy") == selector.split("=")[0] or state.get("pushedBy") == "generator":
        state["accepted"] = value
if selector == "release=keycloak-config" and state.get("configPushes", True):
    state["accepted"] = next(v for v in state["copies"].values() if v is not None)
json.dump(state, open(state_path, "w"))
'''

CURL_STUB = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["STUB_STATE"]))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as log:
    log.write("curl " + " ".join(args) + "\n")
stdin = sys.stdin.read()
if "client_secret@-" in args:
    value = stdin
elif "-K" in args:
    value = stdin.split("Authorization: token ", 1)[1].rsplit('"', 1)[0]
else:
    sys.exit(2)
sys.stdout.write("200" if value == state["accepted"] else "401")
'''


def run(tmp_path: Path, state: dict, *args: str):
    state = {"copies": {"keycloak": OLD, "portal": OLD}, "accepted": OLD, "release": "secrets-x", **state}
    state["regenerate"] = state.get("regenerate", NEW)
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "rotate-secret.sh").write_text(SCRIPT.read_text())
    (scripts / "rotate-secret.sh").chmod(0o755)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for name, body in (("kubectl", KUBECTL_STUB), ("helmfile", HELMFILE_STUB), ("curl", CURL_STUB)):
        (stub_bin / name).write_text(body)
        (stub_bin / name).chmod(0o755)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    calls_file = tmp_path / "calls.log"
    calls_file.write_text("")
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["STUB_STATE"] = str(state_file)
    env["STUB_CALLS"] = str(calls_file)
    result = subprocess.run(
        ["scripts/rotate-secret.sh", "--bound", "2", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    calls = calls_file.read_text().splitlines()
    for text in (result.stdout, result.stderr, *calls):
        assert OLD not in text and NEW not in text, "a credential reached the output or a command line"
    return result, calls, json.loads(state_file.read_text())


def deployment(name: str, secret: str) -> dict:
    return {
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {"template": {"spec": {"containers": [
            {"name": "app", "env": [{"name": "S", "valueFrom": {"secretKeyRef": {"name": secret, "key": "k"}}}]},
        ]}}},
    }


CLIENT = ("--instance", "dev", "--secret", "keycloak-client-portal-api", "--idm", "https://idm.x", "--realm", "r")


def test_what_the_platform_does_not_generate_is_refused_and_nothing_is_touched(tmp_path):
    """OPS-45: the administrators and operator-supplied keys have their own runbook."""
    for name in ("gitea-admin-credentials", "keycloak-admin-user", "agent-runner-model-key"):
        result, calls, _ = run(tmp_path, {}, "--instance", "dev", "--secret", name)
        assert result.returncode == 2, name
        assert "Runbook 5" in result.stderr
        assert calls == []


def test_a_secret_without_a_helm_release_is_never_deleted(tmp_path):
    result, calls, state = run(tmp_path, {"release": ""}, "--instance", "dev", "--secret", "portal-cookie-key")
    assert result.returncode == 2
    assert "no Helm release" in result.stderr
    assert not any("delete" in c for c in calls)
    assert state["copies"] == {"keycloak": OLD, "portal": OLD}


def test_a_client_secret_is_rotated_everywhere_pushed_to_keycloak_and_measured(tmp_path):
    """OPS-45: every copy goes before the apply, Keycloak gets the new one, readers restart."""
    workloads = {"portal": [deployment("portal", "keycloak-client-portal-api"), deployment("other", "unrelated")]}
    result, calls, state = run(tmp_path, {"workloads": workloads}, *CLIENT)
    assert result.returncode == 0, result.stdout + result.stderr
    deletes = [i for i, c in enumerate(calls) if "delete secret" in c]
    generator = next(i for i, c in enumerate(calls) if "secret-name=keycloak-client-portal-api sync" in c)
    config = next(i for i, c in enumerate(calls) if "release=keycloak-config sync" in c)
    assert len(deletes) == 2 and max(deletes) < generator < config
    restarted = [c for c in calls if "rollout restart" in c]
    assert restarted == ["kubectl -n portal rollout restart deployment/portal"]
    assert state["copies"] == {"keycloak": NEW, "portal": NEW}
    assert "the old value is refused" in result.stdout
    assert "rotated" in result.stdout


def test_a_client_secret_keycloak_never_received_fails_the_run(tmp_path):
    """The measurement, not the apply, decides: the old secret still working is a failure."""
    result, _, _ = run(tmp_path, {"configPushes": False}, *CLIENT)
    assert result.returncode == 1
    assert "still accepted" in result.stdout


def test_a_copy_that_survives_the_apply_stops_the_run(tmp_path):
    result, _, _ = run(tmp_path, {"regenerate": OLD}, *CLIENT)
    assert result.returncode == 2
    assert "holds the old value" in result.stderr


def test_a_database_password_is_measured_by_a_login_on_the_primary(tmp_path):
    state = {"copies": {"portal": OLD, "postgres": OLD}, "pushedBy": "generator", "primary": "postgres/pg-1"}
    result, calls, _ = run(tmp_path, state, "--instance", "dev", "--secret", "db-portal")
    assert result.returncode == 0, result.stdout + result.stderr
    logins = [c for c in calls if " exec -i pg-1 " in c]
    assert len(logins) == 2, "one login with the old password, one with the new"
    assert all("PGPASSWORD" in c and "-U 'portal'" in c for c in logins)


def test_a_database_with_no_primary_to_ask_fails_rather_than_passes(tmp_path):
    state = {"copies": {"portal": OLD}, "pushedBy": "generator", "primary": "/"}
    result, _, _ = run(tmp_path, state, "--instance", "dev", "--secret", "db-portal")
    assert result.returncode == 1
    assert "no CloudNativePG primary" in result.stdout


def test_a_forge_token_is_minted_again_by_the_bootstrap_and_the_old_one_is_refused(tmp_path):
    state = {"copies": {"portal": OLD}, "release": "", "pushedBy": "release"}
    result, calls, _ = run(tmp_path, state, "--instance", "dev", "--secret", "gitea-token-portal", "--forge", "https://x/git")
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("release=gitea-bootstrap sync" in c for c in calls)
    assert not any("secret-name=" in c for c in calls)


def test_a_session_key_is_rotated_and_its_readers_restart_without_a_measurement(tmp_path):
    workloads = {"portal": [deployment("portal", "portal-cookie-key")]}
    result, calls, _ = run(tmp_path, {"workloads": workloads}, "--instance", "dev", "--secret", "portal-cookie-key")
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("rollout restart deployment/portal" in c for c in calls)
    assert not any(c.startswith("curl") for c in calls)


def test_a_session_key_that_comes_back_unchanged_stops_the_run(tmp_path):
    result, _, _ = run(tmp_path, {"regenerate": OLD}, "--instance", "dev", "--secret", "portal-cookie-key")
    assert result.returncode == 2
    assert "holds the old value" in result.stderr


def test_a_demo_persons_password_is_pushed_to_the_realm(tmp_path):
    result, calls, _ = run(tmp_path, {}, "--instance", "dev", "--secret", "keycloak-user-jana")
    assert result.returncode == 0, result.stdout + result.stderr
    generator = next(i for i, c in enumerate(calls) if "secret-name=keycloak-user-jana sync" in c)
    config = next(i for i, c in enumerate(calls) if "release=keycloak-config sync" in c)
    assert generator < config
