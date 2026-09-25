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

# Starts its own containers from module-scoped fixtures; split over xdist workers, each worker
# would start a second set beside the first. One worker runs the whole module (ci.yml loadgroup).
pytestmark = pytest.mark.xdist_group("docker-bystrica-pipelines")

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
    # T-2783: the region's further ŠÚ SR cubes, each a complete recorded answer of 2026-09-25.
    SEED / "bbsk/bbsk-pipeline-uchadzaci-bento.yaml": ("pr5001rr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "bbsk/bbsk-pipeline-byty-bento.yaml": ("st3004rr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "bbsk/bbsk-pipeline-mzdy-bento.yaml": ("np3110rr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "bbsk/bbsk-pipeline-navstevnost-bento.yaml": ("cr3802mr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "bbsk/bbsk-pipeline-kapacity-bento.yaml": ("cr3807qr.json", "bbsk.sk", "bbsk-kraj"),
    SEED / "banskabystrica/pipeline-voda-bento.yaml": ("vh5003rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-obyvatelia-bento.yaml": (
        "mesto-obyvatelia-vek.json", "banskabystrica.sk", "banskabystrica-mesto",
    ),
    # T-2781: the city's further ŠÚ SR cubes, each a complete recorded answer of 2026-09-25.
    SEED / "banskabystrica/pipeline-pohyb-bento.yaml": ("mesto-om7103rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-obyvatelstvo-bento.yaml": ("mesto-om7101qr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-ubytovanie-bento.yaml": ("mesto-cr3809qr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-navstevnost-bento.yaml": ("mesto-cr3803mr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-pozemky-bento.yaml": ("mesto-pl5001rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-uchadzaci-bento.yaml": ("mesto-pr5001rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-materske-skoly-bento.yaml": ("mesto-sv5001rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-zakladne-skoly-bento.yaml": ("mesto-sv5002rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
    SEED / "banskabystrica/pipeline-kniznice-bento.yaml": ("mesto-ku5008rr.json", "banskabystrica.sk", "banskabystrica-mesto"),
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
def test_the_region_cubes_carry_the_figures_the_publisher_states(entities):
    """T-2783: read from the publisher on 2026-09-25 by decoding the index, and cross-checked
    there: the 13 okresy sum to the kraj, and the kraj's figures are those its tables print."""
    known = {
        ("pr5001rr", "SK032", "2025", "U15061", None): 28022,
        ("pr5001rr", "SK032", "2025", "U15062", None): 14940,
        ("st3004rr", "SK032", "2024", "DOKONC_BYT", None): 1051,
        ("st3004rr", "SK032", "2025", "DOKONC_BYT", None): 991,
        ("np3110rr", "SK032", "2025", "E_PRIEM_MZDA", None): 1645,
        ("cr3802mr", "SK0321", "2025", "U_CR_0005", "7."): 12027,
        ("cr3807qr", "SK032", "2025", "U_CR_0002", "1.Q."): 773,
        ("cr3807qr", "SK032", "2025", "U_CR_0004", "1.Q."): 24580,
    }
    found = {
        (e["dataSet"]["value"], e["refArea"]["value"], e["refPeriod"]["value"], e["indicator"]["value"],
         e.get("dimensionKey", {}).get("value")): e["value"]["value"]
        for produced in entities.values()
        for e in produced
    }
    for key, expected in known.items():
        assert found.get(key) == expected, key
    completed = [
        value for (cube, area, year, indicator, _), value in found.items()
        if cube == "st3004rr" and year == "2025" and indicator == "DOKONC_BYT" and area != "SK032"
    ]
    assert len(completed) == 13 and sum(completed) == 991, "the okresy do not sum to the kraj"


@requires_docker
def test_the_city_cubes_carry_the_figures_the_publisher_states(entities):
    """T-2781: read from the publisher on 2026-09-25 by decoding the index, and cross-checked:
    the city's area is the one the BBSK municipality register states, and a quarter's end is the
    next quarter's start."""
    known = {
        ("pl5001rr", "2025", "U14010", None): 103376157,
        ("om7103rr", "2025", "IN010114", None): 73312,
        ("om7101qr", "2026Q2", "IN010113", "SPOLU"): 72912,
        ("om7101qr", "2026Q1", "IN010115", "SPOLU"): 72912,
        ("pr5001rr", "2025", "U15061", None): 1631,
    }
    found = {
        (e["dataSet"]["value"], e["refPeriod"]["value"], e["indicator"]["value"],
         e.get("dimensionKey", {}).get("value")): e["value"]["value"]
        for path, produced in entities.items()
        if MAPPINGS[path][2] == "banskabystrica-mesto"
        for e in produced
    }
    for key, expected in known.items():
        assert found.get(key) == expected, key


@requires_docker
def test_the_citys_men_and_women_sum_to_its_population_in_every_quarter(entities):
    produced = entities[SEED / "banskabystrica/pipeline-obyvatelstvo-bento.yaml"]
    by_quarter: dict[tuple[str, str], dict[str, int]] = {}
    for e in produced:
        by_quarter.setdefault((e["refPeriod"]["value"], e["indicator"]["value"]), {})[e["dimensionKey"]["value"]] = e["value"]["value"]
    assert len({period for period, _ in by_quarter}) == 134, "1993Q1 to 2026Q2"
    for key, sexes in by_quarter.items():
        assert set(sexes) == {"SPOLU", "1", "2"}, key
        assert sexes["1"] + sexes["2"] == sexes["SPOLU"], key


@requires_docker
def test_the_city_tourism_cubes_key_by_their_period_and_never_by_a_sum(entities):
    visits = entities[SEED / "banskabystrica/pipeline-navstevnost-bento.yaml"]
    months = {e["dimensionKey"]["value"].split("-")[0] for e in visits}
    assert months == {f"{m}." for m in range(1, 13)}
    assert {e["dimensionKey"]["value"].split("-", 1)[1] for e in visits} == {"VISIT_TOTAL", "VISIT_DOM", "VISIT_FOR"}
    rooms = entities[SEED / "banskabystrica/pipeline-ubytovanie-bento.yaml"]
    assert {e["dimensionKey"]["value"] for e in rooms} == {f"{q}.Q." for q in range(1, 5)}
    assert all(" " not in e["id"] for e in visits + rooms)


@requires_docker
def test_a_month_or_a_quarter_is_the_key_and_never_the_year_to_date_sum(entities):
    """The tourism cubes also publish `1. - 12.` and `1. - 4.Q.`, the sums of the periods; a
    code with spaces is no id segment, and a sum stored beside its parts is counted twice."""
    for name, periods in (("navstevnost", {f"{m}." for m in range(1, 13)}),
                          ("kapacity", {f"{q}.Q." for q in range(1, 5)})):
        produced = entities[SEED / f"bbsk/bbsk-pipeline-{name}-bento.yaml"]
        assert {e["dimensionKey"]["value"] for e in produced} == periods, name
        assert all(" " not in e["id"] for e in produced), name


@requires_docker
def test_a_wage_in_euro_carries_its_unit_in_words_and_no_invented_code(entities):
    """UN/CEFACT Recommendation 20 has no currency, so a wage keeps `unitText` and leaves
    `unitCode` out rather than carry a code that means something else."""
    produced = entities[SEED / "bbsk/bbsk-pipeline-mzdy-bento.yaml"]
    assert produced and all("unitCode" not in e["value"] for e in produced)
    assert {e["unitText"]["value"] for e in produced} == {"EUR"}
    counted = entities[SEED / "bbsk/bbsk-pipeline-uchadzaci-bento.yaml"]
    assert {e["value"]["unitCode"] for e in counted} == {"C62"}


def test_the_raw_space_holds_every_cube_within_the_projects_entity_quota():
    """PF-73: the quota is sized to what the project declares, so the cells of every cube the
    raw space reads, as recorded, have to fit under it with room for the years to come."""
    quota = yaml.safe_load((SEED / "bbsk/bbsk-project.yaml").read_text())["spec"]["quotas"]["entitiesPerSpace"]
    cells = sum(
        sum(cell is not None for cell in json.loads((FIXTURES / fixture).read_text())["value"])
        for path, (fixture, _, space) in MAPPINGS.items()
        if space == "bbsk-kraj"
    )
    assert cells <= quota * 0.8, f"{cells} cells against a quota of {quota}"


def test_the_citys_raw_space_holds_every_cube_within_its_entity_quota():
    """The same rule for `banskabystrica-mesto` (T-2781), whose nine new cubes join `voda`."""
    quota = yaml.safe_load((SEED / "banskabystrica/project.yaml").read_text())["spec"]["quotas"]["entitiesPerSpace"]
    cells = sum(
        sum(cell is not None for cell in json.loads((FIXTURES / fixture).read_text())["value"])
        for path, (fixture, _, space) in MAPPINGS.items()
        if space == "banskabystrica-mesto" and path in CUBE_MAPPINGS
    )
    assert cells <= quota * 0.8, f"{cells} cells against a quota of {quota}"


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
    # Keyed by project: a DataSource name is unique in its project only, and the city and the
    # region both read `susr-pr5001rr`, each for its own territory.
    declared = {
        (doc["metadata"]["namespace"], doc["metadata"]["name"]): doc["spec"]["http"]["url"]
        for folder in (SEED / "bbsk", SEED / "banskabystrica")
        for path in sorted(folder.glob("*.yaml"))
        if path.name != "index.yaml" and not path.name.endswith((".linkml.yaml", "-bento.yaml"))
        for doc in yaml.safe_load_all(path.read_text())
        if isinstance(doc, dict) and doc.get("kind") == "DataSource"
    }
    for path, produced in entities.items():
        pipeline = yaml.safe_load(Path(str(path).replace("-bento.yaml", ".yaml")).read_text())
        wanted = declared[(pipeline["metadata"]["namespace"], pipeline["spec"]["source"]["dataSourceRef"]["name"])]
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


def test_every_cube_mapping_shares_one_decoder_character_for_character():
    """One copy per pipeline because a mapping file belongs to one pipeline; one decoder because
    several decoders would be several chances to read a cube by position again."""
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
        classes = {d["spec"]["contextSpaceRef"]: set(d["spec"]["classes"]) for d in docs if d["kind"] == "DataModel"}
        endpoint_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Endpoint"}
        endpoints = {
            f'urn:ngsi-ld:Endpoint:{ {"bbsk": "bbsk.sk", "banskabystrica": "banskabystrica.sk"}[d["metadata"]["namespace"]] }'
            f':{d["spec"]["contextSpaceRef"]}:{d["metadata"]["name"]}'
            for d in docs
            if d["kind"] == "Endpoint"
        }
        for pipeline in (d for d in docs if d["kind"] == "Pipeline"):
            spec = pipeline["spec"]
            name = pipeline["metadata"]["name"]
            # A fetch names a DataSource of this project; a computation names the Endpoint it
            # reads through. Either way the thing it names is in the seed beside it, so a
            # renamed source breaks here and not in the cluster.
            if "dataSourceRef" in spec["source"]:
                assert spec["source"]["dataSourceRef"]["name"] in sources, name
            else:
                assert spec["source"]["endpointRef"]["name"] in endpoint_names, name
                assert spec["output"]["type"] == "KeyPerformanceIndicator", name
            assert spec["targetEndpoint"] in endpoints, spec["targetEndpoint"]
            # And it writes a type the target space's one model declares, which is all the
            # gateway lets into that space (DM-61).
            space = spec["targetEndpoint"].split(":")[-2]
            assert spec["output"]["type"] in classes[space], name
            # An upsert is what a re-poll of a published table is: the same cell, published
            # again; and an indicator recomputed on a schedule is the same indicator.
            assert spec["output"]["mode"] == "upsert"


def test_a_pipeline_is_fed_by_a_data_source_or_by_a_query_and_the_files_beside_it_say_which():
    """A DataSource fetch carries its mapping in the `-bento.yaml` beside it; a query through an
    Endpoint carries it inline, because the reconciler renders the input from the query itself."""
    for folder in (SEED / "bbsk", SEED / "banskabystrica"):
        mappings = {p.name.replace("-bento.yaml", ".yaml") for p in folder.glob("*-bento.yaml")}
        fetched, queried = set(), set()
        for path in sorted(folder.glob("*.yaml")):
            if path.name == "index.yaml" or path.name.endswith(("-bento.yaml", ".linkml.yaml")):
                continue
            for doc in yaml.safe_load_all(path.read_text()):
                if not isinstance(doc, dict) or doc.get("kind") != "Pipeline":
                    continue
                if "dataSourceRef" in doc["spec"]["source"]:
                    fetched.add(path.name)
                    assert "compute" not in doc["spec"], doc["metadata"]["name"]
                else:
                    queried.add(path.name)
                    assert "bloblang" in doc["spec"]["compute"], doc["metadata"]["name"]
        assert mappings == fetched, f"{folder.name}: {mappings ^ fetched}"
        assert queried, f"{folder.name} computes no indicator"


# Core terms CIM 009 defines for an attribute, never for an entity: a mapping that writes one as
# a top-level key writes an entity the broker refuses whole, with `400 … is a core non-reified
# term and cannot be used as an Attribute name (4.5.1)`.
NON_REIFIED = ("observedAt", "createdAt", "modifiedAt", "deletedAt", "unitCode", "datasetId")


@requires_docker
def test_no_entity_carries_a_core_term_as_an_attribute_of_its_own(entities):
    """The defect that kept both Slovak raw spaces empty for a day (T-2445).

    All four mappings wrote `observedAt` beside `value` as an attribute of the entity. Every
    entity was refused with 400, the stream's `drop_on: [400, 413, 422]` dropped it without a
    line in the log, and the spaces the second demo story reads stayed empty while the runner
    reported the streams live: 3285 refusals for `obyvatelia`, 3275 for `voda`. The timestamp
    belongs inside the attribute it dates.
    """
    for path, produced in entities.items():
        for entity in produced:
            named = [term for term in NON_REIFIED if term in entity]
            assert not named, f"{path.name}: {entity['id']} carries {named} as its own attribute"


def test_no_mapping_assigns_a_core_term_at_the_entity_level():
    """The same rule read off the committed Bloblang, so it holds without a container runtime."""
    for path in MAPPINGS:
        for step in processors(path):
            mapping = step.get("mapping")
            if not mapping:
                continue
            depth = 0
            for line in mapping.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # The entity object is the one nested a single level inside `root = … {`; a key
                # written there is an attribute of the entity, and one written deeper belongs to
                # an attribute, which is where these terms are allowed.
                if depth == 2:
                    for term in NON_REIFIED:
                        assert not stripped.startswith(f'"{term}"'), (
                            f"{path.name}: `{term}` is written as an attribute of the entity; "
                            "CIM 009 4.5.1 allows it only inside one (T-2445)"
                        )
                depth += stripped.count("{") - stripped.count("}")
