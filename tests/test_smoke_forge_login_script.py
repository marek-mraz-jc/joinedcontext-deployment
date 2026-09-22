"""T-1422: scripts/smoke-forge-login.sh walks the forge's Keycloak login the way a browser
does. The suite runs the real script and the real curl against a local stub of the forge and
Keycloak, with a stub `kubectl` that hands out the password."""

import base64
import io
import os
import tarfile
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke-forge-login.sh"
PASSWORD = "s3cret-Pa55&word"
FOLDER = "/git/joinedcontext/configuration/src/branch/main/projects/helsinki"
APP = "/git/joinedcontext/helsinki_map-alerts"
FORM = ('<html><form id="kc-form-login" onsubmit="return true;" '
        'action="{base}/kc/authenticate?session_code=a&amp;tab_id=b" method="post"></form>'
        '{error}</html>')


def archive():
    """What the forge's download link answers: the repository as a tar.gz with its files."""
    data = b"<html>map</html>"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        entry = tarfile.TarInfo("helsinki_map-alerts/index.html")
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def serve(mode):
    """mode: ok | pkce (the forge's button fails) | no-team (404 after login) | writable |
    forkable (the forge lets a reader fork) | app-hidden (the application repository is a 404
    to a reader) | app-public (anyone reads it) | app-empty (it holds no commit) | no-apps."""
    forks = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, body="", headers=()):
            self.send_response(code)
            for k, v in headers:
                self.send_header(k, v)
            data = body if isinstance(body, bytes) else body.encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def base(self):
            return f"http://{self.headers['Host']}"

        def do_GET(self):
            signed_in = "forge=session" in (self.headers.get("Cookie") or "")
            if self.path == "/git/user/oauth2/keycloak":
                if mode == "pkce":
                    return self.send(302, headers=[("Location", "/git/user/login")])
                return self.send(302, headers=[("Location", "/kc/auth")])
            if self.path == "/git/user/login":
                msg = "Missing parameter: code_challenge_method" if mode == "pkce" else ""
                return self.send(200, f'<div class="ui negative message flash-error"><p>{msg}</p></div>')
            if self.path == "/kc/auth":
                return self.send(200, FORM.format(base=self.base(), error=""))
            if self.path.startswith("/git/user/oauth2/keycloak/callback"):
                return self.send(302, headers=[("Location", "/git/"), ("Set-Cookie", "forge=session; Path=/")])
            if self.path == "/git/":
                return self.send(200, "<html>dashboard</html>")
            if self.path == FOLDER:
                if not signed_in or mode == "no-team":
                    return self.send(404, "<html>Not found</html>")
                return self.send(200, '<a href="/git/joinedcontext/configuration/_new/main/projects/helsinki">Add File</a><a>project.yaml</a>')
            if self.path == FOLDER.replace("/src/branch/", "/_new/"):
                if mode == "writable":
                    return self.send(200, '<form><input name="commit_choice" value="direct"></form>')
                return self.send(200, "<p>You cannot edit this repository directly. Instead you can create a fork</p>")
            if self.path == FOLDER.split("/src/branch/")[0] + "/fork":
                return self.send(200, '<input type="hidden" name="_csrf" value="tok"><input name="uid" type="hidden" value="4">')
            if self.path == "/git/org/joinedcontext/teams/readers":
                return self.send(200 if signed_in else 404, "<html>readers</html>")
            if self.path == "/git/joinedcontext":
                if not signed_in:
                    return self.send(404)
                listed = "" if mode == "no-apps" else f'<a href="{APP}">helsinki_map-alerts</a>'
                return self.send(200, f'<a href="/git/joinedcontext/configuration">configuration</a>{listed}')
            if self.path == APP:
                if mode == "app-public" or (signed_in and mode != "app-hidden"):
                    tree = "" if mode == "app-empty" else f'<a href="{APP}/src/branch/main/index.html">index.html</a>'
                    return self.send(200, f"<html>{tree}</html>")
                return self.send(404)
            if self.path == APP + "/archive/main.tar.gz" and signed_in and mode not in ("app-hidden", "app-empty"):
                return self.send(200, archive())
            if self.path in ("/git/demo.steward/configuration", "/git/demo.viewer/configuration"):
                return self.send(200 if forks else 404, "<html>fork</html>")
            self.send(404)

        def do_POST(self):
            body = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if self.path.endswith("/fork"):
                if mode == "forkable" and body.get("_csrf") == ["tok"] and body.get("uid") == ["4"]:
                    forks.append(self.path)
                    return self.send(303, headers=[("Location", "/git/")])
                return self.send(400, '{"errorMessage":"The owner has already reached the limit of 0 repositories."}')
            if body.get("password") == [PASSWORD] and body["username"][0].endswith("@hel.fi"):
                return self.send(302, headers=[("Location", "/git/user/oauth2/keycloak/callback?code=x")])
            err = '<span id="input-error" class="kc-feedback">Invalid username or password.</span>'
            self.send(200, FORM.format(base=self.base(), error=err))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(tmp_path, mode, password=PASSWORD):
    server = serve(mode)
    kubectl = tmp_path / "kubectl"
    encoded = base64.b64encode(password.encode()).decode() if password else ""
    kubectl.write_text(f'#!/bin/sh\ncase "$*" in *secret*) printf %s "{encoded}";; esac\n')
    kubectl.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "JC_SMOKE_ORG": "hel.fi"}
    try:
        return subprocess.run([str(SCRIPT), f"http://127.0.0.1:{server.server_port}"],
                              env=env, capture_output=True, text=True, timeout=60)
    finally:
        server.shutdown()


def test_both_demo_people_sign_in_and_read_without_write(tmp_path):
    r = run(tmp_path, "ok")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok    an anonymous visitor does not read the configuration repository (404)" in r.stdout
    for user in ("demo.steward", "demo.viewer"):
        assert f"ok    {user} signs in to the forge through Keycloak" in r.stdout
        assert f"ok    {user} reads the configuration repository without write access" in r.stdout
    assert PASSWORD not in r.stdout + r.stderr


def test_a_wrong_password_fails_with_the_keycloak_message_never_the_password(tmp_path):
    r = run(tmp_path, "ok", password="wrong-pass")
    assert r.returncode == 1
    assert "Invalid username or password." in r.stdout
    assert "wrong-pass" not in r.stdout + r.stderr


def test_the_broken_button_fails_naming_the_forges_error(tmp_path):
    r = run(tmp_path, "pkce")
    assert r.returncode == 1
    assert "reaches no login form: Missing parameter: code_challenge_method" in r.stdout


def test_a_404_after_login_names_the_team_mapping(tmp_path):
    r = run(tmp_path, "no-team")
    assert r.returncode == 1
    assert "maps to no forge team" in r.stdout


def test_an_editor_in_the_forge_fails(tmp_path):
    r = run(tmp_path, "writable")
    assert r.returncode == 1
    assert "may commit to the configuration repository" in r.stdout


def test_a_missing_secret_fails_instead_of_skipping(tmp_path):
    r = run(tmp_path, "ok", password="")
    assert r.returncode == 1
    assert "no password in Secret keycloak-user-demo-steward" in r.stdout


def test_an_anonymous_read_fails(tmp_path, monkeypatch):
    # The stub answers the folder to anyone holding the cookie; hand it to the anonymous call.
    monkeypatch.setenv("CURL_HOME", str(tmp_path))
    (tmp_path / ".curlrc").write_text('cookie = "forge=session"\n')
    r = run(tmp_path, "ok")
    assert "FAIL  an anonymous visitor reads the configuration repository" in r.stdout


def test_a_reader_who_can_fork_the_repository_fails(tmp_path):
    r = run(tmp_path, "forkable")
    assert r.returncode == 1
    assert "forked the configuration repository" in r.stdout


def test_a_refused_fork_passes(tmp_path):
    r = run(tmp_path, "ok")
    assert "ok    demo.viewer cannot fork the configuration repository (404)" in r.stdout


def test_every_application_repository_is_read_and_downloaded_by_a_reader_and_hidden_from_anyone(tmp_path):
    """T-2601, PF-79, AP-78: the owner met a 404 on an App's repository; the readers team holds
    every repository of the organization, so the source opens and downloads for both people."""
    r = run(tmp_path, "ok")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok    an anonymous visitor does not read helsinki_map-alerts (404)" in r.stdout
    for user in ("demo.steward", "demo.viewer"):
        assert f"ok    {user} is in the forge team readers" in r.stdout
        assert f"ok    {user} reads and downloads application repository helsinki_map-alerts (1 files)" in r.stdout
    assert "not read configuration" not in r.stdout, "the configuration repository is no App"


def test_an_application_repository_a_reader_cannot_open_fails(tmp_path):
    r = run(tmp_path, "app-hidden")
    assert r.returncode == 1
    assert "FAIL  demo.viewer: application repository helsinki_map-alerts answers 404" in r.stdout


def test_an_application_repository_anyone_reads_fails(tmp_path):
    r = run(tmp_path, "app-public")
    assert r.returncode == 1
    assert "FAIL  an anonymous visitor reads helsinki_map-alerts (200)" in r.stdout


def test_an_application_repository_with_no_files_fails(tmp_path):
    r = run(tmp_path, "app-empty")
    assert r.returncode == 1
    assert "FAIL  demo.steward: application repository helsinki_map-alerts lists no files" in r.stdout


def test_a_forge_with_no_application_repository_says_so_and_passes(tmp_path):
    r = run(tmp_path, "no-apps")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok    the forge holds no application repository yet" in r.stdout


def test_a_person_the_group_map_lands_nowhere_fails_on_the_team(tmp_path):
    r = run(tmp_path, "no-team")
    assert r.returncode == 1
    assert "the forge holds no application repository yet" not in r.stdout, (
        "with nobody signed in, no list of applications is claimed"
    )
