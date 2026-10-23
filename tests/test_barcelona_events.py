"""The Ajuntament's activity agendas become SDM Events, checked and counted (T-5265).

Bento runs the committed mapping over rows recorded from the bcn-agenda DataSource's DataStore
query on 2026-10-22 (`fixtures/barcelona/agenda/agenda-sql.json`): seven usable activities of
the three agendas, three rows the source really carries and a map cannot use (a point at 0,0, a
row with no position, a permanent collection with no start day) and two rows the test made (an
end before the start, the concert listed twice under a second id). Each bad row is dropped and
counted by its reason. Without a container runtime the Bento cases skip.
"""

import copy
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

import open_data
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-barcelona-open-data")

ROOT = Path(__file__).resolve().parent.parent
BARCELONA = ROOT / "components/context-gateway/seed/barcelona"
MAPPING = BARCELONA / "barcelona-pipeline-agenda-bento.yaml"
FIXTURE = Path(__file__).resolve().parent / "fixtures/barcelona/agenda/agenda-sql.json"
URN = "urn:ngsi-ld:Event:barcelona.cat:barcelona:{}"


def answer(modified: str | None = None, records: list | None = None) -> dict:
    """The recorded answer, its newest change moved to `modified` (now by default), so the
    staleness check judges the rows as the day's run would."""
    doc = json.loads(FIXTURE.read_text())
    if records is not None:
        doc["result"]["records"] = records
    stamp = modified or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    for row in doc["result"]["records"][:1]:
        row["modified"] = stamp
    return doc


def run(doc: dict) -> tuple[list[dict], str, int]:
    config = {"input": {"stdin": {"scanner": {"to_the_end": {}}}},
              "pipeline": yaml.safe_load(MAPPING.read_text())["pipeline"],
              "output": {"stdout": {"codec": "lines"}}, "logger": {"level": "info", "format": "logfmt"}}
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=barcelona.cat", "-e", "JC_SPACE=barcelona",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO,
         "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=json.dumps(doc).encode(), capture_output=True, timeout=120)
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("[")]
    events = [e for line in lines for e in json.loads(line)]
    return events, result.stderr.decode() + result.stdout.decode(), result.returncode


@requires_docker
def test_the_recorded_rows_map_to_valid_events_and_each_bad_row_is_dropped_by_reason():
    events, log, code = run(answer())
    assert code == 0, log
    by_id = {e["id"]: e for e in events}
    assert sorted(by_id) == sorted(URN.format(i) for i in (
        "99400013467", "99400642884", "99400255636", "2025121918", "99400300596", "2042164840"))
    assert ('dropped by reason {\\"duplicate\\":1,\\"ends before it starts\\":1,\\"no position\\":1,'
            '\\"outside Barcelona\\":1,\\"start day missing or before 2000\\":1}') in log, log
    for entity in events:
        assert not open_data.schema_errors(BARCELONA / "barcelona.v1.schema.json", entity), entity
        # The main category is one of the platform's fifteen codes (T-5363), which SDM's
        # suggested category list lacks; every other member passes the pinned SDM schema.
        errors = [e for e in open_data.sdm_errors("dataModel.TourismDestinations/Event", entity)
                  if not e.startswith("category/0")]
        assert not errors, (entity["id"], errors)
        lon, lat = entity["location"]["value"]["coordinates"]
        assert 2.04 <= lon <= 2.24 and 41.3 <= lat <= 41.48, entity["id"]
    concert = by_id[URN.format("99400642884")]
    assert concert["name"]["value"] == "Concert d’Any Nou del Gran Teatre del Liceu"
    assert concert["category"]["value"] == ["music", "spectacle"]
    assert concert["subCategory"]["value"] == ["music"]
    # A winter day starts at +01:00 in Barcelona, a summer one at +02:00.
    assert concert["startDate"]["value"] == "2027-01-04T00:00:00+01:00"
    assert concert["contactPoint"]["value"] == {"telephone": "934 859 913"}
    assert concert["source"]["value"] == "https://opendata-ajuntament.barcelona.cat/data/dataset/agenda-cultural"
    walk = by_id[URN.format("99400013467")]
    assert walk["category"]["value"] == ["sport"], "the sports agenda is sport whatever the name says"
    assert walk["address"]["value"] == {"streetAddress": "Passeig de Pujades 10", "postalCode": "08003",
                                        "addressLocality": "Barcelona", "district": "Ciutat Vella",
                                        "addressCountry": "ES"}
    workshop = by_id[URN.format("99400255636")]
    assert workshop["startDate"]["value"] == "2026-09-16T00:00:00+02:00"
    assert workshop["category"]["value"] == ["hobby-workshop"]
    assert by_id[URN.format("2025121918")]["category"]["value"] == ["exhibition-museum", "museum"]
    # A running activity with no last day carries no endDate rather than an empty one.
    assert "endDate" not in by_id[URN.format("2042164840")]


@requires_docker
@pytest.mark.parametrize("doc, message", [
    (answer(records=[]), "the Barcelona agendas list no current activity"),
    (answer(modified="2026-01-01T00:00:00"), "the Barcelona agendas are stale"),
    ({"success": False, "error": {"message": "relation does not exist"}}, "Open Data BCN refused the agenda query"),
])
def test_an_empty_stale_or_refused_answer_fails_the_run_instead_of_writing(doc, message):
    events, log, _ = run(copy.deepcopy(doc))
    # A thrown mapping error leaves the message flagged; the runner's output refuses a flagged
    # message, so the endpoint never sees an empty or an old list.
    assert message in log, log
    assert events == [] or all("id" not in e for e in events)


def test_the_datasource_reads_the_three_agendas_in_one_query_from_open_data_bcn():
    source = yaml.safe_load((BARCELONA / "barcelona-datasource-agenda.yaml").read_text())
    url = urlsplit(source["spec"]["http"]["url"])
    assert (url.scheme, url.netloc, url.path) == (
        "https", "opendata-ajuntament.barcelona.cat", "/data/api/3/action/datastore_search_sql")
    sql = parse_qs(url.query)["sql"][0]
    for resource in ("877ccf66-9106-4ae2-be51-95a9f6469e4c", "3abb2414-1ee0-446e-9c25-380e938adb73",
                     "ab2d47b7-8493-4ed5-9f63-49ed116135f9"):
        assert f'"{resource}"' in sql
    assert sql.startswith("SELECT DISTINCT ON (id) ") and "end_date >= now() - interval '1 day'" in sql
    # Read only: one SELECT, no statement after it.
    assert ";" not in sql and not any(w in sql.upper() for w in ("INSERT ", "UPDATE ", "DELETE ", "DROP "))


def test_the_pipeline_runs_daily_through_the_one_door_and_the_endpoint_publishes_events_only():
    pipeline = yaml.safe_load((BARCELONA / "barcelona-pipeline-agenda.yaml").read_text())["spec"]
    assert pipeline["period"] == "24h" and pipeline["output"] == {"type": "Event", "mode": "upsert"}
    assert pipeline["targetEndpoint"] == "urn:ngsi-ld:Endpoint:barcelona.cat:barcelona:barcelona"
    endpoint = yaml.safe_load((BARCELONA / "barcelona-endpoint-events.yaml").read_text())["spec"]
    assert endpoint["policyRef"] == "urn:ngsi-ld:Policy:barcelona.cat:barcelona:public-events"
    assert endpoint["publish"]["ckan"]["instanceRef"] == {"kind": "CkanInstance", "name": "barcelona"}
    assert {"ngsi-ld", "csv", "ogc-features", "odata"} <= set(endpoint["enabledRepresentations"])
    policy = yaml.safe_load((BARCELONA / "barcelona-policy-public-events.yaml").read_text())["spec"]
    assert policy["assignee"] == {"kind": "role", "id": "public"}
    assert [e["type"] for rule in policy["information"] for e in rule["entities"]] == ["Event"]
    assert not {"upsertBatch", "createBatch", "deleteBatch", "createEntity"} & set(policy["operations"])


@requires_docker
def test_one_place_within_20_m_is_one_event_and_each_event_expires_by_itself():
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    base = answer()["result"]["records"][1]
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()

    def row(rid, lat, name="Mercat de prova", ends="2027-01-04"):
        return dict(base, id=rid, name=name, lat=str(lat), lon="2.17335", ends=ends)
    # 41.38004 and 41.38013 lie 10 m apart on either side of a 0.0001-degree grid line; 41.38049
    # lies 50 m from the first; the last activity ends today.
    events, log, code = run(answer(records=[
        row("11", 41.38004), row("12", 41.38013), row("13", 41.38049),
        dict(row("14", 41.39, name="Taller d'avui", ends=today.isoformat()), starts=today.isoformat())]))
    assert code == 0, log
    by_id = {e["id"].rsplit(":", 1)[1]: e for e in events}
    assert len({"11", "12"} & set(by_id)) == 1 and {"13", "14"} <= set(by_id), sorted(by_id)
    assert '{\\"duplicate\\":1}' in log, log
    now = datetime.now(timezone.utc)
    for event in events:
        expires = datetime.strptime(event["expiresAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert now < expires <= now + timedelta(days=3, minutes=1), event
    midnight = datetime.combine(today + timedelta(days=1), datetime.min.time(), ZoneInfo("Europe/Madrid"))
    assert by_id["14"]["expiresAt"] == midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
