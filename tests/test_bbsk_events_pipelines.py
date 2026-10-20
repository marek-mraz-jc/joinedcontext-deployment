"""The events pipelines of the Banská Bystrica Region, one per kept source (T-4896, PL-43).

Each template runs in Bento over a feed recorded from its publisher on 2026-10-20
(fixtures/bbsk-events/), with the detail pages a template reads served from the recording and the
clock pinned to that day, so the cases do not age. What reaches the Endpoint is checked against
the Event model of T-4895: an event without a name, a start or a GPS point is refused there and
lands in the run's rejected list (PL-62), never in the space.

Without a container runtime the Bento cases skip; the seed and inventory cases do not.
"""

import copy
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
import yaml

pytestmark = pytest.mark.xdist_group("docker-bbsk-events-pipelines")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/bbsk"
EVENTS = ROOT / "seeds/bbsk-events"
FIXTURES = Path(__file__).resolve().parent / "fixtures/bbsk-events"
BENTO = "ghcr.io/warpstreamlabs/bento:1.22.0@sha256:ef674bebae45793c982c350d8f37c2c7661133c1dc65a5517fb977b36dc09841"
#: 2026-10-20T00:00:00Z, the day the fixtures were recorded.
NOW = 1792454400
SCHEMA = json.loads((SEED / "bbsk-podujatia.v1.schema.json").read_text())
VALID = jsonschema.Draft7Validator(
    {**copy.deepcopy(SCHEMA), "$ref": "#/definitions/Event"}
)

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no container runtime for Bento"
)

sys.path.insert(0, str(EVENTS))
import generate


def processors(name: str) -> list:
    return yaml.safe_load(
        (SEED / f"bbsk-pipeline-podujatia-{name}-bento.yaml").read_text()
    )["pipeline"]["processors"]


def offline(steps: list, pages: dict) -> list:
    """The steps with the clock pinned and each detail request answered from the recording."""
    text = json.dumps(steps).replace("let now = timestamp_unix()", f"let now = {NOW}")
    steps = json.loads(text)
    table = json.dumps(
        [{"path": k, "page": v} for k, v in pages.items()], ensure_ascii=False
    )
    for step in steps:
        if "branch" in step:
            assert [next(iter(p)) for p in step["branch"]["processors"]] == [
                "sleep",
                "http",
            ]
            assert step["branch"]["processors"][1]["http"]["url"].startswith("https://")
            step["branch"]["processors"] = [
                {
                    "mapping": (
                        f'let p = {table}.filter(x -> x.path == "/akcia/" + @event_path || x.path == "/events/" + @event_path).index(0).catch(null)\n'
                        'root = if $p == null { throw("no recorded page for %v".format(@event_path)) } else { $p.page }'
                    )
                }
            ]
    return steps


def run(steps: list, payload: str) -> list:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        work = Path(directory)
        work.chmod(0o777)
        (work / "in.txt").write_text(payload)
        (work / "cfg.yaml").write_text(
            yaml.safe_dump(
                {
                    "input": {
                        "file": {"paths": ["/w/in.txt"], "scanner": {"to_the_end": {}}}
                    },
                    "pipeline": {"processors": steps},
                    "output": {"file": {"path": "/w/out.json", "codec": "lines"}},
                },
                allow_unicode=True,
            )
        )
        for item in work.iterdir():
            item.chmod(0o666)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{work}:/w",
                "-w",
                "/w",
                "-e",
                "JC_ORG_DOMAIN=bbsk.sk",
                "-e",
                "JC_SPACE=bbsk-podujatia",
                BENTO,
                "-c",
                "/w/cfg.yaml",
            ],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert "level=error" not in result.stderr, result.stderr[-2000:]
        produced = work / "out.json"
        lines = produced.read_text().splitlines() if produced.is_file() else []
        return [e for line in lines if line.strip() for e in json.loads(line)]


def pipeline(name: str, fixture: str, pages: str | None = None) -> list:
    recorded = json.loads((FIXTURES / "pages" / pages).read_text()) if pages else {}
    return run(offline(processors(name), recorded), (FIXTURES / fixture).read_text())


def key_values(entity: dict) -> dict:
    """The entity as the model's key-values shape, without the NGSI-LD system members."""
    out = {}
    for k, v in entity.items():
        if k in ("scope", "expiresAt"):
            continue
        out[k] = (
            v.get("value", v.get("object"))
            if isinstance(v, dict) and "type" in v and k not in ("id", "type")
            else v
        )
    return out


def wp_event(i: int, day: datetime, title: str | None = None) -> dict:
    return {
        "id": i,
        "link": f"https://www.banskabystrica.sk/podujatia/e-{i}/",
        "title": {"rendered": title or f"Podujatie {i}"},
        "content": {"rendered": "<p>Text</p>"},
        "modified_gmt": "2026-10-01T10:00:00",
        "meta_box": {
            "date_start": day.strftime("%Y-%m-%d"),
            "time_start": "18:00",
            "date_end": None,
            "time_end": None,
            "address_street": "Námestie SNP",
            "address_number": "1",
            "address_locality": "Banská Bystrica",
            "coordinates": {"latitude": "48.7363", "longitude": "19.1462"},
        },
    }


# --- seed and inventory -----------------------------------------------------------------------------------------


def test_the_seed_is_what_the_templates_and_the_inventory_generate():
    assert generate.main(check=True) == 0, "run python3 seeds/bbsk-events/generate.py"


def test_every_kept_source_with_a_template_has_its_pipeline_and_the_rest_are_named():
    rows = [
        r
        for r in csv.DictReader((EVENTS / "sources.csv").open(encoding="utf-8"))
        if r["decision"] == "pipeline"
    ]
    built = {r["check_url"] for r in generate.kept_sources()}
    without = sorted({r["feed_kind"] for r in rows if r["check_url"] not in built})
    # Sliač's RSS holds its date only in free text; T-4896 says which rows wait and why.
    assert without == ["wp-rss"]
    assert len(built) >= 15
    towns = {r["town"] for r in generate.kept_sources()} - {generate.REGION}
    assert len(towns) >= 10


def test_every_http_input_is_https_to_its_inventory_host_with_a_timeout():
    hosts = {
        generate.urlsplit(r["check_url"]).hostname for r in generate.kept_sources()
    }
    for path in SEED.glob("bbsk-datasource-podujatia-*.yaml"):
        http = yaml.safe_load(path.read_text())["spec"]["http"]
        assert (
            http["url"].startswith("https://")
            and generate.urlsplit(http["url"]).hostname in hosts
        ), path.name
        assert http["timeout"] == "30s" and "authorization" not in http, path.name
    for path in SEED.glob("bbsk-pipeline-podujatia-*-bento.yaml"):
        for step in yaml.safe_load(path.read_text())["pipeline"]["processors"]:
            if "branch" in step:
                http = step["branch"]["processors"][1]["http"]
                assert http["url"].split("${!")[0].count("/") >= 4, (
                    path.name
                )  # scheme, host and a fixed path
                assert http["timeout"] == "20s" and step["branch"]["processors"][0] == {
                    "sleep": {"duration": "1s"}
                }


def test_each_source_runs_once_a_day_in_its_own_night_minute_into_the_events_space():
    minutes = []
    for path in SEED.glob("bbsk-pipeline-podujatia-*[!o].yaml"):
        spec = yaml.safe_load(path.read_text())["spec"]
        assert spec["targetEndpoint"] == generate.TARGET and spec["output"] == {
            "type": "Event",
            "mode": "upsert",
        }
        minute, hour, *rest = spec["schedule"].split()
        assert rest == ["*", "*", "*"] and spec["period"] == "24h"
        minutes.append(int(hour) * 60 + int(minute))
    # 00:00-02:59 UTC is 01:00-05:00 in Bratislava in winter and summer alike.
    assert len(set(minutes)) == len(minutes) and max(minutes) < 180


# --- the templates in Bento ---------------------------------------------------------------------------------


@requires_docker
def test_bento_lints_every_generated_stream():
    for path in sorted(SEED.glob("bbsk-pipeline-podujatia-*-bento.yaml")):
        cfg = {
            "input": {"stdin": {}},
            "pipeline": yaml.safe_load(path.read_text())["pipeline"],
            "output": {"stdout": {}},
        }
        result = subprocess.run(
            ["docker", "run", "--rm", "-i", BENTO, "lint", "/dev/stdin"],
            input=yaml.safe_dump(cfg, allow_unicode=True),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, f"{path.name}: {result.stdout}{result.stderr}"


@requires_docker
def test_banska_bystrica_wordpress_events_carry_their_own_gps():
    entities = pipeline("banskabystrica", "banskabystrica-wp-rest.json")
    assert entities and all(
        e["type"] == "Event" and e["scope"] == "/SK/BB/banska-bystrica"
        for e in entities
    )
    for e in entities:
        assert VALID.is_valid(key_values(e)), list(VALID.iter_errors(key_values(e)))
        assert e["expiresAt"] >= "2026-10-20T00:00:00Z"
    assert all("description" in e for e in entities), (
        "CC BY 4.0: the text may be republished"
    )
    text = " ".join(e["description"]["value"] for e in entities)
    assert "vkmk.sk" in (FIXTURES / "banskabystrica-wp-rest.json").read_text()
    assert "@" not in text and "417 37 24" not in text and "413 48 68" not in text


@requires_docker
def test_the_events_calendar_and_ical_sources_give_facts_only():
    for name, fixture in (
        ("visitbanskabystrica", "visitbanskabystrica-tribe.json"),
        ("centralslovakia", "centralslovakia.ics"),
    ):
        entities = pipeline(name, fixture)
        assert entities, name
        for e in entities:
            assert e["startDate"]["value"] and "description" not in e, (name, e)
    ical = {
        e["name"]["value"]: e
        for e in pipeline("centralslovakia", "centralslovakia.ics")
    }
    # "SNG Zvolen" is a venue of the table: the castle's point, scoped to Zvolen.
    assert ical["Moháč 500SK"]["location"]["value"]["coordinates"] == [
        19.1276837,
        48.5729001,
    ]
    assert ical["Moháč 500SK"]["scope"] == "/SK/BB/zvolen"
    # A whole-day DTEND is exclusive: 20261026 is the 25th, the last day.
    assert ical["Moháč 500SK"]["endDate"]["value"] == "2026-10-25"
    assert (
        ical["Coffee Tour Banská Bystrica"]["startDate"]["value"]
        == "2026-11-14T08:30:00+01:00"
    )


@requires_docker
def test_weby_feeds_read_each_event_page_and_place_it_by_the_venue_table():
    lucenec = {
        e["name"]["value"]: e
        for e in pipeline("lucenec", "lucenec-atom.xml", "weby.json")
    }
    apollo = lucenec["SILNÉ REČI"]
    assert apollo["startDate"]["value"] == "2026-11-12T19:00:00+01:00"
    assert apollo["location"]["value"]["coordinates"] == [19.6642043, 48.3319139]
    assert (
        apollo["venue"]["value"] == "Kino Apollo"
        and apollo["scope"] == "/SK/BB/lucenec"
    )
    # A venue nobody checked by hand gives no point, so the model refuses the event (owner 2026-10-20).
    arena = lucenec["Futsalová Liga majstrov"]
    assert "location" not in arena and not VALID.is_valid(key_values(arena))
    zvolen = {
        e["name"]["value"]: e
        for e in pipeline("zvolen", "zvolen-rss1.xml", "weby.json")
    }
    assert zvolen["Pravda v háji"]["startDate"]["value"] == "2026-12-19"


@requires_docker
def test_mec_events_take_their_dates_from_the_pages_json_ld():
    by_name = {
        e["name"]["value"]: e
        for e in pipeline("banskastiavnica", "banskastiavnica-mec.json", "mec.json")
    }
    vedatour = by_name["Vedatour / Vedátor v Art Cafe"]
    assert (
        vedatour["startDate"]["value"] == "2026-10-24T20:30:00+02:00"
        and "endDate" not in vedatour
    )
    assert vedatour["location"]["value"]["coordinates"] == [18.8960644, 48.4585939]
    assert VALID.is_valid(key_values(vedatour))


@requires_docker
def test_an_item_off_the_sources_host_is_never_fetched():
    feed = (
        (FIXTURES / "lucenec-atom.xml")
        .read_text()
        .replace(
            "https://www.lucenec.sk/akcia/silne-reci-1.html",
            "https://www.lucenec.sk@attacker.example/akcia/silne-reci-1.html",
        )
    )
    steps = offline(
        processors("lucenec"), json.loads((FIXTURES / "pages/weby.json").read_text())
    )
    forged = [e for e in run(steps, feed) if e["name"]["value"] == "SILNÉ REČI"]
    assert forged and "startDate" not in forged[0]


@requires_docker
def test_of_150_events_the_100_soonest_upcoming_are_kept():
    day = datetime.fromtimestamp(NOW, UTC)
    past = [wp_event(i, day - timedelta(days=i + 2)) for i in range(30)]
    future = [wp_event(100 + i, day + timedelta(days=i + 1)) for i in range(120)]
    steps = offline(processors("banskabystrica"), {})
    entities = run(steps, json.dumps(list(reversed(past + future))))
    starts = sorted(e["startDate"]["value"] for e in entities)
    assert len(entities) == 100
    assert starts[0].startswith((day + timedelta(days=1)).strftime("%Y-%m-%d"))
    assert starts[-1].startswith((day + timedelta(days=100)).strftime("%Y-%m-%d"))
    assert run(steps, json.dumps(past)) == []


@requires_docker
def test_one_event_announced_by_two_sources_is_one_entity():
    wp = run(
        offline(processors("banskabystrica"), {}),
        json.dumps(
            [
                {
                    **wp_event(
                        1,
                        datetime(2026, 11, 14, tzinfo=UTC),
                        "Richard Autner &#038; band",
                    ),
                    "meta_box": {
                        **wp_event(1, datetime(2026, 11, 14))["meta_box"],
                        "time_start": "19:00",
                    },
                }
            ]
        ),
    )
    tribe = [
        e
        for e in pipeline("visitbanskabystrica", "visitbanskabystrica-tribe.json")
        if e["name"]["value"] == "Richard Autner & band"
    ]
    assert len(wp) == 1 and len(tribe) == 1
    assert wp[0]["id"] == tribe[0]["id"] and wp[0]["id"].startswith(
        "urn:ngsi-ld:Event:bbsk-podujatia:"
    )


@requires_docker
def test_an_event_without_gps_name_or_start_is_refused_by_the_model():
    day = datetime.fromtimestamp(NOW, UTC) + timedelta(days=3)
    no_gps = wp_event(1, day)
    no_gps["meta_box"]["coordinates"] = None
    no_name = {**wp_event(2, day), "title": {"rendered": " "}}
    no_start = wp_event(3, day)
    no_start["meta_box"]["date_start"] = None
    out = {
        e["sourceId"]["value"]: e
        for e in run(
            offline(processors("banskabystrica"), {}),
            json.dumps([no_gps, no_name, no_start, wp_event(4, day)]),
        )
    }
    assert VALID.is_valid(key_values(out["4"]))
    for refused in ("1", "2", "3"):
        assert not VALID.is_valid(key_values(out[refused])), refused
    assert (
        "location" not in out["1"]
        and "name" not in out["2"]
        and "startDate" not in out["3"]
    )
