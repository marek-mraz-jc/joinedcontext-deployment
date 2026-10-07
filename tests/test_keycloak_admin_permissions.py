"""T-2725, AP-27: the admin-permissions Job narrows the Portal's client administration.

The pinned Keycloak runs in a container with a realm shaped like ours: fine-grained admin
permissions on, `portal-api` holding `view-clients` and `query-users`, the `edge` client, and an
App client carrying `managed-by: joinedcontext`. The Job's own script runs inside it, and the
test asks the Admin API as `portal-api` what it may still do. Measured on Keycloak 26.6.4 on
2026-10-06: before the script `portal-api` writes nothing; after it, it creates and changes App
clients and is refused every write on the edge, on itself and on Keycloak's own clients.
"""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "components/keycloak/charts/admin-permissions/files/sync-admin-permissions.sh"
IMAGES = ROOT / "components/keycloak/images.yaml"
REALM = "t2725"

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="no container runtime for Keycloak")


def image() -> str:
    app = yaml.safe_load(IMAGES.read_text())["keycloak"]["app"]
    return f"{app['repository']}:{app['tag']}@{app['digest']}"


def call(base, method, path, token=None, body=None, form=None):
    data, headers = None, {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text.strip().startswith(("[", "{")) else text, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:300], error.headers


def token(base, realm, client, secret=None, user=None):
    form = {"client_id": client}
    if user:
        form.update(grant_type="password", username=user, password=user)
    else:
        form.update(grant_type="client_credentials", client_secret=secret)
    status, body, _ = call(base, "POST", f"/realms/{realm}/protocol/openid-connect/token", form=form)
    assert status == 200, body
    return body["access_token"]


@pytest.fixture(scope="module")
def keycloak():
    name = f"t2725-kc-{int(time.time())}"
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "-P", "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
         "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=admin", image(), "start-dev"],
        check=True, capture_output=True,
    )
    try:
        port = subprocess.run(["docker", "port", name, "8080/tcp"], check=True, capture_output=True,
                              text=True).stdout.split("\n")[0].rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                if call(base, "GET", "/realms/master")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(2)
        else:
            pytest.fail("Keycloak did not start within 3 minutes")
        subprocess.run(["docker", "cp", str(SCRIPT), f"{name}:/tmp/sync.sh"], check=True)
        yield name, base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def realm(base, permissions=True):
    """The realm as our import leaves it, before the Job: returns the ids the checks use."""
    admin = token(base, "master", "admin-cli", user="admin")
    call(base, "DELETE", f"/admin/realms/{REALM}", admin)
    status, body, _ = call(base, "POST", "/admin/realms", admin,
                           {"realm": REALM, "enabled": True, "adminPermissionsEnabled": permissions})
    assert status == 201, body

    def client(client_id, attributes=None, service_account=False):
        status, body, headers = call(base, "POST", f"/admin/realms/{REALM}/clients", admin, {
            "clientId": client_id, "publicClient": False, "secret": f"{client_id}-secret",
            "serviceAccountsEnabled": service_account, "attributes": attributes or {}})
        assert status == 201, body
        return headers["Location"].rsplit("/", 1)[1]

    ids = {
        "portal": client("portal-api", service_account=True),
        "edge": client("edge"),
        "app": client("app-bikes", {"managed-by": "joinedcontext"}),
    }
    management = call(base, "GET", f"/admin/realms/{REALM}/clients?clientId=realm-management", admin)[1][0]["id"]
    roles = {r["name"]: r for r in call(base, "GET", f"/admin/realms/{REALM}/clients/{management}/roles", admin)[1]}
    account = call(base, "GET", f"/admin/realms/{REALM}/clients/{ids['portal']}/service-account-user", admin)[1]["id"]
    status, body, _ = call(base, "POST", f"/admin/realms/{REALM}/users/{account}/role-mappings/clients/{management}",
                           admin, [roles["view-clients"], roles["query-users"]])
    assert status == 204, body
    ids["admin"] = admin
    return ids


def sync(name):
    return subprocess.run(
        ["docker", "exec", "-e", "KEYCLOAK_URL=http://localhost:8080", "-e", "KEYCLOAK_USER=admin",
         "-e", "KEYCLOAK_PASSWORD=admin", "-e", f"REALM={REALM}", "-e", "PRINCIPAL=portal-api",
         name, "bash", "/tmp/sync.sh"],
        capture_output=True, text=True, timeout=180,
    )


def may(base, ids):
    portal = token(base, REALM, "portal-api", "portal-api-secret")
    admin = lambda method, path, body=None: call(base, method, f"/admin/realms/{REALM}{path}", portal, body)[0]
    return {
        "create an app client": admin("POST", "/clients", {"clientId": f"app-{time.time_ns()}",
                                                           "attributes": {"managed-by": "joinedcontext"}}),
        "change an app client": admin("PUT", f"/clients/{ids['app']}", {"clientId": "app-bikes", "description": "x",
                                                                          "attributes": {"managed-by": "joinedcontext"}}),
        "change the edge": admin("PUT", f"/clients/{ids['edge']}", {"clientId": "edge", "description": "x"}),
        "regenerate the edge secret": admin("POST", f"/clients/{ids['edge']}/client-secret"),
        "delete the edge": admin("DELETE", f"/clients/{ids['edge']}"),
        "change itself": admin("PUT", f"/clients/{ids['portal']}", {"clientId": "portal-api", "description": "x"}),
        "list clients": admin("GET", "/clients"),
    }


def test_the_portal_writes_its_own_clients_and_no_other(keycloak):
    name, base = keycloak
    ids = realm(base)
    before = may(base, ids)
    assert before["create an app client"] == 403 and before["change an app client"] == 403, before

    first = sync(name)
    assert first.returncode == 0, first.stderr
    assert "denied portal-api the writes on" in first.stdout
    after = may(base, ids)
    assert after == {
        "create an app client": 201,
        "change an app client": 204,
        "change the edge": 403,
        "regenerate the edge secret": 403,
        "delete the edge": 403,
        "change itself": 403,
        "list clients": 200,
    }, after

    # Idempotent: a second run rewrites the same four objects.
    again = sync(name)
    assert again.returncode == 0, again.stderr
    assert again.stdout.count("updated ") == 4, again.stdout

    # A client added by hand is the Portal's until the next run, and not after it.
    # A fresh admin token: master's admin-cli tokens live 60 s, and two runs of the Job on a busy
    # runner outlast the one `realm()` took, which answered 401 here (T-3179).
    admin = token(base, "master", "admin-cli", user="admin")
    status, _, headers = call(base, "POST", f"/admin/realms/{REALM}/clients", admin, {"clientId": "by-hand"})
    assert status == 201
    late = headers["Location"].rsplit("/", 1)[1]
    portal = token(base, REALM, "portal-api", "portal-api-secret")
    change = lambda: call(base, "PUT", f"/admin/realms/{REALM}/clients/{late}", portal,
                          {"clientId": "by-hand", "description": "x"})[0]
    assert change() == 204
    assert sync(name).returncode == 0
    assert change() == 403


def test_a_realm_without_admin_permissions_fails_the_run(keycloak):
    name, base = keycloak
    realm(base, permissions=False)
    run = sync(name)
    assert run.returncode != 0
    assert "adminPermissionsEnabled is off" in run.stderr, run.stderr
