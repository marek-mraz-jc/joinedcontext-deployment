"""The Portal reads a space's counts from the broker's admin surface (T-2889, T-2996).

`GET {JC_PORTAL_BROKER_URL}/q/tenants/{space}` is the one read behind every row of the Context
Spaces list. dev-173 routed only DELETE there, so the list showed no entities for any space for as
long as it was pinned; these cases hold the URL and the pinned image to that read.
"""

import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BROKER = ROOT / "components/context-broker"
CURL = "curlimages/curl:8.10.1@sha256:d9b4541e214bcd85196d6e92e2753ac6d0ea699f0af5741f8c6cccbfcf00ef4b"

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no container runtime, so the pinned broker cannot run"
)


def pinned_broker() -> str:
    image = yaml.safe_load((BROKER / "images.yaml").read_text())["context-broker"]["broker"]
    return f"{image['repository']}@{image['digest']}"


def test_the_portals_broker_url_is_the_brokers_service_port():
    values = (ROOT / "components/portal/values/portal/base-values.yaml.gotmpl").read_text()
    # The value quotes the template's own arguments, so it is read to the end of its line.
    (url,) = re.findall(r'^\s+JC_PORTAL_BROKER_URL: "(.+)"$', values, re.M)
    service = (BROKER / "values/broker/base-values.yaml.gotmpl").read_text()
    port = re.search(r"^\s+port: (\d+)$", service, re.M).group(1)
    assert re.fullmatch(r"http://context-broker\.\{\{[^}]+\}\}\.svc\.cluster\.local:" + port, url), url


@requires_docker
def test_the_pinned_broker_answers_a_get_of_one_tenant():
    """dev-173 answered 405 here; the Portal needs 200 for a tenant that exists."""
    name = f"broker-admin-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, pinned_broker()], check=True,
                   capture_output=True, timeout=300)
    try:
        def get(path: str) -> str:
            return subprocess.run(
                ["docker", "run", "--rm", "--network", f"container:{name}", CURL, "-s",
                 "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
                 f"http://127.0.0.1:9090{path}"],
                capture_output=True, text=True, timeout=60,
            ).stdout

        deadline = time.monotonic() + 60
        while get("/q/ready") != "200":
            assert time.monotonic() < deadline, "the pinned broker never became ready"
            time.sleep(1)
        # The default Tenant exists even when empty (CIM 009 5.5.10).
        assert get("/q/tenants/default") == "200", "GET /q/tenants/default is not served"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
