"""The events pipelines, one per kept source and store: the Banská Bystrica Region's (T-4896, PL-43) and the
national store slovensko-podujatia (T-5047).

Each template runs in Bento over a feed recorded from its publisher on 2026-10-20
(fixtures/bbsk-events/), with the detail pages a template reads served from the recording and the
clock pinned to that day, so the cases do not age. What reaches the Endpoint is checked against
the Event model: an event without a name, a start or a link is refused there and lands in the run's
rejected list (PL-62), never in the space; one without a GPS point or an organizer is kept (owner 2026-10-22).

Without a container runtime the Bento cases skip; the seed and inventory cases do not.
"""

import copy
import csv
import json
import os
import re
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
NATIONAL = ROOT / "components/context-gateway/seed/slovensko"
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

#: CIM 009 4.18: [/] ScopeLevel *(/ScopeLevel), ScopeLevel = unicodeLetter *(letter/digit/_). The broker
#: refuses any other scope, and a refused upsert member answers 403 AccessDenied (T-5051).
SCOPE = re.compile(r"(/[^\W\d_]\w*)+")


def processors(name: str, ns: str = "bbsk") -> list:
    return yaml.safe_load(
        (ROOT / "components/context-gateway/seed" / ns / f"{ns}-pipeline-podujatia-{name}-bento.yaml").read_text()
    )["pipeline"]["processors"]


def template(kind: str, host: str, store: str = "slovensko", region: str = "BA", town: str = "Častá", path: str = "/",
             org_type: str = "municipality") -> list:
    """A kind's generated steps for a made-up row, so a template is tested apart from the inventory."""
    row = {"feed_kind": kind, "host": f"https://{host}", "town": town, "town_slug": generate.slug(town),
           "org_type": org_type, "site": f"https://{host}",
           "region": region, "events_url": f"https://{host}/", "check_url": f"https://{host}{path}", "licence_terms": "no licence stated",
           "scope": generate.REGIONS[region][0], "region_name": generate.REGIONS[region][1]}
    return generate.processors(row, next(s for s in generate.STORES if s["ns"] == store))


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
                        f'let p = {table}.filter(x -> x.path == "/akcia/" + @event_path || x.path == "/events/" + @event_path || x.path == "/" + @event_path || x.path == @event_path).index(0).catch(null)\n'
                        'root = if $p == null { throw("no recorded page for %v".format(@event_path)) } else { $p.page }'
                    )
                }
            ]
    return steps


def run(steps: list, payload: str, space: str = "bbsk-podujatia", refused: bool = False) -> list:
    """The records the steps write; `refused` expects the run to fail with an error and write nothing."""
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
                f"JC_SPACE={space}",
                BENTO,
                "-c",
                "/w/cfg.yaml",
            ],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        # A fixture records some of a feed's pages; the stub's refusal for the others is no error of the template.
        log = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if "no recorded page" not in line)
        assert ("level=error" in log) == refused, log[-2000:]
        if refused:
            return []
        produced = work / "out.json"
        lines = produced.read_text().splitlines() if produced.is_file() else []
        entities = [e for line in lines if line.strip() for e in json.loads(line)]
        for e in entities:
            assert SCOPE.fullmatch(e["scope"]), e["scope"]
        return entities


def pipeline(name: str, fixture: str, pages: str | None = None) -> list:
    recorded = json.loads((FIXTURES / "pages" / pages).read_text()) if pages else {}
    return run(offline(processors(name), recorded), (FIXTURES / fixture).read_text())


def home_point(events_url: str) -> list[float]:
    """[lon, lat] of the venues.csv row homes.csv names for a source."""
    events = ROOT / "seeds/bbsk-events"
    (home,) = [h for h in csv.DictReader((events / "homes.csv").open(encoding="utf-8")) if h["events_url"] == events_url]
    (row,) = [v for v in csv.DictReader((events / "venues.csv").open(encoding="utf-8"))
              if (v["town"], v["match"]) == (home["town"], home["match"])]
    return [float(row["lon"]), float(row["lat"])]


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
        for f in generate.INVENTORIES
        for r in csv.DictReader((EVENTS / f).open(encoding="utf-8"))
        if r["decision"] == "pipeline"
    ]
    built = {r["check_url"] for r in generate.kept_sources()}
    without = sorted({r["feed_kind"] for r in rows if r["check_url"] not in built})
    # Free-text dates (wp-rss, joomla-rss, most wp-rest event pages) need one parser per site, and the runner
    # reads https only (Betliar's iCal is http); T-5047 says which rows wait and why.
    assert without == ["ical", "joomla-rss", "wp-rest", "wp-rss"]
    towns = {r["town"] for r in generate.kept_sources()} - {generate.REGION}
    assert len(towns) >= 60


def test_the_national_store_reads_at_least_100_sources_from_all_eight_regions():
    rows = generate.store_rows(generate.STORES[1])
    assert len(rows) >= 100
    by_region = {code: sum(r["region"] == code for r in rows) for code in generate.REGIONS}
    assert all(n >= 6 for n in by_region.values()), by_region
    assert len(list(p for p in NATIONAL.glob("slovensko-pipeline-podujatia-*.yaml") if not p.name.endswith("-bento.yaml"))) == len(rows)


def test_every_kept_source_names_its_licence_and_robots_reading():
    for row in generate.kept_sources():
        assert row["licence_terms"].strip(), row["name"]
        assert row["robots_allows"].startswith("y"), row["name"]
        assert row["read_on"] >= "2026-10-20", row["name"]


def test_every_http_input_is_https_to_its_inventory_host_with_a_timeout():
    hosts = {
        generate.urlsplit(r["check_url"]).hostname for r in generate.kept_sources()
    }
    for path in [*SEED.glob("bbsk-datasource-podujatia-*.yaml"), *NATIONAL.glob("slovensko-datasource-podujatia-*.yaml")]:
        http = yaml.safe_load(path.read_text())["spec"]["http"]
        assert (
            http["url"].startswith("https://")
            and generate.urlsplit(http["url"]).hostname in hosts
        ), path.name
        assert http["timeout"] == "30s" and "authorization" not in http, path.name
    for path in [*SEED.glob("bbsk-pipeline-podujatia-*-bento.yaml"), *NATIONAL.glob("slovensko-pipeline-podujatia-*-bento.yaml")]:
        for step in yaml.safe_load(path.read_text())["pipeline"]["processors"]:
            if "branch" in step:
                http = step["branch"]["processors"][1]["http"]
                # The source's own host, fixed: the item's path is checked by the request_map before the request.
                fixed = http["url"].split("${!")[0]
                assert generate.urlsplit(fixed).hostname in hosts and fixed.count("/") >= 3, path.name
                # One request a second, three or ten where the CMS's robots.txt asks Crawl-Delay 3 (Lego) or 10 (TUZVO).
                assert http["timeout"] == "20s" and step["branch"]["processors"][0] in (
                    {"sleep": {"duration": "1s"}}, {"sleep": {"duration": "3s"}}, {"sleep": {"duration": "10s"}}
                )


def test_each_source_runs_once_a_day_in_its_own_night_minute_into_the_events_space():
    minutes = []
    for path in (p for p in SEED.glob("bbsk-pipeline-podujatia-*.yaml") if not p.name.endswith("-bento.yaml")):
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


def test_each_national_feed_runs_every_3_hours_and_each_village_calendar_daily_in_its_own_minute():
    target = generate.STORES[1]["target"]
    assert target == "urn:ngsi-ld:Endpoint:joinedcontext.com:slovensko-podujatia:slovensko-podujatia-zapis"
    starts = {"3h": [], "24h": []}
    for path in (p for p in NATIONAL.glob("slovensko-pipeline-podujatia-*.yaml") if not p.name.endswith("-bento.yaml")):
        spec = yaml.safe_load(path.read_text())["spec"]
        kind = yaml.safe_load(NATIONAL.joinpath(path.name.replace("-pipeline-", "-datasource-")).read_text())["metadata"]["title"]["en"]
        daily = kind.endswith(("(lego-html)", "(weby-feed)", "(umb-cms)", "(drupal-kalendar)"))
        assert spec["targetEndpoint"] == target and spec["period"] == ("24h" if daily else "3h"), path.name
        minute, hour, *rest = spec["schedule"].split()
        assert rest == ["*", "*", "*"], path.name
        if daily:
            assert hour.isdigit(), path.name
        else:
            assert hour.endswith("-23/3"), path.name
        starts[spec["period"]].append(int(hour.split("-")[0]) * 60 + int(minute))
    assert len(set(starts["3h"])) == len(starts["3h"]) and max(starts["3h"]) < 180
    assert len(set(starts["24h"])) == len(starts["24h"]) and max(starts["24h"]) < 1440


# --- the templates in Bento ---------------------------------------------------------------------------------


@requires_docker
def test_bento_lints_every_generated_stream():
    """One Bento lint over every stream: a container per stream took minutes for the ~290 generated pipelines."""
    paths = sorted([*SEED.glob("bbsk-pipeline-podujatia-*-bento.yaml"), *NATIONAL.glob("slovensko-pipeline-podujatia-*-bento.yaml")])
    assert paths
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        work = Path(directory)
        work.chmod(0o777)
        for path in paths:
            cfg = {
                "input": {"stdin": {}},
                "pipeline": yaml.safe_load(path.read_text())["pipeline"],
                "output": {"stdout": {}},
            }
            (work / path.name).write_text(yaml.safe_dump(cfg, allow_unicode=True))
            (work / path.name).chmod(0o666)
        result = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{work}:/w", BENTO, "lint", *(f"/w/{p.name}" for p in paths)],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"


@requires_docker
def test_banska_bystrica_wordpress_events_carry_their_own_gps():
    entities = pipeline("banskabystrica", "banskabystrica-wp-rest.json")
    assert entities and all(
        e["type"] == "Event" and e["scope"] == "/SK/BB/banska_bystrica"
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
    # A venue nobody checked by hand gives no point, never the town's centre; the event is kept (owner 2026-10-22).
    arena = lucenec["Futsalová Liga majstrov"]
    assert "location" not in arena and VALID.is_valid(key_values(arena))
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
    # The forged item's page is never read, so it has no date and is refused (T-5215); the others are written.
    out = run(steps, feed)
    assert out and all(e["name"]["value"] != "SILNÉ REČI" for e in out)


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
def test_an_event_without_name_or_start_is_refused_and_one_without_gps_kept():
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
    assert VALID.is_valid(key_values(out["4"])) and VALID.is_valid(key_values(out["1"]))
    assert not VALID.is_valid(key_values(out["2"])) and "name" not in out["2"]
    # A record without a start is never stored without a date (owner 2026-10-22, T-5215); one without GPS that
    # names no place takes the town office's point (homes.csv).
    assert "3" not in out
    assert out["1"]["location"]["value"]["coordinates"] == home_point("https://www.banskabystrica.sk/podujatia/")


# --- the national space (T-4898) ----------------------------------------------------------------------------


def test_every_source_writes_its_own_region_and_only_bbsk_sources_reach_the_regions_store():
    """A source elsewhere never writes under /SK/BB, and the scope comes from the inventory row, not from the
    feed; the region's own store holds its own sources alone (T-5047)."""
    regions = {r["region"] for r in generate.kept_sources()}
    assert regions == set(generate.REGIONS)
    bbsk = {p.name for p in SEED.glob("bbsk-pipeline-podujatia-*-bento.yaml")}
    assert bbsk == {f"bbsk-pipeline-{r['name']}-bento.yaml" for r in generate.kept_sources() if r["region"] == "BBSK"}
    for row in generate.kept_sources():
        code, name = generate.REGIONS[row["region"]]
        text = (NATIONAL / f"slovensko-pipeline-{row['name']}-bento.yaml").read_text()
        assert (
            f'"scope": if $town != null {{ "/SK/{code}" + "/" + $town.replace_all("-", "_") }}'
            in text
        ), row["name"]
        assert f'"addressRegion": "{name}"' in text, row["name"]
        assert ('"/SK/BB"' in text) == (row["region"] == "BBSK"), row["name"]


def test_every_scope_a_pipeline_can_write_is_a_valid_ngsi_ld_scope():
    """The town comes from the inventory row or the venue table, both slugs with hyphens; the
    template writes them with "_", so the broker takes the scope (T-5051: six sources got 403)."""
    towns = {r["town_slug"] for r in generate.kept_sources()} - {None}
    with (EVENTS / "venues.csv").open(encoding="utf-8") as f:
        towns |= {v["town"] for v in csv.DictReader(f)}
    assert "banska-bystrica" in towns and "velky-krtis" in towns
    for row in generate.kept_sources():
        code, _ = generate.REGIONS[row["region"]]
        assert SCOPE.fullmatch(f"/SK/{code}")
    for town in towns:
        assert SCOPE.fullmatch("/SK/BB/" + town.replace("-", "_")), town


@requires_docker
def test_an_events_calendar_time_without_seconds_is_read():
    """visithumenne.sk writes "2026-11-03 19:00": before T-5051 the template failed on it and the
    unchanged object reached the tail, which wants an array ("expected array value, got object")."""
    feed = json.loads((FIXTURES / "visitbanskabystrica-tribe.json").read_text())
    feed["events"][0].update(
        start_date="2026-11-03 19:00", end_date="2026-11-03 20:40:00"
    )
    entities = run(offline(processors("visithumenne", "slovensko"), {}), json.dumps(feed), "slovensko-podujatia")
    assert [e["startDate"]["value"] for e in entities] == ["2026-11-03T19:00:00+01:00"]
    assert entities[0]["endDate"]["value"] == "2026-11-03T20:40:00+01:00"
    assert entities[0]["scope"] == "/SK/PO/humenne"


def test_each_dataset_lists_its_sources_with_their_licence():
    def listed(file: str) -> dict:
        spec = yaml.safe_load((SEED / file).read_text())["spec"]
        return {s["url"]: s for s in spec["catalog"]["source"]}

    kept = generate.kept_sources()
    national = {s["url"]: s for s in yaml.safe_load((NATIONAL / "slovensko-endpoint-podujatia.yaml").read_text())["spec"]["catalog"]["source"]}
    region = listed("bbsk-endpoint-podujatia.yaml")
    assert set(national) == {r["events_url"] for r in kept}
    assert set(region) == {r["events_url"] for r in kept if r["region"] == "BBSK"}
    for row in kept:
        text = national[row["events_url"]]["description"]["en"]
        if row["licence_terms"].startswith("CC-BY"):
            assert "licence CC-BY" in text, row["name"]
        else:
            assert "no licence stated, facts only" in text, row["name"]


@requires_docker
def test_a_source_outside_the_region_lands_in_its_own_region_at_its_venue():
    # Recorded 2026-10-21 (start_date=now): four events at Dom umenia, one with no venue.
    out = {
        e["sourceId"]["value"]: e
        for e in run(offline(processors("domumenia-piestany", "slovensko"), {}),
                     (FIXTURES / "piestany-tribe.json").read_text(), "slovensko-podujatia")
    }
    assert len(out) == 5
    placed = [e for e in out.values() if "location" in e]
    assert len(placed) == 4
    for e in placed:
        assert e["scope"] == "/SK/TT/piestany"
        assert e["location"]["value"]["coordinates"] == [17.8400391, 48.5923954]
        assert e["address"]["value"]["addressRegion"] == "Trnavský kraj"
        assert "description" not in e  # no licence stated: facts only
        assert VALID.is_valid(key_values(e)), e["name"]
    (unplaced,) = [e for e in out.values() if "location" not in e]
    assert VALID.is_valid(key_values(unplaced))


# --- the national store's adapters (T-5047) -----------------------------------------------------------------


def national(kind: str, host: str, payload: str, pages: str | None = None, refused: bool = False, path: str = "/",
             org_type: str = "municipality") -> list:
    recorded = json.loads((FIXTURES / "pages" / pages).read_text()) if pages else {}
    return run(offline(template(kind, host, path=path, org_type=org_type), recorded), payload, "slovensko-podujatia", refused)


@requires_docker
def test_lsvr_events_take_their_dates_from_the_pages_json_ld_written_with_a_space():
    # Recorded 2026-10-21 from casta.sk: LSVR writes "2026-12-31 23:59:00", Bratislava's wall time.
    out = {e["name"]["value"]: e for e in national("lsvr-rest", "www.casta.sk", (FIXTURES / "casta-lsvr.json").read_text(), "lsvr.json")}
    assert len(out) == 3
    toast = out["Novoročný prípitok v obci"]
    assert toast["startDate"]["value"] == "2026-12-31T23:59:00+01:00"
    assert toast["endDate"]["value"] == "2027-01-01T03:00:00+01:00"
    assert toast["id"].startswith("urn:ngsi-ld:Event:slovensko-podujatia:") and toast["scope"] == "/SK/BA/casta"
    # Častá's events name no place of their own, so they take the village office's point (homes.csv, T-5215),
    # never the village centre (owner 2026-10-20).
    office = home_point("https://www.casta.sk/")
    assert all(e["location"]["value"]["coordinates"] == office for e in out.values())


@requires_docker
def test_a_printed_date_with_a_leading_zero_day_or_month_is_read():
    # int64() reads "08" and "09" as octal: before T-5287 each such event failed its branch and was never written.
    printed = {"a": "09. 08. 2026", "b": "08. 09. 2026", "c": "01. 10. 2026"}
    items = [{"id": i, "link": f"https://www.casta.sk/events/{k}/", "title": {"rendered": f"Podujatie {k}"}, "modified_gmt": None}
             for i, k in enumerate(printed)]
    pages = {f"/events/{k}/": '<ul class="post__info"><li class="post__info-item post__info-item--date">'
             f'<p class="post__info-item-text">{v}</p></li></ul>' for k, v in printed.items()}
    # The clock sits before every date, so none of them is past and dropped.
    steps = json.loads(json.dumps(offline(template("lsvr-rest", "www.casta.sk"), pages)).replace(
        f"let now = {NOW}", f"let now = {int(datetime(2026, 8, 1, tzinfo=UTC).timestamp())}"))
    out = {e["name"]["value"]: e["startDate"]["value"] for e in run(steps, json.dumps(items), "slovensko-podujatia")}
    assert out == {"Podujatie a": "2026-08-09", "Podujatie b": "2026-09-08", "Podujatie c": "2026-10-01"}


@requires_docker
def test_a_national_event_leaves_a_day_after_its_end_or_8_hours_after_the_last_run_that_saw_it():
    out = {e["name"]["value"]: e for e in national("lsvr-rest", "www.casta.sk", (FIXTURES / "casta-lsvr.json").read_text(), "lsvr.json")}
    lease = datetime.fromtimestamp(NOW + 8 * 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Every event here ends later than the lease, so the lease decides: a source that drops it ends it in 8 h.
    assert {e["expiresAt"] for e in out.values()} == {lease}
    day = datetime.fromtimestamp(NOW, UTC)

    def ended(hours_ago: int) -> list:
        item = [{"id": 9, "link": "https://www.casta.sk/events/vcera/", "title": {"rendered": "Včera"}, "modified_gmt": None}]
        at = lambda h: (day - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        page = '<script type="application/ld+json">{"@type":"Event","startDate":"%s","endDate":"%s"}</script>' % (
            at(hours_ago + 2), at(hours_ago))
        return run(offline(template("lsvr-rest", "www.casta.sk"), {"/events/vcera/": page}), json.dumps(item), "slovensko-podujatia")

    # An event that ended 20 hours ago stays until a day after its end, earlier than the lease; one that ended
    # 25 hours ago is past its day and never loaded.
    (yesterday,) = ended(20)
    assert yesterday["expiresAt"] == (day + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ended(25) == []


@requires_docker
def test_a_region_event_leaves_52_hours_after_the_last_run_that_saw_it():
    # T-5081: without a lease a region event the model now refuses (or its source dropped) stayed half until its end.
    steps = template("lsvr-rest", "www.casta.sk", store="bbsk", region="BBSK")
    pages = json.loads((FIXTURES / "pages" / "lsvr.json").read_text())
    out = run(offline(steps, pages), (FIXTURES / "casta-lsvr.json").read_text())
    lease = datetime.fromtimestamp(NOW + 52 * 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert out and {e["expiresAt"] for e in out} == {lease}


@requires_docker
def test_a_wordpress_list_that_is_no_list_fails_the_run_and_an_empty_one_writes_nothing():
    national("lsvr-rest", "www.casta.sk", '{"code":"rest_no_route"}', refused=True)
    assert national("lsvr-rest", "www.casta.sk", "[]") == []


@requires_docker
def test_an_item_off_the_sources_host_or_with_dot_segments_is_never_fetched():
    items = [{"id": 1, "link": "https://www.casta.sk@attacker.example/events/x/", "title": {"rendered": "A"}},
             {"id": 2, "link": "https://www.casta.sk/events/../../etc/", "title": {"rendered": "B"}}]
    # Neither page is read, so neither has a date: both are refused (T-5215).
    assert national("lsvr-rest", "www.casta.sk", json.dumps(items)) == []


@requires_docker
def test_an_rss_feed_of_event_posts_reads_each_posts_json_ld():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>Podujatia</title>
<item><title>Novoročný prípitok v obci</title><link>https://www.casta.sk/events/novorocny-pripitok-v-obci-2/</link><guid>p-1</guid></item>
</channel></rss>"""
    (e,) = national("wp-rss-jsonld", "www.casta.sk", rss, "lsvr.json")
    assert e["startDate"]["value"] == "2026-12-31T23:59:00+01:00" and e["sourceId"]["value"] == "p-1"
    national("wp-rss-jsonld", "www.casta.sk", "<html>not a feed</html>", refused=True)


@requires_docker
def test_lego_events_read_each_pages_machine_readable_time_and_venue():
    # Recorded 2026-10-21 from jaslovske-bohunice.sk (Lego CMS); the Christmas market page is that page with
    # its title and time changed, so one event is past and one upcoming on the fixtures' day.
    html = (FIXTURES / "jaslovske-bohunice-lego.html").read_text()
    out = national("lego-html", "www.jaslovske-bohunice.sk", html, "lego.json", path="/zivot-v-obci/najblizsie-podujatia/")
    # The off-host and the news link are never read; the seniors' afternoon of 18 October stays its day of grace.
    by_name = {e["name"]["value"]: e for e in out}
    assert set(by_name) == {"Vianočné trhy", "Posedenie dôchodcov"}
    market = by_name["Vianočné trhy"]
    assert market["name"]["value"] == "Vianočné trhy"
    assert market["startDate"]["value"] == "2026-12-12T10:00:00+01:00"
    assert market["endDate"]["value"] == "2026-12-12T18:00:00+01:00"
    assert market["venue"]["value"] == "Športový areál ŠK Blava - športová hala č.2"
    assert market["eventCategory"]["value"] == "ostatné (akcie pre seniorov)"
    assert "description" not in market  # no licence stated: facts only
    assert national("lego-html", "www.jaslovske-bohunice.sk", "<html><body>Žiadne podujatia</body></html>") == []


@requires_docker
def test_a_page_with_its_events_as_json_ld_gives_each_event_and_a_page_without_json_ld_fails():
    page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},
{"@type":"MusicEvent","name":"Lúčnica: Vianoce","startDate":"2026-12-20T19:00","url":"https://www.lucnica.sk/vianoce",
 "location":{"@type":"Place","name":"Istropolis","address":{"@type":"PostalAddress","streetAddress":"Trnavské mýto 1",
 "addressLocality":"Bratislava"},"geo":{"latitude":48.1601,"longitude":17.1290}}}]}</script>
<script type="application/ld+json">not json</script></html>"""
    (e,) = national("jsonld", "www.lucnica.sk", page)
    assert e["startDate"]["value"] == "2026-12-20T19:00:00+01:00"
    assert e["location"]["value"]["coordinates"] == [17.129, 48.1601]
    assert e["address"]["value"]["streetAddress"] == "Trnavské mýto 1" and VALID.is_valid(key_values(e))
    national("jsonld", "www.lucnica.sk", "<html><body>Warning: require_once()</body></html>", refused=True)


# --- organizer and link (T-5081) -----------------------------------------------------------------------------


def tribe_event(i: int, organizer: list | dict, url: str | None = "default") -> dict:
    day = (datetime.fromtimestamp(NOW, UTC) + timedelta(days=5)).strftime("%Y-%m-%d")
    return {
        "id": i, "title": f"Koncert {i}", "start_date": f"{day} 19:00:00", "end_date": f"{day} 21:00:00", "all_day": False,
        "url": f"https://www.casta.sk/udalost/koncert-{i}/" if url == "default" else url,
        "venue": {"venue": "Kultúrny dom", "address": "Hlavná 1", "city": "Častá", "geo_lat": "48.39", "geo_lng": "17.35"},
        "organizer": organizer,
    }


@requires_docker
def test_the_events_calendar_organizer_gives_its_name_and_web_site_and_never_a_contact():
    feed = {"events": [
        tribe_event(1, [{"organizer": "Stredoslovenské múzeum", "website": "https://www.stredoslovenskemuzeum.sk",
                         "email": "info@muzeum.sk", "phone": "+421 48 412 58 97"}]),
        tribe_event(2, [{"organizer": "Ján Novák, tel. 0905 123 456, jan.novak@example.sk", "website": "mailto:jan@example.sk"}]),
        tribe_event(3, []),
    ]}
    out = {e["sourceId"]["value"]: e for e in national("tribe-rest", "www.casta.sk", json.dumps(feed))}
    assert out["1"]["organizer"]["value"] == {"name": "Stredoslovenské múzeum", "url": "https://www.stredoslovenskemuzeum.sk"}
    # A contact typed into the name is cut out; a mailto: is no web site.
    assert out["2"]["organizer"]["value"] == {"name": "Ján Novák"}
    # The feed names no organizer: the municipality whose calendar it is runs the event.
    assert out["3"]["organizer"]["value"] == {"name": "Obec Častá", "url": "https://www.casta.sk"}
    for e in out.values():
        assert VALID.is_valid(key_values(e)), list(VALID.iter_errors(key_values(e)))
        assert "@" not in json.dumps(e["organizer"]) and "0905" not in json.dumps(e["organizer"])


@requires_docker
def test_an_aggregators_event_keeps_no_organizer_and_is_kept():
    feed = {"events": [tribe_event(1, []), tribe_event(2, {"organizer": "Divadlo J. G. Tajovského", "website": ""})]}
    out = {e["sourceId"]["value"]: e for e in national("tribe-rest", "www.casta.sk", json.dumps(feed),
                                                       org_type="tourism organisation (OOCR Test)")}
    assert "organizer" not in out["1"] and VALID.is_valid(key_values(out["1"]))
    assert out["2"]["organizer"]["value"] == {"name": "Divadlo J. G. Tajovského"} and VALID.is_valid(key_values(out["2"]))


@requires_docker
def test_an_event_without_its_own_page_links_to_the_organizers_listing_page():
    feed = {"events": [tribe_event(1, [], url=None), tribe_event(2, [], url="javascript:alert(1)")]}
    for e in national("tribe-rest", "www.casta.sk", json.dumps(feed)):
        assert e["url"]["value"] == "https://www.casta.sk/" and VALID.is_valid(key_values(e))


@requires_docker
def test_json_ld_organizer_and_weby_usporiadatel_and_ical_organizer_are_read():
    page = """<script type="application/ld+json">{"@type":"Event","name":"Prednáška","startDate":"2026-11-20T17:00",
 "url":"https://www.lucnica.sk/p","organizer":[{"@type":"Organization","name":"Univerzita Mateja Bela","url":"https://www.umb.sk",
 "email":"x@umb.sk"}],"location":{"name":"Aula","geo":{"latitude":48.73,"longitude":19.15}}}</script>"""
    (e,) = national("jsonld", "www.lucnica.sk", page)
    assert e["organizer"]["value"] == {"name": "Univerzita Mateja Bela", "url": "https://www.umb.sk"}
    # MEC writes the café that runs the evening as its organizer.
    mec = {x["name"]["value"]: x for x in pipeline("banskastiavnica", "banskastiavnica-mec.json", "mec.json")}
    assert mec["Vedatour / Vedátor v Art Cafe"]["organizer"]["value"]["name"] == "Art Café"
    lucenec = {x["name"]["value"]: x for x in pipeline("lucenec", "lucenec-atom.xml", "weby.json")}
    assert lucenec["SILNÉ REČI"]["organizer"]["value"] == {"name": "Mesto Lučenec"}
    ics = "\r\n".join(["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:u-1", "SUMMARY:Jarmok", "DTSTART:20261125T090000Z",
                        'ORGANIZER;CN="Mesto Zvolen":mailto:podatelna@zvolen.sk', "GEO:48.57;19.12",
                        "URL:https://www.zvolen.sk/jarmok", "END:VEVENT", "END:VCALENDAR"])
    (ev,) = national("ical", "www.zvolen.sk", ics)
    assert ev["organizer"]["value"] == {"name": "Mesto Zvolen"} and "podatelna" not in json.dumps(ev)
    assert VALID.is_valid(key_values(ev))


def test_every_source_names_an_organizer_unless_it_is_an_aggregator():
    for row in generate.kept_sources():
        organizer = generate.organizer(row)
        if generate.AGGREGATORS.match(row["org_type"]):
            assert organizer is None, row["name"]
        else:
            assert organizer and organizer["name"] and organizer["url"].startswith("https://"), row["name"]


# --- HTML kinds of the universities and geocoded venues (T-5083) --------------------------------------------


def bbsk_html(kind: str, host: str, town: str, path: str, org_type: str, payload: str, pages: str) -> dict:
    steps = template(kind, host, store="bbsk", region="BBSK", town=town, path=path, org_type=org_type)
    recorded = json.loads((FIXTURES / "pages" / pages).read_text())
    return {e["name"]["value"]: e for e in run(offline(steps, recorded), payload)}


@requires_docker
def test_umb_events_read_each_pages_event_table_and_place_it_by_the_geocoded_venue():
    # Recorded 2026-10-21 from umb.sk; the third page has a made-up contact row added, which is never read.
    out = bbsk_html("umb-cms", "www.umb.sk", "Banská Bystrica", "/kalendar-udalosti/",
                    "university (Univerzita Mateja Bela v Banskej Bystrici)",
                    (FIXTURES / "umb-kalendar.html").read_text(), "umb.json")
    # The menu link without an h3 title, the off-host and the off-path links are never read.
    assert set(out) == {"GAUDEAMUS BRNO", "Školenie: Od konfliktu k porozumeniu: Ako vystúpiť z dramatického trojuholníka",
                        "Občianske fórum 2026"}
    school = out["Školenie: Od konfliktu k porozumeniu: Ako vystúpiť z dramatického trojuholníka"]
    assert school["startDate"]["value"] == "2026-10-27T13:30:00+01:00"
    assert school["endDate"]["value"] == "2026-10-27T15:30:00+01:00"
    assert school["organizer"]["value"] == {"name": "Centrum podpory a ďalšieho vzdelávania UMB"}
    # The room text matches the venue geocoded from its address, never the town's centre.
    assert school["location"]["value"]["coordinates"] == [19.1376321, 48.7395768]
    assert school["url"]["value"].startswith("https://www.umb.sk/kalendar-udalosti/skolenie-")
    forum = out["Občianske fórum 2026"]
    assert VALID.is_valid(key_values(forum)), list(VALID.iter_errors(key_values(forum)))
    assert "nováková" not in json.dumps(forum, ensure_ascii=False).lower() and "@" not in json.dumps(forum)
    # A fair in Brno: no venue of Banská Bystrica's table, so no point; the event is kept. "Iné" is no
    # organizer: the university whose calendar it is stands in.
    brno = out["GAUDEAMUS BRNO"]
    assert brno["address"]["value"]["addressLocality"] == "Brno" and "location" not in brno
    assert VALID.is_valid(key_values(brno))
    assert brno["organizer"]["value"] == {"name": "Univerzita Mateja Bela v Banskej Bystrici", "url": "https://www.umb.sk"}


@requires_docker
def test_tuzvo_events_come_from_this_and_the_next_months_list_without_the_persons_named():
    # Recorded 2026-10-21 from tuzvo.sk, the persons' names replaced; November repeats one October event.
    out = bbsk_html("drupal-kalendar", "www.tuzvo.sk", "Zvolen", "/sk/kalendar-podujati",
                    "university (Technická univerzita vo Zvolene)",
                    (FIXTURES / "tuzvo-kalendar.html").read_text(), "tuzvo.json")
    assert "Krajina - človek - kultúra" in out and "Výstava plodov starých odrôd ovocných drevín" in out
    assert len(out) == len({e["id"] for e in out.values()})
    fair = out["Výstava plodov starých odrôd ovocných drevín"]
    assert fair["startDate"]["value"] == "2026-11-04T09:00:00+01:00"
    assert fair["venue"]["value"] == "FEE E214" and fair["eventCategory"]["value"]
    assert fair["organizer"]["value"]["name"] and fair["url"]["value"].startswith("https://www.tuzvo.sk/sk/")
    assert fair["location"]["value"]["coordinates"] == [19.1165987, 48.5729663]
    assert "Test Osoba" not in json.dumps(out, ensure_ascii=False)
    # A venue nobody geocoded (ÚTVŠ) gives no point; the event is kept without one, never put at Zvolen's centre.
    sport = out["Súčasné trendy v športe, pohybových aktivitách a životnom štýle"]
    assert "location" not in sport and VALID.is_valid(key_values(sport))


def test_the_next_month_is_read_from_the_same_list_page_10_seconds_later():
    steps = template("drupal-kalendar", "www.tuzvo.sk", store="bbsk", region="BBSK", town="Zvolen",
                     path="/sk/kalendar-podujati", org_type="university (Technická univerzita vo Zvolene)")
    (branch,) = [s["branch"] for s in steps if "branch" in s]
    assert branch["processors"][0] == {"sleep": {"duration": "10s"}}
    assert branch["processors"][1]["http"]["url"] == "https://www.tuzvo.sk/${! @event_path }"
    assert '"/sk/kalendar-podujati".trim_prefix("/") + "?mini="' in branch["request_map"]


@requires_docker
def test_an_event_naming_no_place_or_only_the_town_takes_its_organizers_address():
    # T-5135, owner 2026-10-22: GPS from the source, the venue table, or the institution's address; never a town centre.
    def event(i: int, venue) -> dict:
        e = tribe_event(i, [], url=f"https://svkbb.eu/udalosti/e-{i}/")
        e["venue"] = venue
        return e

    feed = {"events": [
        event(1, []),
        event(2, {"venue": "Banská Bystrica", "city": "Banská Bystrica"}),
        event(3, {"venue": "Neznáma sála", "city": "Banská Bystrica"}),
        event(4, {"venue": "Záhrada", "city": "Banská Bystrica", "geo_lat": "48.7336", "geo_lng": "19.1423"}),
    ]}
    steps = offline(processors("svkbb"), {})
    out = {e["name"]["value"]: e for e in run(steps, json.dumps(feed))}
    library = [19.1436671, 48.7373616]
    assert out["Koncert 1"]["location"]["value"]["coordinates"] == library and "venue" not in out["Koncert 1"]
    assert out["Koncert 1"]["address"]["value"]["streetAddress"] == "Lazovná 240/9"
    assert out["Koncert 2"]["location"]["value"]["coordinates"] == library
    assert out["Koncert 2"]["venue"]["value"] == "Banská Bystrica", "the venue stays as the source wrote it"
    assert "location" not in out["Koncert 3"], "a place nobody placed gets no point, never the organizer's"
    assert out["Koncert 4"]["location"]["value"]["coordinates"] == [19.1423, 48.7336]
    assert all(VALID.is_valid(key_values(e)) for e in out.values())


def test_every_home_names_one_venue_of_a_kept_source_and_no_aggregator():
    homes = list(csv.DictReader((EVENTS / "homes.csv").open(encoding="utf-8")))
    kept = {r["events_url"]: r for r in generate.kept_sources()}
    assert homes and len({h["events_url"] for h in homes}) == len(homes)
    for h in homes:
        assert h["events_url"] in kept, h
        assert generate.organizer(kept[h["events_url"]]) is not None, f"an aggregator has no address of its own: {h}"
        assert generate.home(kept[h["events_url"]])["match"] == h["match"]


# --- T-5215: dates from the page, notices out, one entity per event ---------------------------------------------


def lsvr_page(info: str, ld_start: str = "") -> str:
    """An LSVR (TownPress) event page as recorded 2026-10-22 from obecpredajna.sk: empty JSON-LD dates."""
    return (
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Event","name":"X",'
        f'"startDate":"{ld_start}","endDate":""}}</script><main>{info}</main>'
    )


MULTIDAY = """<ul class="post__info post__info--multiday"> <li class="post__info-item post__info-item--date">
<h3 class="post__info-item-title">Začiatok</h3> <p class="post__info-item-text"> 28. augusta 2027 <br>Celodenná udalosť </p> </li>
<li class="post__info-item post__info-item--date"> <h3 class="post__info-item-title">Koniec</h3>
<p class="post__info-item-text"> 30. augusta 2027 <br>Celodenná udalosť </p> </li></ul>"""
SINGLEDAY = """<ul class="post__info post__info--singleday"> <li class="post__info-item post__info-item--date">
<h3 class="post__info-item-title">Dátum</h3> <p class="post__info-item-text"> 7. 12. 2026 </p> </li>
<li class="post__info-item post__info-item--time"> <h3 class="post__info-item-title">Čas</h3>
<p class="post__info-item-text"> 8:00 - 12:30 </p> </li></ul>"""


def wp_items(*names: str) -> str:
    return json.dumps([{"id": i, "link": f"https://www.casta.sk/events/e{i}/", "title": {"rendered": n}}
                       for i, n in enumerate(names)])


@requires_docker
def test_an_lsvr_page_without_json_ld_dates_gives_the_dates_it_prints():
    pages = {"/events/e0/": lsvr_page(MULTIDAY), "/events/e1/": lsvr_page(SINGLEDAY),
             "/events/e2/": lsvr_page("<p>Bez dátumu</p>")}
    steps = offline(template("lsvr-rest", "www.casta.sk"), pages)
    out = {e["name"]["value"]: e for e in run(steps, wp_items("Biatlon", "Jarmok", "Nič"), "slovensko-podujatia")}
    assert out["Biatlon"]["startDate"]["value"] == "2027-08-28" and out["Biatlon"]["endDate"]["value"] == "2027-08-30"
    assert out["Jarmok"]["startDate"]["value"] == "2026-12-07T08:00:00+01:00"
    assert out["Jarmok"]["endDate"]["value"] == "2026-12-07T12:30:00+01:00"
    assert "Nič" not in out, "a page that prints no date is refused, never stored dateless"


@requires_docker
def test_an_eventon_offset_with_a_one_digit_hour_is_read():
    # Recorded 2026-10-22 from k13.sk (EventON): "2026-11-14T10:00+2:00".
    page = ('<script type="application/ld+json">{"@context":"http://schema.org","@type":"Event","name":"SteelPark",'
            '"startDate":"2027-11-14T10:00+2:00","endDate":"2027-11-15T18:00+1:00"}</script>')
    (e,) = run(offline(template("eventon-rest", "www.casta.sk"), {"/events/e0/": page}), wp_items("SteelPark"),
               "slovensko-podujatia")
    assert e["startDate"]["value"] == "2027-11-14T10:00:00+02:00" and e["endDate"]["value"] == "2027-11-15T18:00:00+01:00"


@requires_docker
def test_notices_are_never_loaded_for_any_source_kind():
    notices = ["Vývoz triedeného zberu plastov", "Odvoz komunálneho odpadu", "Zber papiera", "Papier",
               "Zasadnutie OZ – 30.09.2026", "Oznámenie o prerušení distribúcie elektriny", "VZN č. 3/2026",
               "Zámer predaja pozemku", "Komunálne voľby", "Svadba", "Rodinná oslava"]
    events = ["Mikuláš v obci", "Koncert skupiny FIDEM", "Zberateľská burza"]
    day = datetime.fromtimestamp(NOW, UTC) + timedelta(days=3)
    # wp-rest-sc (feed with dates), lsvr-rest (page JSON-LD), lego-html and every other kind share common.yaml.
    sc = run(offline(processors("banskabystrica"), {}),
             json.dumps([wp_event(i, day, title=t) for i, t in enumerate(notices + events)]))
    assert sorted(e["name"]["value"] for e in sc) == sorted(events)
    page = '<script type="application/ld+json">{"@type":"Event","startDate":"' + day.strftime("%Y-%m-%dT%H:%M:%S+00:00") + '"}</script>'
    pages = {f"/events/e{i}/": page for i in range(len(notices + events))}
    lsvr = run(offline(template("lsvr-rest", "www.casta.sk"), pages), wp_items(*notices, *events), "slovensko-podujatia")
    assert sorted(e["name"]["value"] for e in lsvr) == sorted(events)


@requires_docker
def test_one_event_written_by_two_sources_with_other_punctuation_or_a_minute_apart_is_one_entity():
    # Recorded 2026-10-22 on dev: banskabystrica.sk and vkmk.sk wrote "Kintsugi – japonské umenie" and
    # "Kintsugi: japonské umenie", and "Čarovný kľúčik" at 16:35 and 16:36.
    def one(title: str, at: str) -> str:
        page = '<script type="application/ld+json">{"@type":"Event","startDate":"' + at + '"}</script>'
        (e,) = run(offline(template("lsvr-rest", "www.casta.sk"), {"/events/e0/": page}), wp_items(title), "slovensko-podujatia")
        return e["id"]

    assert one("Kintsugi – japonské umenie", "2027-11-19T16:30:00+01:00") == one("Kintsugi: japonské umenie", "2027-11-19T16:30:00+01:00")
    assert one("Čarovný kľúčik", "2027-11-18T16:35:00+01:00") == one("Čarovný kľúčik", "2027-11-18T16:36:00+01:00")
    assert one("Korčuľovanie", "2027-10-29T10:30:00+01:00") != one("Korčuľovanie", "2027-10-29T15:00:00+01:00")
