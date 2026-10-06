"""Every Žilina mapping over a recorded answer of the real feed (T-3138, PL-03, PL-64).

The committed Bloblang runs in the pinned Bento over documents recorded on 2026-10-06 from the
URL each `DataSource` declares (fixtures/zilina), so a mapping checked here is a mapping that ran.
The empty-read guard every stream starts with is checked the same way: an answer with nothing in
it fails the run instead of writing nothing as if the city had emptied.
"""

import http.server
import json
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-zilina-pipelines")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/zilina"
FIXTURES = Path(__file__).resolve().parent / "fixtures/zilina"
DOMAIN = "zilina.sk"
CITY = "SK031B517402"


def pipelines(prefix: str) -> dict[str, dict]:
    """Every pipeline manifest of the seed whose DataSource name starts with `prefix`."""
    found = {}
    for path in sorted(SEED.glob("zilina-pipeline-*.yaml")):
        if path.name.endswith("-bento.yaml"):
            continue
        manifest = yaml.safe_load(path.read_text())
        source = manifest["spec"]["source"]["dataSourceRef"]["name"]
        if source.startswith(prefix):
            found[manifest["metadata"]["name"]] = {"source": source, "manifest": manifest,
                                                   "bento": path.with_name(path.stem + "-bento.yaml")}
    return found


CUBES = pipelines("susr-")
STATIONS = pipelines("eea-")


def run(pipeline: dict, space: str) -> list[dict]:
    suffix = ".parquet" if pipeline["source"].startswith("eea-") else ".json"
    document = (FIXTURES / (pipeline["source"] + suffix)).read_bytes()
    return open_data.run(pipeline["bento"], document, space, DOMAIN)


@pytest.fixture(scope="module")
def cubes():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(p, "zilina-mesto") for name, p in CUBES.items()}


@pytest.fixture(scope="module")
def stations():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(p, "zilina-verejne") for name, p in STATIONS.items()}


def test_every_inventoried_source_has_its_pipeline():
    assert len(CUBES) == 16 and len(STATIONS) == 5
    for p in [*CUBES.values(), *STATIONS.values()]:
        spec = p["manifest"]["spec"]
        assert spec["targetEndpoint"].startswith("urn:ngsi-ld:Endpoint:zilina.sk:")
        assert spec["schedule"], "every stream runs on a schedule"
        assert (SEED / f"zilina-datasource-{p['manifest']['metadata']['name']}.yaml").is_file()


def test_every_stream_starts_with_the_empty_read_guard():
    for p in [*CUBES.values(), *STATIONS.values()]:
        assert "throw(" in p["bento"].read_text(), p["bento"].name


@requires_docker
def test_every_cube_cell_becomes_one_observation_of_the_city(cubes):
    schema = SEED / "statistical-observation.v1.schema.json"
    for name, entities in cubes.items():
        source = json.loads((FIXTURES / (CUBES[name]["source"] + ".json")).read_text())
        cells = [v for v in (source["value"] if isinstance(source["value"], list) else source["value"].values()) if v is not None]
        assert len(entities) == len(cells), name
        ids = [e["id"] for e in entities]
        assert len(set(ids)) == len(ids), f"{name}: two cells share an id"
        for entity in entities[:50]:
            assert entity["type"] == "StatisticalObservation"
            assert entity["id"].split(":")[3:5] == [DOMAIN, "zilina-mesto"]
            assert entity["refArea"]["value"] == CITY, name
            assert not open_data.schema_errors(schema, entity), (name, open_data.schema_errors(schema, entity))


@requires_docker
def test_the_population_of_the_city_is_the_one_ŠÚ_SR_publishes(cubes):
    end_of_quarter = {e["id"]: e for e in cubes["obyvatelstvo"]}[
        f"urn:ngsi-ld:StatisticalObservation:{DOMAIN}:zilina-mesto:om7101qr-{CITY}-2026Q2-IN010115-SPOLU"]
    assert end_of_quarter["value"]["value"] == 79617


@requires_docker
def test_the_station_is_one_entity_and_each_pollutant_its_own_reading(stations):
    expected = {
        "ovzdusie-pm10": ("pm10", 32.341, "GQ", "2026-10-06T18:00:00Z"),
        "ovzdusie-pm25": ("pm25", 15.417, "GQ", "2026-10-06T18:00:00Z"),
        "ovzdusie-no2": ("no2", 28.1313, "GQ", "2026-10-06T18:00:00Z"),
        # Every ozone hour of the recording carries validity 4, EEA's valid ozone reading.
        "ovzdusie-o3": ("o3", 11.8076, "GQ", "2026-10-05T17:00:00Z"),
        # The file's Unit column says mg.m-3: UN/CEFACT GP, never µg/m³.
        "ovzdusie-co": ("co", 0.63452, "GP", "2026-10-06T18:00:00Z"),
    }
    schema = SEED / "zilina-verejne.v1.schema.json"
    for name, (attribute, value, unit, at) in expected.items():
        [station] = stations[name]
        assert station["id"] == f"urn:ngsi-ld:AirQualityObserved:{DOMAIN}:zilina-verejne:eea-SK0020A"
        reading = station[attribute]
        assert (reading["value"], reading["unitCode"], reading["observedAt"]) == (value, unit, at), name
        assert station["location"]["value"] == {"type": "Point", "coordinates": [18.771215, 49.211447]}
        others = {"pm10", "pm25", "no2", "o3", "co"} - {attribute}
        assert not others & set(station), f"{name} writes only its own pollutant"
        assert not open_data.schema_errors(schema, station), open_data.schema_errors(schema, station)


def guard(path: Path) -> str:
    return next(step["mapping"] for step in yaml.safe_load(path.read_text())["pipeline"]["processors"]
                if "mapping" in step and "throw(" in step["mapping"])


def blobl(mapping: str, document: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "run", "--rm", "-i", BENTO, "blobl", mapping],
                          input=document, capture_output=True, text=True, timeout=120)


@requires_docker
def test_an_empty_cube_answer_fails_the_run_and_a_full_one_passes():
    mapping = guard(CUBES["obyvatelstvo"]["bento"])
    empty = blobl(mapping, json.dumps({"value": [], "id": [], "size": []}) + "\n")
    assert "the cube answered no cell" in empty.stdout + empty.stderr
    refused = blobl(mapping, json.dumps({"status": 400, "status_message": "Bad number of dimension cubes"}) + "\n")
    assert "Bad number of dimension cubes" in refused.stdout + refused.stderr
    full = blobl(mapping, json.dumps({"value": [1]}) + "\n")
    assert '"value":[1]' in full.stdout.replace(" ", ""), full.stdout + full.stderr


@requires_docker
def test_an_empty_station_file_fails_the_run():
    mapping = guard(STATIONS["ovzdusie-pm10"]["bento"])
    empty = blobl(mapping, "[]\n")
    assert "the station file holds no record" in empty.stdout + empty.stderr


DREPO = SEED / "zilina-pipeline-drepo-bento.yaml"
DREPO_HOST = "https://dspace.uniza.sk"


class Library(http.server.BaseHTTPRequestHandler):
    """DREPO's search API over the recorded pages: the first three, cut to the fields the mapping
    reads and with the page count set to three (the real library has fourteen)."""

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        page = FIXTURES / f"drepo-page{query.get('page', ['0'])[0]}.json"
        if not page.is_file() or query.get("size") != ["100"]:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(page.read_bytes())

    def log_message(self, *_):
        pass


def drepo(document: bytes) -> subprocess.CompletedProcess:
    """The drepo mapping over `document`, its page requests answered by `Library` on the host."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Library)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        text = DREPO.read_text().replace(DREPO_HOST, f"http://127.0.0.1:{server.server_port}")
        config = {
            "input": {"stdin": {"scanner": {"to_the_end": {}}}},
            "pipeline": yaml.safe_load(text)["pipeline"],
            # The runner's shared egress limit (pipeline-runner/streams/resources.yaml).
            "rate_limit_resources": [{"label": "pipeline_egress", "local": {"count": 100, "interval": "1s"}}],
            "output": {"stdout": {"codec": "all-bytes"}},
            "logger": {"level": "error"},
        }
        return subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "host", "-e", f"JC_ORG_DOMAIN={DOMAIN}",
             "-e", "JC_SPACE=zilina-uniza", "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh",
             BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
            input=document, capture_output=True, timeout=120,
        )
    finally:
        server.shutdown()


def recorded_items() -> list[dict]:
    return [o["_embedded"]["indexableObject"] for p in range(3)
            for o in json.loads((FIXTURES / f"drepo-page{p}.json").read_text())["_embedded"]["searchResult"]["_embedded"]["objects"]]


@requires_docker
def test_every_page_is_read_and_only_the_openly_licensed_works_enter():
    result = drepo((FIXTURES / "drepo-page0.json").read_bytes())
    assert result.returncode == 0, result.stderr.decode()
    works = json.loads(result.stdout)
    items = recorded_items()
    open_ = [i for i in items if i["metadata"].get("dc.rights.uri")]
    assert len(works) == len(open_) == 251, "every open item of all three pages, and nothing else"
    by_id = {w["id"]: w for w in works}
    assert len(by_id) == len(works)
    schema = SEED / "zilina-uniza.v1.schema.json"
    for work in works:
        assert work["id"].split(":")[3:5] == [DOMAIN, "zilina-uniza"]
        assert work["license"]["value"] == "http://creativecommons.org/licenses/by/4.0/"
        assert not open_data.schema_errors(schema, work), (work["id"], open_data.schema_errors(schema, work))
        assert not {"author", "creator", "contributor"} & set(work)
    first = by_id[f"urn:ngsi-ld:CreativeWork:{DOMAIN}:zilina-uniza:hdluniza-936"]
    assert first["name"]["languageMap"] == {"sk": "Accuracy of digital terrain model on forest roads using airborne LIDAR and UAV point clouds"}
    assert (first["workType"]["value"], first["yearPublished"]["value"]) == ("Conference paper", 2023)
    assert first["url"]["value"] == "http://drepo.uniza.sk/handle/hdluniza/936"
    # No author name of any recorded item reaches the output, in any attribute.
    assert "Kardoš" not in result.stdout.decode()


@requires_docker
def test_a_title_of_no_stated_language_is_written_as_none():
    item = next(i for i in recorded_items() if i["metadata"].get("dc.rights.uri")
                and i["metadata"].get("dc.language.iso", [{}])[0].get("value") in (None, "other"))
    page = {"_embedded": {"searchResult": {"page": {"totalPages": 1, "totalElements": 1},
                                           "_embedded": {"objects": [{"_embedded": {"indexableObject": item}}]}}}}
    result = drepo(json.dumps(page).encode())
    [work] = json.loads(result.stdout)
    assert list(work["name"]["languageMap"]) == ["@none"]


@requires_docker
def test_a_closed_licence_and_a_withdrawn_item_stay_out():
    item = next(i for i in recorded_items() if i["metadata"].get("dc.rights.uri"))
    nc = json.loads(json.dumps(item))
    nc["metadata"]["dc.rights.uri"] = [{"value": "http://creativecommons.org/licenses/by-nc/4.0/"}]
    withdrawn = {**item, "withdrawn": True}
    sa = json.loads(json.dumps(item))
    sa["handle"] = "hdluniza/sa"
    sa["metadata"]["dc.rights.uri"] = [{"value": "https://creativecommons.org/licenses/by-sa/4.0/"}]
    objects = [{"_embedded": {"indexableObject": i}} for i in (nc, withdrawn, sa)]
    page = {"_embedded": {"searchResult": {"page": {"totalPages": 1, "totalElements": 3}, "_embedded": {"objects": objects}}}}
    result = drepo(json.dumps(page).encode())
    assert [w["id"].rsplit(":", 1)[1] for w in json.loads(result.stdout)] == ["hdluniza-sa"]


@requires_docker
def test_an_empty_library_and_a_missing_page_fail_the_run():
    empty = drepo(json.dumps({"_embedded": {"searchResult": {"page": {"totalPages": 0, "totalElements": 0}}}}).encode())
    assert b"the library answered no item" in empty.stdout + empty.stderr
    page = json.loads((FIXTURES / "drepo-page0.json").read_text())
    page["_embedded"]["searchResult"]["page"]["totalPages"] = 4  # page 3 answers 404
    missing = drepo(json.dumps(page).encode())
    assert b"page 3 did not come" in missing.stdout + missing.stderr
