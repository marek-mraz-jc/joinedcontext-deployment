"""Every upcoming Linked Events event becomes an SDM Event, paged and checked (T-5257, PL-03).

Bento runs the committed mapping over a page recorded from the register on 2026-10-22 (five
events with their places and keywords: `fixtures/helsinki/linked-events/upcoming-page.json`)
and five rows the test made from them: a point in Tampere, a swapped longitude and latitude, a
start year typed as 0026, a place with no position and an event listed twice. The calls to the
register are the cut: the page the DataSource read stands in for the first, and the paging test
answers each further page itself. Without a container runtime the Bento cases skip.
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-helsinki-open-data")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
MAPPING = HELSINKI / "helsinki-pipeline-events-bento.yaml"
FIXTURE = Path(__file__).resolve().parent / "fixtures/helsinki/linked-events/upcoming-page.json"
URN = "urn:ngsi-ld:{}:hel.fi:helsinki:{}"


def processors(first: str, page: str) -> list[dict]:
    """The mapping with its mode fixed by `first` (the step that reads the clock) and every
    request to the register answered by the mapping `page`."""
    steps = yaml.safe_load(MAPPING.read_text())["pipeline"]["processors"]
    assert "now()" in steps[1]["mapping"], "the second step chooses the sweep by the clock"
    steps[1] = {"mapping": first}
    for step in steps:
        if "branch" in step:
            assert step["branch"]["processors"][-1]["http"]["url"].startswith("https://api.hel.fi/linkedevents/v1/event/?")
            step["branch"]["processors"] = [{"mapping": page}]
    return steps


def run(document: bytes, first: str, page: str = "root = {}") -> tuple[list[dict], str]:
    config = {"input": {"stdin": {"scanner": {"to_the_end": {}}}},
              "pipeline": {"processors": processors(first, page)},
              "output": {"stdout": {"codec": "lines"}}, "logger": {"level": "info", "format": "logfmt"}}
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO,
         "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=document, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode()
    pages = [json.loads(line) for line in result.stdout.decode().splitlines() if line.strip()]
    return [e for page in pages for e in page], result.stderr.decode()


FULL = 'root = { "query": "q", "first": this }'


@requires_docker
def test_the_recorded_page_maps_to_valid_events_and_drops_each_bad_row_by_reason():
    events, log = run(FIXTURE.read_bytes(), FULL)
    by_id = {e["id"]: e for e in events}
    # The register's own defect: its first upcoming event starts in "0026-09-23", so it is dropped
    # as a start year out of range, beside the test's own bad rows.
    assert sorted(by_id) == sorted(URN.format("Event", i) for i in (
        "hkm-3466", "helsinki-agp5dhl25y", "helsinki-afzapzc5sq", "helsinki-agpg4hzhzq"))
    assert 'dropped by reason {\\"duplicate\\":1,\\"no position\\":1,\\"outside Helsinki\\":2,\\"start year out of range\\":2}' in log, log
    for entity in events:
        assert not open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity), entity
        errors = [e for e in open_data.sdm_errors("dataModel.TourismDestinations/Event", entity)
                  if not e.startswith(("eventStatus", "refPointOfInterest"))]
        assert not errors, (entity["id"], errors)
    dance = by_id[URN.format("Event", "helsinki-agpg4hzhzq")]
    assert dance["refPointOfInterest"] == {"type": "Relationship", "object": URN.format("PointOfInterest", "servicemap-48547")}
    assert dance["thematic"]["value"][0] == "dance (performing arts)"
    assert dance["isAccessibleForFree"]["value"] is True
    assert "webSite" not in dance, "an empty info_url is no website"
    assert "dataProvider" not in dance, "a publisher that is no organization id is dropped"
    # A sub-event names its recurring parent by the parent's own URN.
    assert dance["superEvent"]["object"] == URN.format("Event", "helsinki-agpg4hzprq")
    museum = by_id[URN.format("Event", "hkm-3466")]
    assert museum["webSite"]["value"] == "https://www.helsinginkaupunginmuseo.fi/nayttelyt/lasten-kaupunki/"
    assert museum["thematic"]["value"][0] == "everyday"
    # The publisher is the source a per-source count reads back (T-5666).
    assert museum["dataProvider"] == {"type": "Property", "value": "ahjo:u4804001010"}


@requires_docker
def test_an_empty_register_fails_the_run_instead_of_writing_nothing():
    config = {"input": {"stdin": {"scanner": {"to_the_end": {}}}},
              "pipeline": {"processors": processors(FULL, "root = {}")[:1]},
              "output": {"stdout": {"codec": "lines"}}, "logger": {"level": "error"}}
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO,
         "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=b'{"meta": {"count": 0}, "data": []}', capture_output=True, timeout=120)
    # A thrown mapping error leaves the message flagged; the runner's output refuses a flagged
    # message, so the endpoint never sees an empty list.
    assert b"Linked Events lists no upcoming event" in result.stderr + result.stdout


@requires_docker
def test_every_page_of_the_sweep_is_read_once_and_written_on_its_own():
    page = json.loads(FIXTURE.read_text())
    one = page["data"][1]
    first = dict(page, meta={"count": 250}, data=[one])
    # Each further page answers with the event renamed after the query that asked for it.
    answer = ('root.data = [%s.assign({"id": "helsinki:p" + @query.re_find_all_submatch("page=([0-9]+)").index(0).index(1)})]'
              % json.dumps(one))
    events, _ = run(json.dumps(first).encode(), FULL, answer)
    assert [e["id"].rsplit(":", 1)[1] for e in events] == ["hkm-3466", "helsinki-p2", "helsinki-p3"]


@requires_docker
def test_the_incremental_run_reads_its_own_first_page():
    page = json.loads(FIXTURE.read_text())
    one = page["data"][1]
    incremental = 'root = { "query": "q&last_modified_since=2026-10-22T17:00:00Z", "first": null }'
    answer = ('root = if @query.contains("last_modified_since") { {"meta": {"count": 1}, "data": [%s]} } else { throw("unasked") }'
              % json.dumps(one))
    events, _ = run(FIXTURE.read_bytes(), incremental, answer)
    assert [e["id"] for e in events] == [URN.format("Event", "hkm-3466")]


def test_the_datasource_reads_the_upcoming_list_with_places_and_keywords():
    source = yaml.safe_load((HELSINKI / "helsinki-datasource-events.yaml").read_text())
    url = source["spec"]["http"]["url"]
    assert url.startswith("https://api.hel.fi/linkedevents/v1/event/?")
    assert "include=location,keywords" in url and "start=today" in url and "end=" not in url
