#!/usr/bin/env python3
"""Write one DataSource, Pipeline and mapping per kept events source and store (T-4896, T-5047).

Reads sources.csv (T-4894's inventory of the Banská Bystrica Region), sources-sk.csv (T-4899's and
T-5047's inventory of the rest of Slovakia) and venues.csv (venues checked by hand), takes the rows whose
decision is `pipeline`, whose feed is https and whose feed kind has a template under pipelines/, and writes,
per store of STORES, components/context-gateway/seed/<ns>/<ns>-{datasource,pipeline}-podujatia-<name>.yaml and
its -bento.yaml plus their lines in that folder's index.yaml, and the list of sources with their licence into
the catalogue block of the store's Endpoint (T-4898). The Banská Bystrica Region's store reads its own sources
once a night; the national store (slovensko-podujatia) reads every source every 3 hours. `--check` writes
nothing and fails when a file differs.

Run: python3 seeds/bbsk-events/generate.py [--check]
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEED = ROOT / "components/context-gateway/seed/bbsk"
TARGET = "urn:ngsi-ld:Endpoint:bbsk.sk:bbsk-podujatia:bbsk-podujatia-zapis"
UA = "joinedcontext-platform/1.0 (+https://dev.joinedcontext.com; public events)"
REGION = "Banskobystrický kraj"
#: The inventories, each with the region code of its rows' scope /SK/{code}/{town}.
INVENTORIES = ("sources.csv", "sources-sk.csv")
#: Inventory region -> (scope segment, addressRegion). BBSK rows carry the region's own name.
REGIONS = {
    "BBSK": ("BB", "Banskobystrický kraj"),
    "BA": ("BA", "Bratislavský kraj"),
    "TT": ("TT", "Trnavský kraj"),
    "TN": ("TN", "Trenčiansky kraj"),
    "NR": ("NR", "Nitriansky kraj"),
    "ZA": ("ZA", "Žilinský kraj"),
    "PO": ("PO", "Prešovský kraj"),
    "KE": ("KE", "Košický kraj"),
}
#: The two event stores (owner 2026-10-21, T-5047). Each lists the inventory regions it reads (None: all),
#: its write Endpoint, its cadences and its grace. A cadence names the feed kinds it takes (None: the rest),
#: how often a source runs, the window its runs are staggered over (minutes after 00:00 UTC) and its lease. An
#: event leaves at its end + `grace` seconds, or `lease` seconds after the run that last saw it, whichever comes
#: first (None: no lease). The lease is what ends an event its source dropped or cancelled: spec.expiry is
#: refused where several pipelines write one space (pipeline_expiry::check).
STORES = (
    {
        "ns": "bbsk",
        "domain": "bbsk.sk",
        "space": "bbsk-podujatia",
        "regions": ("BBSK",),
        "target": TARGET,
        "endpoints": ("bbsk-endpoint-podujatia.yaml",),
        # Daily, and the same 52 h lease as the national store's daily sources (T-5081): an event its source
        # dropped, or whose new record the model now refuses (no GPS, start or organizer), leaves within two
        # missed runs instead of staying half until its end.
        "cadences": ({"kinds": None, "period": "24h", "every": 24, "window": 180, "lease": 52 * 3600},),
        "grace": 0,
    },
    {
        "ns": "slovensko",
        "domain": "joinedcontext.com",
        "space": "slovensko-podujatia",
        "regions": None,
        "target": "urn:ngsi-ld:Endpoint:joinedcontext.com:slovensko-podujatia:slovensko-podujatia-zapis",
        "endpoints": ("slovensko-endpoint-podujatia.yaml",),
        # A village's calendar page (Lego, WEBY) changes rarely and every run reads each event page 1-3 s
        # apart: once a day, spread over the day. The feeds run every 3 hours. Each lease outlasts two missed
        # runs, so a source down for one run keeps its events.
        "cadences": (
            {"kinds": ("lego-html", "weby-feed", "umb-cms", "drupal-kalendar"), "period": "24h", "every": 24, "window": 1440, "lease": 52 * 3600},
            {"kinds": None, "period": "3h", "every": 3, "window": 180, "lease": 8 * 3600},
        ),
        "grace": 86400,
    },
)
#: feed kind of the inventory -> template files under pipelines/, run in this order.
TEMPLATES = {
    "wp-rest-sc": ("wp-rest-sc",),
    "tribe-rest": ("tribe-rest",),
    "ical": ("ical",),
    "weby-feed": ("weby-feed",),
    "mec-rest": ("wp-list", "jsonld-pages"),
    "lsvr-rest": ("wp-list", "jsonld-pages"),
    "eventon-rest": ("wp-list", "jsonld-pages"),
    "wp-rest-jsonld": ("wp-list", "jsonld-pages"),
    "wp-rss-jsonld": ("rss-list", "jsonld-pages"),
    "jsonld": ("page-jsonld",),
    "lego-html": ("lego-html",),
    "umb-cms": ("umb-cms",),
    "drupal-kalendar": ("drupal-kalendar",),
}
#: Fewer bytes per run: the fields the template reads (WordPress `_fields`). The kinds that read each
#: event's page list the 50 newest posts: every page read is one more request to a small town's site.
_PAGES = "_fields=id,link,title,modified_gmt&per_page=50"
TRIM = {
    "wp-rest-sc": "_fields=id,link,title,content,modified_gmt,meta_box",
    "mec-rest": _PAGES,
    "lsvr-rest": _PAGES,
    "eventon-rest": _PAGES,
    "wp-rest-jsonld": _PAGES,
}
#: Upcoming events first where the feed sorts and filters itself (owner 2026-10-20).
UPCOMING = {"tribe-rest": "start_date=now"}
INDEX_BEGIN = (
    "# BEGIN generated by seeds/bbsk-events/generate.py (T-4896): do not edit by hand"
)
INDEX_END = "# END generated by seeds/bbsk-events/generate.py"
SOURCES_BEGIN = "    # BEGIN sources generated by seeds/bbsk-events/generate.py (T-4898): do not edit by hand"
SOURCES_END = "    # END sources generated by seeds/bbsk-events/generate.py"


class Dumper(yaml.SafeDumper):
    """Writes a multi-line string (a mapping) as a literal block, so it reads as written."""


Dumper.add_representer(
    str,
    lambda d, v: d.represent_scalar(
        "tag:yaml.org,2002:str", v, style="|" if "\n" in v else None
    ),
)


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def kept_sources() -> list[dict]:
    rows = [
        r
        for f in INVENTORIES
        for r in csv.DictReader((HERE / f).open(encoding="utf-8"))
    ]
    # A plain-http feed stays out: the runner fetches over TLS only (T-4898 names the rows).
    kept = [
        r
        for r in rows
        if r["decision"] == "pipeline"
        and r["feed_kind"] in TEMPLATES
        and r["check_url"].startswith("https://")
    ]
    for row in kept:
        parts = urlsplit(row["check_url"])
        assert parts.scheme == "https" and re.fullmatch(
            r"[a-z0-9.-]+", parts.hostname or ""
        ), row["check_url"]
        labels = parts.hostname.removeprefix("www.").split(".")
        row["name"] = "podujatia-" + labels[0]
        row["host"] = f"https://{parts.hostname}"
        row["town_slug"] = None if row["town"] == REGION else slug(row["town"])
        row["scope"], row["region_name"] = REGIONS[row["region"]]
    names = [r["name"] for r in kept]
    assert len(names) == len(set(names)), names
    return kept


def venues_for(town_slug: str | None) -> list[dict]:
    out = []
    for v in csv.DictReader((HERE / "venues.csv").open(encoding="utf-8")):
        if v["town"] != town_slug and not (town_slug is None and v["regional"] == "y"):
            continue
        out.append(
            {
                "match": v["match"],
                "town": v["town"],
                "venue": v["venue"],
                "streetAddress": v["streetAddress"] or None,
                "addressLocality": v["addressLocality"],
                "lat": float(v["lat"]),
                "lon": float(v["lon"]),
            }
        )
    return out


def cadence(row: dict, store: dict) -> dict:
    return next(c for c in store["cadences"] if c["kinds"] is None or row["feed_kind"] in c["kinds"])


def processors(row: dict, store: dict) -> list:
    """The template's steps then the common tail, each __NAME__ a JSON literal."""
    facts_only = not row["licence_terms"].startswith("CC-BY")
    values = {
        "__VENUES__": json.dumps(
            venues_for(row["town_slug"]), ensure_ascii=False, separators=(",", ":")
        ),
        "__TOWN__": json.dumps(
            None if row["town_slug"] is None else row["town"], ensure_ascii=False
        ),
        "__TOWN_SLUG__": json.dumps(row["town_slug"]),
        "__SCOPE__": json.dumps("/SK/" + row["scope"]),
        "__REGION__": json.dumps(row["region_name"], ensure_ascii=False),
        "__SOURCE__": json.dumps(row["events_url"], ensure_ascii=False),
        "__PROVIDER__": json.dumps(provider(row), ensure_ascii=False),
        "__ORGANIZER__": json.dumps(organizer(row), ensure_ascii=False),
        "__LISTING__": json.dumps(row["events_url"], ensure_ascii=False),
        "__FACTS_ONLY__": "true" if facts_only else "false",
        "__HOST_RE__": re.escape(row["host"]).replace("\\", "\\\\"),
        "__HOST__": row["host"],
        # The events list's own path: a Lego source reads only the event pages under it, never a sidebar's news.
        "__LIST_PATH_RE__": re.escape(urlsplit(row["check_url"]).path).replace("\\", "\\\\"),
        "__LIST_PATH__": json.dumps(urlsplit(row["check_url"]).path),
        "__GRACE__": json.dumps(store["grace"]),
        "__LEASE__": json.dumps(cadence(row, store)["lease"]),
    }
    text = "".join(
        (HERE / "pipelines" / f"{name}.yaml").read_text(encoding="utf-8")
        for name in (*TEMPLATES[row["feed_kind"]], "common")
    )
    for name, value in values.items():
        text = text.replace(name, value)
    assert not re.search(r"__[A-Z_]+__", text), row["name"]
    return yaml.safe_load(text)


def provider(row: dict) -> str:
    host = urlsplit(row["events_url"]).hostname.removeprefix("www.")
    licence = (
        row["licence_terms"].split(" ")[0]
        if row["licence_terms"].startswith("CC-")
        else "licencia neuvedená"
    )
    return f"{row['town']}, {host} ({licence})"


#: Inventory bodies that announce other bodies' events: their calendar names no organizer of its own (T-5081).
AGGREGATORS = re.compile(r"^(regional )?tourism organisation|^region\b")


def organizer(row: dict) -> dict | None:
    """Who runs an event its feed names no organizer for: the body whose calendar it is, never an aggregator.

    The museum, theatre or school of `org_type (Name)`, else the town (`Mesto`) or the municipality (`Obec`,
    a town is one too by law), with its web site.
    """
    kind = row["org_type"]
    if AGGREGATORS.match(kind):
        return None
    named = re.fullmatch(r"[^(]+\((.+)\)", kind)
    if named:
        name = named.group(1).strip()
    elif kind == "town":
        name = f"Mesto {row['town']}"
    elif kind in ("municipality", "village"):
        name = f"Obec {row['town']}"
    else:
        return None
    return {"name": name, "url": row["site"]}


def feed_url(row: dict) -> str:
    """The row's feed with the template's trims; a parameter the trim sets replaces the row's own."""
    url = row["check_url"]
    for extra in (TRIM, UPCOMING):
        if row["feed_kind"] in extra:
            for pair in extra[row["feed_kind"]].split("&"):
                url = re.sub(r"([?&])" + re.escape(pair.split("=")[0]) + r"=[^&]*&?", r"\1", url).rstrip("&?")
                url += ("&" if "?" in url else "?") + pair
    return url


def schedule(minute: int, every: int) -> str:
    """Cron for a run at `minute` after 00:00 UTC, then every `every` hours that day."""
    hour = str(minute // 60) if every == 24 else f"{minute // 60}-23/{every}"
    return f"{minute % 60} {hour} * * *"


def documents(minute: int, row: dict, store: dict) -> dict[str, str]:
    name, town, ns = row["name"], row["town"], store["ns"]
    url = feed_url(row)
    plan = cadence(row, store)
    datasource = {
        "apiVersion": "joinedcontext.com/v1alpha1",
        "kind": "DataSource",
        "metadata": {
            "name": name,
            "namespace": ns,
            "title": {
                "sk": f"Podujatia: {town} ({row['feed_kind']})",
                "en": f"Events: {town} ({row['feed_kind']})",
            },
        },
        "spec": {
            "type": "http",
            "http": {
                "url": url,
                "verb": "GET",
                "headers": {"User-Agent": UA, "Accept": accept(row["feed_kind"])},
                "timeout": "30s",
            },
        },
    }
    pipeline = {
        "apiVersion": "joinedcontext.com/v1alpha1",
        "kind": "Pipeline",
        "metadata": {
            "name": name,
            "namespace": ns,
            "title": {"sk": f"Podujatia: {town}", "en": f"Events: {town}"},
        },
        "spec": {
            "class": "auto",
            "period": plan["period"],
            "schedule": schedule(minute, plan["every"]),
            "source": {"dataSourceRef": {"kind": "DataSource", "name": name}},
            "targetEndpoint": store["target"],
            "output": {"type": "Event", "mode": "upsert"},
            "quotas": {"maxMemoryMb": 128, "cpuMillicores": 100},
        },
    }
    head = (
        f"# Generated by seeds/bbsk-events/generate.py from the inventory row {town} ({row['feed_kind']}),\n"
        f"# read {row['read_on']}: {row['events_url']} (T-4896). Do not edit: change the template or the CSV.\n"
    )
    bento = {"pipeline": {"processors": processors(row, store)}}
    dump = lambda d: yaml.dump(
        d, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=120
    )
    return {
        f"{ns}-datasource-{name}.yaml": head + dump(datasource),
        f"{ns}-pipeline-{name}.yaml": head + dump(pipeline),
        f"{ns}-pipeline-{name}-bento.yaml": head + dump(bento),
    }


def accept(kind: str) -> str:
    return {
        "ical": "text/calendar",
        "weby-feed": "application/rss+xml, application/atom+xml, application/xml",
        "jsonld": "text/html",
        "lego-html": "text/html",
        "umb-cms": "text/html",
        "drupal-kalendar": "text/html",
        "wp-rss-jsonld": "application/rss+xml, application/atom+xml, application/xml",
    }.get(kind, "application/json")


def index_lines(rows: list[dict], ns: str) -> list[str]:
    lines = [INDEX_BEGIN]
    for row in rows:
        lines += [
            f"{ns}-datasource-{row['name']}.yaml: projects/{ns}/datasources/{row['name']}.yaml",
            f"{ns}-pipeline-{row['name']}.yaml: projects/{ns}/pipelines/{row['name']}/pipeline.yaml",
            f"{ns}-pipeline-{row['name']}-bento.yaml: projects/{ns}/pipelines/{row['name']}/bento.yaml",
        ]
    return lines + [INDEX_END]


def catalogue_sources(rows: list[dict]) -> list[str]:
    """The `source:` block of an Endpoint's catalogue: each kept feed with its licence (T-4898)."""
    lines = [SOURCES_BEGIN, "    source:"]
    for row in rows:
        host = urlsplit(row["events_url"]).hostname.removeprefix("www.")
        title = json.dumps(f"{row['town']}, {host}", ensure_ascii=False)
        facts = not row["licence_terms"].startswith("CC-BY")
        sk = (
            "Podujatia zo stránky {}; licencia neuvedená, preberáme len fakty (názov, čas, miesto, odkaz)."
            if facts
            else "Podujatia zo stránky {}; licencia {}."
        )
        en = (
            "Events from {}; no licence stated, facts only (name, time, place, link)."
            if facts
            else "Events from {}; licence {}."
        )
        licence = row["licence_terms"].split(" ")[0]
        lines += [
            f"      - url: {json.dumps(row['events_url'])}",
            f"        title: {{ sk: {title}, en: {title} }}",
            "        description:",
            f"          sk: {json.dumps(sk.format(row['events_url'], licence), ensure_ascii=False)}",
            f"          en: {json.dumps(en.format(row['events_url'], licence), ensure_ascii=False)}",
        ]
    return lines + [SOURCES_END]


def with_block(text: str, begin: str, end: str, block: str) -> str:
    """The text with its generated block replaced, or the block appended when it has none."""
    if begin in text:
        return re.sub(
            re.escape(begin) + r".*?" + re.escape(end) + "\n",
            lambda _: block,
            text,
            flags=re.DOTALL,
        )
    return text.rstrip("\n") + "\n" + block


def store_rows(store: dict) -> list[dict]:
    return [r for r in kept_sources() if store["regions"] is None or r["region"] in store["regions"]]


def wanted_files() -> tuple[dict[Path, str], list[Path]]:
    """Every generated file with its text, and the generated files on disk no store wants any more."""
    wanted: dict[Path, str] = {}
    ours: list[Path] = []
    for store in STORES:
        ns, seed = store["ns"], ROOT / "components/context-gateway/seed" / store["ns"]
        rows = store_rows(store)
        # Each cadence's runs are staggered over its window, so no two of them start in the same minute; the
        # bbsk night window is 00:00-02:59 UTC, 01:00-05:00 in Bratislava in winter and summer (owner 2026-10-20).
        for plan in store["cadences"]:
            mine = [r for r in rows if cadence(r, store) is plan]
            assert len(mine) <= plan["window"], f"{ns}: more sources than minutes in a window"
            for i, row in enumerate(mine):
                for file, text in documents(i * plan["window"] // len(mine), row, store).items():
                    wanted[seed / file] = text
        for file in store["endpoints"]:
            path = seed / file
            block = "\n".join(catalogue_sources(rows)) + "\n"
            wanted[path] = with_block(path.read_text(encoding="utf-8"), SOURCES_BEGIN, SOURCES_END, block)
        index = seed / "index.yaml"
        block = "\n".join(index_lines(rows, ns)) + "\n"
        wanted[index] = with_block(index.read_text(encoding="utf-8"), INDEX_BEGIN, INDEX_END, block)
        ours += [*seed.glob(f"{ns}-datasource-podujatia-*.yaml"), *seed.glob(f"{ns}-pipeline-podujatia-*.yaml")]
    return wanted, [p for p in ours if p not in wanted]


def main(check: bool) -> int:
    wanted, stale = wanted_files()
    differ = [
        p
        for p, t in wanted.items()
        if not p.is_file() or p.read_text(encoding="utf-8") != t
    ]
    if check:
        for p in differ + stale:
            print(f"out of date: {p.relative_to(ROOT)}", file=sys.stderr)
        return 1 if differ or stale else 0
    for p in stale:
        p.unlink()
    for p in differ:
        p.write_text(wanted[p], encoding="utf-8")
    counts = ", ".join(f"{s['ns']} {len(store_rows(s))}" for s in STORES)
    print(f"sources: {counts}; {len(differ)} files written, {len(stale)} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))
