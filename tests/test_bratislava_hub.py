"""The Bratislava hub's districts, places and statistics tables become Smart Data Models entities,
checked and counted (T-5274).

Bento runs each committed mapping over answers recorded from data.bratislava.sk's Feature Services
on 2026-10-23 and 2026-10-24 (`fixtures/bratislava/hub/`): the 17 districts, four tables of places
and the 327 statistics tables of the three statistics pipelines (the first 18 rows of each table the
2026-10-24 batch added). The calls to the hub are the
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
                    # A path with a dot ("1._ročníka") is a path to `get`: the dots go out of the key.
                    "mapping": f'root = {json.dumps({k.replace(".", "%2E"): v for k, v in (answers or {}).items()})}'
                    '.get(@path.replace_all(".", "%2E")).or(throw("unasked"))'
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
    answers = statistics()
    indicators, log = run(
        "bratislava-pipeline-statistics-bento.yaml",
        fixture("services.json"),
        answers,
    )
    # The test's three rows on top of the recording: one district too many, one rate out of range
    # and one figure twice (beside the recording's own duplicate in the census tables).
    figures, dropped = reading("statistics", answers)
    assert logged(log) == dropped
    baseline = reading("statistics", fixture("statistics.json"))[1]
    assert dropped["out of range"] == baseline.get("out of range", 0) + 1
    assert dropped["not a city district"] == baseline["not a city district"] + 1
    assert dropped["duplicate"] == baseline.get("duplicate", 0) + 1
    by_id = {i["id"]: i for i in indicators}
    assert len(by_id) == len(indicators) == len(figures)
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
    kinds = {"places": "PointOfInterest"} | {p: "KeyPerformanceIndicator" for p in STATISTICS}
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    for pipeline, kind in kinds.items():
        text = (SEED / f"bratislava-pipeline-{pipeline}-bento.yaml").read_text()
        for key in sorted(set(re.findall(r'\{ ?"(?:key|name)": "([a-z0-9-]+)"', text))):
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


STATISTICS = {"statistics": "district", "statistics-okresy": "okres", "statistics-mesto": "city", "statistics-zsj": "zsj",
              "statistics-obce": "obec", "statistics-zsj-obyvatelia": "zsj", "statistics-zsj-vek": "zsj"}
CITY_DISTRICTS = {
    "stare mesto": "528595", "podunajske biskupice": "529311", "p biskupice": "529311", "ruzinov": "529320",
    "vrakuna": "529338", "nove mesto": "529346", "raca": "529354", "vajnory": "529362", "devinska nova ves": "529371",
    "d n ves": "529371", "dubravka": "529389", "karlova ves": "529397", "devin": "529401", "lamac": "529419",
    "zahorska bystrica": "529427", "z bystrica": "529427", "cunovo": "529435", "jarovce": "529443",
    "petrzalka": "529460", "rusovce": "529494",
}
OKRESY = {f"bratislava {n}": str(100 + i) for i, ns in enumerate([("i", "1"), ("ii", "2"), ("iii", "3"), ("iv", "4"), ("v", "5")], 1) for n in ns}
FOLDED = str.maketrans("áäàâčçďéěëíĺľňóôöőŕřšťúüűůýžèò", "aaaaccdeeeillnoooorrstuuuuyzcn", ".")
YEAR = re.compile(r"(19|20)\d\d")


def fold(text) -> str:
    return " ".join(str(text).lower().translate(FOLDED).split())


def tables(pipeline: str) -> list[dict]:
    text = (SEED / f"bratislava-pipeline-{pipeline}-bento.yaml").read_text()
    start = text.index("let tables = [") + len("let tables = ")
    return json.loads(text[start : text.index("\n        ]", start) + 10])


def years(value) -> str | None:
    v = str(value).strip()
    if re.fullmatch(r"(19|20)\d\d", v):
        return v
    if re.fullmatch(r"(19|20)\d\d\s*[–-]\s*(19|20)\d\d", v):
        return "-".join(m.group() for m in YEAR.finditer(v))
    return None


def number(value) -> float | None:
    if value is None:
        return None
    text = re.sub(r"[\s %]", "", str(value)).replace(",", ".")
    return float(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None


def reading(pipeline: str, answers: dict) -> tuple[dict, dict]:
    """The figures each table of `pipeline` holds by the matrix's rule, read without the mapping:
    {id: value} and the count of dropped figures by reason."""
    figures, dropped, seen = {}, {}, 0
    for t in tables(pipeline):
        for row in answers[t["path"]]["features"]:
            r = row["attributes"]
            if "only" in t and not str(r.get(t["only"][0]) or "").startswith(t["only"][1]):
                continue
            name = fold(r.get(t["area"]) or "") if t.get("area") else "bratislava"
            zsj = str(r.get(t["area"]) or "").strip() if t["areas"] == "zsj" else ""
            code = {
                "district": CITY_DISTRICTS.get(name),
                "okres": OKRESY.get(name),
                "zsj": zsj if re.fullmatch(r"\d{7}", zsj) and str(r.get(t.get("within")) or "").strip()
                in CITY_DISTRICTS.values() and str(r.get(t.get("label")) or "").strip() else None,
                "obec": re.sub(r"[^a-z0-9]+", "-", name).strip("-") or None,
            }.get(t["areas"], "582000" if name == "bratislava" else None)
            if "spans" in t:
                slug = years(t["spans"].get(str(r.get(t["year"]) or "").strip(), ""))
            elif "fixed" in t:
                slug = years(t["fixed"])
            elif "quarter" in t:
                y, q = str(r.get(t["year"]) or "").strip(), str(r.get(t["quarter"]) or "").strip()
                slug = f"{y}-q{q}" if re.fullmatch(r"(19|20)\d\d", y) and q in {"1", "2", "3", "4"} else None
            else:
                slug = years(r.get(t["year"]) or "")
            by = [re.sub(r"[^a-z0-9]+", "-", fold(r.get(c) or "")).strip("-") for c in t.get("by", [])]
            for column, segment, _, low, high in t["values"]:
                n = number(r.get(column))
                reason = (
                    {"district": "not a city district", "okres": "not a Bratislava okres", "zsj": "not a ZSJ of the city",
                     "obec": "no municipality"}.get(t["areas"], "not Bratislava")
                    if code is None
                    else "no period" if slug is None
                    else "no breakdown" if "" in by
                    else "no number" if n is None
                    else "out of range" if (low is not None and n < low) or (high is not None and n > high)
                    else None
                )
                if reason:
                    dropped[reason] = dropped.get(reason, 0) + 1
                    continue
                seen += 1
                figures.setdefault(kpi(".".join([t["name"], segment, *by, code, slug])), n)
    if seen > len(figures):
        dropped["duplicate"] = seen - len(figures)
    return figures, dropped


def logged(log: str) -> dict:
    found = re.search(r"dropped by reason (\{.*?\})\"", log.replace('\\"', '"'))
    assert found, log
    return json.loads(found.group(1))


@requires_docker
@pytest.mark.parametrize("pipeline", STATISTICS)
def test_each_statistics_pipeline_agrees_with_an_independent_reading_of_its_tables(pipeline):
    """Id for id and value for value, the mapping writes what the tables hold by the matrix's rule
    (Research/bratislava-open-data.md 6.4), and drops the same figures for the same reasons; every
    figure is a valid KeyPerformanceIndicator of its pipeline's areas."""
    answers = fixture("statistics.json")
    indicators, log = run(f"bratislava-pipeline-{pipeline}-bento.yaml", fixture("services.json"), answers)
    figures, dropped = reading(pipeline, answers)
    assert {i["id"]: i["kpiValue"]["value"] for i in indicators} == figures
    assert len(indicators) == len(figures)
    assert logged(log) == dropped
    for indicator in indicators:
        valid(indicator, "dataModel.KeyPerformanceIndicator/KeyPerformanceIndicator")
        assert all(indicator["calculationPeriod"]["value"].values())


def test_the_statistics_pipelines_run_one_mapping_text_split_by_area():
    """The three pipelines differ only in their tables, each table in the pipeline of its areas,
    and no table twice."""
    def body(pipeline: str) -> str:
        text = (SEED / f"bratislava-pipeline-{pipeline}-bento.yaml").read_text()
        start = text.index("        let tables = [")
        return text[text.index("pipeline:"): start] + text[text.index("\n        ]", start):]

    assert len({body(p) for p in STATISTICS}) == 1
    keys = [t["name"] for p in STATISTICS for t in tables(p)]
    assert len(keys) == len(set(keys)) == 354
    for pipeline, areas in STATISTICS.items():
        assert {t["areas"] for t in tables(pipeline)} == {areas}
        manifest = yaml.safe_load((SEED / f"bratislava-pipeline-{pipeline}.yaml").read_text())
        assert manifest["spec"]["source"]["dataSourceRef"]["name"] == "bratislava-hub"
        assert manifest["spec"]["output"] == {"type": "KeyPerformanceIndicator", "mode": "upsert"}


@requires_docker
def test_a_city_table_keeps_bratislava_beside_slovakia_and_a_region_table_its_own_okresy():
    """The fixture's own cases: a Bratislava-and-Slovakia table drops the Slovakia rows, a table of
    the whole region the okresy outside Bratislava, a census table a breakdown left as "-"."""
    answers = fixture("statistics.json")
    city, log = run("bratislava-pipeline-statistics-mesto-bento.yaml", fixture("services.json"), answers)
    assert logged(log)["not Bratislava"] > 0
    assert {i["area"]["value"] for i in city} == {"Bratislava"}
    assert all(":582000." not in i["id"] or i["id"].count(".582000.") == 1 for i in city)
    okresy, log = run("bratislava-pipeline-statistics-okresy-bento.yaml", fixture("services.json"), answers)
    assert {i["area"]["value"] for i in okresy} == {f"Bratislava {n}" for n in ("I", "II", "III", "IV", "V")}
    drivers = kpi("pocet-evidovanych-vodicov.pocet-evidovanych-vodicov.101.2013")
    assert {i["id"]: i for i in okresy}[drivers]["kpiValue"]["value"] == 22038


@requires_docker
def test_a_census_table_reads_each_basic_settlement_unit_of_the_city_and_a_model_its_spans():
    """T-5674: a census 2021 table of the basic settlement units (ZSJ) keys each figure by the ZSJ's
    code, names it with its city district and drops a unit outside the city's 17; a growth model of
    the region's municipalities reads its 1991 as 1991-2021 and drops a year it does not span and a
    row without a municipality."""
    answers = copy.deepcopy(fixture("statistics.json"))
    floor = next(v for k, v in answers.items() if k.startswith("Po%C4%8Det%20bytov%20pod%C4%BEa%20celkovej"))["features"]
    malacky = floor[0]["attributes"] | {"Obec___kód": "507423", "Základná_sídelná_jednotka___kód": "1234567"}
    floor.append({"attributes": malacky})
    growth = next(v for k, v in answers.items() if k.startswith("Model_rastu_po%C4%8Dtu"))["features"]
    growth += [{"attributes": dict(growth[0]["attributes"], ROK="2051")}, {"attributes": dict(growth[0]["attributes"], OBEC=" ")}]
    zsj, log = run("bratislava-pipeline-statistics-zsj-bento.yaml", fixture("services.json"), answers)
    assert logged(log) == reading("statistics-zsj", answers)[1]
    assert logged(log)["not a ZSJ of the city"] == reading("statistics-zsj", fixture("statistics.json"))[1].get("not a ZSJ of the city", 0) + 5
    by_id = {i["id"]: i for i in zsj}
    small = by_id[kpi("pocet-bytov-podla-celkovej-plochy-zsj.do-40-m2.2040640.2021")]
    assert small["kpiValue"]["value"] == 5 and small["area"]["value"] == "Hradný svah (Staré Mesto)"
    assert small["calculationPeriod"]["value"] == {"from": "2021-01-01", "to": "2021-12-31"}
    assert not any(".1234567." in i for i in by_id)
    obce, log = run("bratislava-pipeline-statistics-obce-bento.yaml", fixture("services.json"), answers)
    assert logged(log) == reading("statistics-obce", answers)[1]
    assert logged(log)["no period"] == 1 and logged(log)["no municipality"] == 1
    vinicne = {i["id"]: i for i in obce}[kpi("model-rastu-poctu-obyvatelov-v-obciach-bsk.index-rastu.vinicne.1991-2021")]
    assert vinicne["kpiValue"]["value"] == 1.867268937 and vinicne["area"]["value"] == "Viničné"
    assert vinicne["calculationPeriod"]["value"] == {"from": "1991-01-01", "to": "2021-12-31"}
    assert "calculationFrequency" not in vinicne


@requires_docker
def test_the_p5_tables_read_each_zsj_column_as_a_figure_and_each_municipality_by_name():
    """T-5675: a census table of the residents of the basic settlement units (ZSJ) writes one figure
    per column and unit, an empty cell (a unit with nobody or an anonymised count) writes nothing; the
    age table one figure per year of age; a table of the region's municipalities keys each by its
    folded name, and the sports classes table of the okresy drops a row without a year."""
    answers = fixture("statistics.json")
    units, _ = run("bratislava-pipeline-statistics-zsj-obyvatelia-bento.yaml", fixture("services.json"), answers)
    by_id = {i["id"]: i for i in units}
    women = by_id[kpi("obyvatelia-zsj-pohlavie.zeny.2040640.2021")]
    assert women["kpiValue"]["value"] == 110 and women["area"]["value"] == "Hradný svah (Staré Mesto)"
    assert women["name"]["value"] == "Obyvatelia: Ženy, Hradný svah (Staré Mesto), 2021"
    # The castle (Hrad) has no residents: the hub leaves its cells empty and nothing is written.
    assert not any(".2040560." in i for i in by_id if "obyvatelia-zsj-pohlavie" in i)
    ages, _ = run("bratislava-pipeline-statistics-zsj-vek-bento.yaml", fixture("services.json"), answers)
    assert {i["id"] for i in ages} >= {kpi("obyvatelia-zsj-vek.vek-0.2059910.2021"), kpi("obyvatelia-zsj-vek.vek-99.2059910.2021")}
    assert {i["id"]: i for i in ages}[kpi("obyvatelia-zsj-vek.vek-0.2059910.2021")]["kpiValue"]["value"] == 77
    towns, _ = run("bratislava-pipeline-statistics-obce-bento.yaml", fixture("services.json"), answers)
    flats = {i["id"]: i for i in towns}[kpi("bytovy-fond-v-obciach-bsk.pocet-bytov.rohoznik-okres-malacky.1991")]
    assert flats["area"]["value"] == "Rohožník (Okres Malacky)" and flats["kpiValue"]["value"] == 866
    okresy, _ = run("bratislava-pipeline-statistics-okresy-bento.yaml", fixture("services.json"), answers)
    sport = [i for i in okresy if ":ziaci-sportovych-tried-podla-sportu." in i["id"]]
    assert sport and {i["area"]["value"] for i in sport} <= {"Bratislava II", "Bratislava V"}
