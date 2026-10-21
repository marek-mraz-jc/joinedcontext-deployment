"""Synthetic probes of every public surface (T-5103): the checks against recorded answers, the
round's plan and budget, discovery from the catalogue, and the rendered workload.

The good answers are trimmed copies of what dev and smartcity served on 2026-10-21; the bad ones
are the failures a visitor meets: an error status, an empty page, a body of another kind.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("probe", ROOT / "components/probes/files/probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

API = "https://api.example.org"
SLUG = "4ysiqy53qik5qyvawwaj7wgylpt4uoxa"
JSON = {"content-type": "application/json"}


def j(doc):
    return json.dumps(doc).encode()


ENTITY = {"id": "urn:ngsi-ld:Address:x:1", "type": "Address", "postCode": {"type": "Property", "value": "97401"}}
GOOD = {
    "catalogue": (200, JSON, j({"success": True, "result": {"count": 1, "results": [{"name": "praha-parkoviste-pr"}]}})),
    "assistant": (200, JSON, j({"publicId": "data", "title": {"en": "Open data"}})),
    "ngsi-ld": (200, {**JSON, "ngsild-results-count": "10027"}, j([ENTITY])),
    "odata": (200, JSON, j({"@odata.context": "$metadata#Address", "value": [{"id": "urn:ngsi-ld:Address:x:1"}]})),
    "ogc": (200, {"content-type": "application/geo+json"}, j({
        "type": "FeatureCollection", "numberReturned": 1,
        "features": [{"type": "Feature", "id": "a", "geometry": {"type": "Point", "coordinates": [19.1, 48.7]}, "properties": {}}],
    })),
    "sta": (200, JSON, j({"@iot.nextLink": "Things?$skip=1", "value": [{"@iot.id": "urn:ngsi-ld:Address:x:1", "name": "a"}]})),
    "csv": (200, {"content-type": "text/csv; charset=utf-8; header=present"}, b"id,type,postCode.value\nurn:ngsi-ld:Address:x:1,Address,97401\n"),
    "ical": (200, {"content-type": "text/calendar"}, b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"),
    "mcp": (200, JSON, j({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "query_entities"}, {"name": "get_entity"}]}})),
    "websocket": (101, {"sec-websocket-protocol": "ngsi-ld-ws"}, j({"metadata": {"x-op": "x-welcome", "x-connection": "c1"}})),
}
PROBLEM = j({"type": "https://joinedcontext.com/errors/resource-not-found", "status": 404})
BAD = {
    "catalogue": [(503, JSON, b"<html>"), (200, JSON, j({"success": True, "result": {"count": 0, "results": []}})),
                  (200, JSON, j({"success": False}))],
    "assistant": [(404, JSON, PROBLEM), (200, JSON, j({}))],
    "ngsi-ld": [(400, JSON, PROBLEM), (200, JSON, j([])), (200, JSON, j([ENTITY])),
                (200, {**JSON, "ngsild-results-count": "0"}, j([ENTITY])), (200, JSON, b"{not json")],
    "odata": [(500, JSON, PROBLEM), (200, JSON, j({"value": []})), (200, JSON, j([]))],
    "ogc": [(404, JSON, PROBLEM), (200, JSON, j({"type": "FeatureCollection", "features": []})),
            (200, JSON, j({"collections": []})), (200, JSON, j({"type": "FeatureCollection", "features": [{"type": "Point"}]}))],
    "sta": [(502, JSON, b""), (200, JSON, j({"value": []})), (200, JSON, j({"value": [{"name": "no id"}]}))],
    "csv": [(404, JSON, PROBLEM), (200, JSON, b"id,type\n"), (200, {"content-type": "text/csv"}, b"id,type\n"),
            (200, {"content-type": "text/csv"}, b"name,type\na,b\n")],
    "ical": [(404, JSON, PROBLEM), (200, {}, b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"), (200, {}, b"<html>")],
    "mcp": [(401, JSON, PROBLEM), (200, JSON, j({"result": {"tools": []}})), (200, JSON, j({"error": {"code": -32601}})),
            (200, JSON, j({"result": {"tools": [{"description": "nameless"}]}}))],
    "websocket": [(404, JSON, PROBLEM), (0, {}, b"timed out"), (101, {}, j({"metadata": {"x-op": "x-welcome"}})),
                  (101, {"sec-websocket-protocol": "ngsi-ld-ws"}, j({"metadata": {"x-op": "x-closing"}}))],
}


@pytest.mark.parametrize("surface", sorted(GOOD))
def test_each_check_holds_on_a_good_answer(surface):
    assert probe.CHECKS[surface](*GOOD[surface]) is None


@pytest.mark.parametrize("surface,answer", [(s, a) for s, answers in sorted(BAD.items()) for a in answers])
def test_each_check_fails_a_bad_answer_with_its_own_words(surface, answer):
    reason = probe.CHECKS[surface](*answer)
    assert reason, f"{surface} passed {answer!r}"
    # The reason is the probe's sentence: a response body never reaches /results.json.
    assert "<html>" not in reason and "resource-not-found" not in reason


def test_mcp_answered_as_a_server_sent_event_holds():
    body = b"event: message\ndata: " + GOOD["mcp"][2] + b"\n\n"
    assert probe.check_mcp(200, {"content-type": "text/event-stream"}, body) is None


def test_targets_accept_https_origins_only():
    good = [{"name": "dev", "api": "https://api.dev.example/", "catalogue": "https://opendata.dev.example",
             "assistant": "https://assistant.dev.example", "assistantId": "data"}]
    assert probe.load_targets(json.dumps(good))[0]["api"] == "https://api.dev.example"
    for key, value in [("api", "http://api.dev.example"), ("catalogue", "https://x.example/path"),
                       ("assistant", "file:///etc/passwd"), ("name", "Dev Cluster"), ("assistantId", "../x")]:
        with pytest.raises(ValueError):
            probe.load_targets(json.dumps([{**good[0], key: value}]))
    with pytest.raises(ValueError):
        probe.load_targets("[]")


def test_discovery_keeps_only_endpoints_on_the_targets_own_api():
    doc = {"result": {"results": [
        {"endpoint": f"{API}/api/endpoint/{SLUG}/"},
        {"endpoint": f"{API}/api/endpoint/{SLUG}/"},
        {"endpoint": "https://evil.example/api/endpoint/abc/"},
        {"endpoint": f"{API}/api/endpoint/../admin/"},
        {"name": "no endpoint extra"},
    ]}}
    assert probe.endpoint_slugs(API, doc) == [SLUG]


def test_record_surfaces_reads_the_distributions():
    base = f"{API}/api/endpoint/{SLUG}/"
    doc = {"dcat:distribution": [{"dcat:accessURL": base + path} for path in
                                 ("ngsi-ld/v1/", "file.csv", "ws", "ogc/features/", "odata/v4/", "sta/v1.1/", "mcp",
                                  "ical/v1/events.ics", "schema/v1/model.md")]
           + [{"dcat:accessURL": "https://elsewhere.example/ws"}]}
    assert probe.record_surfaces(API, SLUG, doc) == sorted(probe.SURFACES.values())
    assert probe.record_surfaces(API, SLUG, {"dcat:distribution": "x"}) == []


def test_plan_probes_every_kind_each_round_and_walks_every_endpoint():
    holders = {"ogc": [f"e{i}" for i in range(10)], "mcp": ["e0", "e1"]}
    cursors, seen = {}, set()
    for _ in range(4):
        picks = probe.plan(6, sorted(holders), cursors, holders)
        assert len(picks) <= 6
        assert {k for k, _ in picks} == {"mcp", "ogc"}
        seen |= set(picks)
    assert seen == {(k, e) for k, slugs in holders.items() for e in slugs}
    assert probe.plan(0, ["ogc"], {}, holders) == []


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def recorded_internet(broken=frozenset()):
    """The answers of one target, by URL; a surface in `broken` answers 503."""
    calls = []
    record = {"dcat:distribution": [{"dcat:accessURL": f"{API}/api/endpoint/{SLUG}/{p}"} for p in probe.SURFACES]}

    def get(url, data=None, headers=None, cap=probe.BODY_CAP):
        calls.append(url)
        assert url.startswith(("https://api.example.org/", "https://opendata.example.org/", "https://assistant.example.org/"))
        if "package_search" in url and "fl=" in url:
            return 200, JSON, j({"success": True, "result": {"results": [{"endpoint": f"{API}/api/endpoint/{SLUG}/"}]}}), 0.1
        if url.endswith(f"/api/endpoint/{SLUG}"):
            return 200, JSON, j(record), 0.1
        if url.endswith("/ngsi-ld/v1/types"):
            return 200, JSON, j({"typeList": ["Address"]}), 0.1
        kind = next(k for k, marker in [("catalogue", "package_search"), ("assistant", "/config"), ("ngsi-ld", "/entities?"),
                                        ("odata", "/odata/"), ("ogc", "/ogc/"), ("sta", "/sta/"), ("csv", "file.csv"),
                                        ("ical", ".ics"), ("mcp", "/mcp")] if marker in url)
        return (503, JSON, b"down", 0.1) if kind in broken else (*GOOD[kind], 0.2)

    def ws(url):
        calls.append(url)
        return (0, {}, b"refused", 0.1) if "websocket" in broken else (*GOOD["websocket"], 0.2)

    return get, ws, calls


TARGET = {"name": "dev", "api": API, "catalogue": "https://opendata.example.org", "assistant": "https://assistant.example.org",
          "assistantId": "data"}


def test_a_round_probes_every_surface_within_budget_and_a_broken_one_goes_red_then_green():
    clock = FakeClock()
    get, ws, calls = recorded_internet()
    prober = probe.Prober([TARGET], 30, 900, clock=clock, sleep=clock.sleep, get=get, ws=ws)
    prober.round(TARGET)
    assert len(calls) <= 30
    assert clock.now - 1_000_000.0 == pytest.approx(len(calls) * 2.0, abs=0.1)  # paced 60 s / 30 requests
    results = {(r["endpoint"], r["surface"]): r for r in prober.snapshot()}
    assert set(results) == {(None, "catalogue"), (None, "assistant")} | {(SLUG, s) for s in probe.SURFACES.values()}
    assert all(r["ok"] for r in results.values())

    broken_get, broken_ws, _ = recorded_internet(broken={"odata", "websocket"})
    prober.get, prober.ws = broken_get, broken_ws
    prober.round(TARGET)
    metrics = prober.metrics()
    assert f'jc_probe_up{{target="dev",endpoint="{SLUG}",surface="odata"}} 0' in metrics
    assert f'jc_probe_up{{target="dev",endpoint="{SLUG}",surface="websocket"}} 0' in metrics
    assert f'jc_probe_up{{target="dev",endpoint="{SLUG}",surface="ogc"}} 1' in metrics
    assert 'jc_probe_surface_failing{target="dev",surface="odata"} 1' in metrics
    reasons = {r["surface"]: r["reason"] for r in prober.snapshot() if not r["ok"]}
    assert reasons == {"odata": "status 503", "websocket": "status 0"}

    prober.get, prober.ws = get, ws
    prober.round(TARGET)
    assert all(r["ok"] for r in prober.snapshot())
    assert prober.healthy()


def test_an_endpoint_gone_from_the_catalogue_leaves_the_results():
    clock = FakeClock()
    get, ws, _ = recorded_internet()
    prober = probe.Prober([TARGET], 30, 60, clock=clock, sleep=clock.sleep, get=get, ws=ws)
    prober.round(TARGET)

    def empty_catalogue(url, data=None, headers=None, cap=probe.BODY_CAP):
        if "fl=" in url:
            return 200, JSON, j({"success": True, "result": {"results": []}}), 0.1
        return get(url, data, headers, cap)

    prober.get = empty_catalogue
    clock.now += 120
    prober.round(TARGET)
    assert {r["endpoint"] for r in prober.snapshot()} == {None}


def test_healthz_fails_when_a_target_misses_its_rounds():
    clock = FakeClock()
    prober = probe.Prober([TARGET], 30, 900, clock=clock, sleep=clock.sleep)
    assert prober.healthy()
    clock.now += 181
    assert not prober.healthy()


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def test_rendered_probe_is_anonymous_pinned_and_probes_both_environments(dev):
    deployment = next(d for d in dev if d.get("kind") == "Deployment" and d["metadata"]["name"] == "probe")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["image"].startswith("docker.io/library/python:3.13.16-slim-trixie@sha256:")
    env = {e["name"]: e.get("value") for e in container.get("env", [])}
    targets = probe.load_targets(env["PROBE_TARGETS"])
    assert [t["name"] for t in targets] == ["dev", "smartcity"]
    assert targets[1]["api"] == "https://api.smartcity.joinedcontext.com"
    assert 12 <= int(env["PROBE_BUDGET"]) <= 200
    # No token, no Secret: every probe is a visitor's.
    assert not any("valueFrom" in e for e in container.get("env", []))
    assert not container.get("envFrom")
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert pod["securityContext"]["runAsNonRoot"] is True
    config = next(d for d in dev if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "probe")
    assert config["data"]["probe.py"] == (ROOT / "components/probes/files/probe.py").read_text()


def test_rendered_probe_egress_is_https_and_dns_only(dev):
    policy = next(d for d in dev if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "probe")
    ports = {(p["protocol"], p["port"]) for rule in policy["spec"]["egress"] for p in rule.get("ports", [])}
    assert ports <= {("TCP", 443), ("TCP", 8443), ("UDP", 53), ("TCP", 53)}
    public = next(r for r in policy["spec"]["egress"] if any("ipBlock" in t for t in r["to"]))
    assert "10.0.0.0/8" in public["to"][0]["ipBlock"]["except"]
