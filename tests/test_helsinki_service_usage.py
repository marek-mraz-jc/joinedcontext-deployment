"""Helsinki service usage as Smart Data Model KeyPerformanceIndicator (T-5258, PL-03, DM-01).

Bento runs the committed processors of `helsinki-pipeline-service-usage-bento.yaml` over recorded
answers (`fixtures/helsinki/service-usage/`, fetched on 2026-10-23): Korkeasaari zoo's visitor API
of the current year, trimmed to August..October, and the first four sites of the city's Matomo
export for September 2026. The web analytics call itself is left out: each case feeds the
answers the step after it sees.
"""

import copy
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import yaml

import open_data
from open_data import requires_docker
from test_helsinki_statistics import HELSINKI, ROOT, SDM, bento

pytestmark = pytest.mark.xdist_group("docker-helsinki-statistics")

MAPPING = HELSINKI / "helsinki-pipeline-service-usage-bento.yaml"
FIXTURES = ROOT / "tests/fixtures/helsinki/service-usage"
PREFIX = "urn:ngsi-ld:KeyPerformanceIndicator:hel.fi:helsinki:stat-services-"


def helsinki_today() -> date:
    """The day the mapping counts in: Europe/Helsinki, a day ahead of UTC late each evening."""
    return datetime.now(ZoneInfo("Europe/Helsinki")).date()


def steps() -> list:
    return yaml.safe_load(MAPPING.read_text())["pipeline"]["processors"][0]["try"]


def decode(zoo: dict, sites: list, month: str = "2026-9") -> dict | None:
    out = bento([steps()[2]], {"zoo": zoo, "web": {"month": month, "sites": sites}})
    return out[0] if out else None


def zoo() -> dict:
    return json.loads((FIXTURES / "zoo-year.json").read_text())


def sites() -> list:
    return json.loads((FIXTURES / "matomo-export-2026-9-sites.json").read_text())


@pytest.fixture(scope="module")
def usage():
    if open_data.shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return decode(zoo(), sites())


@requires_docker
def test_the_newest_ended_day_and_month_of_the_zoo_and_each_site_are_one_indicator(usage):
    entities = {e["id"]: e for e in usage["entities"]}
    # The zoo's newest day in the recording ended before today; the running month is never written.
    day = entities[PREFIX + "zoo-visitors-day-total-0910000000"]
    assert day["kpiValue"] == {"type": "Property", "value": 557, "unitCode": "C62", "observedAt": "2026-10-22T00:00:00Z"}
    assert day["calculationPeriod"]["value"] == {"from": "2026-10-22", "to": "2026-10-22"}
    assert day["calculationFrequency"]["value"] == "daily"
    month = entities[PREFIX + "zoo-visitors-month-total-0910000000"]
    newest_ended = "2026-09" if helsinki_today() < date(2026, 11, 1) else "2026-10"
    assert month["calculationPeriod"]["value"]["from"] == f"{newest_ended}-01"
    # Months of the API count from 0: September is month 8 and its total 29,719.
    if newest_ended == "2026-09":
        assert month["kpiValue"]["value"] == 29719 and month["kpiValue"]["observedAt"] == "2026-09-30T00:00:00Z"
    visits = entities[PREFIX + "web-visits-141-0910000000"]
    assert visits["kpiValue"]["value"] == 1144538 and visits["kpiValue"]["observedAt"] == "2026-09-30T00:00:00Z"
    assert visits["name"]["languageMap"]["fi"] == "HEL Etusivu: käynnit kuukaudessa"
    assert visits["dimensionKey"]["value"] == "idsite=141"
    assert entities[PREFIX + "web-pageviews-141-0910000000"]["kpiValue"]["value"] == 2228869
    # Two zoo series and two per site (4 sites).
    assert len(entities) == 2 + 2 * 4 and usage["dropped"] == {}


@requires_docker
def test_every_indicator_meets_the_space_schema_and_the_smart_data_model(usage):
    for entity in usage["entities"]:
        assert open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity) == [], entity["id"]
        assert open_data.sdm_errors(SDM, entity) == [], entity["id"]
        assert entity["id"].startswith(PREFIX)


@requires_docker
def test_out_of_range_not_a_number_and_duplicate_are_dropped_with_a_count():
    recorded = zoo()
    # An out-of-range day: the newest day of the recording at 95,000 visitors.
    recorded["months"][-1]["days"][-1]["total"] = 95000
    listed = sites() + [sites()[0], {"idsite": 5, "label": "x", "main_url": "", "nb_visits": -3, "nb_pageviews": "many"}]
    out = decode(recorded, listed)
    assert out["dropped"] == {"more than 30000 a period": 1, "duplicate id": 2, "negative count": 1, "not a number": 1}
    ids = [e["id"] for e in out["entities"]]
    assert PREFIX + "zoo-visitors-day-total-0910000000" not in ids and len(ids) == len(set(ids))


@requires_docker
def test_no_site_fails_the_run_and_a_year_with_no_ended_day_writes_no_day():
    assert decode(zoo(), []) is None
    january = copy.deepcopy(zoo())
    # On 1 January the answer holds only the running day: nothing of the zoo is written. The
    # mapping's day is Helsinki's, which is already tomorrow from 21:00Z (22:00Z in winter).
    today = helsinki_today()
    january["year"] = today.year
    january["months"] = [{"month": today.month - 1, "total": 100, "days": [{"day": today.day, "total": 100}]}]
    out = decode(january, sites())
    assert out["dropped"] == {"zoo: no ended day in the answer": 1}
    assert not [e for e in out["entities"] if "zoo-visitors" in e["id"]]


def test_service_usage_is_one_public_endpoint_whose_policy_reads_only_its_own_indicators():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    endpoint = yaml.safe_load((HELSINKI / "helsinki-endpoint-statistics-services.yaml").read_text())
    policy = yaml.safe_load((HELSINKI / "helsinki-policy-public-statistics-services.yaml").read_text())
    spec = endpoint["spec"]
    assert spec["policyRef"].endswith(":public-statistics-services")
    assert {"ngsi-ld", "csv", "odata"} <= set(spec["enabledRepresentations"])
    assert spec["catalog"]["license"] == "CC_BY_4_0" and "CC BY 4.0" in spec["catalog"]["attribution"]["en"]
    assert "dimensionKey" in endpoint["metadata"]["description"]["en"]
    assert spec["catalog"]["pipelineRef"] == {"kind": "Pipeline", "name": "service-usage"}
    (selector,) = policy["spec"]["information"][0]["entities"]
    assert selector == {"type": "KeyPerformanceIndicator",
                        "idPattern": "^urn:ngsi-ld:KeyPerformanceIndicator:[a-z0-9.-]+:helsinki:stat-services-[A-Za-z0-9._-]+$"}
    assert not [op for op in policy["spec"]["operations"] if op.startswith(("create", "update", "delete", "upsert", "append"))
                and "Subscription" not in op]
    for name in ["helsinki-datasource-zoo-visitors.yaml", "helsinki-pipeline-service-usage.yaml",
                 "helsinki-pipeline-service-usage-bento.yaml", "helsinki-endpoint-statistics-services.yaml",
                 "helsinki-policy-public-statistics-services.yaml"]:
        assert name in index


def test_the_pipeline_reads_only_the_two_named_hosts_with_a_timeout():
    source = yaml.safe_load((HELSINKI / "helsinki-datasource-zoo-visitors.yaml").read_text())
    assert source["spec"]["http"]["url"] == "https://korkeasaarenkavijat.onrender.com/api/data/year"
    assert source["spec"]["http"]["timeout"] == "30s"
    calls = next(p for p in steps() if "branch" in p)["branch"]["processors"]
    assert calls[0]["http"]["url"] == (
        "https://datastore.hri.fi/Helsinki/kanslia/kavijaanalytiikka/matomo-export-${! @month }-sites.json")
    assert calls[0]["http"]["timeout"] == "30s"
    assert "4194304" in calls[1]["mapping"] and "4194304" in steps()[0]["mapping"]
