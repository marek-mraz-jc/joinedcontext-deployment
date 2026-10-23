"""Open Data BCN transport into the space barcelona (T-5262).

Each committed mapping runs in the pinned Bento over files recorded from
opendata-ajuntament.barcelona.cat on 2026-10-22 (tests/fixtures/barcelona, cut to a few dozen
records, line endings as published). The section list the traffic pipeline reads itself comes
from a stand-in on this machine that answers from the same recording, or with a failure.
"""

import http.server
import json
import subprocess
import threading
from pathlib import Path
from typing import ClassVar

import open_data
import pytest
import yaml
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-barcelona-open-data")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/barcelona"
FIXTURES = ROOT / "tests/fixtures/barcelona"
RESOURCES = ROOT / "components/pipeline-runner/streams/resources.yaml"
SCHEMA = SEED / "barcelona.v1.schema.json"
HOST = "https://opendata-ajuntament.barcelona.cat"
# The state file was written at 22:10:56 Barcelona time, 20:10:56 UTC.
NOW = "2026-10-22T20:15:00Z"
URN = "urn:ngsi-ld:TrafficFlowObserved:barcelona.cat:barcelona:tram-{}"


class OpenDataBcn(http.server.BaseHTTPRequestHandler):
    """The section list as recorded, or `status` instead of it."""

    status: ClassVar[int] = 200
    body: ClassVar[bytes] = b""

    def do_GET(self):
        self.send_response(OpenDataBcn.status)
        self.send_header("Content-Type", "text/csv")
        self.end_headers()
        self.wfile.write(OpenDataBcn.body)

    def log_message(self, *_):
        pass


def bento(processors: list, document: bytes) -> tuple[list[dict], list[str]]:
    processors = [*processors, {"mapping": 'root = if errored() { {"__error": error()} } else { this }'}]
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        "pipeline": {"processors": processors},
        "rate_limit_resources": yaml.safe_load(RESOURCES.read_text())["rate_limit_resources"],
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "none"},
    }
    done = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "host", "-e", "JC_ORG_DOMAIN=barcelona.cat", "-e", "JC_SPACE=barcelona",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=document, capture_output=True, timeout=180, check=False,
    )
    assert done.returncode == 0, done.stderr.decode()
    entities, errors = [], []
    for line in done.stdout.decode().splitlines():
        if line.strip():
            message = json.loads(line)
            if isinstance(message, dict) and "__error" in message:
                errors.append(message["__error"])
            else:
                entities.append(message)
    return entities, errors


def traffic(document: bytes, sections: bytes | None = None, status: int = 200, now: str = NOW,
            counted: bool = False) -> tuple[list[dict], list[str]]:
    """The traffic-state mapping over `document` with its clock at `now`. With `counted`, the
    message the run logs (entities and the dropped counts) instead of the entities."""
    OpenDataBcn.status = status
    OpenDataBcn.body = (FIXTURES / "transit_relacio_trams.csv").read_bytes() if sections is None else sections
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OpenDataBcn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        text = (SEED / "barcelona-pipeline-traffic-state-bento.yaml").read_text()
        text = text.replace(f"{HOST}/data/", f"http://127.0.0.1:{server.server_port}/data/")
        text = text.replace("now()", f'"{now}".ts_parse("2006-01-02T15:04:05Z07:00")')
        processors = yaml.safe_load(text)["pipeline"]["processors"]
        if counted:
            steps = processors[0]["try"]
            processors = [{"try": steps[:steps.index(next(s for s in steps if "log" in s))]}]
        return bento(processors, document)
    finally:
        server.shutdown()


def recorded() -> bytes:
    return (FIXTURES / "traffic-state.dat").read_bytes()


def rows() -> list[list[str]]:
    return [line.strip().split("#") for line in recorded().decode().splitlines() if line.strip()]


@requires_docker
def test_every_recorded_section_with_a_line_is_a_valid_traffic_flow_observed():
    written, errors = traffic(recorded())
    assert errors == []
    # 36 lines, section 535 has no line in the section list (the city lists 526 of the 532).
    assert len(written) == 35
    codes = ["noData", "veryFluid", "fluid", "dense", "veryDense", "congestion", "closed"]
    by_id = {e["id"]: e for e in written}
    for section, _at, state, forecast in rows():
        if section == "535":
            assert URN.format(section) not in by_id
            continue
        entity = by_id[URN.format(section)]
        assert not open_data.schema_errors(SCHEMA, entity), entity
        assert entity["trafficState"]["value"] == codes[int(state)]
        assert entity["trafficStateForecast"]["value"] == codes[int(forecast)]
        assert entity["congested"]["value"] is (state in ("4", "5"))
        assert entity["dateObserved"]["value"] == "2026-10-22T20:10:56Z"
        assert entity["trafficState"]["observedAt"] == "2026-10-22T20:10:56Z"
        line = entity["location"]["value"]
        assert line["type"] == "LineString" and len(line["coordinates"]) >= 2
        assert all(2.04 <= lon <= 2.24 and 41.30 <= lat <= 41.48 for lon, lat in line["coordinates"])
    assert {e["trafficState"]["value"] for e in written} == set(codes)
    first = by_id[URN.format("1")]
    assert first["name"]["value"] == "Diagonal (Ronda de Dalt a Doctor Marañón)"
    assert first["location"]["value"]["coordinates"][0] == [2.11203535639414, 41.3841912394771]


@requires_docker
def test_an_out_of_area_line_a_code_out_of_range_and_a_duplicate_are_left_out_and_counted():
    sections = (FIXTURES / "transit_relacio_trams.csv").read_bytes().replace(
        b'"2.11203535639414,41.3841912394771,', b'"41.3841912394771,2.11203535639414,')  # section 1, lat/lon swapped
    lines = recorded().decode().splitlines()
    extra = ["2#20261022221056#9#1", "3#20261022221056#2#2", "x#y", "4#20261025221056#2#2"]
    document = "\r\n".join(lines + extra).encode()
    out, errors = traffic(document, sections, counted=True)
    assert errors == []
    assert out[0]["dropped"] == {
        "malformedLine": 1, "stateOutOfRange": 1, "timeInFuture": 1, "duplicateSection": 1,
        "sectionWithoutLine": 2, "lineMalformed": 0, "lineOutOfArea": 1,
    }
    ids = [e["id"] for e in out[0]["entities"]]
    assert URN.format("1") not in ids and len(ids) == len(set(ids)) == 34
    # The duplicate 3 is the second line: the first, as recorded, is kept.
    three = next(e for e in out[0]["entities"] if e["id"] == URN.format("3"))
    assert three["trafficState"]["value"] == ["noData", "veryFluid", "fluid", "dense", "veryDense", "congestion", "closed"][
        int(next(r for r in rows() if r[0] == "3")[2])]


@pytest.mark.parametrize("document, sections, status, now, reason", [
    (b"", None, 200, NOW, "names no section"),
    (b"<html>maintenance</html>", None, 200, NOW, "names no section"),
    (None, None, 200, "2026-10-22T20:30:00Z", "older than three 5-minute periods"),
    (None, None, 503, NOW, ""),
    (None, b"id;name\r\n1;x\r\n", 200, NOW, "Tram, Descripció, Coordenades"),
    (b" " * 262145, None, 200, NOW, "more than the 256 kB read"),
], ids=["empty", "html", "stale", "sections-503", "sections-columns", "oversize"])
@requires_docker
def test_an_empty_stale_or_broken_source_fails_the_run_and_writes_nothing(document, sections, status, now, reason):
    written, errors = traffic(recorded() if document is None else document, sections, status, now)
    assert written == []
    assert len(errors) == 1 and reason in errors[0], errors


def test_the_seed_reads_open_data_bcn_every_five_minutes_and_grants_only_the_added_types():
    source = yaml.safe_load((SEED / "barcelona-datasource-traffic-state.yaml").read_text())["spec"]["http"]
    assert source["url"].startswith(f"{HOST}/data/dataset/")
    pipeline = yaml.safe_load((SEED / "barcelona-pipeline-traffic-state.yaml").read_text())["spec"]
    assert pipeline["period"] == "300s"
    assert pipeline["output"] == {"type": "TrafficFlowObserved", "mode": "upsert"}
    # Every call the mapping makes itself goes to the same host.
    text = (SEED / "barcelona-pipeline-traffic-state-bento.yaml").read_text()
    urls = [line.split("url:", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("url:")]
    assert urls and all(u.startswith(f"{HOST}/data/dataset/") for u in urls)
    write = yaml.safe_load((SEED / "barcelona-policy-pipelines-write.yaml").read_text())["spec"]
    assert "deleteBatch" not in write["operations"]
    granted = {e["type"] for rule in write["information"] for e in rule["entities"]}
    model = yaml.safe_load((SEED / "barcelona-datamodel.yaml").read_text())["spec"]["classes"]
    assert granted == set(model) >= {"TrafficFlowObserved"}
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    for name in ("datasource-traffic-state", "pipeline-traffic-state", "pipeline-traffic-state-bento",
                 "endpoint-traffic", "policy-public-traffic"):
        assert f"barcelona-{name}.yaml" in index


PARKING = "urn:ngsi-ld:OnStreetParking:barcelona.cat:barcelona:bsm-{}-{}"


def parking(document: bytes, counted: bool = False) -> tuple[list[dict], list[str]]:
    processors = yaml.safe_load((SEED / "barcelona-pipeline-parking-sections-bento.yaml").read_text())["pipeline"]["processors"]
    if counted:
        steps = processors[0]["try"]
        processors = [{"try": steps[:steps.index(next(s for s in steps if "log" in s))]}]
    return bento(processors, document)


def pieces() -> list[dict]:
    text = (FIXTURES / "TRAMS.CSV").read_bytes().decode("utf-8-sig")
    return list(__import__("csv").DictReader(text.splitlines()))


@requires_docker
def test_every_recorded_parking_section_is_one_valid_on_street_parking_with_its_pieces():
    written, errors = parking((FIXTURES / "TRAMS.CSV").read_bytes())
    assert errors == []
    sections: dict[tuple[str, str], list[dict]] = {}
    for row in pieces():
        sections.setdefault((row["ID_TRAM"], row["TIPUS_TRAM"]), []).append(row)
    assert len(written) == len(sections) == 15
    by_id = {e["id"]: e for e in written}
    for (section, kind), rows in sections.items():
        entity = by_id[PARKING.format(section, kind.lower())]
        assert not open_data.schema_errors(SCHEMA, entity), entity
        assert entity["totalSpotNumber"]["value"] == int(rows[0]["PLACES"])
        assert entity["zoneCode"]["value"] == kind
        assert entity["tariffCode"]["value"] == f'{rows[0]["ID_TARIFA"]}/{rows[0]["ID_HORARIO"]}'
        assert entity["name"]["value"] == rows[0]["ADREÇA"]
        geometry = entity["location"]["value"]
        lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        # The pieces of a section, in no particular order.
        assert sorted(lines) == sorted([[float(r["LONGITUD_I"]), float(r["LATITUD_I"])], [float(r["LONGITUD_F"]), float(r["LATITUD_F"])]] for r in rows)
    assert {e["zoneCode"]["value"] for e in written} == {"AZL", "VM", "VR", "DUM", "BUS"}
    assert any(e["location"]["value"]["type"] == "MultiLineString" for e in written)
    blue = next(e for e in written if e["zoneCode"]["value"] == "AZL")
    assert blue["category"]["value"] == ["blueZone", "feeCharged"] and blue["allowedVehicleType"]["value"] == ["car"]


@requires_docker
def test_an_out_of_area_piece_places_out_of_range_and_a_duplicate_piece_are_left_out_and_counted():
    text = (FIXTURES / "TRAMS.CSV").read_bytes().decode("utf-8")
    lines = text.rstrip("\n").split("\n")
    first = lines[1].split(",")
    swapped = ",".join([first[0], *first[1:5], first[6], first[5], *first[7:]])  # lat/lon swapped
    negative = lines[2].rsplit(",", 1)[0] + ",-3"
    document = "\n".join([*lines, swapped, negative, lines[3], "999,x,,,,,,,,,,,,ZZZ,,,1"]).encode()
    out, errors = parking(document, counted=True)
    assert errors == []
    assert out[0]["dropped"] == {"malformedRow": 1, "placesOutOfRange": 1, "pieceOutOfArea": 1, "duplicatePiece": 1}
    assert len(out[0]["entities"]) == 15


@pytest.mark.parametrize("document, reason", [
    (b"", "does not have the columns"),
    (b"<html><body>503</body></html>", "does not have the columns"),
    ("﻿ID_TRAM,UTM_IX,UTM_FX,UTM_IY,UTM_FY,LATITUD_I,LONGITUD_I,LATITUD_F,LONGITUD_F,ID_TARIFA,ID_HORARIO,"
     "ID_TARIFA1,ID_HORARIO1,TIPUS_TRAM,ADREÇA,COLOR_RGB,PLACES\n".encode(), "does not have the columns"),
    ("﻿ID_TRAM,LATITUD_I,LONGITUD_I,LATITUD_F,LONGITUD_F,ID_TARIFA,ID_HORARIO,TIPUS_TRAM,ADREÇA,PLACES\n"
     "1,0,0,0,0,1,1,AZL,X,1\n".encode(), "names no section"),
], ids=["empty", "html", "header-only", "only-0-0"])
@requires_docker
def test_a_file_that_is_not_the_parking_csv_or_names_no_section_fails_the_run(document, reason):
    written, errors = parking(document)
    assert written == []
    assert len(errors) == 1 and reason in errors[0], errors


def test_the_seed_reads_the_parking_sections_daily_and_publishes_them():
    source = yaml.safe_load((SEED / "barcelona-datasource-parking-sections.yaml").read_text())["spec"]["http"]
    assert source["url"] == f"{HOST}/resources/bsm/TRAMS.CSV"
    pipeline = yaml.safe_load((SEED / "barcelona-pipeline-parking-sections.yaml").read_text())["spec"]
    assert pipeline["period"] == "24h" and pipeline["output"] == {"type": "OnStreetParking", "mode": "upsert"}
    # 10,596 sections of the 3.1 MB file need about 256 MB in Bento (docker --memory, 2026-10-22).
    assert pipeline["quotas"]["maxMemoryMb"] >= 256
    endpoint = yaml.safe_load((SEED / "barcelona-endpoint-parking.yaml").read_text())["spec"]
    assert endpoint["policyRef"].endswith(":public-parking") and "ckan" in endpoint["publish"]
    policy = yaml.safe_load((SEED / "barcelona-policy-public-parking.yaml").read_text())["spec"]
    assert [e["type"] for rule in policy["information"] for e in rule["entities"]] == ["OnStreetParking"]
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    for name in ("datasource-parking-sections", "pipeline-parking-sections", "pipeline-parking-sections-bento",
                 "endpoint-parking", "policy-public-parking"):
        assert f"barcelona-{name}.yaml" in index
