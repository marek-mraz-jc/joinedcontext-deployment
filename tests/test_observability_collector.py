"""The activity collector, judged by running the image the deployment pins (T-0349, OPS-48).

A render test proves the ConfigMap exists. It cannot prove the two things that decide whether
the Activity stream works or leaks: that the released collector accepts this config at all —
a misspelled processor is a CrashLoopBackOff on the cluster, not a template error — and that
the allow-list really strips, so a record arriving with a request body and an Authorization
header reaches the Portal carrying neither.

Both run the pinned image, so both skip where there is no docker.
"""

import gzip
import json
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGES = yaml.safe_load((PROJECT_ROOT / "components/observability/images.yaml").read_text())
IMAGE_SPEC = IMAGES["observability"]["collector"]
IMAGE = f"{IMAGE_SPEC['repository']}:{IMAGE_SPEC['tag']}@{IMAGE_SPEC['digest']}"

# What OPS-48 forbids, spelled out as attributes an emitter might plausibly attach to the same
# record: a request body, a bearer token, and a pod name that says nothing about the event.
FORBIDDEN = {"http.request.body", "authorization", "k8s.pod.name"}
ALLOWED = {"project", "space", "kind", "source", "summary", "severity", "correlationId", "details"}

requires_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@pytest.fixture(scope="module")
def collector_config(rendered):
    """The config the deployment renders, not a copy of it kept in the test."""
    docs = rendered("local")
    cm = next(
        d for d in docs
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "observability-collector-config"
    )
    return yaml.safe_load(cm["data"]["config.yaml"])


def _write_config(directory: Path, config: dict) -> Path:
    """Write the config where the collector's own uid can read it.

    The image runs as 10001 and pytest's tmp directories are 0700 for the user running the
    suite, so without this the collector reports the config as missing rather than unreadable
    and the failure looks like a template bug."""
    directory.chmod(0o755)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    path.chmod(0o644)
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Portal(BaseHTTPRequestHandler):
    """Keycloak's token endpoint and the Portal's ingest route, both of them stubs."""

    batches: list[dict] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path.endswith("/token"):
            self._json(b'{"access_token":"stub-token","token_type":"Bearer","expires_in":300}')
            return
        if self.headers.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        type(self).batches.append({"auth": self.headers.get("authorization"), "body": json.loads(body)})
        self._json(b"{}")

    def _json(self, payload: bytes):
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


RECORD = {
    "resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "context-gateway"}},
            {"key": "k8s.pod.name", "value": {"stringValue": "gateway-abc"}},
        ]},
        "scopeLogs": [{"logRecords": [
            {
                "timeUnixNano": "1788696000000000000",
                "severityText": "WARN",
                "body": {"stringValue": 'raw request body {"citizen":"secret"}'},
                "attributes": [
                    {"key": "project", "value": {"stringValue": "helsinki"}},
                    {"key": "space", "value": {"stringValue": "air-quality"}},
                    {"key": "kind", "value": {"stringValue": "access.denied"}},
                    {"key": "source", "value": {"stringValue": "gateway"}},
                    {"key": "summary", "value": {"stringValue": "An anonymous caller was refused."}},
                    {"key": "severity", "value": {"stringValue": "warning"}},
                    {"key": "correlationId", "value": {"stringValue": "4bf92f3577b34da6a3ce929d0e0e4736"}},
                    {"key": "http.request.body", "value": {"stringValue": '{"citizen":"secret"}'}},
                    {"key": "authorization", "value": {"stringValue": "Bearer a-token"}},
                ],
            },
            {
                "timeUnixNano": "1788696000000000000",
                "body": {"stringValue": "belongs to no project"},
                "attributes": [{"key": "kind", "value": {"stringValue": "pipeline.error"}}],
            },
        ]}],
    }]
}


@pytest.fixture(scope="module")
def exported(collector_config, tmp_path_factory):
    """Post one batch through the pinned collector and return what the Portal was handed."""
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    port = _free_port()
    config = json.loads(json.dumps(collector_config))  # a copy; the other test reads the original
    config["extensions"]["oauth2client"]["token_url"] = f"http://127.0.0.1:{port}/token"
    config["exporters"]["otlphttp/portal"]["logs_endpoint"] = f"http://127.0.0.1:{port}/api/v1/activity"
    d = tmp_path_factory.mktemp("otelcol")
    _write_config(d, config)

    _Portal.batches = []
    server = HTTPServer(("127.0.0.1", port), _Portal)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    name = f"jc-otelcol-test-{port}"
    run = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--network", "host",
         "-e", "JC_ACTIVITY_CLIENT_SECRET=stub-secret", "-v", f"{d}:/etc/otelcol:ro",
         IMAGE, "--config=/etc/otelcol/config.yaml"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    try:
        _wait_for_port(13133)
        post = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "-X", "POST", "http://127.0.0.1:4318/v1/logs",
             "-H", "content-type: application/json", "--data-binary", json.dumps(RECORD)],
            capture_output=True, text=True,
        )
        assert post.stdout == "200", f"{post.stdout} {post.stderr}"
        deadline = time.monotonic() + 30
        while not _Portal.batches and time.monotonic() < deadline:
            time.sleep(0.2)
        assert _Portal.batches, subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True).stderr
        return _Portal.batches
    finally:
        server.shutdown()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _wait_for_port(port: int, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise AssertionError(f"the collector never opened {port}")


def _records(batches):
    return [
        record
        for batch in batches
        for resource in batch["body"]["resourceLogs"]
        for scope in resource["scopeLogs"]
        for record in scope["logRecords"]
    ]


@requires_docker
def test_the_pinned_image_accepts_the_rendered_config(collector_config, tmp_path):
    """`otelcol validate` on the ConfigMap the deployment renders, in the image it pins."""
    _write_config(tmp_path, collector_config)
    result = subprocess.run(
        ["docker", "run", "--rm", "-e", "JC_ACTIVITY_CLIENT_SECRET=stub-secret",
         "-v", f"{tmp_path}:/etc/otelcol:ro", IMAGE, "validate", "--config=/etc/otelcol/config.yaml"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@requires_docker
def test_the_allow_list_drops_every_attribute_it_does_not_name(exported):
    records = _records(exported)
    assert len(records) == 1, "the record naming no project should have been dropped"
    keys = {a["key"] for a in records[0].get("attributes", [])}
    assert keys <= ALLOWED, f"attributes reached the Portal that the allow-list does not name: {keys - ALLOWED}"
    assert not keys & FORBIDDEN
    assert "kind" in keys and "project" in keys


@requires_docker
def test_no_raw_body_or_credential_survives_the_collector(exported):
    """OPS-48 as one assertion over the whole request, not one per field.

    The record went in with a body, a request payload and a bearer token; whatever shape the
    collector rewrites it into, none of those three strings may appear anywhere in what the
    Portal receives."""
    wire = json.dumps([b["body"] for b in exported])
    for leaked in ('{"citizen":"secret"}', "Bearer a-token", "raw request body", "gateway-abc"):
        assert leaked not in wire, f"{leaked!r} survived the collector"


@requires_docker
def test_the_collector_authenticates_as_its_service_account(exported):
    """A token from the client-credentials grant, not an anonymous post (Deployment/05 §5)."""
    assert all(b["auth"] == "Bearer stub-token" for b in exported)


def test_the_image_is_pinned_by_digest():
    assert IMAGE_SPEC["digest"].startswith("sha256:"), "OPS-28: the collector runs a digest, not a tag"


def test_only_the_named_workloads_may_reach_the_collector():
    """The ingress list of OPS-48, read from the component rather than the render.

    The rendered NetworkPolicy has already had `componentNamespace` resolved into a namespace
    selector, so the names that matter are clearest here, and a fourth workload appearing in
    this list is a change somebody has to make on purpose."""
    policies = yaml.safe_load((PROJECT_ROOT / "components/observability/networkpolicies.yaml").read_text())
    collector = policies["observability"]
    senders = {
        peer["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
        for rule in collector["ingress"] for peer in rule["from"]
    }
    assert senders == {"context-broker-broker", "context-gateway-gateway", "pipeline-runner-runner"}

    targets = {
        peer.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/name")
        or peer.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/instance")
        or "dns"
        for rule in collector["egress"] for peer in rule["to"]
    }
    assert targets == {"portal-portal", "keycloak-app", "dns"}, "the collector reaches nothing else"
    assert not any(
        "cnpg.io/cluster" in peer.get("podSelector", {}).get("matchLabels", {})
        for rule in collector["egress"] for peer in rule["to"]
    ), "the collector holds no database credential and must not reach the database"
