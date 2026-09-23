"""T-0231: scripts/smoke.sh must assert exact statuses and fail on anything else.

The script talks to a cluster and to the outside world, so the suite runs it against
stub `curl`/`kubectl`/`wait-rollouts.sh` on PATH inside a throwaway copy of `scripts/`.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SMOKE = PROJECT_ROOT / "scripts" / "smoke.sh"

CURL_STUB = '''#!/usr/bin/env python3
import json, os, sys
spec = json.load(open(os.environ["STUB_SPEC"]))
args = sys.argv[1:]
# The method, the headers and the request body all separate two calls to one URL
# (anonymous vs bearer, create vs delete), so the whole command line is the key.
line = " ".join(args)

DEFAULT_HEADERS = (
    "HTTP/2 200\\r\\nserver: APISIX\\r\\n"
    "strict-transport-security: max-age=31536000; includeSubDomains; preload\\r\\n"
    "x-content-type-options: nosniff\\r\\nx-frame-options: SAMEORIGIN\\r\\n"
    "referrer-policy: no-referrer\\r\\n"
)


def lookup(table, default):
    for match, value in spec.get(table, []):
        needles = match if isinstance(match, list) else [match]
        if all(n in line for n in needles):
            return value
    return default


if "--tls-max" in line:
    sys.exit(spec.get("tls11", 1))
elif "-sSI" in args:
    sys.stdout.write(lookup("headers", spec.get("defaultHeaders", DEFAULT_HEADERS)))
elif "%{http_code}" in args:
    # A conditional read of a schema artifact is a 304, as the gateway answers it (EP-51).
    sys.stdout.write(str(lookup("statuses", 304 if "If-None-Match" in line else 200)))
elif "-D" in args:
    # The response headers of one read (T-2262): the gateway's own caching and its ETag.
    sys.stdout.write(lookup("dumpedHeaders", spec.get("schemaHeaders",
        'HTTP/2 200\\r\\ncache-control: private, no-cache\\r\\netag: "e3b0c442"\\r\\n')))
else:
    sys.stdout.write(lookup("bodies", ""))
'''

KUBECTL_STUB = '''#!/usr/bin/env python3
import base64, itertools, json, os, sys
spec = json.load(open(os.environ["STUB_SPEC"]))
args = sys.argv[1:]
line = " ".join(args)
# The pod selector of APISIX's egress policy (components/apisix/networkpolicies.yaml).
EDGE_SELECTOR = [("app.kubernetes.io/name", "apisix"), ("app.kubernetes.io/instance", "apisix-apisix")]
if args[0] == "get" and args[1] == "configmap" and args[2] == "gitea-bootstrap-seed" and "endpoints__helsinki-" in line:
    # The Helsinki seed's slugs, one per endpoint name (T-0478); nothing seeded by default,
    # because the checks behind them wait up to 210 s for data to flow.
    name = "".join(itertools.takewhile(str.isalnum, line.split("endpoints__helsinki-", 1)[1]))
    seeded = spec.get("helsinkiSeed", {}).get(name)
    sys.stdout.write("spec:\\n  slug: %s\\n" % seeded if seeded else "")
elif args[0] == "get" and args[1] == "configmap" and args[2] == "gitea-bootstrap-seed" and "jsonpath={.data}" in line:
    # The seed's file names, for the residue count (T-0667): one Helsinki endpoint per seeded slug.
    keys = ["projects__helsinki__spaces__helsinki__endpoints__helsinki-%s.yaml" % n for n in spec.get("helsinkiSeed", {})]
    if spec.get("helsinkiSeed"):
        # Two pipelines and two spaces beside the endpoints (T-0750): counted the same way.
        keys += ["projects__helsinki__pipelines__hel-news__pipeline.yaml",
                 "projects__helsinki__pipelines__citybikes-gbfs__pipeline.yaml",
                 "projects__helsinki__spaces__helsinki__space.yaml",
                 "projects__helsinki__spaces__helsinki-kpi__space.yaml"]
    sys.stdout.write(json.dumps({k: "" for k in keys}))
elif args[0] == "get" and args[1] == "configmap" and args[2] == "gitea-bootstrap-seed":
    # The seeded Endpoint manifest the smoke reads the slug from (T-0282, T-0278); "" = nothing seeded.
    sys.stdout.write(spec.get("seedEndpoint", "spec:\\n  slug: mluyob4nz52lok3ssk7pgn5vwt\\n"))
elif args[0] == "get" and args[1] == "configmap" and args[2] == "portal-branding":
    # The block both the Portal and the catalogue theme are served (OPS-46).
    sys.stdout.write(spec.get("branding", "instanceName: Example Context\\ncolours:\\n  primary: '#0000bf'\\n"))
elif args[0] == "get" and args[1] == "configmaps" and "-o name" in line:
    # The sample applications the forge bootstrap seeded (T-2599); `sampleApps: []` is none.
    for app in spec.get("sampleApps", ["helsinki-bikes", "helsinki-events", "helsinki-alerts"]):
        sys.stdout.write("configmap/gitea-bootstrap-app-%s\\n" % app)
elif args[0] == "get" and args[1] == "configmap":
    routes = "".join("  - id: %s\\n" % r for r in spec.get("routes", []))
    sys.stdout.write("routes:\\n" + routes)
    # A credential copied into a rendered config is a credential in `kubectl get -o yaml`
    # (T-0935); the default instance has none, and a test that plants one asserts the catch.
    if spec.get("leakedCredential"):
        sys.stdout.write("  password: %s\\n" % spec["leakedCredential"])
elif args[0] == "get" and args[1] == "deployment" and args[2] == "apisix":
    sys.exit(0 if spec.get("edge", True) else 1)
elif args[0] == "logs":
    # One access-log line for the beacon path, from whoever the edge thinks called (T-0929).
    caller = spec.get("edgeCaller", "203.0.113.7")
    if caller:
        sys.stdout.write('%s - - [17/Sep/2026:08:00:03 +0000] host "GET /smoke-caller HTTP/1.1" 404 0\\n' % caller)
elif args[0] == "get" and args[1] == "statefulset" and args[2] == "artifact-store":
    # The store itself (T-0925, T-0933); an instance without it skips the whole section.
    sys.exit(0 if spec.get("artifactStore", True) else 1)
elif args[0] == "get" and args[1] == "secret" and "artifact-store-role=reader" in line:
    sys.stdout.write("".join("%s " % n for n in spec.get("artifactReaders", ["artifact-store-reader-helsinki"])))
elif args[0] == "get" and args[1] == "secret" and "artifact-store-role=writer" in line:
    # The writer must exist nowhere: the default is an empty list, and a test that hands one
    # over is asserting that the smoke catches it.
    sys.stdout.write("".join("%s " % n for n in spec.get("artifactWriters", [])))
elif args[0] == "get" and args[1] == "secret" and args[2].startswith("artifact-store-reader-"):
    held = spec.get("artifactReaderKeys", {}).get(args[2], ["ACCESS_KEY_ID", "ACCESS_SECRET_KEY"])
    key = line.rsplit(".data.", 1)[1].rstrip("}")
    sys.stdout.write(base64.b64encode(b"a-credential").decode() if key in held else "")
elif args[0] == "get" and args[1] == "secret" and args[2] == "pipeline-secrets":
    # The one Secret the Portal writes for the runner (T-0927, T-0935). `None` is the instance
    # where no pipeline declares a secretRef at all, and the whole section skips.
    resolved = spec.get("pipelineSecrets", {"DEMO_FEED_PASSWORD": "a-credential"})
    if resolved is None:
        sys.exit(1)
    if "go-template" in line:
        sys.stdout.write("".join("%s\\n" % name for name in resolved))
    elif ".data." in line:
        value = resolved.get(line.rsplit(".data.", 1)[1].rstrip("}"), "")
        sys.stdout.write(base64.b64encode(value.encode()).decode() if value else "")
elif args[0] == "exec" and "deploy/gitea-runner" in line:
    # T-1707: the runner's uid and whether it holds a ServiceAccount token.
    if spec.get("runnerWallsRead", True):
        sys.stdout.write("UID=%s\\n" % spec.get("runnerUid", 1000))
        if spec.get("runnerSaToken", False):
            sys.stdout.write("SA-TOKEN\\n")
        sys.stdout.write("WALLS-READ\\n")
elif args[0] == "exec":
    # `sh -c [ -n "$NAME" ]`: the runner has the variable, or it does not. The value is never
    # printed, here or in the script.
    named = next((a.split("$", 1)[1].strip('" ]') for a in args if "$" in a), "")
    sys.exit(1 if named in spec.get("runnerEnvMissing", []) else 0)
elif args[0] == "get" and args[1] == "secret" and args[2].startswith("keycloak-user-"):
    # A demo user's generated password (T-0248); "" = no demo users seeded.
    secret = spec.get("demoPassword", "Passw0rd-demo")
    if not secret:
        sys.exit(1)
    sys.stdout.write(base64.b64encode(secret.encode()).decode())
elif args[0] == "get" and args[1] == "secret":
    secret = spec.get("clientSecret", "s3cr3t")
    if not secret:
        sys.exit(1)
    sys.stdout.write(base64.b64encode(secret.encode()).decode())
elif args[0] == "get" and args[1] == "deployment" and args[2] == "jc-functions":
    sys.exit(0 if spec.get("functions", True) else 1)
elif args[0] == "get" and args[1] == "service" and args[2] == "jc-functions":
    sys.stdout.write("10.43.0.99")
elif args[0] == "port-forward":
    sys.exit(0)
elif args[0] == "run" and args[1].startswith("smoke-functions") and args[1].endswith("-portal"):
    # The probe carrying the Portal's label: the policy's own positive control (T-0686).
    sys.exit(0 if spec.get("functionsPortalReaches", True) else 1)
elif args[0] == "run" and args[1].startswith("smoke-functions"):
    sys.exit(0 if spec.get("functionsReachable") else 1)
elif args[0] == "run" and args[1].startswith("smoke-egress"):
    # The egress probe reports by what it prints, not by its exit status, so the stub prints
    # what the spec says it saw: how long the controller took to program the pod's chains
    # (T-0459), then the destinations that still answered. `egressProbeRan: False` is the pod
    # that never started -- no output at all, which must not read as "the policy stopped it".
    settled = spec.get("egressSettled", 4)
    if settled is not None:
        sys.stdout.write("SETTLED-AFTER=%ds\\n" % settled)
    for destination in spec.get("egressReached", []):
        sys.stdout.write("REACHED-%s\\n" % destination)
    if spec.get("egressProbeRan", True):
        sys.stdout.write("PROBE-RAN\\n")
elif args[0] == "get" and args[1] == "deployments" and "metadata.name=gitea-runner" in line:
    # The Actions runner (T-2608); `runnerNamespace: ""` is an instance without one.
    namespace = spec.get("runnerNamespace", "runners")
    if namespace:
        sys.stdout.write("deployment.apps/gitea-runner\\n" if "name" in args[-1:] else namespace)
elif args[0] == "run" and args[1].startswith("smoke-runner"):
    # Like the egress probe, it reports by what it prints (T-2608).
    if spec.get("runnerProbeRan", True):
        sys.stdout.write("SETTLED-AFTER=4s\\n")
        for destination in spec.get("runnerReached", ["DNS"]):
            sys.stdout.write("REACHED-%s\\n" % destination)
        sys.stdout.write("PROBE-RAN\\n")
elif args[0] == "get" and args[1] == "deployments" and "joinedcontext.com/app=true" in line:
    # T-2665: the published pod-backed Apps as `ns/name|ready|wanted`; ready None = no pod ready.
    for name, ready, wanted in spec.get("appDeployments", [["dev/app-air-quality", 1, 1]]):
        sys.stdout.write("%s|%s|%s\\n" % (name, "" if ready is None else ready, wanted))
elif args[0] == "get" and args[1] == "pods" and "joinedcontext.com/app=true" in line:
    # AP-108: the running pod-backed Apps' addresses; `appPods: []` is an instance without one.
    sys.stdout.write("".join("%s " % ip for ip in spec.get("appPods", ["10.42.0.20"])))
elif args[0] == "run" and args[1].startswith("smoke-app") and args[1].endswith("-edge"):
    # The probe carrying APISIX's labels: the App policy's own positive control. Like the
    # cluster, it passes only with every label the edge's egress policy selects (T-2667).
    edge = all('"%s": "%s"' % pair in line for pair in EDGE_SELECTOR)
    sys.exit(0 if spec.get("appEdgeReaches", True) and edge else 1)
elif args[0] == "run" and args[1].startswith("smoke-app"):
    # Reports by what it prints, like the edge-peer probe.
    if spec.get("appPeerRan", True):
        sys.stdout.write("PROBE-RAN\\n")
    for port in spec.get("appPeerReached", []):
        sys.stdout.write("REACHED-%s\\n" % port)
elif args[0] == "get" and args[1] == "pods" and "app.kubernetes.io/name=apisix" in line:
    # T-0939: the probe aims at the APISIX pod's own address; `apisixPodIp: ""` is no pod.
    sys.stdout.write(spec.get("apisixPodIp", "10.42.0.9"))
elif args[0] == "run" and args[1].startswith("smoke-edgepeer"):
    # T-0939: like the egress probe, it reports by what it prints. `edgePeerRan: False` is a
    # probe that never ran, which must not read as "the policy refused it".
    if spec.get("edgePeerRan", True):
        sys.stdout.write("PROBE-RAN\\n")
    for port in spec.get("edgePeerReached", []):
        sys.stdout.write("REACHED-%s\\n" % port)
elif args[0] == "run":
    sys.exit(0 if spec.get("netpolReachable") else 1)
else:
    sys.exit(1)
'''

OPENSSL_STUB = '''#!/usr/bin/env python3
import json, os, sys
spec = json.load(open(os.environ["STUB_SPEC"]))
sys.stdout.write("New, (NONE), Cipher is (NONE)\\n" if spec.get("cbcRefused", True)
                 else "New, TLSv1.2, Cipher is ECDHE-RSA-AES128-SHA256\\n")
'''

ROLLOUTS_STUB = "#!/bin/sh\nexit 0\n"


def sandbox(tmp_path: Path, spec: dict) -> dict:
    """A copy of the script with stubbed neighbours; returns the env to run it with."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "smoke.sh").write_text(SMOKE.read_text())
    (scripts / "smoke.sh").chmod(0o755)
    (scripts / "wait-rollouts.sh").write_text(ROLLOUTS_STUB)
    (scripts / "wait-rollouts.sh").chmod(0o755)

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for name, body in (("curl", CURL_STUB), ("kubectl", KUBECTL_STUB), ("openssl", OPENSSL_STUB)):
        (stub_bin / name).write_text(body)
        (stub_bin / name).chmod(0o755)

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["STUB_SPEC"] = str(spec_file)
    return env


def run(tmp_path: Path, spec: dict, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = sandbox(tmp_path, spec)
    env.update(extra_env or {})
    result = subprocess.run(
        ["scripts/smoke.sh", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    # pytest cuts the repr of a CompletedProcess where the reason stands (T-2660), but shows a
    # failing case's captured stderr whole: every FAIL line, the summary and the script's own
    # stderr go there, so the next red case names its line.
    named = [line for line in result.stdout.splitlines() if "FAIL" in line or " passed, " in line]
    print("smoke.sh", *args, "->", result.returncode, *named, result.stderr, sep="\n", file=sys.stderr)
    return result


# What the Portal's /api/v1/auth/login answers: the Keycloak authorization URL carrying the
# callback the portal-api client lists (T-0270), on the Portal host (ADR-N-019).
LOGIN_REDIRECT = ("https://idm.example.test/realms/dev/protocol/openid-connect/auth?client_id=portal-api"
                  "&redirect_uri=https%3A%2F%2Fportal.example.test%2Fapi%2Fv1%2Fauth%2Fcallback&state=s")
# What the edge login answers an anonymous visitor of the Portal host: lua-resty-openidc's
# authorization URL with the `edge` client and the callback that client lists (AP-27).
EDGE_REDIRECT = ("https://idm.example.test/realms/dev/protocol/openid-connect/auth?response_type=code"
                 "&client_id=edge&state=s&redirect_uri=https%3A%2F%2Fportal.example.test%2Fcallback"
                 "&nonce=n&scope=openid&code_challenge=c&code_challenge_method=S256")

# First match wins, so the narrower keys come first.
HEALTHY_STATUSES = [
    ["/invoke", 401],
    ["pipelines/test", 200],
    ["/entities?", 200],
    ["/ckan", 302],
    ["-X DELETE", 204],
    ["someone-else.sk", 400],
    ["entities/urn", 200],
    ["/entities", 201],
    [["Bearer", ".forged"], 401],
    ["eyJleHAiOjF9", 401],
    [["Bearer", "/api/v1/auth/me"], 200],
    ["/api/v1/auth/me", 401],
    ["/api/v1/health", 200],
    # The configuration repository is private: without a session the forge serves nothing (PF-79).
    ["configuration/raw/branch", 404],
]

# What a branded CKAN front page looks like from outside: the instance's own name and its
# own primary colour, both from the block above and neither of them in any image (OPS-47).
CATALOGUE_PAGE = (
    "<html><head><title>Example Context</title>"
    "<style>:root { --jc-primary: #0000bf; }</style></head><body>Example Context</body></html>"
)

# The Helsinki seed's slugs (T-0478), one per endpoint name, and the answers a healthy space
# gives: the policy slice is empty on the bikes endpoint, every type flows on `all`. The flow
# checks return the moment an entity answers, so a healthy instance never waits.
HELSINKI_SEED = {"events": "hsevents", "bikes": "hsbikes", "transport": "hstransport", "all": "hsall"}

# What jc-functions answers the smoke's function when the gateway answered it (T-0686).
FUNCTION_ANSWER = '{"status":200,"body":{"gateway":200},"logs":["smoke"]}'

# What the Portal answers for a sample application the lane has built (T-2599).
BUILT_APP = '{"kind":"App","status":{"build":{"commit":"%s","digest":"sha256:%s"}}}' % ("a" * 40, "b" * 64)

HEALTHY = {
    "routes": ["portal-ui", "portal-api", "context-space", "context-endpoint", "gitea-forge", "ckan"],
    "helsinkiSeed": HELSINKI_SEED,
    "bodies": [["/api/v1/projects/helsinki/apps/helsinki-", BUILT_APP],[["Bearer", "/invoke"], FUNCTION_ANSWER],
               # The organization's Actions runner, online (T-2608, ADR-N-028).
               ["actions/runners", '{"runners":[{"name":"gitea-runner-1","status":"online"}]}'],
               ["clients?clientId=edge", '[{"protocolMappers":[{"config":{"included.client.audience": "portal-api"}}]}]'],
               # Both of the proxy's audiences: the gateway, which it reads endpoints through, and
               # the Portal's internal listener, which answers its run lookups. A healthy instance
               # has both mappers, and smoke.sh checks each on its own (T-0666, T-2420).
               ["clients?clientId=helsinki-agent-proxy",
                '[{"protocolMappers":[{"config":{"included.custom.audience": "context-gateway"}},'
                '{"config":{"included.custom.audience": "portal-internal"}}]}]'],
               # The access document each endpoint answers, which is where the probe reads the
               # type it may ask for (T-1211, EP-55): `retrieveOps` grants entity reads and not
               # the type list, so a probe that asked for the type list would be a 403.
               ["hsevents/access", '{"permissions":[{"resource":{"type":"Event"}}]}'],
               ["hsbikes/access", '{"permissions":[{"resource":{"type":"BikeHireDockingStation"}}]}'],
               ["hstransport/access", '{"permissions":[{"resource":{"type":"Vehicle"}}]}'],
               ["hsall/access", '{"permissions":[{"resource":{"type":"Event"}}]}'],
               ["hsbikes/ngsi-ld/v1/entities?type=Event", "[]"],
               ["hsall/ngsi-ld/v1/entities?type=", '[{"id":"urn:ngsi-ld:x"}]'],
               # What the endpoint's space lists, so the smoke can retrieve each of them by id
               # (T-0945). A healthy space serves everything it lists.
               ["entities?type=AirQualityObserved",
                '[{"id":"urn:ngsi-ld:AirQualityObserved:example.test:ovzdusie:1"},'
                '{"id":"urn:ngsi-ld:AirQualityObserved:example.test:ovzdusie:2"}]'],
               ["openid-configuration", '{"jwks_uri":"https://idm/certs"}'],
               ["/token", '{"access_token":"a.b.c"}'],
               ["/api/v1/auth/login", LOGIN_REDIRECT],
               ["/api/v1/projects/helsinki/spaces", json.dumps({"items": [{"kind": "ContextSpace", "metadata": {"name": n}} for n in ("helsinki", "helsinki-kpi")]})],
               ["/api/v1/projects/helsinki/pipelines", json.dumps({"items": [{"kind": "Pipeline"} for _ in range(2)]})],
               ["/api/v1/projects/helsinki/endpoints", json.dumps({"items": [{"kind": "Endpoint"} for _ in HELSINKI_SEED]})],
               [["%{redirect_url}", "https://portal.example.test/"], EDGE_REDIRECT],
               [["%{redirect_url}", "https://example.test/"], "https://portal.example.test/"],
               ["datasources?dryRun=All", '{"valid": true, "probe": {"skipped": "the feed could not be reached: connection refused"}}'],
               ["api_token_list", '{"help": "", "success": true, "result": []}'],
               # The forge's teams (PF-79, PF-80): the administrators' own team and the one a
               # person signed in with Keycloak lands in. Gitea answers "none" as the summary
               # permission of any unit map it did not mint itself, so the map is what the
               # smoke reads.
               ["/api/v1/orgs/joinedcontext/teams", json.dumps([
                   {"name": "Owners", "permission": "owner",
                    "units_map": {"repo.code": "owner", "repo.issues": "owner"}},
                   {"name": "readers", "permission": "none",
                    "units_map": {"repo.code": "read", "repo.issues": "read", "repo.pulls": "read"}},
               ], separators=(",", ":"))],
               ["data.example.test/", CATALOGUE_PAGE]],
    "statuses": HEALTHY_STATUSES,
}


def test_a_datasource_check_that_reaches_inside_the_cluster_fails(tmp_path):
    """T-0752: a Check of an in-cluster address or the metadata service must answer unreachable;
    a status from the address, or an answer without a refusal, is the runner's egress letting a
    typed URL in."""
    spec = dict(HEALTHY)
    spec["bodies"] = [
        [["datasources?dryRun=All", "kubernetes.default.svc"], '{"valid": true, "probe": {"skipped": "the feed answered 200 OK"}}'],
        [["datasources?dryRun=All", "169.254.169.254"], '{"valid": true, "probe": {"records": 1, "bytes": 90}}'],
        *HEALTHY["bodies"],
    ]
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  a probe of https://kubernetes.default.svc/version reached it: the feed answered 200 OK" in result.stdout
    assert "FAIL  a probe of https://169.254.169.254/hetzner/v1/metadata answered no refusal" in result.stdout
    assert "ok    a probe of http://context-broker.dev.svc:8080/ngsi-ld/v1/types stays outside the cluster" in result.stdout
    assert "2 failed, 0 skipped" in result.stdout


def test_missing_arguments_are_refused(tmp_path):
    """Both URLs are mandatory: a one-argument call must not silently smoke half a platform."""
    result = run(tmp_path, HEALTHY, "https://example.test")
    assert result.returncode != 0
    assert "usage: smoke.sh" in result.stderr


def test_full_platform_passes(tmp_path):
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "0 failed, 0 skipped" in result.stdout
    assert "ok    portal host sends an anonymous visitor to the edge login" in result.stdout
    assert "ok    apex redirects to the portal host" in result.stdout
    assert "ok    portal API answers a bearer call through the edge (200)" in result.stdout
    assert "client_credentials token" in result.stdout
    assert "ok    demo user demo.viewer@hel.fi logs in with a password grant" in result.stdout
    assert "entity create through the endpoint (201)" in result.stdout
    assert "write with a foreign URN prefix is refused (400)" in result.stdout
    assert "git forge answers under the /git prefix (200)" in result.stdout
    assert "catalogue front page carries the instance name" in result.stdout
    assert "ok    pipeline test runs a candidate on the runner and captures the output (200)" in result.stdout
    assert "ok    helsinki lists 4 endpoints for 4 seeded (no residue)" in result.stdout
    assert "ok    helsinki lists 2 pipelines for 2 seeded (no residue)" in result.stdout
    assert "ok    helsinki lists 2 spaces for 2 seeded (no residue)" in result.stdout
    assert "ok    agent proxy client mints tokens with audience context-gateway" in result.stdout
    assert "ok    helsinki-bikes does not serve events" in result.stdout
    assert "ok    city bike stations are flowing into the space" in result.stdout
    assert "ok    buses are flowing into the space" in result.stdout
    assert "catalogue front page carries the branded primary colour" in result.stdout
    assert "ok    the publisher's CKAN API token authenticates as the site administrator" in result.stdout
    assert "postgres refuses a pod outside the allowed selectors" in result.stdout
    assert "ok    jc-functions refuses an invocation without the Portal's token (401)" in result.stdout
    assert "ok    jc-functions runs a function for the Portal's token and the function reads the gateway" in result.stdout
    assert "ok    a pod with the Portal's label reaches jc-functions:8080" in result.stdout
    assert "ok    jc-functions refuses a pod that is not the Portal" in result.stdout
    assert "security response headers present" in result.stdout
    assert "the edge refuses TLS 1.1" in result.stdout
    assert "the edge refuses CBC and 3DES suites" in result.stdout


def test_an_instance_without_the_helsinki_seed_skips_its_checks(tmp_path):
    """No seed, no 210 s wait for data that will never come: the section is a skip."""
    result = run(tmp_path, dict(HEALTHY, helsinkiSeed={}), "https://example.test", "https://idm.example.test")
    assert "skip  helsinki endpoints (no Helsinki seed on the gateway in this instance)" in result.stdout


def test_a_schema_artifact_is_revalidated_and_answers_304(tmp_path):
    """EP-51, T-2262: the gateway's `private, no-cache` and ETag reach the reader, and a second
    read with the ETag is a 304 — the edge no longer replaces them with `no-store`."""
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    # Once on main (run 35738512945, T-2653) the whole Helsinki section was skipped and pytest
    # cut the output where the reason stood: every skip line and the section are named here.
    helsinki = [line for line in result.stdout.splitlines() if "skip" in line or "helsinki" in line]
    assert "ok    a schema artifact may be kept and revalidated by its reader (private, no-cache)" in result.stdout, helsinki
    assert "ok    a second read of a schema artifact with its ETag is a 304 (304)" in result.stdout, helsinki


def test_an_edge_that_forbids_keeping_a_schema_artifact_fails_the_run(tmp_path):
    """The regression T-2262 fixed: the edge's `no-store` over the gateway's header, and no 304."""
    spec = dict(HEALTHY, schemaHeaders="HTTP/2 200\r\ncache-control: no-store, no-cache, must-revalidate\r\n")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  a schema artifact says Cache-Control 'no-store, no-cache, must-revalidate', expected 'private, no-cache'" in result.stdout
    assert "FAIL  a schema artifact carries no ETag to revalidate with" in result.stdout


def test_pipeline_residue_beyond_one_take_fails_the_run(tmp_path):
    """Pipelines and spaces are counted the way endpoints are (T-0750)."""
    listed = json.dumps({"items": [{"kind": "Pipeline"} for _ in range(4)]})
    spec = dict(HEALTHY, bodies=[["/api/v1/projects/helsinki/pipelines", listed]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  helsinki lists 4 pipelines for 2 seeded: residue of takes or e2e (T-0667)" in result.stdout


def test_endpoint_residue_beyond_one_take_fails_the_run(tmp_path):
    """Two endpoints more than the seed commits is residue of takes or e2e (T-0667)."""
    listed = json.dumps({"items": [{"kind": "Endpoint"} for _ in range(len(HELSINKI_SEED) + 2)]})
    spec = dict(HEALTHY, bodies=[["/api/v1/projects/helsinki/endpoints", listed]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  helsinki lists 6 endpoints for 4 seeded: residue of takes or e2e (T-0667)" in result.stdout


def test_an_endpoint_list_that_does_not_answer_is_not_called_clean(tmp_path):
    """No endpoints at all for a seeded instance is a list that failed, not a clean one (T-0667)."""
    spec = dict(HEALTHY, bodies=[["/api/v1/projects/helsinki/endpoints", "{}"]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  helsinki lists no endpoints for 4 seeded: the list did not answer" in result.stdout


def test_an_agent_proxy_without_the_gateway_audience_fails_the_run(tmp_path):
    """Seeded slugs alone never name an endpoint approved later: the kit pass reads 401 (T-0666)."""
    slugs_only = '[{"protocolMappers":[{"config":{"included.custom.audience": "si6epqkx364lprho5uaigutk274r5grb"}}]}]'
    spec = dict(HEALTHY, bodies=[["clients?clientId=helsinki-agent-proxy", slugs_only]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  agent proxy client has no context-gateway audience" in result.stdout
    spec = dict(HEALTHY, bodies=[["clients?clientId=helsinki-agent-proxy", "[]"]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert "skip  agent proxy audience (no helsinki-agent-proxy client in realm dev)" in result.stdout


def test_a_function_that_cannot_read_the_gateway_fails_the_run(tmp_path):
    """Status 0 from the host request is the runtime's egress to the gateway refused (T-0686)."""
    cut_off = '{"status":200,"body":{"gateway":0},"logs":["smoke"]}'
    spec = dict(HEALTHY, bodies=[[["Bearer", "/invoke"], cut_off]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  jc-functions did not answer the smoke function with the gateway's 200: " + cut_off in result.stdout


def test_jc_functions_open_to_any_pod_or_closed_to_the_portal_fails_the_run(tmp_path):
    """The unlabelled probe must be refused, and the Portal-labelled one must get through, or the
    refusal only measured a pod that could not dial (T-0686)."""
    result = run(tmp_path, dict(HEALTHY, functionsReachable=True), "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  an unlabelled pod reached jc-functions:8080" in result.stdout
    result = run(tmp_path, dict(HEALTHY, functionsPortalReaches=False), "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  a pod with the Portal's label cannot reach jc-functions:8080" in result.stdout


def test_an_instance_without_jc_functions_skips_the_functions_checks(tmp_path):
    result = run(tmp_path, dict(HEALTHY, functions=False), "https://example.test", "https://idm.example.test")
    assert "skip  functions (jc-functions is not deployed in this instance)" in result.stdout
    assert "jc-functions refuses" not in result.stdout


def test_a_ckan_token_that_no_longer_authenticates_fails_the_run(tmp_path):
    """A token signed with a key the catalogue lost reads as anonymous and is refused (T-0493)."""
    refused = '{"success": false, "error": {"__type": "Authorization Error"}}'
    spec = dict(HEALTHY, bodies=[["api_token_list", refused]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  the CKAN API token in ckan-api-token no longer authenticates (T-0493)" in result.stdout


def test_wrong_status_fails_the_run(tmp_path):
    """An authenticated route that answers an anonymous call must turn the run red."""
    spec = dict(HEALTHY, statuses=[[["Bearer", "/api/v1/auth/me"], 200], ["/api/v1/auth/me", 200]])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  portal API rejects an unauthenticated call (expected 401, got 200)" in result.stdout


def test_accepted_tampered_token_fails_the_run(tmp_path):
    """APISIX no longer verifies tokens, so the Portal accepting a forged signature is the
    regression this suite exists to catch."""
    statuses = [[["Bearer", ".forged"], 200]] + HEALTHY_STATUSES
    spec = dict(HEALTHY, statuses=statuses)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  portal API refuses a tampered token (expected 401, got 200)" in result.stdout


def test_login_redirect_with_another_callback_fails_the_run(tmp_path):
    """The redirect_uri the Portal sends must be the one the client lists, exactly: the
    old /auth/callback is the defect T-0270 fixed, and Keycloak refuses it with a 400 page
    no status check ever sees."""
    bodies = [["/api/v1/auth/login", LOGIN_REDIRECT.replace("%2Fapi%2Fv1%2Fauth%2Fcallback", "%2Fauth%2Fcallback")]]
    spec = dict(HEALTHY, bodies=bodies + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  portal login redirect is not keycloak with redirect_uri=" in result.stdout


# The edge checks need no endpoint: without the context-endpoint route the run skips the
# endpoint blocks and their polling deadlines, and the edge is judged in a second.
EDGE_ONLY = dict(HEALTHY, routes=[r for r in HEALTHY["routes"] if r != "context-endpoint"])


def test_the_edge_login_is_asserted_on_a_healthy_platform(tmp_path):
    """ADR-N-019: the Portal host sends an anonymous visitor to Keycloak with the `edge`
    client, the apex redirects to the Portal host, and a bearer call reaches the Portal
    through the edge on the new host."""
    result = run(tmp_path, EDGE_ONLY, "https://example.test", "https://idm.example.test")
    assert "ok    portal host sends an anonymous visitor to the edge login" in result.stdout
    assert "ok    apex redirects to the portal host" in result.stdout
    assert "ok    portal API answers a bearer call through the edge (200)" in result.stdout
    assert "ok    portal login redirects to keycloak with the callback the client lists" in result.stdout
    assert "0 failed" in result.stdout, result.stdout


def test_a_portal_host_without_the_edge_login_fails_the_run(tmp_path):
    """ADR-N-019: an anonymous visitor of the Portal host is sent to Keycloak by the edge. A
    Portal that answers the page itself (no plugin in front), or a redirect to Keycloak with
    another client or callback (which Keycloak refuses with a 400 nobody sees), is red."""
    for body in ("", EDGE_REDIRECT.replace("client_id=edge", "client_id=portal-ui"),
                 EDGE_REDIRECT.replace("%2Fcallback", "%2Fother")):
        bodies = [[["%{redirect_url}", "https://portal.example.test/"], body]] + HEALTHY["bodies"]
        result = run(tmp_path, dict(EDGE_ONLY, bodies=bodies), "https://example.test", "https://idm.example.test")
        assert result.returncode != 0
        assert "FAIL  portal host does not redirect to the edge login with client_id=edge" in result.stdout


def test_an_apex_that_does_not_redirect_to_the_portal_fails_the_run(tmp_path):
    bodies = [[["%{redirect_url}", "https://example.test/"], ""]] + HEALTHY["bodies"]
    result = run(tmp_path, dict(EDGE_ONLY, bodies=bodies), "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  apex does not redirect to https://portal.example.test/ (got: none)" in result.stdout


def test_endpoint_round_trip_uses_the_seeded_slug_and_the_conformance_token(tmp_path):
    """T-0282: the slug is the seed's, not a literal, and the writes carry the token of the
    account the policy names — the Portal's token would be refused."""
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    assert "ok    client_credentials token for banskabystrica-conformance" in result.stdout
    assert "ok    entity create through the endpoint (201)" in result.stdout
    assert "0 failed, 0 skipped" in result.stdout


def test_every_listed_entity_is_retrieved_by_id(tmp_path):
    """T-0945: a healthy space serves what it lists, and the smoke says how many it read."""
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    assert "ok    every listed entity retrieves by id (2 of them)" in result.stdout


def test_an_entity_that_lists_but_never_retrieves_fails_the_run(tmp_path):
    """The drift T-0945 is about: the broker holds a row the gateway refuses on retrieve, so
    nobody can read or correct it. The smoke names the id, and fails."""
    spec = dict(HEALTHY, statuses=[["entities/urn:ngsi-ld:AirQualityObserved", 400]] + HEALTHY_STATUSES)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  listed but not retrievable" in result.stdout
    assert "urn:ngsi-ld:AirQualityObserved:example.test:ovzdusie:1(400)" in result.stdout


def test_a_space_holding_nothing_skips_the_retrieval(tmp_path):
    """An empty space is not a broken one: skip, never a silent pass."""
    spec = dict(HEALTHY, bodies=[["entities?type=AirQualityObserved", ""]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert "skip  every listed entity retrieves by id (the space holds none)" in result.stdout


def test_unseeded_gateway_skips_the_round_trip(tmp_path):
    """An instance whose gateway seeds no Endpoint has nothing to round-trip: skip, never pass."""
    spec = dict(HEALTHY, seedEndpoint="")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert "skip  endpoint round trip (no Endpoint seeded" in result.stdout
    assert "0 failed, 1 skipped" in result.stdout


def test_endpoint_not_found_fails_the_run(tmp_path):
    """The 404 that hid behind a slug the gateway could never serve is a failure, not a skip."""
    spec = dict(HEALTHY, statuses=[["/entities", 404]] + HEALTHY_STATUSES)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  entity create through the endpoint (expected 201, got 404)" in result.stdout


def test_refused_demo_login_fails_the_run(tmp_path):
    """T-0248: a seeded demo user Keycloak refuses (wrong password, required action, policy)
    is a red run, because DEMO.md step 1 starts with exactly this login."""
    # The script reads the token out of the body, so a refusal is a body without one.
    spec = dict(HEALTHY, bodies=[["grant_type=password", '{"error":"invalid_grant"}']] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  demo user demo.viewer@hel.fi cannot log in with a password grant" in result.stdout


def test_instance_without_demo_users_skips_the_login(tmp_path):
    """Production seeds no demo users: the login is skipped, never passed."""
    spec = dict(HEALTHY, demoPassword="")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "skip  demo user login (no demo users seeded" in result.stdout
    assert "skip  portal space list (no demo user token)" in result.stdout
    assert "skip  sample apps (no demo user token to read them with)" in result.stdout
    assert "0 failed, 3 skipped" in result.stdout


def test_absent_routes_skip_instead_of_passing(tmp_path):
    """A component this instance does not deploy must be reported as skipped, never as a pass."""
    spec = dict(HEALTHY, routes=["keycloak"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "skip  portal API (route portal-api not configured" in result.stdout
    assert "skip  endpoint round trip (route context-endpoint not configured" in result.stdout
    assert "skip  portal host (route portal-ui not configured" in result.stdout
    assert "skip  helsinki endpoints (route context-endpoint not configured" in result.stdout
    assert "skip  git forge (route gitea-forge not configured" in result.stdout
    assert "skip  catalogue (route ckan not configured" in result.stdout
    assert "skip  chunked body (route portal-api not configured" in result.stdout
    assert "7 skipped" in result.stdout


def test_an_unbranded_catalogue_fails_the_run(tmp_path):
    """The whole claim of OPS-46/OPS-47 is that the catalogue a visitor sees is the
    instance's own. A CKAN serving the stock theme answers 200 all the same, so only the
    page content can catch a theme that did not load."""
    spec = dict(HEALTHY, bodies=[["data.example.test/", "<html><body>CKAN</body></html>"]] + HEALTHY["bodies"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  catalogue front page does not carry the instance name" in result.stdout
    assert "FAIL  catalogue front page does not carry the branded primary colour" in result.stdout


def test_reachable_database_fails_the_run(tmp_path):
    """The NetworkPolicy check is inverted: the probe pod connecting is the failure."""
    spec = dict(HEALTHY, netpolReachable=True)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  an unlabelled pod reached postgres-cluster-rw:5432" in result.stdout


def test_reachable_coredns_fails_the_run(tmp_path):
    """T-0454: default-deny is Ingress and Egress, and a controller enforcing only ingress
    passes every other check in this suite. CoreDNS is the leg that discriminates: it is up
    and it is reachable the moment the egress half stops being enforced."""
    spec = dict(HEALTHY, egressReached=["DNS"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  an unlabelled pod reached CoreDNS" in result.stdout


def test_reachable_internet_fails_the_run(tmp_path):
    """The other leg, and the one a break-in actually uses."""
    spec = dict(HEALTHY, egressReached=["NET"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  an unlabelled pod reached 1.1.1.1:443" in result.stdout


def test_both_egress_legs_are_named_when_both_reach(tmp_path):
    spec = dict(HEALTHY, egressReached=["DNS", "NET"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  an unlabelled pod reached CoreDNS 1.1.1.1:443" in result.stdout


def test_an_egress_probe_that_never_ran_fails_the_run(tmp_path):
    """A pod that never started produces exactly the same silence as a pod the policy
    stopped. Without this the check would go green the day the image or the namespace
    changes, which is the failure mode this whole task exists to prevent."""
    spec = dict(HEALTHY, egressProbeRan=False)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the egress probe never ran" in result.stdout


def test_a_pod_that_reaches_the_edge_data_plane_fails_the_run(tmp_path):
    """EP-20, T-0939: APISIX trusts X-Real-IP from the pod network, so a pod other than the
    ingress controller that reaches 9080 can name itself any caller and spend their quota."""
    spec = dict(HEALTHY, edgePeerReached=["9080"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  a pod outside the ingress controller reached APISIX on port 9080 —" in result.stdout


def test_a_pod_that_reaches_the_mesh_port_of_the_edge_fails_the_run(tmp_path):
    """EP-20, T-0939: 4143 is where meshed traffic lands; narrowing 9080 alone leaves it open."""
    spec = dict(HEALTHY, edgePeerReached=["9080", "4143"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "reached APISIX on port 9080 4143 —" in result.stdout


def test_an_edge_peer_probe_that_never_ran_fails_the_run(tmp_path):
    """EP-20: a probe that never ran is silent exactly like a refused one."""
    spec = dict(HEALTHY, edgePeerRan=False)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the edge-peer probe never ran" in result.stdout


def test_no_apisix_pod_to_probe_fails_the_run(tmp_path):
    """EP-20: with no APISIX pod address the probe has nothing to aim at, which is no verdict."""
    spec = dict(HEALTHY, apisixPodIp="")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  no APISIX pod in" in result.stdout


def test_an_edge_that_admits_only_the_ingress_controller_passes(tmp_path):
    """EP-20: the green line names both ports it measured."""
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "ok    APISIX refuses a pod that is not the ingress controller on 9080 and 4143" in result.stdout


def test_an_enforced_egress_policy_passes(tmp_path):
    spec = dict(HEALTHY)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "ok    an unlabelled pod reaches neither CoreDNS nor the internet" in result.stdout


def test_the_pass_line_reports_how_long_the_controller_took(tmp_path):
    """T-0459: the controller programs a NEW pod's egress chains a few seconds after the pod
    is running, so a probe that calls out at container start measures that gap and not the
    policy. The probe settles first and prints how long it waited; the number is on the pass
    line so a window that grows is visible instead of silent."""
    spec = dict(HEALTHY, egressSettled=8)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "(settled after 8s, ceiling 30s)" in result.stdout


def test_a_pod_filtered_from_its_first_packet_settles_at_zero(tmp_path):
    """What a plugin that programs policy before the pod joins the network would produce, and
    the reading that says the window has been closed rather than merely waited out."""
    spec = dict(HEALTHY, egressSettled=0)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "(settled after 0s, ceiling 30s)" in result.stdout


def test_a_window_that_never_closes_still_fails_the_run(tmp_path):
    """The settle loop is bounded, so a pod that is never filtered runs the measurement anyway
    and fails on it. Waiting forever for a refusal that is not coming would turn the check into
    a hang, which reads as a broken suite rather than as an open control."""
    spec = dict(HEALTHY, egressSettled=72, egressReached=["NET"])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  an unlabelled pod reached 1.1.1.1:443" in result.stdout


def test_a_settle_window_inside_the_ceiling_passes_and_prints_both_numbers(tmp_path):
    """SEC-GAP-05 (docs/Deployment/08, "The startup window"): the ceiling is what makes the gap an
    accepted one rather than an open one, so
    the pass line carries the measured window and the ceiling it was held to. A reader of the
    smoke output can tell a window that is closing from one that is creeping towards the bound."""
    spec = dict(HEALTHY, egressSettled=24)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0
    assert "ok    an unlabelled pod reaches neither CoreDNS nor the internet (settled after 24s, ceiling 30s)" in result.stdout


def test_a_settle_window_over_the_ceiling_fails_the_run(tmp_path):
    """SEC-GAP-05: the gap is bounded by this check and by nothing else. A controller that has got
    slower must fail the run, naming the measured seconds and the allowed seconds, instead of
    printing a larger number on a green line."""
    spec = dict(HEALTHY, egressSettled=44)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the egress settle window was 44s, over the 30s ceiling (JC_NETPOL_SETTLE)" in result.stdout


def test_the_ceiling_defaults_to_thirty_seconds_and_the_variable_moves_it(tmp_path):
    """The default is the documented one (docs/Deployment/08) and it is read from the
    environment, so a cluster with a slower controller is a deliberate decision with a value
    beside it rather than an edit to the script."""
    spec = dict(HEALTHY, egressSettled=44)
    default = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert default.returncode == 1
    assert "over the 30s ceiling" in default.stdout
    raised = run(tmp_path, spec, "https://example.test", "https://idm.example.test",
                 extra_env={"JC_NETPOL_SETTLE": "60"})
    assert raised.returncode == 0
    assert "(settled after 44s, ceiling 60s)" in raised.stdout
    # An empty value is an unset one, the way every other knob of this script reads its
    # environment: a pipeline that passes JC_NETPOL_SETTLE="$SOMETHING" with nothing behind it
    # gets the default and not a refusal.
    empty = run(tmp_path, spec, "https://example.test", "https://idm.example.test",
                extra_env={"JC_NETPOL_SETTLE": ""})
    assert empty.returncode == 1
    assert "over the 30s ceiling" in empty.stdout


@pytest.mark.parametrize("value", ["thirty", "30s", "-5", "2.5", " 30"])
def test_a_ceiling_that_is_not_a_whole_number_of_seconds_is_refused(tmp_path, value):
    """An unparsable value must not read as zero, as infinity, or as the default: either of the
    first two silently inverts the check, and the third hides a typo in a deployment pipeline."""
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test",
                 extra_env={"JC_NETPOL_SETTLE": value})
    assert result.returncode == 2
    assert "JC_NETPOL_SETTLE must be a whole number of seconds" in result.stderr
    assert "settled after" not in result.stdout


def test_a_ceiling_the_probe_could_never_exceed_is_refused(tmp_path):
    """The probe waits at most 18 rounds of 4 seconds, so a ceiling at or above 72 seconds can
    never be exceeded: the check would report a pass for every window there is. Refusing the
    value keeps "raise the number until it is green" from being a way to switch the bound off."""
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test",
                 extra_env={"JC_NETPOL_SETTLE": "72"})
    assert result.returncode == 2
    assert "is not below the probe own bound of 72s" in result.stderr


def test_the_probe_bound_in_the_script_matches_the_one_the_ceiling_is_checked_against(tmp_path):
    """The probe's bound lives in the pod's own shell command and the ceiling check compares
    against a constant, so the two can drift apart. Then a ceiling between the real bound and
    the constant would pass validation and never bite."""
    script = SMOKE.read_text()
    rounds = int(re.search(r"i=0; while \[ \$i -lt (\d+) \]", script).group(1))
    sleep = int(re.search(r"i=\$\(\(i\+1\)\); sleep (\d+);", script).group(1))
    constant = int(re.search(r"^settle_probe_seconds=(\d+)$", script, re.M).group(1))
    assert rounds * sleep == constant


def test_a_probe_that_reports_no_window_fails_the_run(tmp_path):
    """The window is the measurement this check exists for. A probe that reached nothing and
    printed no number proved the policy and not the bound, and an empty measurement compared
    with the ceiling would pass by accident."""
    spec = dict(HEALTHY, egressSettled=None)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the egress probe printed no settle window" in result.stdout


def test_missing_client_secret_fails_the_run(tmp_path):
    """No token means the suite proved nothing about authentication; it must not pass."""
    spec = dict(HEALTHY, clientSecret="")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  no client secret for apisix-gateway" in result.stdout


def test_missing_security_header_fails_the_run(tmp_path):
    """A route that stops emitting HSTS is a silent regression; the suite must catch it."""
    spec = dict(HEALTHY, defaultHeaders="HTTP/2 200\r\nserver: APISIX\r\nx-frame-options: DENY\r\n")
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  response headers missing: strict-transport-security" in result.stdout


def test_legacy_tls_and_ciphers_fail_the_run(tmp_path):
    """BSI TR-02102 is asserted against the live listener, so both halves must be able to fail."""
    spec = dict(HEALTHY, tls11=0, cbcRefused=False)
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the edge negotiated TLS 1.1" in result.stdout
    assert "FAIL  the edge negotiated a CBC or 3DES suite" in result.stdout


def test_an_instance_without_the_store_skips_the_section(tmp_path):
    """A component this instance does not deploy is skipped, never passed (T-0925)."""
    result = run(tmp_path, {**HEALTHY, "artifactStore": False}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "skip  artifact store (the component is not deployed in this instance)" in result.stdout


def test_a_store_no_organization_can_read_fails(tmp_path):
    """The reconciler minting nothing, or handing nothing over, is what T-0933 looked like from
    the outside: the store runs and no serving namespace can read it."""
    result = run(tmp_path, {**HEALTHY, "artifactReaders": []}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  no organization has a reader credential" in result.stdout


def test_a_reader_missing_a_key_fails(tmp_path):
    """Half a credential is a pod that starts and cannot authenticate."""
    spec = {**HEALTHY, "artifactReaderKeys": {"artifact-store-reader-helsinki": ["ACCESS_KEY_ID"]}}
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  a reader Secret is missing a key: artifact-store-reader-helsinki/ACCESS_SECRET_KEY" in result.stdout


def test_a_writer_credential_in_the_cluster_fails(tmp_path):
    """The writer publishes. A Secret carrying it hands a serving pod the power to replace an
    artifact, which is the one thing the two roles exist to keep apart (PF-32)."""
    spec = {**HEALTHY, "artifactWriters": ["artifact-store-writer-helsinki"]}
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  a writer credential was written into the cluster:artifact-store-writer-helsinki" in result.stdout


def test_an_edge_that_logs_a_pod_address_fails(tmp_path):
    """Every caller arriving as the ingress pod is one rate-limit bucket for the internet."""
    result = run(tmp_path, {**HEALTHY, "edgeCaller": "10.42.0.125"}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  the edge logged the caller as 10.42.0.125, a pod address" in result.stdout


def test_an_instance_without_the_edge_skips_the_caller_check(tmp_path):
    result = run(tmp_path, {**HEALTHY, "edge": False}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "skip  edge caller (no APISIX in this instance)" in result.stdout


def test_a_request_that_never_reached_the_access_log_skips(tmp_path):
    """A log the smoke cannot read is not a passing check."""
    result = run(tmp_path, {**HEALTHY, "edgeCaller": ""}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "skip  edge caller (the request did not reach the edge's access log)" in result.stdout


def test_an_instance_where_no_pipeline_asks_for_a_credential_skips(tmp_path):
    """No `pipeline-secrets` Secret is the installation whose pipelines name no credential,
    not a broken resolver (T-0935)."""
    result = run(tmp_path, {**HEALTHY, "pipelineSecrets": None}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "skip  pipeline credentials (no pipeline on this instance declares a secretRef)" in result.stdout


def test_a_credential_the_runner_never_receives_fails_the_run(tmp_path):
    """The Secret written and the process not carrying it is a stream that reads an empty
    password and a broker that refuses it — with every manifest looking correct."""
    spec = {**HEALTHY, "runnerEnvMissing": ["DEMO_FEED_PASSWORD"]}
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  the runner's environment is missing a resolved credential: DEMO_FEED_PASSWORD" in result.stdout


def test_a_credential_copied_into_a_configmap_fails_the_run(tmp_path):
    """A credential in a ConfigMap is a credential in `kubectl get -o yaml`, which is the one
    thing the whole resolution path exists to avoid (CC-06)."""
    spec = {**HEALTHY, "leakedCredential": "a-credential"}
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  a resolved credential is written in plaintext into a ConfigMap: DEMO_FEED_PASSWORD" in result.stdout


def test_a_resolver_that_refused_everything_fails_the_run(tmp_path):
    """An empty Secret is every reference refused: the runner has nothing, and the pipelines
    that named a credential are not running."""
    result = run(tmp_path, {**HEALTHY, "pipelineSecrets": {}}, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1, result.stdout
    assert "FAIL  pipeline-secrets is empty" in result.stdout


def test_a_runner_that_reaches_the_internet_fails_the_run(tmp_path):
    """AP-81: the Actions runner runs untrusted build code with egress to the forge, the Portal
    API and DNS only (ADR-N-028)."""
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    assert "ok    a runner pod resolves names and reaches no internet address" in result.stdout
    result = run(tmp_path, dict(HEALTHY, runnerReached=["DNS", "NET"]), "https://example.test", "https://idm.example.test")
    assert result.returncode != 0
    assert "FAIL  a pod with the runner's label reached 1.1.1.1:443" in result.stdout


def test_a_runner_probe_that_measured_nothing_fails_the_run(tmp_path):
    """AP-81: a probe that never ran, or could not even resolve a name, proves no refusal."""
    for spec, line in [
        (dict(HEALTHY, runnerProbeRan=False), "FAIL  the runner probe never ran"),
        (dict(HEALTHY, runnerReached=[]), "FAIL  a pod with the runner's label cannot resolve names"),
    ]:
        result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
        assert result.returncode != 0
        assert line in result.stdout


def test_an_instance_without_the_runner_skips_its_checks(tmp_path):
    result = run(tmp_path, dict(HEALTHY, runnerNamespace=""), "https://example.test", "https://idm.example.test")
    assert "skip  actions runner egress (no gitea-runner in this instance)" in result.stdout
    assert "skip  actions runner (no gitea-runner in this instance)" in result.stdout


def test_a_runner_the_forge_does_not_show_online_fails_the_run(tmp_path):
    """ADR-N-028 §3.3: a runner Deployment whose runner never came online builds nothing."""
    result = run(tmp_path, HEALTHY, "https://example.test", "https://idm.example.test")
    assert "ok    an Actions runner is registered in joinedcontext and online (waited 0s)" in result.stdout
    offline = dict(HEALTHY, bodies=[["actions/runners", '{"runners":[{"name":"r-1","status":"offline"}]}']]
                   + HEALTHY["bodies"])
    result = run(tmp_path, offline, "https://example.test", "https://idm.example.test",
                 extra_env={"JC_SMOKE_RUNNER_WAIT": "0"})
    assert result.returncode != 0
    assert "FAIL  no Actions runner of joinedcontext is online after 0s" in result.stdout


def test_an_app_pod_reached_only_from_apisix_passes(tmp_path):
    """AP-26, AP-108: the positive control and the refusal, with how many App pods ran."""
    result = run(tmp_path, dict(HEALTHY, appPods=["10.42.0.20", "10.42.0.21"]), "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    assert "ok    a pod with APISIX's label reaches an App pod on 8080 (first of 2)" in result.stdout
    assert "ok    an App pod refuses a pod that is not APISIX on 8080 and 4143" in result.stdout


def test_an_app_pod_open_to_any_pod_fails_the_run(tmp_path):
    """AP-26: a pod that reaches the App past the edge skips its login front."""
    result = run(tmp_path, dict(HEALTHY, appPeerReached=["8080", "4143"]), "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  a pod outside APISIX reached the App pod at 10.42.0.20 on port 8080 4143 —" in result.stdout


def test_an_app_pod_apisix_cannot_reach_fails_the_run(tmp_path):
    """AP-108: an App the edge cannot reach serves nobody, and makes the refusal meaningless."""
    result = run(tmp_path, dict(HEALTHY, appEdgeReaches=False), "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  a pod with APISIX's label cannot reach the App pod at 10.42.0.20:8080" in result.stdout


def test_an_app_peer_probe_that_never_ran_fails_the_run(tmp_path):
    result = run(tmp_path, dict(HEALTHY, appPeerRan=False), "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  the App-peer probe never ran" in result.stdout


def test_an_instance_without_app_pods_skips_with_the_count(tmp_path):
    result = run(tmp_path, dict(HEALTHY, appPods=[]), "https://example.test", "https://idm.example.test")
    assert "skip  App pods (0 pod-backed Apps run in this instance)" in result.stdout
    assert "reaches an App pod" not in result.stdout


def test_every_seeded_sample_app_is_built_and_the_wait_is_said(tmp_path):
    """AP-75, AP-80 (T-2599): each seeded app reads as built at its commit, with the seconds waited."""
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test")
    assert result.returncode == 0, result.stdout
    for app in ("helsinki-bikes", "helsinki-events", "helsinki-alerts"):
        assert re.search(rf"ok    sample app {app} is built at aaaaaaaaaaaa after [0-9]+ s", result.stdout)


def test_a_sample_app_the_lane_never_built_fails_the_run(tmp_path):
    """AP-80: no status.build within the wait is a failure naming the app, not a skip."""
    spec = dict(HEALTHY, bodies=[b for b in HEALTHY["bodies"] if b[1] != BUILT_APP])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test", extra_env={"JC_SMOKE_APP_WAIT": "0"})
    assert result.returncode == 1
    assert "FAIL  sample app helsinki-alerts has no status.build after 0 s" in result.stdout


def test_an_instance_without_sample_apps_skips_them(tmp_path):
    result = run(tmp_path, dict(HEALTHY, sampleApps=[]), "https://example.test", "https://idm.example.test")
    assert "skip  sample apps (none is seeded in this instance)" in result.stdout


def test_a_published_app_whose_pod_is_ready_passes(tmp_path):
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test")
    assert "ok    App deployment dev/app-air-quality has 1 of 1 pods ready" in result.stdout


def test_a_published_app_with_no_ready_pod_fails_the_run(tmp_path):
    """T-2665: an image the node cannot pull left two Apps in ImagePullBackOff while smoke was green."""
    spec = dict(HEALTHY, appDeployments=[["dev/app-air-quality", 1, 1], ["dev/app-hsl-transport", None, 1]])
    result = run(tmp_path, spec, "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert "FAIL  App deployment dev/app-hsl-transport has 0 of 1 pods ready" in result.stdout


def test_an_instance_without_pod_backed_apps_skips_the_readiness(tmp_path):
    result = run(tmp_path, dict(HEALTHY, appDeployments=[]), "https://example.test", "https://idm.example.test")
    assert "skip  App deployments (no pod-backed App is published in this instance)" in result.stdout


def test_the_stub_admits_the_edge_probe_by_the_selector_the_edge_policy_really_has():
    """T-2667: the smoke's APISIX-labelled probe was refused on dev because it carried the name
    label alone while the edge's egress policy selects name and instance; the stub holds the same
    selector as the chart, so the probe's labels are checked against what the cluster applies."""
    import yaml

    policies = yaml.safe_load((PROJECT_ROOT / "components/apisix/networkpolicies.yaml").read_text())
    for name, value in policies["apisix"]["podSelector"].items():
        assert f'("{name}", "{value}")' in KUBECTL_STUB, name


def test_the_runners_walls_are_read_from_the_running_pod(tmp_path):
    result = run(tmp_path, dict(HEALTHY), "https://example.test", "https://idm.example.test")
    assert "ok    the runner runs as uid 1000 and holds no Kubernetes token" in result.stdout


@pytest.mark.parametrize(
    ("walls", "said"),
    [
        ({"runnerUid": 0}, "FAIL  the runner runs as uid 0: an application's build runs as root"),
        ({"runnerSaToken": True}, "FAIL  the runner holds a Kubernetes ServiceAccount token"),
        ({"runnerWallsRead": False}, "FAIL  the runner could not be asked for its uid and token"),
    ],
)
def test_a_runner_as_root_or_with_a_token_fails_the_run(tmp_path, walls, said):
    """T-1707 steps 2 and 4 (AP-81): the untrusted build runs as the runner's uid and next to its
    filesystem; root, a mounted token, or a runner nobody could ask is a failure, never a skip."""
    result = run(tmp_path, dict(HEALTHY, **walls), "https://example.test", "https://idm.example.test")
    assert result.returncode == 1
    assert said in result.stdout
