"""T-0048: scripts/emergency-revoke.sh must revoke, restart, and then MEASURE.

The script talks to a cluster and to Keycloak, so the suite runs it against stub
`kubectl` and `curl` on PATH inside a throwaway copy of `scripts/`, the way
test_smoke_script.py does. Every stub call is recorded, so a test can assert both what
the script did and what it never did (OPS-45, R48, PF-38).
"""

import base64
import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "emergency-revoke.sh"

SEEDED_POLICY = """apiVersion: joinedcontext.com/v1alpha1
kind: Policy
metadata:
  name: public-read
  namespace: bb-ovzdusie
spec:
  operations: [retrieveOps]
"""

KUBECTL_STUB = '''#!/usr/bin/env python3
import json, os, sys
spec = json.load(open(os.environ["STUB_SPEC"]))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as log:
    log.write("kubectl " + " ".join(args) + "\\n")

if "get" in args and "secret" in args and "-A" in args:
    if not spec.get("listOk", True):
        sys.exit(1)
    sys.stdout.write("".join(ns + "\\n" for ns in spec.get("secretCopies", [])))
elif "patch" in args and "secret" in args:
    ns = args[args.index("-n") + 1]
    with open(os.environ["STUB_PATCHES"], "a") as patches:
        patches.write(ns + " " + sys.stdin.read().strip() + "\\n")
    sys.exit(1 if ns in spec.get("patchFails", []) else 0)
elif "get" in args and "deployments,statefulsets" in args:
    ns = args[args.index("-n") + 1]
    sys.stdout.write("".join(w + "\\n" for w in spec.get("workloads", {}).get(ns, [])))
elif "get" in args and "configmap" in args:
    sys.stdout.write(spec.get("seededPolicy", ""))
elif "patch" in args:
    sys.exit(0 if spec.get("patchOk", True) else 1)
elif "rollout" in args and "restart" in args:
    sys.exit(0 if spec.get("restartOk", True) else 1)
elif "rollout" in args and "status" in args:
    sys.exit(0 if spec.get("rolloutReady", True) else 1)
else:
    sys.exit(1)
'''

# The verify loop asks the same URL repeatedly; `refusedAfter` is how many calls the
# endpoint keeps answering 200 before the revocation reaches it.
CURL_STUB = '''#!/usr/bin/env python3
import json, os, sys
spec = json.load(open(os.environ["STUB_SPEC"]))
line = " ".join(sys.argv[1:])
with open(os.environ["STUB_CALLS"], "a") as log:
    log.write("curl " + line + "\\n")

if "/protocol/openid-connect/token" in line:
    sys.stdout.write('{"access_token":"admin.token.value"}')
elif "/admin/realms/" in line and "/users?" in line:
    sys.stdout.write(spec.get("userLookup", '[{"id":"user-uuid","username":"jana.kovacova"}]'))
elif "/admin/realms/" in line and "/clients?" in line:
    sys.stdout.write(spec.get("clientLookup", '[{"id":"client-uuid","clientId":"conformance"}]'))
elif "/client-secret" in line:
    sys.stdout.write(spec.get("rotatedAnswer", '{"type":"secret","value":"rotated.client.secret"}'))
    sys.stdout.write("\\n" + str(spec.get("adminWriteStatus", 200)))
elif "/logout" in line:
    sys.stdout.write(str(spec.get("adminWriteStatus", 204)))
else:
    calls = sum(1 for l in open(os.environ["STUB_CALLS"]) if "Authorization: Bearer" in l and "/api/endpoint/" in l)
    still_open = spec.get("refusedAfter", 1)
    sys.stdout.write("200" if calls <= still_open - 1 else str(spec.get("refusedStatus", 403)))
'''


def run(tmp_path: Path, spec: dict, *args: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "emergency-revoke.sh").write_text(SCRIPT.read_text())
    (scripts / "emergency-revoke.sh").chmod(0o755)

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for name, body in (("kubectl", KUBECTL_STUB), ("curl", CURL_STUB)):
        (stub_bin / name).write_text(body)
        (stub_bin / name).chmod(0o755)

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    calls_file = tmp_path / "calls.log"
    calls_file.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["STUB_SPEC"] = str(spec_file)
    env["STUB_CALLS"] = str(calls_file)
    env["STUB_PATCHES"] = str(tmp_path / "patches.log")
    env.setdefault("KEYCLOAK_ADMIN_TOKEN", "admin.token.value")

    result = subprocess.run(
        ["scripts/emergency-revoke.sh", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    return result, calls_file.read_text().splitlines()


def token_file(tmp_path: Path) -> str:
    path = tmp_path / "compromised-token"
    path.write_text("compromised.jwt.value")
    return str(path)


def test_nothing_to_revoke_is_refused(tmp_path):
    result, calls = run(tmp_path, {}, "--instance", "dev")
    assert result.returncode == 2, result.stdout
    assert "nothing to revoke" in result.stderr
    assert calls == [], "a refused invocation must not touch the cluster"


def test_the_policy_leaves_the_repository_before_the_gateway_restarts(tmp_path):
    result, calls = run(
        tmp_path, {"seededPolicy": SEEDED_POLICY},
        "--instance", "dev", "--namespace", "dev", "--policy", "public-read",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    patch = next(i for i, c in enumerate(calls) if "patch configmap" in c)
    restart = next(i for i, c in enumerate(calls) if "rollout restart" in c)
    assert patch < restart, "restarting first would reload the policy that is being revoked"
    assert '"op": "remove"' in calls[patch] and "/data/policy.yaml" in calls[patch]


def test_a_policy_the_repository_does_not_carry_fails_loudly(tmp_path):
    result, calls = run(
        tmp_path, {"seededPolicy": ""},
        "--instance", "dev", "--policy", "public-read",
    )
    assert result.returncode == 1
    assert "is not in configmap" in result.stderr
    assert not any("patch configmap" in c for c in calls), "nothing to remove, nothing patched"


def test_an_unfinished_rollout_is_a_failure_not_a_revocation(tmp_path):
    result, _ = run(
        tmp_path, {"seededPolicy": SEEDED_POLICY, "rolloutReady": False},
        "--instance", "dev", "--policy", "public-read", "--bound", "1",
    )
    assert result.returncode == 1
    assert "did not become ready" in result.stderr


def test_a_user_is_logged_out_and_a_service_account_secret_is_rotated(tmp_path):
    result, calls = run(
        tmp_path, {"seededPolicy": SEEDED_POLICY},
        "--instance", "dev", "--policy", "public-read",
        "--user", "jana.kovacova", "--service-account", "conformance",
        "--idm", "https://idm.example.test",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("/admin/realms/dev/users/user-uuid/logout" in c for c in calls)
    assert any("/admin/realms/dev/clients/client-uuid/client-secret" in c for c in calls)


def test_the_refusal_is_measured_and_passes_inside_the_bound(tmp_path):
    result, calls = run(
        tmp_path, {"seededPolicy": SEEDED_POLICY, "refusedAfter": 1},
        "--instance", "dev", "--policy", "public-read", "--bound", "5",
        "--verify-url", "https://host/api/endpoint/slug/ngsi-ld/v1/entities?type=X",
        "--verify-token-file", token_file(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "is refused (403)" in result.stdout
    assert any("/api/endpoint/" in c and "Authorization: Bearer" in c for c in calls)


def test_a_credential_still_accepted_after_the_bound_fails_the_run(tmp_path):
    result, _ = run(
        tmp_path, {"seededPolicy": SEEDED_POLICY, "refusedAfter": 99},
        "--instance", "dev", "--policy", "public-read", "--bound", "2",
        "--verify-url", "https://host/api/endpoint/slug/ngsi-ld/v1/entities?type=X",
        "--verify-token-file", token_file(tmp_path),
    )
    assert result.returncode == 1
    assert "still answers 200" in result.stderr
    assert "OPS-45" in result.stderr


def test_no_token_or_password_is_ever_printed(tmp_path):
    env_secret = "sup3r-admin-password"
    os.environ["KEYCLOAK_ADMIN_PASSWORD"] = env_secret
    try:
        result, _ = run(
            tmp_path, {"seededPolicy": SEEDED_POLICY, "refusedAfter": 1},
            "--instance", "dev", "--policy", "public-read",
            "--user", "jana.kovacova", "--idm", "https://idm.example.test",
            "--verify-url", "https://host/api/endpoint/slug/ngsi-ld/v1/entities?type=X",
            "--verify-token-file", token_file(tmp_path),
        )
    finally:
        del os.environ["KEYCLOAK_ADMIN_PASSWORD"]
    printed = result.stdout + result.stderr
    for secret in (env_secret, "admin.token.value", "compromised.jwt.value"):
        assert secret not in printed, f"{secret} reached the console"


# T-2841: a platform client's secret lives in the generated Secret `keycloak-client-<client>`,
# which keycloak-config-cli imports on every apply. Rotated in Keycloak alone, the next apply
# wrote the compromised secret back.
EDGE_READER = 'Deployment/apisix {"containers":[{"env":[{"name":"OIDC_SECRET","valueFrom":{"secretKeyRef":{"key":"client-secret","name":"keycloak-client-edge"}}}]}]}'
PROXY_READER = 'Deployment/bikes-agent-proxy {"volumes":[{"name":"s","secret":{"secretName":"keycloak-client-edge-agent-proxy"}}]}'


def revoke_client(tmp_path: Path, spec: dict, client: str = "edge"):
    return run(
        tmp_path, {"seededPolicy": SEEDED_POLICY, **spec},
        "--instance", "dev", "--policy", "public-read",
        "--service-account", client, "--idm", "https://idm.example.test",
    )


def patches(tmp_path: Path) -> list[str]:
    path = tmp_path / "patches.log"
    return path.read_text().splitlines() if path.exists() else []


def test_a_platform_clients_new_secret_reaches_every_copy_and_its_readers_restart(tmp_path):
    result, calls = revoke_client(tmp_path, {
        "secretCopies": ["keycloak", "apisix"],
        "workloads": {"apisix": [EDGE_READER, PROXY_READER]},
    })
    assert result.returncode == 0, result.stdout + result.stderr
    written = base64.b64encode(b"rotated.client.secret").decode()
    assert patches(tmp_path) == [
        f'keycloak {{"data":{{"client-secret":"{written}"}}}}',
        f'apisix {{"data":{{"client-secret":"{written}"}}}}',
    ], "Keycloak and every copy of the Secret must hold the same new secret"
    rotated = next(i for i, c in enumerate(calls) if "/client-secret" in c)
    first_patch = next(i for i, c in enumerate(calls) if "patch secret keycloak-client-edge" in c)
    assert rotated < first_patch
    assert any("-n apisix rollout restart deployment/apisix" in c for c in calls)
    assert not any("bikes-agent-proxy" in c and "restart" in c for c in calls), "only the readers of this Secret restart"
    printed = result.stdout + result.stderr
    assert "rotated.client.secret" not in printed and written not in printed
    assert not any("rotated.client.secret" in c or written in c for c in calls), "the secret never rides on a command line"


def test_a_client_the_portal_created_is_rotated_in_keycloak_only(tmp_path):
    result, calls = revoke_client(tmp_path, {"secretCopies": []}, client="bikes-sensors")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rotated in Keycloak only" in result.stdout
    assert patches(tmp_path) == []
    assert any("/client-secret" in c for c in calls)


def test_a_copy_left_with_the_revoked_secret_fails_the_run(tmp_path):
    result, _ = revoke_client(tmp_path, {
        "secretCopies": ["keycloak", "apisix"],
        "patchFails": ["apisix"],
    })
    assert result.returncode == 1
    assert "Secret keycloak-client-edge in apisix still holds the revoked secret" in result.stderr


def test_no_new_secret_in_keycloaks_answer_leaves_the_secret_alone_and_fails(tmp_path):
    result, _ = revoke_client(tmp_path, {"secretCopies": ["keycloak"], "rotatedAnswer": "{}"})
    assert result.returncode == 1
    assert "did not answer the new secret" in result.stderr
    assert patches(tmp_path) == []


def test_copies_that_cannot_be_listed_fail_the_run(tmp_path):
    result, _ = revoke_client(tmp_path, {"listOk": False})
    assert result.returncode == 1
    assert "cannot list the copies of Secret keycloak-client-edge" in result.stderr
