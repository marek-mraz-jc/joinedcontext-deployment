"""The city's traffic and cycle counters become TrafficFlowObserved (T-5253, PL-03, DM-01).

Bento runs the committed cycle-counters and traffic-counters mappings over answers of the city's
traffic measurement API (lidotiku.api.hel.fi) recorded on 2026-10-22 (`fixtures/helsinki/lidotiku`).
The cycle stations are real ones with what the API gets wrong: a station at 0,0, a clone, the
Lauttasaari bridge station listed twice, a pedestrian-only station and one silent since 2024; two
records were edited, one to lose its position and one to swap its coordinates, and Baana got one
negative count and one unknown direction. The LAM stations are real too; one was moved to
Kauniainen, one day's count of HEL510 doubled with a negative value and an unknown direction, and
HEL409's southbound speed raised to 400 km/h.

The mappings count yesterday in Helsinki time, so every recorded time is moved by whole days to
make 2026-10-21 yesterday, wall clock and UTC offset as Helsinki has them on the new date. The calls
to the API are the cut: each branch is answered from the recording by counter id.

Without a container runtime the Bento cases skip.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import open_data
import pytest
import yaml

pytestmark = pytest.mark.xdist_group("docker-helsinki-traffic-counters")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
FIXTURES = Path(__file__).resolve().parent / "fixtures/helsinki/lidotiku"
BENTO = "ghcr.io/warpstreamlabs/bento:1.22.0@sha256:ef674bebae45793c982c350d8f37c2c7661133c1dc65a5517fb977b36dc09841"
URN = "urn:ngsi-ld:TrafficFlowObserved:hel.fi:helsinki:"
TZ = ZoneInfo("Europe/Helsinki")
RECORDED_YESTERDAY = date(2026, 10, 21)
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})([+-]\d{2}:\d{2})")


def moved(text: str) -> str:
    """The recording with every time moved so that 2026-10-21 is yesterday in Helsinki."""
    shift = (datetime.now(TZ).date() - timedelta(days=1)) - RECORDED_YESTERDAY

    def one(m: re.Match) -> str:
        local = datetime.fromisoformat(f"{m[1]}T{m[2]}") + shift
        return local.replace(tzinfo=TZ).isoformat()

    return STAMP.sub(one, text)


def run(mapping: str, document: str, answers: list[dict]) -> tuple[list[dict], list[str]]:
    """The mapping with its n-th branch answered from answers[n] by counter id; the entities it
    writes and the WARN lines it logs."""
    steps, n = [], 0
    for step in yaml.safe_load((HELSINKI / mapping).read_text())["pipeline"]["processors"]:
        if "branch" in step:
            branch = dict(step["branch"])
            branch["processors"] = [{"mapping": f'root = {json.dumps(answers[n])}.get(@counter).or({{"failed": true}})'}]
            step, n = {"branch": branch}, n + 1
        steps.append(step)
    config = {"input": {"stdin": {"scanner": {"to_the_end": {}}}}, "pipeline": {"processors": steps},
              "output": {"stdout": {"codec": "lines"}}, "logger": {"level": "warn", "format": "json"}}
    folder = tempfile.mkdtemp()
    os.chmod(folder, 0o755)
    (Path(folder) / "c.json").write_text(json.dumps(config))
    os.chmod(Path(folder) / "c.json", 0o644)
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
             "-v", f"{folder}:/cfg:ro", BENTO, "-c", "/cfg/c.json"],
            input=document, capture_output=True, text=True, timeout=180, check=False,
        )
    finally:
        shutil.rmtree(folder)
    # Bento logs to stderr when its output is stdout.
    logs = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert result.returncode == 0 and all(log["level"] == "warning" for log in logs), result.stderr
    entities = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert all(e["type"] == "TrafficFlowObserved" for e in entities)
    return entities, [log["msg"] for log in logs]


def rows(name: str) -> dict:
    return {k: {"rows": v} for k, v in json.loads(moved((FIXTURES / name).read_text())).items()}


@pytest.fixture(scope="module")
def cycle():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime, so Bento cannot run the mapping")
    entities, warnings = run("helsinki-pipeline-cycle-counters-bento.yaml",
                             moved((FIXTURES / "cycle-counters.json").read_text()), [rows("cycle-observations.json")])
    return {e["id"].removeprefix(URN): e for e in entities}, warnings


@pytest.fixture(scope="module")
def traffic():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime, so Bento cannot run the mapping")
    entities, warnings = run("helsinki-pipeline-traffic-counters-bento.yaml",
                             moved((FIXTURES / "traffic-counters.json").read_text()),
                             [rows("traffic-counts.json"), rows("traffic-speeds.json")])
    return {e["id"].removeprefix(URN): e for e in entities}, warnings


def test_only_working_bicycle_stations_in_helsinki_are_written(cycle):
    entities, _ = cycle
    assert sorted(entities) == ["cycle-100016107", "cycle-100020820", "cycle-300048239"]


def test_every_left_out_station_is_counted_with_its_reason(cycle):
    _, warnings = cycle
    assert 'cycle counters left out: {"duplicate":1,"noLocation":1,"outsideHelsinki":1,"spareOrClone":1,"swappedCoordinates":1}' in warnings
    assert "cycle counter 100016670: left out stale" in warnings
    # Forumin tunneli counts pedestrians only.
    assert "cycle counter 100016673: left out noBicycleCountForTheDay" in warnings


def test_a_day_is_the_sum_of_its_bicycle_rows_and_bad_rows_are_counted(cycle):
    entities, warnings = cycle
    # Lauttasaari bridge writes a row a quarter hour, labelled 3600 s; the day is their sum.
    assert entities["cycle-100016107"]["intensity"]["value"] == 1963
    assert entities["cycle-100020820"]["intensity"]["value"] == 209
    # Baana keeps its real total: the negative row and the unknown direction are left out.
    assert entities["cycle-300048239"]["intensity"]["value"] == 4124
    assert 'cycle counter 300048239: left out {"outOfRange":1,"unknownDirection":1}' in warnings


def test_an_observation_carries_the_day_its_place_and_the_smart_data_model(cycle):
    entities, _ = cycle
    baana = entities["cycle-300048239"]
    day = datetime.now(TZ).date() - timedelta(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    utc = "%Y-%m-%dT%H:%M:%SZ"
    assert baana["dateObservedFrom"]["value"] == start.astimezone(ZoneInfo("UTC")).strftime(utc)
    assert baana["dateObserved"]["value"] == baana["dateObservedTo"]["value"] == end.astimezone(ZoneInfo("UTC")).strftime(utc)
    assert baana["intensity"]["observedAt"] == baana["dateObserved"]["value"]
    assert baana["vehicleType"]["value"] == "bicycle"
    assert baana["name"]["languageMap"] == {"fi": "Baana"}
    assert baana["location"]["value"] == {"type": "Point", "coordinates": [24.92606, 60.16933]}
    assert "trafficDirection" not in baana
    for entity in entities.values():
        assert not open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity), entity["id"]
        assert not open_data.sdm_errors("dataModel.Transportation/TrafficFlowObserved", entity), entity["id"]


def test_lam_stations_write_each_direction_with_its_speed(traffic):
    entities, _ = traffic
    assert sorted(entities) == ["lam-4667-north", "lam-4667-south", "lam-4668-north", "lam-4668-south", "lam-5595"]
    assert entities["lam-4667-north"]["intensity"]["value"] == 9967
    assert entities["lam-4667-north"]["trafficDirection"]["value"] == "north"
    assert entities["lam-4667-north"]["averageVehicleSpeed"]["value"] == 34.2
    assert entities["lam-4667-north"]["averageVehicleSpeed"]["unitCode"] == "KMH"
    # 400 km/h is a broken reading: the count stays, the speed goes.
    assert entities["lam-4667-south"]["intensity"]["value"] == 9950
    assert "averageVehicleSpeed" not in entities["lam-4667-south"]
    # HEL510 measures no speed (its mean is 0): no speed rather than a standing queue.
    assert "averageVehicleSpeed" not in entities["lam-4668-north"]
    assert entities["lam-4668-south"]["intensity"]["value"] == 9477
    # HEL116 counts bicycles, its direction "Pyörämittaus".
    assert entities["lam-5595"]["vehicleType"]["value"] == "bicycle"
    assert "trafficDirection" not in entities["lam-5595"]
    for entity in entities.values():
        assert not open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity), entity["id"]
        assert not open_data.sdm_errors("dataModel.Transportation/TrafficFlowObserved", entity), entity["id"]


def test_lam_left_out_stations_and_rows_are_counted(traffic):
    _, warnings = traffic
    assert 'traffic counters left out: {"outsideHelsinki":1}' in warnings
    assert "traffic counter 4705: left out stale" in warnings
    assert "traffic counter 4702: left out stale" in warnings
    assert 'traffic counter 4668: left out {"outOfRange":1,"unknownDirection":1}' in warnings
    assert 'traffic counter 4667: left out {"speedOutOfRange":1}' in warnings


def test_a_run_with_no_station_in_helsinki_fails_instead_of_writing_nothing():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime, so Bento cannot run the mapping")
    document = json.loads((FIXTURES / "traffic-counters.json").read_text())
    document["results"]["features"] = [f for f in document["results"]["features"] if f["properties"]["id"] == 4703]
    with pytest.raises(AssertionError, match="no LAM station of the answer lies in Helsinki"):
        run("helsinki-pipeline-traffic-counters-bento.yaml", json.dumps(document), [{}, {}])


def test_both_pipelines_run_daily_into_the_space_and_publish_through_their_own_policy():
    for name, prefix in (("cycle", "cycle"), ("traffic", "lam")):
        pipeline = yaml.safe_load((HELSINKI / f"helsinki-pipeline-{name}-counters.yaml").read_text())["spec"]
        assert pipeline["period"] == "24h" and pipeline["output"]["type"] == "TrafficFlowObserved"
        source = yaml.safe_load((HELSINKI / f"helsinki-datasource-{name}-counters.yaml").read_text())["spec"]["http"]
        assert source["url"].startswith("https://lidotiku.api.hel.fi/api/counters/?source=")
        # The mapping fetches the same host only, for one station at a time.
        hosts = set(re.findall(r"https://([^/]+)/", (HELSINKI / f"helsinki-pipeline-{name}-counters-bento.yaml").read_text()))
        assert hosts == {"lidotiku.api.hel.fi"}
        policy = yaml.safe_load((HELSINKI / f"helsinki-policy-public-{name}-counts.yaml").read_text())["spec"]
        (grant,) = policy["information"][0]["entities"]
        assert re.match(grant["idPattern"], f"{URN}{prefix}-4667-north")
        assert not re.match(grant["idPattern"], f"{URN}{'lam' if prefix == 'cycle' else 'cycle'}-4667-north")
        endpoint = yaml.safe_load((HELSINKI / f"helsinki-endpoint-{name}-counts.yaml").read_text())["spec"]
        assert endpoint["policyRef"].endswith(f":public-{name}-counts")
        assert endpoint["catalog"]["pipelineRef"]["name"] == f"{name}-counters"
        # The custom property is named in the catalogue description (T-5253 Done when).
        description = yaml.safe_load((HELSINKI / f"helsinki-endpoint-{name}-counts.yaml").read_text())["metadata"]["description"]
        assert all("trafficDirection" in text for text in description.values())
