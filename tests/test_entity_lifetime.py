"""T-4823: a bus that stops reporting and a Digitraffic Alert that ended leave the space by their
own `expiresAt` (NGSI-LD 4.22), which the broker hides from every read once it passes and then
deletes. Two reaper pipelines did this before by reading the space back and batch-deleting what
they judged stale; they are gone, and so is the delete grant they needed beyond the one the
service-alerts withdrawal keeps (Alerts only).

Bento runs the committed mappings; without a container runtime those cases skip, the seed cases
do not."""

import json
from datetime import UTC, datetime, timedelta

import yaml
from open_data import requires_docker
from test_helsinki_open_data import HELSINKI, run
from test_hfp_fleet_cap import bento, frame


def stamp(text: str) -> datetime:
    return datetime.fromisoformat(text)


@requires_docker
def test_a_vehicle_expires_five_minutes_after_the_position_it_reports():
    (bus,) = bento([frame(7, "01", tst="2026-09-25T16:01:00.575Z")], threads=1)
    assert bus["expiresAt"] == "2026-09-25T16:06:00.575Z"
    assert bus["location"]["observedAt"] == "2026-09-25T16:01:00.575Z"


@requires_docker
def test_a_report_whose_time_cannot_be_read_is_dropped_rather_than_living_forever():
    # The thirty-second sampling reads seconds 17..19; this one passes it and still is no time.
    assert bento([frame(7, "01", tst="2026-09-25T16:01:00 nonsense")], threads=1) == []


def situation(n: int, ends: str | None) -> dict:
    timing = {"startTime": "2026-10-12T08:00:00Z"} | ({"endTime": ends} if ends else {})
    return {
        "geometry": {"type": "Point", "coordinates": [24.95, 60.17]},
        "properties": {
            "situationId": f"GUID7000{n}",
            "situationType": "ROAD_WORK",
            "releaseTime": "2026-10-12T08:00:00Z",
            "announcements": [{
                "title": "Tie 4, Helsinki",
                "locationDetails": {"roadAddressLocation": {"primaryPoint": {"municipality": "Helsinki"}}},
                "timeAndDuration": timing,
            }],
        },
    }


@requires_docker
def test_an_alert_expires_at_its_validto_or_an_hour_after_the_feed_last_listed_it():
    before = datetime.now(UTC).replace(microsecond=0)
    soon = (before + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    later = (before + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = {e["id"][-1]: e for e in run("traffic-messages", {"features": [
        situation(1, soon), situation(2, later), situation(3, None), situation(4, "2026-01-01T00:00:00Z"),
    ]})}
    after = datetime.now(UTC)
    lease = (before + timedelta(hours=1), after + timedelta(hours=1))
    # Ending within the hour: its own end, in UTC (the feed's offset is read, not dropped).
    assert stamp(written["1"]["expiresAt"]) == before + timedelta(minutes=20) - timedelta(hours=3)
    assert written["1"]["expiresAt"].endswith("Z")
    # Ending later, or never said: the hour the next run moves on while the feed lists it.
    for n in ("2", "3"):
        assert lease[0] <= stamp(written[n]["expiresAt"]) <= lease[1], written[n]["expiresAt"]
    # An end already past is written as expired, so no read shows it.
    assert written["4"]["expiresAt"] == "2026-01-01T00:00:00Z"


def test_no_reaper_pipeline_is_seeded():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    assert not [name for name in index if "reaper" in name or name.endswith("-live.yaml")], index
    assert not list(HELSINKI.glob("*reaper*"))
    for name in index:
        if name.startswith("helsinki-pipeline-") and name.endswith("-bento.yaml"):
            text = (HELSINKI / name).read_text()
            if "entityOperations/delete" in text:
                assert name == "helsinki-pipeline-service-alerts-bento.yaml", name


def test_the_pipelines_may_delete_only_alerts():
    """The reapers' deleteBatch over every type of the city space is gone: the pipelines account
    keeps a delete there only over Alerts, the one type a pipeline still withdraws."""
    deleting = []
    for path in sorted(HELSINKI.glob("helsinki-policy-*.yaml")):
        policy = yaml.safe_load(path.read_text())
        spec = policy["spec"]
        if spec["contextSpaceRef"]["name"] != "helsinki" or spec.get("assignee", {}).get("id") != "pipelines":
            continue
        if "deleteBatch" not in spec.get("operations", []):
            continue
        deleting.append(path.name)
        assert spec["operations"] == ["deleteBatch"], path.name
        assert [e["type"] for rule in spec["information"] for e in rule["entities"]] == ["Alert"], path.name
    assert deleting == ["helsinki-policy-pipelines-delete-alerts.yaml"], deleting
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    assert index["helsinki-policy-pipelines-delete-alerts.yaml"].endswith("/policies/pipelines-delete-alerts.yaml")


def test_one_history_default():
    """The platform's history default is the broker's ANTARES_RETENTION_HISTORY_DEFAULT; the
    `retention.history` of platform-settings.yaml had no reader and said something else."""
    settings = yaml.safe_load((HELSINKI / "helsinki-platform-settings.yaml").read_text())
    assert "retention" not in settings, json.dumps(settings)
