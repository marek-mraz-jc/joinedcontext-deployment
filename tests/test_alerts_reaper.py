"""T-3122: an Alert whose validTo has passed leaves the space. The traffic-messages feed asks
Digitraffic for active messages only and upserts them, so an ended road work used to stay on the
Alerts desk for weeks (round b on dev: 168 of 233 Alerts past their validTo). The alerts reaper
reads the Alerts back through the public endpoint and deletes the expired Digitraffic ones in one
batch, the way the vehicles reaper removes stale buses."""

import json
import subprocess

import yaml

import open_data
from open_data import requires_docker
from test_helsinki_open_data import HELSINKI

DIGITRAFFIC = "https://tie.digitraffic.fi/api/traffic-message/v1/messages"


def _reaped(alerts: list[dict]) -> list:
    """The ids the reaper sends to the batch delete: its processors up to the http call."""
    stream = yaml.safe_load((HELSINKI / "helsinki-pipeline-alerts-reaper-bento.yaml").read_text())
    processors = stream["pipeline"]["processors"]
    cut = next(i for i, p in enumerate(processors) if "http" in p)
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        "pipeline": {"processors": processors[:cut]},
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh",
         open_data.BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=json.dumps(alerts).encode(), capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode()
    return [json.loads(line) for line in result.stdout.decode().splitlines() if line.strip()]


def alert(n: int, valid_to: str | None, source: str = DIGITRAFFIC) -> dict:
    doc = {"id": f"urn:ngsi-ld:Alert:hel.fi:helsinki:GUID{n}", "type": "Alert",
           "category": "traffic", "source": source}
    if valid_to is not None:
        doc["validTo"] = valid_to
    return doc


@requires_docker
def test_only_expired_digitraffic_alerts_are_deleted():
    reaped = _reaped([
        alert(1, "2026-09-14T06:53:19.721Z"),         # ended a month ago
        alert(2, "2999-01-01T00:00:00Z"),             # still running
        alert(3, None),                               # open-ended: kept
        alert(4, "2026-09-14T06:53:19Z", "steward"),  # not the feed's: kept
        alert(5, "not a date"),                       # unreadable: kept
        alert(6, "2026-10-01T00:00:00+03:00"),        # an offset, ended
    ])
    assert reaped == [["urn:ngsi-ld:Alert:hel.fi:helsinki:GUID1", "urn:ngsi-ld:Alert:hel.fi:helsinki:GUID6"]]


@requires_docker
def test_nothing_expired_sends_nothing():
    assert _reaped([alert(2, "2999-01-01T00:00:00Z")]) == []
    assert _reaped([]) == []


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
