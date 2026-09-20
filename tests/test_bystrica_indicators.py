"""Every indicator of the region demonstration, computed by Bento from real rows (T-2306, T-2307).

The three indicator pipelines carry their Bloblang inline, because each one reads a query through
an Endpoint rather than a DataSource fetch. These cases run that Bloblang under the engine the
runner uses, over the entities the ingestion mappings produced from answers recorded on
2026-09-20, and assert the value, the unit, the window, the territory and the provenance of every
indicator the contract promises.

The two things a KPI dashboard can get wrong that a viewer cannot see are asserted by name: a
figure read against the wrong year, and a window with no readings shown as a zero.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures/bystrica"
BENTO = "ghcr.io/warpstreamlabs/bento:1.21.1@sha256:656c55de3f8deddd4ee743f3c76f3b497e67324e940f2bc1769693cd8b906364"

INGEST = {
    "om7102rr.json": (SEED / "bbsk/bbsk-pipeline-obyvatelstvo-bento.yaml", "bbsk.sk", "bbsk-kraj"),
    "zp3803rs.json": (SEED / "bbsk/bbsk-pipeline-emisie-bento.yaml", "bbsk.sk", "bbsk-kraj"),
    "vh5003rr.json": (SEED / "banskabystrica/pipeline-voda-bento.yaml", "banskabystrica.sk", "banskabystrica-mesto"),
    "mesto-obyvatelia-vek.json": (
        SEED / "banskabystrica/pipeline-obyvatelia-bento.yaml", "banskabystrica.sk", "banskabystrica-mesto",
    ),
}

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no container runtime, so Bento cannot run the mapping"
)


def bento(mapping: str, document, env: dict):
    """Run one Bloblang mapping over one document, through a Bento stream.

    A stream rather than `bento blobl`, because a page of five hundred entities is one line and
    `blobl` reads stdin with a scanner that refuses it.
    """
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        work = Path(directory)
        work.chmod(0o777)
        (work / "in.json").write_text(json.dumps(document, separators=(",", ":")))
        (work / "cfg.yaml").write_text(yaml.safe_dump({
            "input": {"file": {"paths": ["/w/in.json"], "scanner": {"to_the_end": {}}}},
            "pipeline": {"processors": [{"mapping": mapping}]},
            "output": {"file": {"path": "/w/out.json", "codec": "all-bytes"}},
        }))
        for item in work.iterdir():
            item.chmod(0o666)
        args = ["docker", "run", "--rm", "--user", f"{__import__('os').getuid()}:{__import__('os').getgid()}",
                "-v", f"{work}:/w", "-w", "/w"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        result = subprocess.run(args + [BENTO, "-c", "/w/cfg.yaml"], capture_output=True, text=True, timeout=240)
        produced = work / "out.json"
        assert produced.is_file(), (result.stderr or result.stdout)[-2000:]
        return json.loads(produced.read_text())


def mapping_of(path: Path) -> str:
    document = yaml.safe_load(path.read_text())
    if "pipeline" in document:
        return next(s["mapping"] for s in document["pipeline"]["processors"] if "mapping" in s)
    return document["spec"]["compute"]["bloblang"]


def ingested(*fixtures) -> list[dict]:
    """The raw entities the ingestion mappings produce from the recorded answers."""
    rows: list[dict] = []
    for fixture in fixtures:
        path, domain, space = INGEST[fixture]
        document = json.loads((FIXTURES / fixture).read_text())
        env = {"JC_ORG_DOMAIN": domain, "JC_SPACE": space}
        steps = yaml.safe_load(path.read_text())["pipeline"]["processors"]
        mapping = mapping_of(path)
        if any("unarchive" in step for step in steps):
            rows += [bento(mapping, element, env) for element in document]
        else:
            rows += bento(mapping, document, env)
    return rows


# Three readings, two of them inside the last 24 hours the stations reported. The third is six
# months older, so it is in the calendar year and out of the day.
AIR = [
    {"id": "urn:ngsi-ld:AirQualityObserved:banskabystrica.sk:ovzdusie:station-1",
     "type": "AirQualityObserved",
     "dateObserved": {"type": "Property", "value": "2026-09-01T06:00:00Z"},
     "pm10": {"type": "Property", "value": 18.4, "unitCode": "GQ"},
     "pm25": {"type": "Property", "value": 11.2, "unitCode": "GQ"}},
    {"id": "urn:ngsi-ld:AirQualityObserved:banskabystrica.sk:ovzdusie:station-2",
     "type": "AirQualityObserved",
     "dateObserved": {"type": "Property", "value": "2026-09-01T07:00:00Z"},
     "pm10": {"type": "Property", "value": 52.6, "unitCode": "GQ"},
     "pm25": {"type": "Property", "value": 30.0, "unitCode": "GQ"}},
    {"id": "urn:ngsi-ld:AirQualityObserved:banskabystrica.sk:ovzdusie:station-3",
     "type": "AirQualityObserved",
     "dateObserved": {"type": "Property", "value": "2026-03-01T07:00:00Z"},
     "pm10": {"type": "Property", "value": 90.0, "unitCode": "GQ"},
     "pm25": {"type": "Property", "value": 4.0, "unitCode": "GQ"}},
]

REQUIRED = {"id", "type", "name", "currentValue", "calculationPeriod", "calculationFormula",
            "derivedFrom", "computedBy", "updatedAt"}


@pytest.fixture(scope="module")
def region():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    rows = ingested("om7102rr.json", "zp3803rs.json")
    return bento(
        mapping_of(SEED / "bbsk/bbsk-pipeline-ukazovatele.yaml"), rows,
        {"JC_ORG_DOMAIN": "bbsk.sk", "JC_SPACE": "bbsk-kpi", "JC_SOURCE_SPACE": "bbsk-kraj"},
    )


@pytest.fixture(scope="module")
def air():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return bento(
        mapping_of(SEED / "banskabystrica/pipeline-ukazovatele-ovzdusie.yaml"), AIR,
        {"JC_ORG_DOMAIN": "banskabystrica.sk", "JC_SPACE": "banskabystrica-kpi",
         "JC_SOURCE_SPACE": "ovzdusie"},
    )


@pytest.fixture(scope="module")
def city():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    rows = ingested("vh5003rr.json", "mesto-obyvatelia-vek.json")
    return bento(
        mapping_of(SEED / "banskabystrica/pipeline-ukazovatele-mesto.yaml"), rows,
        {"JC_ORG_DOMAIN": "banskabystrica.sk", "JC_SPACE": "banskabystrica-kpi",
         "JC_SOURCE_SPACE": "banskabystrica-mesto"},
    )


@requires_docker
def test_the_region_computes_one_indicator_per_territory(region):
    assert len(region) == 28, "two indicators over the kraj and its 13 okresy"
    names = {e["name"]["value"] for e in region}
    assert sum(n.startswith("obyvatelstvo-stav-") for n in names) == 14
    assert sum(n.startswith("emisie-tuhe-km2-") for n in names) == 14
    assert "obyvatelstvo-stav-kraj" in names
    assert "emisie-tuhe-km2-okres-ziar-nad-hronom" in names


@requires_docker
def test_the_population_is_the_publishers_newest_year_and_not_a_position_in_the_array(region):
    """The figure and the year it belongs to, read back from the cube by hand.

    `om7102rr` carries 1993 to 2025 and its period dimension comes back newest first. The
    indicator takes the newest year, and these are the three most recent the cube publishes.
    """
    kraj = next(e for e in region if e["name"]["value"] == "obyvatelstvo-stav-kraj")
    assert kraj["currentValue"]["value"] == 607581
    assert kraj["currentValue"]["unitCode"] == "C62"
    assert kraj["calculationPeriod"]["value"]["start"] == "2025-01-01T00:00:00Z"
    assert kraj["calculationPeriod"]["value"]["end"] == "2025-12-31T23:59:59Z"

    okres = next(e for e in region if e["name"]["value"] == "obyvatelstvo-stav-okres-banska-bystrica")
    assert okres["currentValue"]["value"] == 106000
    # The region is not the city and the okres is neither: three different numbers, three
    # different territories, each named on its own entity.
    assert kraj["currentValue"]["value"] != okres["currentValue"]["value"]


@requires_docker
def test_the_emissions_indicator_is_tonnes_per_square_kilometre_of_its_own_district(region):
    emissions = {e["name"]["value"]: e for e in region if e["name"]["value"].startswith("emisie-")}
    for entity in emissions.values():
        assert entity["currentValue"]["unitCode"] == "TNE"
        assert entity["calculationPeriod"]["value"]["start"] == "2023-01-01T00:00:00Z", "the newest year zp3803rs carries"
        assert isinstance(entity["currentValue"]["value"], (int, float))
    assert emissions["emisie-tuhe-km2-kraj"]["currentValue"]["value"] == 0.4


@requires_docker
def test_the_air_indicators_use_the_window_they_name(air):
    by_name = {e["name"]["value"]: e for e in air}
    assert set(by_name) == {"pm10-24h-mesto", "pm25-rok-mesto"}

    day = by_name["pm10-24h-mesto"]
    # The two readings inside the day, not the third one six months older.
    assert day["currentValue"]["value"] == pytest.approx((18.4 + 52.6) / 2)
    assert day["currentValue"]["unitCode"] == "GQ"
    assert day["calculationPeriod"]["value"] == {
        "start": "2026-08-31T07:00:00Z", "end": "2026-09-01T07:00:00Z",
    }

    year = by_name["pm25-rok-mesto"]
    assert year["currentValue"]["value"] == pytest.approx((11.2 + 30.0 + 4.0) / 3)
    assert year["calculationPeriod"]["value"]["start"] == "2026-01-01T00:00:00Z"


@requires_docker
def test_the_window_ends_at_the_newest_reading_and_not_at_the_wall_clock(air):
    """A 24-hour mean ending "now" over a source that stopped reporting is a window with nothing
    in it. Ending it at the newest reading gives the most recent 24 hours the stations did
    report, and `updatedAt` standing well after `calculationPeriod.end` is what shows a reader
    the source is static rather than the air being clean."""
    for entity in air:
        assert entity["calculationPeriod"]["value"]["end"] == "2026-09-01T07:00:00Z"
        assert entity["updatedAt"]["value"]["@value"] > entity["calculationPeriod"]["value"]["end"]


@requires_docker
def test_an_empty_window_says_not_measured_and_never_zero():
    produced = bento(
        mapping_of(SEED / "banskabystrica/pipeline-ukazovatele-ovzdusie.yaml"), [],
        {"JC_ORG_DOMAIN": "banskabystrica.sk", "JC_SPACE": "banskabystrica-kpi",
         "JC_SOURCE_SPACE": "ovzdusie"},
    )
    assert len(produced) == 2, "the indicator is written, not skipped"
    for entity in produced:
        assert entity["currentValue"]["value"] == "not measured"
        # No quantity, so no unit and nothing observed; everything else is still there, because
        # the question was asked of a real window through a real endpoint.
        assert "unitCode" not in entity["currentValue"]
        assert "observedAt" not in entity["currentValue"]
        assert REQUIRED <= set(entity)


@requires_docker
def test_a_region_with_no_row_for_a_territory_says_not_measured_too():
    rows = ingested("zp3803rs.json")
    produced = bento(
        mapping_of(SEED / "bbsk/bbsk-pipeline-ukazovatele.yaml"), rows,
        {"JC_ORG_DOMAIN": "bbsk.sk", "JC_SPACE": "bbsk-kpi", "JC_SOURCE_SPACE": "bbsk-kraj"},
    )
    assert len(produced) == 28, "every territory is written, measured or not"
    population = [e for e in produced if e["name"]["value"].startswith("obyvatelstvo-stav-")]
    assert len(population) == 14
    assert all(e["currentValue"]["value"] == "not measured" for e in population)
    emissions = [e for e in produced if e["name"]["value"].startswith("emisie-")]
    assert all(isinstance(e["currentValue"]["value"], (int, float)) for e in emissions)


@requires_docker
def test_the_water_indicator_records_every_input_of_its_division(city):
    assert len(city) == 1
    water = city[0]
    assert water["name"]["value"] == "spotreba-vody-obyvatel-mesto"
    assert water["currentValue"]["unitCode"] == "LTR"
    # 4 053 thousand m3 over 72 123 people over 365 days is 154 litres a person a day.
    assert water["currentValue"]["value"] == 154
    formula = water["calculationFormula"]["value"]
    for part in ("vh5003rr/U03084", "4053", "72123", "365"):
        assert part in formula, formula


@requires_docker
def test_every_indicator_carries_the_provenance_that_makes_it_auditable(region, air, city):
    """PF-55: an indicator carries its provenance or it is refused. `derivedFrom` names the
    Endpoint the sources were read through and `computedBy` the Pipeline that computed it."""
    for entity in region + air + city:
        assert REQUIRED <= set(entity), entity["id"]
        assert entity["type"] == "KeyPerformanceIndicator"
        assert entity["derivedFrom"]["object"].startswith("urn:ngsi-ld:Endpoint:")
        assert entity["computedBy"]["object"].startswith("urn:ngsi-ld:Pipeline:")
        assert entity["calculationFormula"]["value"].strip() != ""
        assert entity["updatedAt"]["value"]["@type"] == "DateTime"


@requires_docker
def test_every_indicator_id_is_the_contracts_urn_and_names_its_own_project(region, air, city):
    for entities, domain, space in ((region, "bbsk.sk", "bbsk-kpi"),
                                    (air, "banskabystrica.sk", "banskabystrica-kpi"),
                                    (city, "banskabystrica.sk", "banskabystrica-kpi")):
        for entity in entities:
            segments = entity["id"].split(":")
            assert segments[:5] == ["urn", "ngsi-ld", "KeyPerformanceIndicator", domain, space], entity["id"]
            assert len(segments) == 6, entity["id"]
            # PF-54: `name` is the `{localId}`, so a renamed indicator cannot keep an id that
            # says otherwise, and the territory is in both.
            assert segments[5] == entity["name"]["value"]


@requires_docker
def test_no_indicator_carries_an_attribute_the_platform_would_refuse(region, air, city):
    """The published `KeyPerformanceIndicator` schema closes the object, so `territory`, `state`
    and `threshold` are rejected at the write. The territory is the suffix of the id and the
    threshold is the view's (Development/10 §4)."""
    for entity in region + air + city:
        assert set(entity) <= REQUIRED | {"@context"}, set(entity) - REQUIRED


def test_every_indicator_pipeline_reads_through_an_endpoint_and_writes_through_one():
    for folder in (SEED / "bbsk", SEED / "banskabystrica"):
        for path in sorted(folder.glob("*.yaml")):
            if path.name in ("index.yaml",) or path.name.endswith(("-bento.yaml", ".linkml.yaml")):
                continue
            for doc in yaml.safe_load_all(path.read_text()):
                if not isinstance(doc, dict) or doc.get("kind") != "Pipeline":
                    continue
                spec = doc["spec"]
                if spec["output"]["type"] != "KeyPerformanceIndicator":
                    continue
                assert spec["class"] == "scheduled", doc["metadata"]["name"]
                # PL-18, PF-39: never the store, always the space's own Endpoint.
                assert "endpointRef" in spec["source"], doc["metadata"]["name"]
                assert "dataSourceRef" not in spec["source"], doc["metadata"]["name"]
                assert spec["targetEndpoint"].split(":")[-1].endswith("-kpi"), spec["targetEndpoint"]
                assert spec["compute"]["kind"] == "bloblang"


def test_no_indicator_of_one_body_can_be_computed_from_the_others_space():
    """The separation the demonstration exists to show, asserted where it is decided.

    A KPI of the region computed from the city's rows would be a figure eight times too small
    under the region's name, and nothing in the entity would say so. Three things stop it and all
    three are here: the pipeline reads one Endpoint and that Endpoint is its own project's; it
    writes its own project's KPI endpoint; and its mapping mints ids from `JC_ORG_DOMAIN` and
    `JC_SPACE`, which the reconciler sets from the pipeline's own project, so a mapping copied
    into the other project mints the other project's ids and cannot forge the first one's.
    """
    domains = {"bbsk": "bbsk.sk", "banskabystrica": "banskabystrica.sk"}
    seen = 0
    for folder, project in ((SEED / "bbsk", "bbsk"), (SEED / "banskabystrica", "banskabystrica")):
        other = next(d for p, d in domains.items() if p != project)
        for path in sorted(folder.glob("*.yaml")):
            for doc in yaml.safe_load_all(path.read_text()):
                if not isinstance(doc, dict) or doc.get("kind") != "Pipeline":
                    continue
                spec = doc["spec"]
                if spec["output"]["type"] != "KeyPerformanceIndicator":
                    continue
                seen += 1
                assert doc["metadata"]["namespace"] == project
                # One source, and it is named by reference inside this project, so it resolves
                # to this project's Endpoint and to no other's.
                assert set(spec["source"]) == {"endpointRef", "query"}
                assert spec["source"]["endpointRef"]["name"] in {
                    e["metadata"]["name"]
                    for f in folder.glob("*.yaml")
                    for e in yaml.safe_load_all(f.read_text())
                    if isinstance(e, dict) and e.get("kind") == "Endpoint"
                }
                assert spec["targetEndpoint"].split(":")[3] == domains[project]
                mapping = spec["compute"]["bloblang"]
                assert 'env("JC_ORG_DOMAIN")' in mapping and 'env("JC_SPACE")' in mapping
                # The type prefix is rightly literal — a KPI is a KPI. The body and its spaces
                # are not: they come from the environment the reconciler sets per project.
                for literal in (other, other.removesuffix(".sk"), domains[project]):
                    assert literal not in mapping, f"{doc['metadata']['name']}: {literal} is hard coded"
    assert seen == 3, "the region's pipeline and the city's two"


def test_the_read_every_indicator_pipeline_declares_is_one_a_policy_permits():
    """A pipeline that may write its answer but not read its question computes nothing (T-2445).

    The three indicator pipelines read `GET /entities` through an Endpoint of their own project.
    That operation is `queryEntity`; `queryBatch` is only the `POST /entityOperations/query`
    form, and granting one is not granting the other. Both raw-space policies named `queryBatch`
    alone, so every read came back `403 Access Denied by Policy`, the stream's `errored()` guard
    dropped the tick whole, and `banskabystrica-kpi` and `bbsk-kpi` stayed empty with no failure
    anywhere to read. This asserts the grant that makes the declared read possible, per pipeline.
    """
    covers = {"queryEntity", "retrieveOps", "redirectionOps", "federationOps"}
    seen = 0
    for folder in (SEED / "bbsk", SEED / "banskabystrica"):
        documents = [
            doc
            for path in sorted(folder.glob("*.yaml"))
            for doc in yaml.safe_load_all(path.read_text())
            if isinstance(doc, dict)
        ]
        spaces = {
            doc["metadata"]["name"]: doc["spec"]["contextSpaceRef"]
            for doc in documents
            if doc.get("kind") == "Endpoint"
        }
        for doc in documents:
            if doc.get("kind") != "Pipeline" or doc["spec"]["output"]["type"] != "KeyPerformanceIndicator":
                continue
            source = spaces[doc["spec"]["source"]["endpointRef"]["name"]]
            account = doc["spec"].get("serviceAccountRef", {}).get("name", "pipelines")
            granted = {
                operation
                for policy in documents
                if policy.get("kind") == "Policy"
                and policy["spec"]["contextSpaceRef"]["name"] == source
                and policy["spec"]["assignee"] == {"kind": "serviceAccount", "id": account}
                for operation in policy["spec"]["operations"]
            } | {
                # A space anyone may read is readable by this account too: the air pipeline's
                # source is the city's public endpoint.
                operation
                for policy in documents
                if policy.get("kind") == "Policy"
                and policy["spec"]["contextSpaceRef"]["name"] == source
                and policy["spec"]["assignee"] == {"kind": "role", "id": "public"}
                for operation in policy["spec"]["operations"]
            }
            seen += 1
            assert granted & covers, (
                f"{doc['metadata']['name']} reads {source} with GET /entities and no policy "
                f"grants it queryEntity; it has {sorted(granted)}"
            )
    assert seen == 3, "the region's pipeline and the city's two"
