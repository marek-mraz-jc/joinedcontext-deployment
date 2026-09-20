"""Every Banská Bystrica mapping over a recorded answer of the real feed (T-2305, PL-03, PL-52).

The mappings are run by Bento, so these cases run them by Bento: the committed Bloblang is
executed against a document recorded from the publisher on 2026-09-20, and the entities it
produces are asserted whole. A mapping checked only by reading it is a mapping nobody ran.

The recorded fixtures are in `fixtures/bystrica/`. They are answers, not inventions: each one
was fetched with the URL the `DataSource` beside the mapping declares.

Without a container runtime the Bento cases skip; the shape cases below do not, because they
are what stops the four mappings drifting apart.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures/bystrica"
# The same digest `test_demo_feeds.py` pins for the runner: the mapping is tested by the engine
# that will execute it, not by a re-implementation of it.
BENTO = "ghcr.io/warpstreamlabs/bento:1.21.1@sha256:656c55de3f8deddd4ee743f3c76f3b497e67324e940f2bc1769693cd8b906364"

# mapping -> (fixture, org domain, space segment)
MAPPINGS = {
    SEED / "bbsk/bbsk-pipeline-obyvatelstvo-bento.yaml": ("om7102rr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "bbsk/bbsk-pipeline-emisie-bento.yaml": ("zp3803rs.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "banskabystrica/pipeline-voda-bento.yaml": ("vh5003rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-obyvatelia-bento.yaml": (
        "mesto-obyvatelia-vek.json", "banskabystrica.sk", "banskabystrica-mesto",
    ),
}

CUBE_MAPPINGS = [p for p in MAPPINGS if p.name != "pipeline-obyvatelia-bento.yaml"]

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no container runtime, so Bento cannot run the mapping"
)


def processors(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text())["pipeline"]["processors"]


def run(path: Path, fixture: str, domain: str, space: str) -> list[dict]:
    """Execute the mapping's processors over the recorded document, as the runner would."""
    document = json.dumps(json.loads((FIXTURES / fixture).read_text()), separators=(",", ":"))
    steps = processors(path)
    payload = document
    for step in steps:
        if "unarchive" in step:
            # `unarchive: json_array` turns one message into one per element; the mapping after
            # it sees one element, so the remaining steps run per element and are re-archived.
            elements = json.loads(payload)
            mapped = [
                run_mapping(step_after, json.dumps(element, separators=(",", ":")), domain, space)
                for step_after in [s for s in steps[steps.index(step) + 1:] if "mapping" in s]
                for element in elements
            ]
            return [json.loads(line) for line in mapped if line.strip() not in ("", "null")]
        if "mapping" in step:
            payload = run_mapping(step, payload, domain, space)
        if "archive" in step:
            break
    return json.loads(payload)


def run_mapping(step: dict, payload: str, domain: str, space: str) -> str:
    with_env = ["-e", f"JC_ORG_DOMAIN={domain}", "-e", f"JC_SPACE={space}"]
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", *with_env, BENTO, "blobl", step["mapping"]],
        input=payload, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


@pytest.fixture(scope="module")
def entities():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {path: run(path, *config) for path, config in MAPPINGS.items()}


@requires_docker
def test_every_mapping_produces_entities_of_the_one_type_it_declares(entities):
    for path, produced in entities.items():
        assert produced, path.name
        assert {e["type"] for e in produced} == {"StatisticalObservation"}, path.name


@requires_docker
def test_every_id_is_the_four_segment_urn_of_its_own_project(entities):
    for path, produced in entities.items():
        _, domain, space = MAPPINGS[path]
        for entity in produced:
            segments = entity["id"].split(":")
            assert segments[:5] == ["urn", "ngsi-ld", "StatisticalObservation", domain, space], entity["id"]
            assert len(segments) == 6, entity["id"]
            # The localId is the publisher's own key, and it begins with the cube it came from.
            assert segments[5].startswith(entity["dataSet"]["value"] + "-"), entity["id"]


@requires_docker
def test_no_two_entities_of_one_run_share_an_id(entities):
    for path, produced in entities.items():
        ids = [e["id"] for e in produced]
        assert len(set(ids)) == len(ids), f"{path.name}: an upsert would overwrite its own row"


@requires_docker
def test_the_year_of_a_figure_is_the_publishers_year_and_not_its_position(entities):
    """The defect this file exists for.

    `value` is flat and row-major over `size`, and `dimension.{name}.category.index` is NOT
    sorted: the period comes back newest first. A mapping that walks the array and counts years
    upwards reports every figure against the wrong year, and the figure is real, so nothing about
    it looks wrong. These four were read from the publisher on 2026-09-20 by decoding the index.
    """
    known = {
        ("om7102rr", "SK032", "2024"): 611124,
        ("om7102rr", "SK032", "2023"): 614356,
        ("om7102rr", "SK0321", "2024"): 106604,
        ("vh5003rr", "SK0321508438", "2023"): 3868,
        ("vh5003rr", "SK0321508438", "2022"): 3991,
    }
    found = {
        (e["dataSet"]["value"], e["refArea"]["value"], e["refPeriod"]["value"]): e["value"]["value"]
        for produced in entities.values()
        for e in produced
    }
    for key, expected in known.items():
        assert key in found, key
        assert found[key] == expected, f"{key}: {found[key]} is the wrong year's figure"


@requires_docker
def test_the_emissions_mapping_keeps_the_pollutant_it_sliced(entities):
    produced = entities[SEED / "bbsk/bbsk-pipeline-emisie-bento.yaml"]
    assert {e["dimensionKey"]["value"] for e in produced} == {"1"}, "one pollutant, the solid one"
    # 14 territories over the five years the cube carries, minus the cells it leaves empty.
    assert {e["refArea"]["value"] for e in produced} >= {"SK032", "SK0323", "SK032D"}
    for entity in produced:
        assert entity["value"]["unitCode"] == "TNE"
        assert entity["id"].endswith("-ODPAD_TONY_KM2-1")


@requires_docker
def test_the_city_register_is_dated_by_the_day_it_was_read_because_it_declares_no_period(entities):
    produced = entities[SEED / "banskabystrica/pipeline-obyvatelia-bento.yaml"]
    assert len(produced) == 105, "one row per year of age, 0 to 104"
    periods = {e["refPeriod"]["value"] for e in produced}
    assert len(periods) == 1 and len(periods.pop()) == len("2026-09-20")
    # "   1 071" with a non-breaking space is 1071, and the counts sum to the register's total.
    assert sum(e["value"]["value"] for e in produced) == 72123
    assert {e["refArea"]["value"] for e in produced} == {"SK0321508438"}


@requires_docker
def test_every_entity_carries_the_request_that_produced_it(entities):
    """A row that cannot be fetched again is not a row, so `source` is the DataSource's own URL
    and not a shortened one that would need a human to reconstruct the query."""
    declared = {
        doc["metadata"]["name"]: doc["spec"]["http"]["url"]
        for folder in (SEED / "bbsk", SEED / "banskabystrica")
        for path in sorted(folder.glob("*.yaml"))
        if path.name != "index.yaml" and not path.name.endswith((".linkml.yaml", "-bento.yaml"))
        for doc in yaml.safe_load_all(path.read_text())
        if isinstance(doc, dict) and doc.get("kind") == "DataSource"
    }
    for path, produced in entities.items():
        pipeline = yaml.safe_load(Path(str(path).replace("-bento.yaml", ".yaml")).read_text())
        wanted = declared[pipeline["spec"]["source"]["dataSourceRef"]["name"]]
        for entity in produced:
            assert entity["source"]["value"] == wanted, path.name


@requires_docker
def test_a_cell_the_publisher_left_empty_writes_nothing_rather_than_a_zero():
    """A zero is a measurement, and a dashboard cannot tell it apart from a real one.

    The recorded answers happen to be complete, so the empty cell is induced: the document is
    the publisher's own, with one cell replaced by `null`, which is what a cube with a gap in a
    territory's series returns. The shape is real; only the gap is put there on purpose.
    """
    path = SEED / "bbsk/bbsk-pipeline-emisie-bento.yaml"
    document = json.loads((FIXTURES / "zp3803rs.json").read_text())
    assert all(cell is not None for cell in document["value"]), "the recorded answer is complete"
    gapped = dict(document, value=[None] + document["value"][1:])

    step = next(s for s in processors(path) if "mapping" in s)
    produced = json.loads(
        run_mapping(step, json.dumps(gapped, separators=(",", ":")), "bbsk.sk", "bbsk-kraj")
    )
    assert len(produced) == len(document["value"]) - 1
    assert all(e["value"]["value"] is not None for e in produced)
    # The row that was dropped is the one that had no number, not the one after it.
    assert not any(e["id"].endswith(":zp3803rs-SK032-2023-ODPAD_TONY_KM2-1") for e in produced)


def test_the_three_cube_mappings_share_one_decoder_character_for_character():
    """Three copies because a mapping file belongs to one pipeline; one decoder because three
    decoders would be three chances to read a cube by position again."""
    bodies = []
    for path in CUBE_MAPPINGS:
        mapping = next(s["mapping"] for s in processors(path) if "mapping" in s)
        head, _, decoder = mapping.partition("# JSON-stat 2.0, decoded by the index")
        assert decoder, f"{path.name} does not carry the shared decoder"
        bodies.append(decoder)
    assert len(set(bodies)) == 1, "the copies of the JSON-stat decoder have drifted apart"


def test_no_mapping_writes_its_own_space_or_domain_as_a_literal():
    # CC-82, PL-57: a mapping reads both from the environment, so a space renamed in one place
    # does not leave an id pointing at the old one.
    for path in MAPPINGS:
        text = path.read_text()
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            # A comment explains, and `source_url` is the publisher's address: one of them is
            # `egov.banskabystrica.sk`, which is a host and not this project's org domain.
            if stripped.startswith("#") or stripped.startswith("let source_url ="):
                continue
            for literal in ("bbsk.sk", "banskabystrica.sk", "bbsk-kraj", "banskabystrica-mesto"):
                assert literal not in line, f"{path.name}:{number}: {stripped}"
        assert 'env("JC_ORG_DOMAIN")' in text and 'env("JC_SPACE")' in text, path.name


def test_every_pipeline_names_a_data_source_and_an_endpoint_the_seed_holds():
    for folder in (SEED / "bbsk", SEED / "banskabystrica"):
        docs = [
            doc
            for path in sorted(folder.glob("*.yaml"))
            if path.name != "index.yaml" and not path.name.endswith((".linkml.yaml", "-bento.yaml"))
            for doc in yaml.safe_load_all(path.read_text())
            if isinstance(doc, dict) and "kind" in doc
        ]
        sources = {d["metadata"]["name"] for d in docs if d["kind"] == "DataSource"}
        endpoints = {
            f'urn:ngsi-ld:Endpoint:{ {"bbsk": "bbsk.sk", "banskabystrica": "banskabystrica.sk"}[d["metadata"]["namespace"]] }'
            f':{d["spec"]["contextSpaceRef"]}:{d["metadata"]["name"]}'
            for d in docs
            if d["kind"] == "Endpoint"
        }
        for pipeline in (d for d in docs if d["kind"] == "Pipeline"):
            spec = pipeline["spec"]
            assert spec["source"]["dataSourceRef"]["name"] in sources, pipeline["metadata"]["name"]
            assert spec["targetEndpoint"] in endpoints, spec["targetEndpoint"]
            assert spec["output"]["type"] == "StatisticalObservation"
            # An upsert is what a re-poll of a published table is: the same cell, published again.
            assert spec["output"]["mode"] == "upsert"


def test_every_mapping_has_its_pipeline_and_every_pipeline_its_mapping():
    for folder in (SEED / "bbsk", SEED / "banskabystrica"):
        mappings = {p.name.replace("-bento.yaml", ".yaml") for p in folder.glob("*-bento.yaml")}
        pipelines = {
            path.name
            for path in folder.glob("*.yaml")
            if not path.name.endswith((".linkml.yaml", "-bento.yaml"))
            for doc in yaml.safe_load_all(path.read_text())
            if isinstance(doc, dict) and doc.get("kind") == "Pipeline"
        }
        assert mappings == pipelines, f"{folder.name}: {mappings ^ pipelines}"
