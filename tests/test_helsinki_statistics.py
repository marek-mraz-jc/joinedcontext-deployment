"""The Helsinki area statistics as Smart Data Model KeyPerformanceIndicator (T-5258, PL-03, DM-01).

Bento runs the committed processors of `helsinki-pipeline-statistics-bento.yaml` over recorded
answers of stat.hel.fi (`fixtures/helsinki/statistics/`, PXWEB JSON-stat 2.0, fetched on 2026-10-22
with the query the pipeline sends, CC BY 4.0) and over the recorded sub-district register. The
call to stat.hel.fi itself is the one step left out: each case feeds the table, the register and
the recorded answer as the branch hands them on. Every entity is checked against the space's
generated JSON Schema and against the vendored Smart Data Model. The edge cases are those answers
edited in the one place they name.

Without a container runtime the Bento cases skip; the seed cases do not.
"""

import copy
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import open_data
import pytest
import yaml
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-helsinki-statistics")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
MAPPING = HELSINKI / "helsinki-pipeline-statistics-bento.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures/helsinki/statistics"
BENTO = "ghcr.io/warpstreamlabs/bento:1.22.0@sha256:ef674bebae45793c982c350d8f37c2c7661133c1dc65a5517fb977b36dc09841"
PREFIX = "urn:ngsi-ld:KeyPerformanceIndicator:hel.fi:helsinki:stat-"
SDM = "dataModel.KeyPerformanceIndicator/KeyPerformanceIndicator"
THEMES = ["population", "housing", "employment", "income", "education"]
# Two sub-districts of the register: Kruununhaka and Kluuvi.
REGISTER = ["0911101010", "0911101020"]


def steps() -> list:
    return yaml.safe_load(MAPPING.read_text())["pipeline"]["processors"][0]["try"]


def tables() -> dict:
    """The table list of the first step, read by running it over a one-code register."""
    out = bento(steps()[:1], {"features": [{"properties": {"kokotunnus": "0911101010"}}]})
    return {m["table"]["id"]: m["table"] for m in out[0]}


def bento(processors: list, message: dict) -> list:
    """The processors over one message; one output line per message, errored ones dropped."""
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        # A failed step leaves the message flagged, which the runner reports as a failed run; here
        # it is dropped so the case sees nothing written.
        "pipeline": {"processors": processors + [{"catch": [{"mapping": "root = deleted()"}]}]},
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=json.dumps(message), capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def decode(table: dict, answer: dict, register=REGISTER) -> dict | None:
    """The step after the call, as the runner's log and writer see it: the table's summary with
    its entities, or None when the step fails the message."""
    out = bento([steps()[3]], {"table": table, "register": register, "answer": answer})
    return out[0] if out else None


def answer(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def table():
    if open_data.shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return tables()


@pytest.fixture(scope="module")
def unemployment(table):
    return decode(table["alu_tyom_003t"], answer("alu_tyom_003t"))


@requires_docker
def test_the_register_becomes_one_message_per_table_and_an_empty_register_fails_the_run(table):
    # 16 sub-district series and 46 breakdown or region tables (the rework of the review).
    assert len(table) == 62
    assert len({t["id"] for t in table.values()}) == 62
    assert {t["depth"] for t in table.values() if "depth" in t} <= {"basicDistrict", "majorDistrict"}
    assert {t["theme"] for t in table.values()} == set(THEMES)
    # Every table names its dimensions and keeps a breakdown the query can send.
    for t in table.values():
        assert t["path"].endswith(f"/{t['id']}.px") and t["every"] in {"yearly", "quarterly", "monthly"}
        assert t["keep"], t["id"]
    assert bento(steps()[:1], {"features": []}) == []
    # The recorded register (the subdistricts fixture) yields the codes of its sub-districts only.
    recorded = json.loads((ROOT / "tests/fixtures/helsinki/open-data/subdistricts.json").read_text())
    out = bento(steps()[:1], recorded)
    assert out[0][0]["register"] == ["0913301103", "0911102520"]


@requires_docker
def test_every_cell_of_the_newest_period_is_one_indicator_per_area(unemployment):
    assert unemployment["table"] == "alu_tyom_003t" and unemployment["period"] == "2024"
    entities = {e["id"]: e for e in unemployment["entities"]}
    # 197 areas x 2 measures = 394 cells: 54 empty cells and the two of "091 999 Muut" dropped.
    assert len(entities) == 338
    rate = entities[PREFIX + "employment-alu_tyom_003t-ALL-tyottomyysaste-0911101010"]
    assert rate["kpiValue"]["unitCode"] == "P1" and 0 <= rate["kpiValue"]["value"] <= 100
    assert rate["kpiValue"]["observedAt"] == "2024-12-31T00:00:00Z"
    assert rate["calculationPeriod"]["value"] == {"from": "2024-01-01", "to": "2024-12-31"}
    assert rate["calculationFrequency"]["value"] == "yearly"
    assert rate["area"]["value"] == "Kruununhaka" and rate["divisionLevel"]["value"] == "subDistrict"
    assert rate["refArea"] == {"type": "Relationship",
                               "object": "urn:ngsi-ld:AdministrativeArea:hel.fi:helsinki:subdistrict-0911101010"}
    assert rate["name"]["languageMap"]["fi"] == "Työttömät ja työttömyysaste: Työttömyysaste, % – Kruununhaka"
    assert rate["dimensionKey"]["value"] == "Sukupuoli=ALL;Tiedot=tyottomyysaste"
    assert rate["source"]["value"] == "https://stat.hel.fi/pxweb/fi/Aluesarjat/Aluesarjat__tyo__tyom/alu_tyom_003t.px/"
    city = entities[PREFIX + "employment-alu_tyom_003t-ALL-tyottomat-0910000000"]
    assert city["kpiValue"] == {"type": "Property", "value": 44735, "unitCode": "C62", "observedAt": "2024-12-31T00:00:00Z"}
    assert city["divisionLevel"]["value"] == "city" and "refArea" not in city
    levels = {e["divisionLevel"]["value"] for e in entities.values()}
    assert levels == {"city", "majorDistrict", "basicDistrict", "subDistrict", "cityPart"}


@requires_docker
def test_every_indicator_meets_the_space_schema_and_the_smart_data_model(unemployment, table):
    monthly = decode(table["alu_tyom_040k"], answer("alu_tyom_040k"))
    quarterly = decode(table["alu_astuo_039g"], answer("alu_astuo_039g"))
    for entity in unemployment["entities"] + monthly["entities"] + quarterly["entities"]:
        assert open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity) == [], entity["id"]
        assert open_data.sdm_errors(SDM, entity) == [], entity["id"]
        assert entity["id"].startswith(PREFIX)


@requires_docker
def test_a_month_and_a_quarter_carry_their_own_first_and_last_day(table):
    monthly = decode(table["alu_tyom_040k"], answer("alu_tyom_040k"))
    assert monthly["period"] == "2026M08" and len(monthly["entities"]) == 19
    one = monthly["entities"][0]
    assert one["calculationPeriod"]["value"] == {"from": "2026-08-01", "to": "2026-08-31"}
    assert one["kpiValue"]["observedAt"] == "2026-08-31T00:00:00Z" and one["area"]["value"] == "Helsinki"
    assert one["districtCode"]["value"] == "0910000000" and one["divisionLevel"]["value"] == "city"
    quarterly = decode(table["alu_astuo_039g"], answer("alu_astuo_039g"))
    assert quarterly["entities"][0]["calculationPeriod"]["value"] == {"from": "2026-07-01", "to": "2026-09-30"}
    # Square metres of floor area and a count of dwellings, by the measure's own label.
    assert {e["kpiValue"]["unitCode"] for e in quarterly["entities"]} == {"C62", "MTK"}


@requires_docker
def test_out_of_area_out_of_range_duplicate_and_unknown_sub_district_are_dropped_or_flagged_with_a_count(table):
    edited = copy.deepcopy(answer("alu_tyom_003t"))
    alue = edited["dimension"]["Alue"]["category"]
    tiedot = edited["dimension"]["Tiedot"]["category"]
    # An out-of-area point: Kluuvi's code becomes Espoo's.
    alue["index"]["0490000000"] = alue["index"].pop("0911101020")
    alue["label"]["0490000000"] = "049 Espoo"
    # An out-of-range value: Kruununhaka's unemployment rate (the second measure) at 140 %.
    position = alue["index"]["0911101010"] * 2 + 1
    edited["value"][position] = 140
    # A duplicate: two measure codes that collapse to one id ("a+b" and "a_b").
    tiedot["index"] = {"a+b": 0, "a_b": 1}
    tiedot["label"] = {"a+b": "Työttömät", "a_b": "Työttömyysaste, %"}
    out = decode(table["alu_tyom_003t"], edited, register=["0911101080"])
    dropped = out["dropped"]
    assert dropped["not a Helsinki area"] == 2 + 2
    assert dropped["percentage outside 0..100"] == 1
    # Every area's two measures share one id now: the second of each pair is dropped.
    assert dropped["duplicate id"] > 100
    # Every sub-district but Katajanokka (0911101080) is written without its link and counted.
    linked = [e for e in out["entities"] if "refArea" in e]
    assert [e["districtCode"]["value"] for e in linked] == ["0911101080"]
    assert dropped["sub-district not in the register (written without refArea)"] > 0
    assert len(out["entities"]) == len({e["id"] for e in out["entities"]})


@requires_docker
def test_a_dotted_code_is_one_category_and_depth_stops_at_the_basic_districts(table):
    # Building production by quarter: measure codes "1.1" and "1.2" are categories, not paths.
    out = decode(table["alu_ratuo_039k"], answer("alu_ratuo_039k"))
    assert table["alu_ratuo_039k"]["depth"] == "basicDistrict"
    entities = {e["id"]: e for e in out["entities"]}
    city = entities[PREFIX + "housing-alu_ratuo_039k-1.1-YHT-raklkm-0910000000"]
    assert city["name"]["languageMap"]["fi"].startswith("Helsingin rakennustuotanto")
    assert "1.1 Uudet rakennukset" in city["name"]["languageMap"]["fi"]
    assert city["dimensionKey"]["value"] == "raktoimpide=1.1;rakluokka=YHT;Tiedot=raklkm"
    # No sub-district: the sub-district totals are the integrated housing tables.
    assert {e["divisionLevel"]["value"] for e in entities.values()} == {"city", "majorDistrict", "basicDistrict", "cityPart"}
    assert "sub-district not in the register (written without refArea)" not in out["dropped"]
    for entity in out["entities"]:
        assert open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity) == [], entity["id"]
        assert open_data.sdm_errors(SDM, entity) == [], entity["id"]


@requires_docker
def test_a_net_migration_keeps_its_sign_and_a_region_table_keeps_the_helsinki_row(table):
    out = decode(table["alu_vamuu_010w"], answer("alu_vamuu_010w"))
    net = [e for e in out["entities"] if e["dimensionKey"]["value"].endswith("Tiedot=netmuu")]
    assert net and any(e["kpiValue"]["value"] < 0 for e in net)
    assert "negative count or amount" not in out["dropped"]
    assert {e["districtCode"]["value"] for e in out["entities"]} == {"0910000000"}
    # A gross flow is still a count: a negative one is dropped and counted.
    edited = copy.deepcopy(answer("alu_vamuu_010w"))
    edited["value"][0] = -5
    assert decode(table["alu_vamuu_010w"], edited)["dropped"]["negative count or amount"] == 1


@requires_docker
def test_an_empty_or_stale_table_fails_its_message_instead_of_writing(table):
    empty = copy.deepcopy(answer("alu_tyom_040k"))
    empty["value"] = [None] * len(empty["value"])
    assert decode(table["alu_tyom_040k"], empty) is None
    stale = copy.deepcopy(answer("alu_tyom_040k"))
    old = (date.today() - timedelta(days=200)).strftime("%YM%m")
    stale["dimension"]["Kuukausi"]["category"] = {"index": {old: 0}, "label": {old: old}}
    assert decode(table["alu_tyom_040k"], stale) is None


def test_each_theme_is_one_public_endpoint_whose_policy_reads_only_its_own_indicators():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    for theme in THEMES:
        endpoint = yaml.safe_load((HELSINKI / f"helsinki-endpoint-statistics-{theme}.yaml").read_text())
        policy = yaml.safe_load((HELSINKI / f"helsinki-policy-public-statistics-{theme}.yaml").read_text())
        spec = endpoint["spec"]
        assert spec["policyRef"].endswith(f":public-statistics-{theme}")
        assert {"ngsi-ld", "csv", "odata"} <= set(spec["enabledRepresentations"])
        assert spec["catalog"]["license"] == "CC_BY_4_0" and "CC BY 4.0" in spec["catalog"]["attribution"]["en"]
        assert "dimensionKey" in endpoint["metadata"]["description"]["en"]
        assert spec["catalog"]["pipelineRef"] == {"kind": "Pipeline", "name": "statistics"}
        (selector,) = policy["spec"]["information"][0]["entities"]
        assert selector == {"type": "KeyPerformanceIndicator",
                            "idPattern": f"^urn:ngsi-ld:KeyPerformanceIndicator:[a-z0-9.-]+:helsinki:stat-{theme}-[A-Za-z0-9._-]+$"}
        # Read only: no write, delete or update operation.
        assert not [op for op in policy["spec"]["operations"] if op.startswith(("create", "update", "delete", "upsert", "append"))
                    and "Subscription" not in op]
        assert f"helsinki-endpoint-statistics-{theme}.yaml" in index
        assert f"helsinki-policy-public-statistics-{theme}.yaml" in index


def test_the_pipeline_reads_only_the_city_hosts_and_keeps_ten_years_of_history():
    text = MAPPING.read_text()
    assert "url: https://stat.hel.fi/api/v1/fi/Aluesarjat/${! @stat_path }" in text
    calls = next(p for p in steps() if "branch" in p)["branch"]["processors"]
    assert calls[0]["http"]["timeout"] == "30s" and calls[0]["http"]["rate_limit"] == "hel_stat"
    source = yaml.safe_load((HELSINKI / "helsinki-datasource-statistics.yaml").read_text())
    assert source["spec"]["http"]["url"].startswith("https://kartta.hel.fi/ws/geoserver/avoindata/wfs?")
    rates = {r["label"]: r["local"] for r in yaml.safe_load(
        (ROOT / "components/pipeline-runner/streams/resources.yaml").read_text())["rate_limit_resources"]}
    assert rates["hel_stat"] == {"count": 1, "interval": "1s"}
    space = yaml.safe_load((HELSINKI / "helsinki-space.yaml").read_text())
    (rule,) = [r for r in space["spec"]["retention"] if r["entityType"] == "KeyPerformanceIndicator"]
    assert rule["history"] == "P3650D"
