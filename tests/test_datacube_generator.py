"""ŠÚ SR's DATAcube as one public space per theme in project slovensko (T-4390).

`scripts/open-data/datacube.py` reads DATAcube's collection and writes `slovensko/susr-<theme>/`.
Here it runs over a recorded excerpt of the collection (`fixtures/slovensko/datacube/`, fetched on
2026-10-17: themes as, ps and is), with the dimension sizes stubbed, and Bento runs the generated
decoder over two recorded cubes. The committed folders are checked against each other: every
pipeline reads its folder's DataSources, every catalogue row names its folder's Endpoint.
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


def recorded() -> dict[str, list[dict]]:
    return datacube.themes(datacube.datasets(json.loads((FIXTURES / "collection-sk.json").read_text()),
                                             json.loads((FIXTURES / "collection-en.json").read_text())))


def generate(seed: Path, cells: dict[str, int] | None = None):
    themed = recorded()
    cells = cells or {d["code"]: 1000 for ds in themed.values() for d in ds}
    themed, left = datacube.cut(themed, cells)
    files, rows = datacube.render(themed, cells, seed)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return files, rows, left


def test_a_theme_with_fewer_than_three_recent_datasets_is_skipped():
    themed = recorded()
    # is: three datasets, two of them last updated in 2022.
    assert sorted(themed) == ["as", "ps"]
    assert [d["code"] for d in themed["as"]] == ["as1001rs", "as1003rs", "as1007rs"]


def test_a_dataset_without_an_sk_label_takes_the_en_one_and_without_either_the_themes_name():
    by = {d["code"]: d for ds in recorded().values() for d in ds}
    # as1007rs is "Default" in sk.
    assert by["as1007rs"]["title"] == {"sk": "The most frequent causes of death of population",
                                       "en": "The most frequent causes of death of population"}
    assert by["as1001rs"]["title"]["sk"] == "Obyvateľstvo a charakteristiky veku"
    assert by["ps1002rs"]["title"] == datacube.THEMES["ps"][0]


def test_endpoint_slugs_are_stable_across_two_runs(tmp_path):
    first, rows, _ = generate(tmp_path)
    again, rows_again, _ = generate(tmp_path)
    assert first == again and rows == rows_again
    slugs = [yaml.safe_load(first[tmp_path / f"susr-{t}/endpoint.yaml"])["spec"]["slug"] for t in ("as", "ps")]
    assert len(set(slugs)) == 2 and all(re.fullmatch(r"[a-z2-7]{32}", s) for s in slugs)


def test_every_generated_manifest_is_a_slovensko_manifest_of_its_own_space(tmp_path):
    files, _, _ = generate(tmp_path)
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
    files, rows, _ = generate(tmp_path)
    slug = {t: yaml.safe_load(files[tmp_path / f"susr-{t}/endpoint.yaml"])["spec"]["slug"] for t in ("as", "ps")}
    assert set(rows) == {f"susr-{d['code']}" for ds in recorded().values() for d in ds}
    for name, row in rows.items():
        assert row == {"endpoint": slug[name[5:7]], "type": "KeyPerformanceIndicator",
                       "dataset": f"https://data.dev.joinedcontext.com/dataset/{name}", "location": False, "filtered": True}


def test_a_cube_over_the_limit_is_left_out_and_a_theme_left_with_none_goes(tmp_path):
    cells = {"as1001rs": datacube.CUBE_LIMIT + 1, "as1003rs": 10, "as1007rs": 10,
             "ps1002rs": datacube.CUBE_LIMIT + 1, "ps1003rs": datacube.CUBE_LIMIT + 1, "ps1004rs": datacube.CUBE_LIMIT + 1}
    files, rows, left = generate(tmp_path, cells)
    assert sorted(d["code"] for d in left) == ["as1001rs", "ps1002rs", "ps1003rs", "ps1004rs"]
    assert not any("susr-ps" in str(p) for p in files) and "susr-as1001rs" not in rows
    pipeline = yaml.safe_load(files[tmp_path / "susr-as/pipeline.yaml"])
    assert [s["dataSourceRef"]["name"] for s in pipeline["spec"]["sources"]] == ["susr-as1003rs", "susr-as1007rs"]


def test_roles_come_from_the_collection_notes():
    assert datacube.roles({"a_rok": {"note": "Rok"}, "a_obc": {"note": "0 SR + Oblasti + Kraje"}, "a_ukaz": {"note": "Ukazovateľ"},
                           "a_mj": {"note": "Merná jednotka"}, "a_poh": {"note": "Pohlavie"}, "a_x": {}}) == {
        "period": "a_rok", "area": "a_obc", "indicator": "a_ukaz", "unit": "a_mj", "keys": ["a_poh", "a_x"]}
    # A cube nothing dates is not taken.
    assert datacube.roles({"a_poh": {"note": "Pohlavie"}})["period"] is None


def decode(theme: str, fixture: str, tmp_path: Path) -> list[dict]:
    files, _, _ = generate(tmp_path)
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


def test_the_committed_themes_are_whole_and_listed_in_the_catalogue():
    assert len(committed()) == 30
    od = json.loads((ROOT / "charts/ckan/files/od-datasets.json").read_text())
    named = set()
    for folder in committed():
        for f in datacube.MODEL_FILES:
            assert (folder / f).read_text() == (SEED / "susr" / f).read_text(), f"{folder.name}/{f} is not the model's copy"
        slug = yaml.safe_load((folder / "endpoint.yaml").read_text())["spec"]["slug"]
        sources = {s["dataSourceRef"]["name"] for s in yaml.safe_load((folder / "pipeline.yaml").read_text())["spec"]["sources"]}
        files = {yaml.safe_load(p.read_text())["metadata"]["name"] for p in folder.glob("datasource-*.yaml")}
        assert sources == files, folder.name
        for name in files:
            assert od[name]["endpoint"] == slug, name
        named |= files
    assert named == {k for k in od if k.startswith("susr-")}


def test_no_cube_over_the_limit_is_read_whole():
    for folder in committed():
        quota = yaml.safe_load((folder / "pipeline.yaml").read_text())["spec"]["quotas"]["maxMemoryMb"]
        assert quota <= datacube.memory(datacube.CUBE_LIMIT), folder.name


@pytest.mark.parametrize("cells,mb", [(0, 128), (1000, 192), (100_000, 384), (10**9, 2048)])
def test_memory_grows_with_the_largest_cube_and_stays_bounded(cells, mb):
    assert datacube.memory(cells) == mb
