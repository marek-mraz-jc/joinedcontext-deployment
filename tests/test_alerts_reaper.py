"""T-3122: an Alert whose message has ended leaves the space. The traffic-messages feed asks
Digitraffic for active messages only and upserts them, so an ended road work used to stay on the
Alerts desk for weeks (round b on dev: 168 of 233 Alerts past their validTo). The alerts reaper
reads the Alerts back through the public endpoint and the active feed beside them, and deletes in
one batch the Digitraffic Alerts whose validTo has passed or that the feed no longer lists (round
c: 27 of 65 left had no validTo and had left the feed), the way the vehicles reaper removes stale
buses. Without a feed answer only validTo decides, so an outage deletes nothing that is running."""

import json
import subprocess

import yaml

import open_data
from open_data import requires_docker
from test_helsinki_open_data import HELSINKI

DIGITRAFFIC = "https://tie.digitraffic.fi/api/traffic-message/v1/messages"


def _stream() -> dict:
    return yaml.safe_load((HELSINKI / "helsinki-pipeline-alerts-reaper-bento.yaml").read_text())


def _reaped(alerts: list[dict], active: list[str] | None) -> list:
    """The ids the reaper sends to the batch delete: its processors after the feed branch up to
    the http call, given the Alerts read back and the situation ids the feed listed (`None`:
    the feed did not answer)."""
    processors = _stream()["pipeline"]["processors"]
    start = next(i for i, p in enumerate(processors) if "branch" in p) + 1
    cut = next(i for i, p in enumerate(processors) if "http" in p)
    message = {"alerts": alerts} if active is None else {"alerts": alerts, "active": active}
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        "pipeline": {"processors": processors[start:cut]},
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh",
         open_data.BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=json.dumps(message).encode(), capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode()
    return [json.loads(line) for line in result.stdout.decode().splitlines() if line.strip()]


def alert(n: int, valid_to: str | None, source: str = DIGITRAFFIC) -> dict:
    doc = {"id": f"urn:ngsi-ld:Alert:hel.fi:helsinki:GUID{n}", "type": "Alert",
           "category": "traffic", "source": source}
    if valid_to is not None:
        doc["validTo"] = valid_to
    return doc


RUNNING = ["GUID1", "GUID2", "GUID3", "GUID4", "GUID5", "GUID6"]


@requires_docker
def test_only_expired_digitraffic_alerts_are_deleted():
    reaped = _reaped([
        alert(1, "2026-09-14T06:53:19.721Z"),         # ended a month ago
        alert(2, "2999-01-01T00:00:00Z"),             # still running
        alert(3, None),                               # open-ended and in the feed: kept
        alert(4, "2026-09-14T06:53:19Z", "steward"),  # not the feed's: kept
        alert(5, "not a date"),                       # unreadable and in the feed: kept
        alert(6, "2026-10-01T00:00:00+03:00"),        # an offset, ended
    ], RUNNING)
    assert reaped == [["urn:ngsi-ld:Alert:hel.fi:helsinki:GUID1", "urn:ngsi-ld:Alert:hel.fi:helsinki:GUID6"]]


@requires_docker
def test_an_alert_the_feed_no_longer_lists_is_deleted():
    reaped = _reaped([
        alert(3, None),                     # no validTo, gone from the feed: the round c case
        alert(5, "not a date"),             # unreadable, gone from the feed
        alert(7, None),                     # no validTo, still in the feed: kept
        alert(8, None, "steward"),          # not the feed's, whatever the feed says: kept
        alert(9, "2999-01-01T00:00:00Z"),   # a validTo ahead, gone from the feed
    ], ["GUID7"])
    assert reaped == [[
        "urn:ngsi-ld:Alert:hel.fi:helsinki:GUID3",
        "urn:ngsi-ld:Alert:hel.fi:helsinki:GUID5",
        "urn:ngsi-ld:Alert:hel.fi:helsinki:GUID9",
    ]]


@requires_docker
def test_without_a_feed_answer_only_valid_to_decides():
    alerts = [alert(1, "2026-09-14T06:53:19Z"), alert(3, None), alert(9, "2999-01-01T00:00:00Z")]
    expired = [["urn:ngsi-ld:Alert:hel.fi:helsinki:GUID1"]]
    # the feed failed (no `active`), or answered nothing: an outage deletes nothing that runs
    assert _reaped(alerts, None) == expired
    assert _reaped(alerts, []) == expired


@requires_docker
def test_nothing_expired_sends_nothing():
    assert _reaped([alert(2, "2999-01-01T00:00:00Z")], ["GUID2"]) == []
    assert _reaped([], ["GUID2"]) == []
    assert _reaped([], None) == []


def test_the_reaper_reads_the_feed_the_ingest_reads():
    branch = next(p["branch"] for p in _stream()["pipeline"]["processors"] if "branch" in p)
    http = branch["processors"][0]["http"]
    ingest = yaml.safe_load((HELSINKI / "helsinki-datasource-traffic-messages.yaml").read_text())
    assert http["url"] == ingest["spec"]["http"]["url"]
    assert http["verb"] == "GET"
    assert http["headers"]["Digitraffic-User"] == ingest["spec"]["http"]["headers"]["Digitraffic-User"]
    assert http["rate_limit"] == "pipeline_egress"


def test_the_reaper_is_seeded_beside_the_feed():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    for seeded, path in [
        ("helsinki-datasource-alerts-live.yaml", "projects/helsinki/datasources/helsinki-alerts-live.yaml"),
        ("helsinki-pipeline-alerts-reaper.yaml", "projects/helsinki/pipelines/alerts-reaper/pipeline.yaml"),
        ("helsinki-pipeline-alerts-reaper-bento.yaml", "projects/helsinki/pipelines/alerts-reaper/bento.yaml"),
    ]:
        assert index.get(seeded) == path, seeded
    pipeline = yaml.safe_load((HELSINKI / "helsinki-pipeline-alerts-reaper.yaml").read_text())
    source = yaml.safe_load((HELSINKI / "helsinki-datasource-alerts-live.yaml").read_text())
    feed = yaml.safe_load((HELSINKI / "helsinki-pipeline-traffic-messages.yaml").read_text())
    endpoint = yaml.safe_load((HELSINKI / "helsinki-endpoint-alerts.yaml").read_text())
    assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == source["metadata"]["name"]
    # The read-back goes through the public Alerts endpoint, the delete through the endpoint
    # and the Policy every feed write takes (deleteBatch of pipelines-write).
    assert f"/api/endpoint/{endpoint['spec']['slug']}/ngsi-ld/v1/entities?type=Alert" in source["spec"]["http"]["url"]
    assert pipeline["spec"]["targetEndpoint"] == feed["spec"]["targetEndpoint"]
    assert pipeline["spec"]["schedule"] == feed["spec"]["schedule"]
    policy = yaml.safe_load((HELSINKI / "helsinki-policy-pipelines-write.yaml").read_text())
    assert "deleteBatch" in policy["spec"]["operations"]
