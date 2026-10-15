"""HSL's GTFS static feed in the Helsinki space (T-3890, PL-03, PL-72).

Bento runs each committed mapping over a 20-row cut of the member it reads from hsl.zip, fetched
on 2026-10-12 (`fixtures/helsinki/gtfs/`, CRLF as HSL writes it), with the member name the
archive read sets, and every entity it writes is checked against the space's generated JSON
Schema. The edge cases are rows of that cut edited in the one field they name.

Without a container runtime the Bento cases skip; the seed cases do not.
"""

import shutil
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-helsinki-open-data")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
FIXTURES = Path(__file__).resolve().parent / "fixtures/helsinki/gtfs"
URN = "urn:ngsi-ld:{}:hel.fi:helsinki:{}"

# pipeline -> (its DataSource file, the members it names, the type it declares)
PIPELINES = {
    "transit-stops": ("transit-stops", ["stops.txt"], "GtfsStop"),
    "gtfs-routes": ("gtfs-routes", ["agency.txt", "routes.txt"], "GtfsRoute"),
    "gtfs-shapes": ("gtfs-shapes", ["shapes.txt"], "GtfsShape"),
}


def member(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def run(pipeline: str, name: str, text: bytes | None = None) -> list[dict]:
    return open_data.run_all(HELSINKI / f"helsinki-pipeline-{pipeline}-bento.yaml",
                             member(name) if text is None else text, "helsinki",
                             metadata={"archive_filename": name})


def raw(pipeline: str, name: str, text: bytes) -> bytes:
    return open_data._bento(HELSINKI / f"helsinki-pipeline-{pipeline}-bento.yaml", text, "helsinki",
                            "hel.fi", "lines", {"archive_filename": name})


def by_id(entities: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in entities}


@pytest.fixture(scope="module")
def written():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {
        "stops": run("transit-stops", "stops.txt"),
        "agency": run("gtfs-routes", "agency.txt"),
        "routes": run("gtfs-routes", "routes.txt"),
        "shapes": run("gtfs-shapes", "shapes.txt"),
    }


@requires_docker
def test_every_entity_is_one_the_gateway_accepts_and_ids_are_unique(written):
    for name, entities in written.items():
        assert entities, name
        for entity in entities:
            assert not open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity), (name, entity["id"])
            assert entity["dataProvider"]["value"].startswith("Helsinki Region Transport (HSL)")
            assert entity["source"]["value"] == "https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip"
        assert len(by_id(entities)) == len(entities), name


@requires_docker
def test_a_station_is_a_station_and_its_platforms_name_it(written):
    stops = by_id(written["stops"])
    kamppi = stops[URN.format("GtfsStation", "1000001")]
    assert kamppi["name"]["languageMap"] == {"fi": "Kamppi (lähiliikenneterminaali)"}
    assert "hasStop" not in kamppi, "the model computes a station's platforms from them"
    assert "stopCode" not in kamppi
    for platform in ("1040271", "1040272"):
        assert stops[URN.format("GtfsStop", platform)]["hasParentStation"]["object"] == kamppi["id"]
    # A station GTFS lists no platform for is still a station.
    assert stops[URN.format("GtfsStation", "1000015")]["type"] == "GtfsStation"
    assert URN.format("GtfsStop", "1000001") not in stops


@requires_docker
def test_a_stop_says_what_serves_it_and_nothing_is_made_up(written):
    stops = by_id(written["stops"])
    alone = stops[URN.format("GtfsStop", "1010107")]
    assert "hasParentStation" not in alone
    assert alone["stopCode"]["value"] == "H2014" and alone["fareZone"]["value"] == "A"
    assert alone["wheelChairAccessible"]["value"] == "2"
    assert alone["location"]["value"] == {"type": "Point", "coordinates": [24.956946, 60.174167]}
    assert alone["page"]["value"] == "http://aikataulut.hsl.fi/pysakit/fi/1010107.html"
    modes = {stops[URN.format("GtfsStop", i)]["transportMode"]["value"] for i in ("1010107", "1010419", "4610505", "1030701")}
    assert modes == {"bus", "tram", "train", "ferry"}
    assert any(e["transportMode"]["value"] == "metro" for e in written["stops"] if e["type"] == "GtfsStop")
    # A stop beyond HSL's zones ("Ei HSL") carries no fare zone.
    beyond = [e for e in written["stops"] if e["type"] == "GtfsStop" and "fareZone" not in e]
    assert len(beyond) == 1


@requires_docker
def test_rows_the_mapping_cannot_place_are_left_out(written):
    ids = {e["id"].rsplit(":", 1)[1] for e in written["stops"]}
    assert "1040273" not in ids, "an entrance (location type 2) is no stop"
    assert "1010109" not in ids, "a stop without a latitude is not written somewhere wrong"
    assert not any("bad" in i for i in ids), "an id no URN can carry"
    # A parent that is a stop, not a station, is not linked.
    assert "hasParentStation" not in by_id(written["stops"])[URN.format("GtfsStop", "1010110")]
    assert len(written["stops"]) == 16 - 3


@requires_docker
def test_a_line_names_its_agency_and_its_basic_route_type(written):
    agency = written["agency"]
    assert [a["id"] for a in agency] == [URN.format("GtfsAgency", "HSL")]
    assert agency[0]["agencyName"]["value"] == "Helsingin seudun liikenne"
    assert agency[0]["timezone"]["value"] == "Europe/Helsinki"
    routes = by_id(written["routes"])
    assert len(routes) == 7
    tram = routes[URN.format("GtfsRoute", "1001")]
    assert tram["shortName"]["value"] == "1" and tram["routeType"]["value"] == "0"
    assert tram["operatedBy"]["object"] == agency[0]["id"]
    assert tram["name"]["languageMap"]["fi"].startswith("Eira")
    kinds = {i: (routes[URN.format("GtfsRoute", i)]["routeType"]["value"], routes[URN.format("GtfsRoute", i)]["transportMode"]["value"])
             for i in ("31M1", "1019", "3001I", "1040")}
    assert kinds == {"31M1": ("1", "metro"), "1019": ("4", "ferry"), "3001I": ("2", "train"), "1040": ("3", "bus")}
    # A line whose shape the cut does not hold is written all the same: nothing links the two.
    assert URN.format("GtfsRoute", "1009") in routes


@requires_docker
def test_a_shape_is_one_line_in_sequence_order(written):
    shapes = by_id(written["shapes"])
    assert set(shapes) == {URN.format("GtfsShape", "1001-5_20260831_1"), URN.format("GtfsShape", "1002_20260831_1")}
    one = shapes[URN.format("GtfsShape", "1001-5_20260831_1")]
    assert one["name"]["languageMap"] == {"fi": "1001 5_20260831_1"}
    assert one["location"]["value"]["type"] == "LineString"
    assert one["location"]["value"]["coordinates"][0] == [24.963295, 60.188027]
    assert len(one["location"]["value"]["coordinates"]) == 12 == len(one["distanceTravelled"]["value"])
    assert one["distanceTravelled"]["value"] == sorted(one["distanceTravelled"]["value"])


@requires_docker
def test_a_long_shape_keeps_about_200_points_and_its_last():
    head = b"shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence,shape_dist_traveled\r\n"
    rows = b"".join(b"L_1,60.%06d,24.900000,%d,%d.000\r\n" % (i, i, i) for i in range(1, 1001))
    (shape,) = run("gtfs-shapes", "shapes.txt", head + rows)
    line = shape["location"]["value"]["coordinates"]
    assert 200 <= len(line) <= 201
    assert line[0] == [24.9, 60.000001] and line[-1] == [24.9, 60.001]


@requires_docker
def test_a_shapes_file_the_mapping_cannot_read_writes_no_shape():
    text = member("shapes.txt")
    lines = text.split(b"\r\n")
    # Columns in another order, a shape's points apart, a shape not starting at 1: each fails.
    reordered = b"shape_id,shape_pt_lon,shape_pt_lat,shape_pt_sequence,shape_dist_traveled" + text[text.index(b"\r\n"):]
    apart = b"\r\n".join([lines[0], lines[1], lines[14], lines[2]] + lines[3:14] + lines[15:])
    no_start = b"\r\n".join([lines[0]] + lines[2:])
    for broken in (reordered, apart, no_start):
        assert b'"GtfsShape"' not in raw("gtfs-shapes", "shapes.txt", broken)


@requires_docker
def test_a_member_the_pipeline_does_not_read_and_an_empty_member_write_nothing():
    assert run("transit-stops", "routes.txt", member("stops.txt")) == []
    assert run("gtfs-shapes", "stops.txt", member("shapes.txt")) == []
    assert run("gtfs-routes", "stops.txt", member("routes.txt")) == []
    assert run("transit-stops", "stops.txt", member("stops.txt").split(b"\r\n")[0] + b"\r\n") == []
    assert run("gtfs-routes", "routes.txt", member("routes.txt").split(b"\r\n")[0] + b"\r\n") == []


def test_each_source_reads_only_its_named_members_of_the_zip_within_a_bound():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    model = yaml.safe_load((HELSINKI / "helsinki-datamodel.yaml").read_text())
    public = yaml.safe_load((HELSINKI / "helsinki-policy-public-all.yaml").read_text())
    readable = {e["type"] for rule in public["spec"]["information"] for e in rule["entities"]}
    for name, (source, members, kind) in PIPELINES.items():
        pipeline = yaml.safe_load((HELSINKI / f"helsinki-pipeline-{name}.yaml").read_text())
        datasource = yaml.safe_load((HELSINKI / f"helsinki-datasource-{source}.yaml").read_text())
        http = datasource["spec"]["http"]
        assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == datasource["metadata"]["name"]
        assert pipeline["spec"]["output"]["type"] == kind
        assert pipeline["spec"]["targetEndpoint"] == "urn:ngsi-ld:Endpoint:{orgDomain}:helsinki:helsinki-all"
        assert pipeline["spec"]["quotas"]["maxMemoryMb"] <= 256
        # Never the whole 79 MB archive: the named members by Range, each bounded (PL-72).
        assert http["url"] == "https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip"
        assert http.get("verb", "GET") == "GET" and "Range" not in http.get("headers", {})
        assert http["archive"] == {"format": "zip", "members": members, "maxBytes": http["archive"]["maxBytes"]}
        assert 0 < http["archive"]["maxBytes"] <= 256 * 1024 * 1024
        assert not {"stop_times.txt", "trips.txt", "trips2.txt", "translations.txt"} & set(members)
        for seeded in (f"helsinki-datasource-{source}.yaml", f"helsinki-pipeline-{name}.yaml",
                       f"helsinki-pipeline-{name}-bento.yaml"):
            assert seeded in index, seeded
    for kind in ("GtfsStop", "GtfsStation", "GtfsAgency", "GtfsRoute", "GtfsShape"):
        assert kind in model["spec"]["classes"] and kind in readable, kind
    # Paused until the runner can inflate shapes.txt under its bound (T-3953).
    assert yaml.safe_load((HELSINKI / "helsinki-pipeline-gtfs-shapes.yaml").read_text())["spec"]["enabled"] is False
    # The ArcGIS stop register this feed replaces is gone; its lines stay for TransitRoute.
    assert "hsl-stops.yaml" not in " ".join(str(v) for v in index.values())


@requires_docker
@pytest.mark.parametrize("pipeline, name", [("transit-stops", "stops.txt"), ("gtfs-routes", "routes.txt"), ("gtfs-routes", "agency.txt")])
def test_every_entity_written_leaves_its_urn_in_the_runners_gtfs_cache(pipeline, name, tmp_path):
    """T-4052: hsl-hfp-vehicles links a vehicle only to a line or stop whose URN the read left in
    the `gtfs` cache. Each entity goes out once, as its own message, and its URN is cached; a URN
    the read did not write is not."""
    mapping = yaml.safe_load((HELSINKI / f"helsinki-pipeline-{pipeline}-bento.yaml").read_text())
    probe = lambda key, field: {"branch": {  # noqa: E731
        "request_map": 'root = ""',
        "processors": [{"cache": {"resource": "gtfs", "operator": "exists", "key": key}}],
        "result_map": f"root.{field} = content().string()",
    }}
    mapping["pipeline"]["processors"] += [
        {"mapping": "meta urn = this.id\nroot = {\"id\": this.id}"},
        probe('${! meta("urn") }', "cached"),
        probe(URN.format("GtfsStop", "nope"), "stranger"),
    ]
    probed = tmp_path / "probed.yaml"
    probed.write_text(yaml.safe_dump(mapping))
    seen = open_data.run_all(probed, member(name), "helsinki", metadata={"archive_filename": name})
    assert len(seen) == len(run(pipeline, name)) > 0
    assert all(s == {"id": s["id"], "cached": "true", "stranger": "false"} for s in seen), seen
