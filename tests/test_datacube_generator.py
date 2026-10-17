"""ŠÚ SR's DATAcube as 44 public Endpoints of project slovensko (T-4390, T-4402).

`scripts/open-data/datacube.py` writes one space `slovensko/<topic>/` per entry of its TOPICS: one or
two headline tables of a theme, each at most CUBE_LIMIT cells. Here it runs over a recorded excerpt
of the collection (`fixtures/slovensko/datacube/`, fetched on 2026-10-17: themes as, ps and is), with
the dimension sizes stubbed, and Bento runs the generated decoder over two recorded cubes. The
committed folders are checked against TOPICS, the seed index, the pipelines' account and the catalogue.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/slovensko"
FIXTURES = Path(__file__).resolve().parent / "fixtures/slovensko/datacube"
SCHEMA = SEED / "susr/statistical-observation.v1.schema.json"

spec = importlib.util.spec_from_file_location("datacube", ROOT / "scripts/open-data/datacube.py")
datacube = importlib.util.module_from_spec(spec)
spec.loader.exec_module(datacube)

DNS = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TITLE = {"sk": "Téma", "en": "Topic"}
FIXTURE_TOPICS = [
    {"name": "susr-as", "theme": "as", "title": TITLE, "cubes": ["as1001rs", "as1007rs"]},
    {"name": "susr-ps", "theme": "ps", "title": TITLE, "cubes": ["ps1002rs"]},
]


def items() -> list[dict]:
    return datacube.datasets(json.loads((FIXTURES / "collection-sk.json").read_text()),
                             json.loads((FIXTURES / "collection-en.json").read_text()))


def generate(seed: Path, topics=FIXTURE_TOPICS):
    chosen = datacube.selected(items(), topics)
    cells = {d["code"]: 1000 for _, ds in chosen for d in ds}
    files, rows = datacube.render(chosen, cells, seed)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return files, rows


def test_a_topic_takes_its_tables_in_its_order_and_a_missing_or_undated_one_is_an_error():
    chosen = datacube.selected(items(), FIXTURE_TOPICS)
    assert [(t["name"], [d["code"] for d in ds]) for t, ds in chosen] == [
        ("susr-as", ["as1001rs", "as1007rs"]), ("susr-ps", ["ps1002rs"])]
    with pytest.raises(ValueError, match="susr-x: DATAcube has no dated table zz9999rs"):
        datacube.selected(items(), [{"name": "susr-x", "theme": "as", "title": TITLE, "cubes": ["as1001rs", "zz9999rs"]}])
    undated = [d | {"dimensions": {"a_poh": {"note": "Pohlavie"}}} if d["code"] == "as1001rs" else d for d in items()]
    with pytest.raises(ValueError, match="as1001rs"):
        datacube.selected(undated, FIXTURE_TOPICS)


def test_a_dataset_without_an_sk_label_takes_the_en_one():
    by = {d["code"]: d for d in items()}
    # as1007rs is "Default" in sk.
    assert by["as1007rs"]["title"] == {"sk": "The most frequent causes of death of population",
                                       "en": "The most frequent causes of death of population"}
    assert by["as1001rs"]["title"]["sk"] == "Obyvateľstvo a charakteristiky veku"


def test_a_cubes_size_is_the_product_of_its_dimensions():
    ds = [{"code": "as1001rs", "dimensions": {"a": {}, "b": {}}}, {"code": "ps1002rs", "dimensions": {"c": {}}}]
    counts = {"a": 3, "b": 4, "c": 0}
    get = lambda url: {"category": {"index": dict.fromkeys(range(counts[url.split("/")[-1].split("?")[0]]))}}  # noqa: E731
    assert datacube.sizes(ds, get) == {"as1001rs": 12, "ps1002rs": 0}


def test_endpoint_slugs_are_stable_across_two_runs(tmp_path):
    first, rows = generate(tmp_path)
    again, rows_again = generate(tmp_path)
    assert first == again and rows == rows_again
    slugs = [yaml.safe_load(first[tmp_path / f"{t['name']}/endpoint.yaml"])["spec"]["slug"] for t in FIXTURE_TOPICS]
    assert len(set(slugs)) == 2 and all(re.fullmatch(r"[a-z2-7]{32}", s) for s in slugs)


def test_every_generated_manifest_is_a_slovensko_manifest_of_its_own_space(tmp_path):
    files, _ = generate(tmp_path)
    kinds = {}
    for path, text in files.items():
        if path.suffix != ".yaml" or path.name.endswith(".linkml.yaml"):
            continue
        doc = yaml.safe_load(text)
        space = path.parent.name
        assert doc["apiVersion"].startswith("joinedcontext.com/v1alpha") and doc["metadata"]["namespace"] == "slovensko"
        assert DNS.match(doc["metadata"]["name"]) and len(doc["metadata"]["name"]) <= 40, path
        kinds.setdefault(space, []).append(doc["kind"])
        ref = doc["spec"].get("contextSpaceRef")
        if ref is not None:
            assert (ref["name"] if isinstance(ref, dict) else ref) == space, path
        if doc["kind"] == "DataSource":
            url = doc["spec"]["http"]["url"]
            assert url.startswith("https://data.statistics.sk/api/v2/dataset/") and "headers" in doc["spec"]["http"]
            assert set(doc["spec"]["http"]["headers"]) == {"Accept"}, "a DataSource carries no credential"
        if doc["kind"] == "Policy" and doc["spec"]["assignee"]["kind"] == "serviceAccount":
            assert "deleteBatch" not in doc["spec"]["operations"]
        if doc["kind"] == "Pipeline":
            assert doc["spec"]["outputs"][0]["targetEndpoint"] == f"urn:ngsi-ld:Endpoint:joinedcontext.com:{space}:{space}"
    for space, ks in kinds.items():
        assert sorted(set(ks)) == ["ContextSpace", "DataModel", "DataSource", "Endpoint", "Pipeline", "Policy"], space


def test_catalogue_rows_name_the_generated_endpoint(tmp_path):
    files, rows = generate(tmp_path)
    slug = {t["name"]: yaml.safe_load(files[tmp_path / f"{t['name']}/endpoint.yaml"])["spec"]["slug"] for t in FIXTURE_TOPICS}
    owner = {f"susr-{c}": t["name"] for t in FIXTURE_TOPICS for c in t["cubes"]}
    assert set(rows) == set(owner)
    for name, row in rows.items():
        assert row == {"endpoint": slug[owner[name]], "type": "KeyPerformanceIndicator",
                       "dataset": f"https://data.dev.joinedcontext.com/dataset/{name}", "location": False, "filtered": True}


def test_the_index_block_and_the_account_roles_are_replaced_not_appended():
    entries = datacube.placed(datacube.selected(items(), FIXTURE_TOPICS))
    assert entries["susr-ps/datasource-ps1002rs.yaml"] == "projects/slovensko/datasources/susr-ps1002rs.yaml"
    assert entries["susr-as/endpoint.yaml"] == "projects/slovensko/spaces/susr-as/endpoints/susr-as.yaml"
    once = datacube.index_text("a.yaml: x/a.yaml\n", entries)
    assert datacube.index_text(once, entries) == once and once.startswith("a.yaml: x/a.yaml\n" + datacube.PLACED)
    account = "spec:\n  roles:\n    - { role: space-writer, scope: { contextSpace: ovzdusie-sk } }\nstatus: {}\n"
    once = datacube.account_text(account, ["susr-as", "susr-ps"])
    assert datacube.account_text(once, ["susr-as", "susr-ps"]) == once
    assert once.splitlines()[-1] == "status: {}" and once.count("contextSpace: susr-") == 2


def test_roles_come_from_the_collection_notes():
    assert datacube.roles({"a_rok": {"note": "Rok"}, "a_obc": {"note": "0 SR + Oblasti + Kraje"}, "a_ukaz": {"note": "Ukazovateľ"},
                           "a_mj": {"note": "Merná jednotka"}, "a_poh": {"note": "Pohlavie"}, "a_x": {}}) == {
        "period": "a_rok", "area": "a_obc", "indicator": "a_ukaz", "unit": "a_mj", "keys": ["a_poh", "a_x"]}
    # A cube nothing dates is not taken.
    assert datacube.roles({"a_poh": {"note": "Pohlavie"}})["period"] is None


def decode(theme: str, fixture: str, tmp_path: Path) -> list[dict]:
    files, _ = generate(tmp_path)
    steps = yaml.safe_load(files[tmp_path / f"susr-{theme}/pipeline.yaml"])["spec"]["steps"]
    rendered = tmp_path / "steps.yaml"
    rendered.write_text(yaml.safe_dump({"pipeline": {"processors": [{"mapping": s["bloblang"]} for s in steps]}}))
    return open_data.run(rendered, (FIXTURES / fixture).read_bytes(), f"susr-{theme}", "joinedcontext.com")


@requires_docker
def test_a_cube_becomes_one_valid_entity_per_cell_as_the_model_example_shows(tmp_path):
    entities = decode("as", "as1001rs.json", tmp_path)
    cube = json.loads((FIXTURES / "as1001rs.json").read_text())
    assert len(entities) == len([v for v in cube["value"] if v is not None])
    assert len({e["id"] for e in entities}) == len(entities)
    example = json.loads((SEED / "susr/statistical-observation.v1.example.jsonld").read_text())
    [cell] = [e for e in entities if e["id"] == example["id"]]
    assert {k: v for k, v in cell.items()} == {k: v for k, v in example.items() if k != "@context"}
    for e in entities:
        assert not open_data.schema_errors(SCHEMA, e), (e["id"], open_data.schema_errors(SCHEMA, e))


@requires_docker
def test_a_unit_dimension_is_the_unit_text_and_every_other_dimension_a_key(tmp_path):
    entities = decode("ps", "ps1002rs.json", tmp_path)
    assert len({e["id"] for e in entities}) == len(entities) == 132
    e = next(e for e in entities if e["refPeriod"]["value"] == "2015" and e["dimensionKey"]["value"] == "TOTAL-SPECU_RATE-TOTAL")
    assert e["unitText"]["value"] == "v %" and e["indicator"]["value"] == "U_PS_0001" and e["kpiValue"]["value"] == 17.3
    assert e["isPartOf"]["value"] == "https://data.dev.joinedcontext.com/dataset/susr-ps1002rs"
    for e in entities:
        assert not open_data.schema_errors(SCHEMA, e)


def committed() -> list[Path]:
    return sorted(SEED.glob("susr-*/"))


def test_the_committed_folders_are_the_44_topics_whole_and_listed_in_the_catalogue():
    topics = {t["name"]: t for t in datacube.TOPICS}
    assert len(topics) == len(datacube.TOPICS) == 44
    assert [f.name for f in committed()] == sorted(topics), "a susr- seed folder no topic names, or a topic not generated"
    assert set(t["theme"] for t in topics.values()) == set(datacube.THEMES)
    od = json.loads((ROOT / "charts/ckan/files/od-datasets.json").read_text())
    named = set()
    for folder in committed():
        assert 1 <= len(topics[folder.name]["cubes"]) <= 2, folder.name
        assert all(c[:2] == topics[folder.name]["theme"] for c in topics[folder.name]["cubes"]), folder.name
        for f in datacube.MODEL_FILES:
            assert (folder / f).read_text() == (SEED / "susr" / f).read_text(), f"{folder.name}/{f} is not the model's copy"
        slug = yaml.safe_load((folder / "endpoint.yaml").read_text())["spec"]["slug"]
        sources = {s["dataSourceRef"]["name"] for s in yaml.safe_load((folder / "pipeline.yaml").read_text())["spec"]["sources"]}
        files = {yaml.safe_load(p.read_text())["metadata"]["name"] for p in folder.glob("datasource-*.yaml")}
        assert sources == files == {f"susr-{c}" for c in topics[folder.name]["cubes"]}, folder.name
        for name in files:
            assert od[name]["endpoint"] == slug, name
        named |= files
    assert named == {k for k in od if k.startswith("susr-")}


def test_every_committed_seed_file_is_placed_in_the_index_and_its_space_has_a_writer():
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    on_disk = {str(p.relative_to(SEED)) for f in committed() for p in f.iterdir()}
    assert {k for k in index if k.startswith("susr-") and "/" in k} == on_disk
    assert len(set(index.values())) == len(index), "two seed files placed at one path"
    account = yaml.safe_load((SEED / "slovensko-serviceaccount-pipelines.yaml").read_text())
    writers = {r["scope"]["contextSpace"] for r in account["spec"]["roles"] if r["role"] == "space-writer"}
    assert {f.name for f in committed()} <= writers


def test_no_cube_over_the_limit_is_read_whole():
    for folder in committed():
        quota = yaml.safe_load((folder / "pipeline.yaml").read_text())["spec"]["quotas"]["maxMemoryMb"]
        assert quota <= datacube.memory(datacube.CUBE_LIMIT), folder.name


@pytest.mark.parametrize("cells,mb", [(0, 128), (1000, 192), (100_000, 384), (10**9, 2048)])
def test_memory_grows_with_the_largest_cube_and_stays_bounded(cells, mb):
    assert datacube.memory(cells) == mb


def test_every_topic_cube_is_in_the_collection_and_under_the_limit():
    # The TOPICS cubes' collection entries and cell counts (product of the dimension sizes), as
    # `datacube.py --cache` read them on 2026-10-17; the generator refuses a cube over the limit live.
    recorded = json.loads((FIXTURES / "topics-recorded.json").read_text())
    for topic in datacube.TOPICS:
        for code in topic["cubes"]:
            assert code in recorded, f"{topic['name']}: {code} is not in the collection"
            assert recorded[code]["theme"] == topic["theme"] and recorded[code]["cells"] <= datacube.CUBE_LIMIT, code
