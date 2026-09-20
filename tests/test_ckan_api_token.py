"""The catalogue API token Job (T-0493): its script against a fake CKAN and a fake Kubernetes API.

The fakes hold what the real ones decide: CKAN refuses an API call on a session without the CSRF
token and reads an unknown token as anonymous; the API server answers 404 for a Secret that is
not there. Nothing here needs a cluster.
"""

import base64
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "charts/ckan/files/api-token.py"
PASSWORD = "admin-password-9f3"
# A token's shape without a token: built from parts, because a JWT-shaped literal is exactly what
# the history scan is there to catch.
MINTED = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJqdGkiOiJuZXcifQ", "c2lnbmF0dXJl"])


class FakeCkan:
    def __init__(self):
        self.tokens = {}  # token -> (id, name)
        self.calls = []

    def handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body="", headers=()):
                self.send_response(status)
                for key, value in headers:
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body.encode())

            def session(self):
                return self.headers.get("Cookie", "")

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                if self.path == "/api/3/action/status_show":
                    return self.reply(200, '{"success": true}')
                if self.path == "/user/login":
                    return self.reply(200, '<input type="hidden" name="_csrf_token" value="form-csrf"/>',
                                      [("Set-Cookie", "ckan=anon; Secure; HttpOnly")])
                if self.path == "/dataset/" and "ckan=signed-in" in self.session():
                    return self.reply(200, '<meta name="_csrf_token" content="page-csrf" />')
                return self.reply(404)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                action = self.path.rsplit("/", 1)[-1]
                fake.calls.append(("POST", action))
                if self.path == "/user/login":
                    ok = ("ckan=anon" in self.session() and "_csrf_token=form-csrf" in body
                          and f"password={PASSWORD}" in body)
                    if not ok:
                        return self.reply(200, "Login failed")
                    return self.reply(302, headers=[("Location", "http://ckan/dashboard/datasets"),
                                                    ("Set-Cookie", "ckan=signed-in; Secure; HttpOnly")])
                payload = json.loads(body or "{}")
                bearer = self.headers.get("Authorization")
                on_session = "ckan=signed-in" in self.session() and self.headers.get("X-CSRFToken") == "page-csrf"
                if not (on_session or bearer in fake.tokens):
                    return self.reply(403, '{"success": false}')
                if action == "api_token_list":
                    result = [{"id": i, "name": n} for i, n in fake.tokens.values()]
                elif action == "api_token_revoke":
                    fake.tokens = {t: v for t, v in fake.tokens.items() if v[0] != payload["jti"]}
                    result = None
                elif action == "api_token_create":
                    fake.tokens[MINTED] = ("new", payload["name"])
                    result = {"token": MINTED}
                else:
                    return self.reply(404)
                return self.reply(200, json.dumps({"success": True, "result": result}))

        return Handler


class FakeKube:
    def __init__(self, token=None):
        self.secret = None if token is None else base64.b64encode(token.encode()).decode()
        self.writes = []

    def handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body=b""):
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if fake.secret is None:
                    return self.reply(404)
                return self.reply(200, json.dumps({"data": {"token": fake.secret}}).encode())

            def do_PUT(self):
                return self.write(200 if fake.secret is not None else 404)

            def do_POST(self):
                return self.write(201)

            def write(self, status):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if status != 404:
                    fake.writes.append((self.command, self.path, body))
                    fake.secret = body["data"]["token"]
                return self.reply(status)

        return Handler


def serve(fake):
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(ckan, kube, tmp_path, password=PASSWORD):
    ckan_server, kube_server = serve(ckan), serve(kube)
    try:
        return subprocess.run(
            ["python3", "-c", SCRIPT.read_text()],
            env={"CATALOGUE": f"127.0.0.1:{ckan_server.server_port}", "ADMIN_USER": "ckan_admin",
                 "ADMIN_PASSWORD": password, "TOKEN_SECRET": "ckan-api-token", "TOKEN_NAME": "jcctl",
                 "NAMESPACE": "dev", "KUBE_API": f"http://127.0.0.1:{kube_server.server_port}",
                 "SA_DIR": str(tmp_path)},
            capture_output=True, text=True, timeout=60,
        )
    finally:
        ckan_server.shutdown()
        kube_server.shutdown()


def test_a_first_install_mints_the_token_into_a_new_secret(tmp_path):
    ckan, kube = FakeCkan(), FakeKube()
    result = run(ckan, kube, tmp_path)
    assert result.returncode == 0, result.stderr
    assert [(method, path) for method, path, _ in kube.writes] == [("POST", "/api/v1/namespaces/dev/secrets")]
    written = kube.writes[0][2]
    assert written["metadata"] == {"name": "ckan-api-token", "namespace": "dev"}
    assert base64.b64decode(written["data"]["token"]).decode() == MINTED
    assert "minted jcctl into Secret ckan-api-token" in result.stdout
    for leak in (MINTED, PASSWORD, "page-csrf"):
        assert leak not in result.stdout + result.stderr


def test_a_token_that_still_authenticates_is_kept(tmp_path):
    ckan = FakeCkan()
    ckan.tokens[MINTED] = ("new", "jcctl")
    kube = FakeKube(token=MINTED)
    result = run(ckan, kube, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "still authenticates" in result.stdout
    assert kube.writes == []
    assert ("POST", "api_token_create") not in ckan.calls


def test_a_stale_token_is_revoked_by_name_and_replaced(tmp_path):
    ckan = FakeCkan()
    ckan.tokens["eyJ.old.token"] = ("old", "jcctl")
    ckan.tokens["eyJ.other.token"] = ("other", "someone-else")
    kube = FakeKube(token="eyJ.lost.token")
    result = run(ckan, kube, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "eyJ.old.token" not in ckan.tokens, "the previous jcctl token still works"
    assert "eyJ.other.token" in ckan.tokens, "a token of another name was revoked"
    assert [(method, path) for method, path, _ in kube.writes] == [("PUT", "/api/v1/namespaces/dev/secrets/ckan-api-token")]


def test_a_refused_sign_in_writes_nothing_and_fails_the_job(tmp_path):
    ckan, kube = FakeCkan(), FakeKube()
    result = run(ckan, kube, tmp_path, password="wrong")
    assert result.returncode != 0
    assert "could not sign in" in result.stderr
    assert kube.writes == [] and ckan.tokens == {}
