"""The Bratislava hub's districts, places and statistics tables become Smart Data Models entities,
checked and counted (T-5274).

Bento runs each committed mapping over answers recorded from data.bratislava.sk's Feature Services
on 2026-10-23 (`fixtures/bratislava/hub/`): the 17 districts, four tables of places and 18
statistics tables (the long series cut to their two newest years). The calls to the hub are the
cut: each table's answer comes from the recording. The tests add the rows the owner's validation
asks for (2026-10-22T18:10Z): a point outside the city, a value out of range and a duplicate, each
dropped with a counted reason. Without a container runtime the Bento cases skip.
"""

import copy
import json
import re
import subprocess
import tempfile
from pathlib import Path

import open_data
import pytest
import yaml
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-bratislava-hub")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/bratislava"
FIXTURES = Path(__file__).resolve().parent / "fixtures/bratislava/hub"
SCHEMA = SEED / "bratislava.v1.schema.json"
HUB = "https://services8.arcgis.com/pRlN1m0su5BYaFAS/arcgis/rest/services/"
URN = "urn:ngsi-ld:{}:bratislava.sk:bratislava:{}"


def kpi(local: str) -> str:
    return URN.format("KeyPerformanceIndicator", local)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def run(
    mapping: str, document: dict, answers: dict | None = None
) -> tuple[list[dict], str]:
    """The committed mapping over `document`; each table request answered from `answers` by the
    path the mapping asks for, an unknown path refused."""
    steps = yaml.safe_load((SEED / mapping).read_text())["pipeline"]["processors"]
    for step in steps:
        if "branch" in step:
            http = step["branch"]["processors"][-1]["http"]
            assert http["url"].startswith(HUB + "${! @path }/FeatureServer/0/query?"), (
                http["url"]
            )
            step["branch"]["processors"] = [
                {
                    "mapping": f'root = {json.dumps(answers)}.get(@path).or(throw("unasked"))'
                }
            ]
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        "pipeline": {"processors": steps},
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "info", "format": "logfmt"},
    }
    # The recorded answers make the config too long for an argument: it goes in as a file.
    with tempfile.TemporaryDirectory() as work:
        Path(work, "c.json").write_text(json.dumps(config))
        Path(work).chmod(0o755)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "-e",
                "JC_ORG_DOMAIN=bratislava.sk",
                "-e",
                "JC_SPACE=bratislava",
                "-v",
                f"{work}:/work:ro",
                "--entrypoint",
                "/bento",
                BENTO,
                "-c",
                "/work/c.json",
            ],
            input=json.dumps(document).encode(),
            capture_output=True,
            timeout=180,
            check=False,
        )
    lines = [
        line for line in result.stdout.decode().splitlines() if line.startswith("[")
    ]
    return [
        e for line in lines for e in json.loads(line)
    ], result.stderr.decode() + result.stdout.decode()


def valid(entity: dict, model: str) -> None:
    assert not open_data.schema_errors(SCHEMA, entity), entity
    assert not open_data.sdm_errors(model, entity), entity


def statistics() -> dict:
    """The recorded tables plus the test's own rows: offences in a district the city does not
    have, an unemployment rate of 140 % and the Nové Mesto offences of 2025 twice."""
    answers = copy.deepcopy(fixture("statistics.json"))
    offences = next(
        v for k, v in answers.items() if k.startswith("Po%C4%8Det_priestupkov")
    )["features"]
    rows = next(
        v
        for k, v in answers.items()
        if k.startswith("Miera_evidovanej_nezamestnanosti")
    )["features"]
    nove = next(f for f in offences if f["attributes"]["MESTSKA_CAST"] == "Nové Mesto")
    offences += [
        {"attributes": dict(nove["attributes"], MESTSKA_CAST="Bratislava I")},
        copy.deepcopy(nove),
    ]
    rows.append(
        {
            "attributes": dict(
                rows[0]["attributes"], NEZAMESTNANOST_V__=140.0, ROK="2019"
            )
        }
    )
    return answers


@requires_docker
def test_the_district_layer_maps_to_17_valid_areas():
    areas, log = run(
        "bratislava-pipeline-districts-bento.yaml", fixture("districts.geojson")
    )
    assert len(areas) == 17, log
    by_id = {a["id"]: a for a in areas}
    nove = by_id[URN.format("AdministrativeArea", "district-529346")]
    assert (
        nove["name"]["value"] == "Nové Mesto"
        and nove["districtCode"]["value"] == "529346"
    )
    assert nove["location"]["value"]["type"] == "Polygon"
    for area in areas:
        valid(area, "extensions/AdministrativeArea")


@requires_docker
def test_a_district_outline_outside_the_city_writes_nothing():
    layer = copy.deepcopy(fixture("districts.geojson"))
    layer["features"][0]["geometry"]["coordinates"][0][0] = [19.14, 48.74]
    areas, log = run("bratislava-pipeline-districts-bento.yaml", layer)
    assert areas == [] and "the outline of Staré Mesto leaves Bratislava" in log, log
    layer["features"] = layer["features"][:16]
    areas, log = run("bratislava-pipeline-districts-bento.yaml", layer)
    assert areas == [] and "holds 16 districts, not 17" in log, log


@requires_docker
def test_the_recorded_tables_of_places_map_to_valid_places_and_each_bad_row_is_dropped_by_reason():
    answers = copy.deepcopy(fixture("places.json"))
    fix = next(v for k, v in answers.items() if k.startswith("Fixpointy"))["features"]
    # The same drop point again, and once more 5 m away under a new address line.
    fix.append(copy.deepcopy(fix[0]))
    fix.append(
        {
            "attributes": dict(
                fix[0]["attributes"],
                Adresa="Stavbárska 40A",
                Latitude=str(
                    float(fix[0]["attributes"]["Latitude"].replace(",", ".")) + 0.00004
                ),
            )
        }
    )
    places, log = run(
        "bratislava-pipeline-places-bento.yaml", fixture("services.json"), answers
    )
    # The recording's own defect: Kreatívne centrum Arténa at 48.735, 19.136 is Banská Bystrica.
    assert 'dropped by reason {\\"duplicate\\":2,\\"outside Bratislava\\":1}' in log, (
        log
    )
    by_key = {}
    for place in places:
        by_key.setdefault(place["id"].split(":")[-1].split(".")[0], []).append(place)
        valid(place, "dataModel.PointOfInterest/PointOfInterest")
    assert {k: len(v) for k, v in by_key.items()} == {
        "bezbarierovost": 161,
        "celozivotne-vzdelavanie": 98,
        "fixpointy": 13,
        "sluzby-bez-domova": 36,
    }
    # The lifelong-learning table writes the latitude in X: the provider lands in Ružinov.
    provider = next(
        p
        for p in by_key["celozivotne-vzdelavanie"]
        if p["name"]["value"] == "3EC International a. s."
    )
    assert provider["location"]["value"]["coordinates"] == [17.159578, 48.145443]
    assert provider["url"]["value"] == "https://www.3ec.sk"
    assert provider["address"]["value"]["streetAddress"] == "Hraničná 18"


@requires_docker
def test_a_table_the_hub_no_longer_lists_is_left_out_and_logged():
    services = copy.deepcopy(fixture("services.json"))
    services["services"] = [
        s for s in services["services"] if not s["name"].startswith("Fixpointy")
    ]
    places, log = run(
        "bratislava-pipeline-places-bento.yaml", services, fixture("places.json")
    )
    assert "the hub no longer lists fixpointy" in log, log
    assert not [p for p in places if ":fixpointy." in p["id"]] and places


@requires_docker
def test_the_recorded_statistics_map_to_valid_indicators_and_each_bad_figure_is_dropped_by_reason():
    indicators, log = run(
        "bratislava-pipeline-statistics-bento.yaml",
        fixture("services.json"),
        statistics(),
    )
    # The land-use table leaves two columns empty for 2021 and 2022 (2 x 34 cells): no number.
    assert (
        'dropped by reason {\\"duplicate\\":1,\\"no number\\":68,\\"not a city district\\":1,'
        '\\"out of range\\":1}'
    ) in log, log
    by_id = {i["id"]: i for i in indicators}
    assert len(by_id) == len(indicators) == 1326
    for indicator in indicators:
        valid(indicator, "dataModel.KeyPerformanceIndicator/KeyPerformanceIndicator")
    offences = by_id[kpi("priestupky.pocet.529346.2025")]
    assert (
        offences["kpiValue"]["value"] == 20704
        and offences["area"]["value"] == "Nové Mesto"
    )
    assert offences["calculationPeriod"]["value"] == {
        "from": "2025-01-01",
        "to": "2025-12-31",
    }
    # The mosquito table's mojibake ("Raèa") and thousands with a space ("1 445") still land.
    assert by_id[kpi("komare.kontroly.529354.2025")]["kpiValue"]["value"] == 1445
    # The prognoses abbreviate ("D. N. Ves") and the fertility table counts five-year periods.
    assert kpi("prognoza-obyvatelia.pocet.529371.2035") in by_id
    fertility = by_id[kpi("plodnost.uhrnna.529435.2017-2021")]
    assert fertility["calculationPeriod"]["value"] == {
        "from": "2017-01-01",
        "to": "2021-12-31",
    }
    assert (
        by_id[kpi("nezamestnanost.miera.529401.2022-q3")]["calculationFrequency"][
            "value"
        ]
        == "quarterly"
    )
    # Only the all-founders row of a school table, never the districts' own schools beside it.
    assert by_id[kpi("ms-kapacita.miesta.528595.2021")]["kpiValue"]["value"] == 1953


def test_each_dataset_has_its_endpoint_and_policy_narrowed_to_its_own_rows():
    """Every table key of the places and statistics mappings is one public dataset: an Endpoint
    whose Policy reads only the ids of that table, harvested into the city's CKAN organisation."""
    kinds = {"places": "PointOfInterest", "statistics": "KeyPerformanceIndicator"}
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    for pipeline, kind in kinds.items():
        text = (SEED / f"bratislava-pipeline-{pipeline}-bento.yaml").read_text()
        for key in sorted(set(re.findall(r'\{ "key": "([a-z0-9-]+)"', text))):
            endpoint = yaml.safe_load(
                (SEED / f"bratislava-endpoint-{key}.yaml").read_text()
            )
            policy = yaml.safe_load(
                (SEED / f"bratislava-policy-public-{key}.yaml").read_text()
            )
            assert (
                endpoint["spec"]["policyRef"]
                == f"urn:ngsi-ld:Policy:bratislava.sk:bratislava:public-{key}"
            )
            assert endpoint["spec"]["catalog"]["pipelineRef"] == {
                "kind": "Pipeline",
                "name": pipeline,
            }
            assert endpoint["spec"]["publish"]["ckan"]["instanceRef"] == {
                "kind": "CkanInstance",
                "name": "bratislava",
            }
            entities = policy["spec"]["information"][0]["entities"]
            assert entities == [
                {
                    "type": kind,
                    "idPattern": f"^urn:ngsi-ld:{kind}:[a-z0-9.-]+:bratislava:{key}[.][a-z0-9.-]+$",
                }
            ]
            assert "upsertBatch" not in policy["spec"]["operations"]
            assert (
                f"bratislava-endpoint-{key}.yaml" in index
                and f"bratislava-policy-public-{key}.yaml" in index
            )
