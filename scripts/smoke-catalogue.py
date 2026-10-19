#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""Check every catalogue dataset and every public Endpoint on its standard interfaces (T-4716).

    scripts/smoke-catalogue.py <domain> <env> [out-dir]

Reads only public data, anonymously: CKAN's package_search and the gateway's DCAT feed for the
inventory, then per dataset NGSI-LD, MCP, OData, OGC API Features and the data model (every run),
and the datastore count, WebSocket, map and CSV (rotating, least recently checked first).
One request at a time, at most 50 a minute, 500 a run and 10 minutes (owner limit, T-4716).
Writes `<out-dir>/smoke-catalogue-<env>-<time>.tsv` (default out-dir `.smoke`) and exits 1
on any ko. Testing/05 §4.1 is the contract.
"""

import contextlib
import csv
import functools
import html
import importlib.util
import json
import re
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

INTERVAL = 1.2  # seconds between two requests: 50 a minute
BUDGET = 500
DEADLINE = 600.0
TIMEOUT = 20.0
MAX_BODY = 1 << 20  # an interface answer: limit=1, or the head of file.csv
MAX_INVENTORY = 64 << 20  # package_search and the DCAT feed, read whole
TOLERANCE = 0.01
RETRIES = 3
# The tables stay where an apply leaves them: _dev-assemble deletes deployment/, and the
# rotation reads the previous table (gitignored).
DEFAULT_OUT = ".smoke"
CORE = ["ngsi-ld", "mcp", "odata", "ogc", "model"]
ROTATING = ["datastore", "websocket", "map", "csv"]
COLUMNS = ["inventory", *CORE, *ROTATING]
MCP_LIST = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
NOT_THIS_RUN = re.compile(r"not this run \(last: (\S+) (\w+)\)")


class OutOfBudget(Exception):
    """The run's requests or minutes are spent: the rest is `not this run`, never a ko."""


@dataclass
class Answer:
    status: int
    ctype: str = ""
    body: bytes = b""
    seconds: float = 0.0
    error: str = ""
    retry_after: str = ""

    def json(self):
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    def why(self) -> str:
        return self.error or f"{self.status} {self.ctype}".strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect is an answer of its own: following it would be a request the limiter never saw.
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Overtime(Exception):
    """A request past TIMEOUT in total; not an OSError, so urllib does not wrap it."""


@contextlib.contextmanager
def cut_at(seconds: float):
    """Interrupt whatever runs inside after `seconds` of wall time. urllib's own timeout is per
    connect and per read, so a slow handshake, a slow first byte and a trickle each got it whole
    (dev runs 2 and 3 overran 10 minutes by 40 s). Main thread only; the script has no other."""
    def expire(signum, frame):
        raise Overtime()

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def send(method: str, url: str, headers: dict, body: bytes | None, limit: int = MAX_BODY) -> Answer:
    """One HTTP request through urllib, at most `limit` bytes and TIMEOUT seconds; never raises."""
    started = time.monotonic()
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with cut_at(TIMEOUT), OPENER.open(request, timeout=TIMEOUT) as response:
            return Answer(response.status, response.headers.get("Content-Type", ""),
                          response.read(limit), time.monotonic() - started)
    except Overtime:
        return Answer(0, seconds=TIMEOUT, error=f"timeout after {TIMEOUT:.0f} s")
    except urllib.error.HTTPError as error:
        return Answer(error.code, error.headers.get("Content-Type", ""), error.read(limit),
                      time.monotonic() - started, retry_after=error.headers.get("Retry-After", ""))
    except (TimeoutError, socket.timeout):
        return Answer(0, seconds=TIMEOUT, error=f"timeout after {TIMEOUT:.0f} s")
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return Answer(0, seconds=TIMEOUT, error=f"timeout after {TIMEOUT:.0f} s")
        return Answer(0, seconds=time.monotonic() - started, error=f"no answer ({reason})")


@functools.cache
def smoke_ws():
    spec = importlib.util.spec_from_file_location("smoke_ws", Path(__file__).resolve().parent / "smoke-ws.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def open_socket(url: str, entity_type: str) -> tuple[int, int, str]:
    """scripts/smoke-ws.py's upgrade and subscribe: (upgrade status, x-status, error)."""
    ws = smoke_ws()
    try:
        with cut_at(TIMEOUT):
            sock, status = ws.connect(url, TIMEOUT)
            with sock:
                if status != 101:
                    return status, 0, ""
                try:
                    return 101, ws.subscribe(sock, entity_type), ""
                except (OSError, ValueError) as error:
                    return 101, 0, str(error)
    except Overtime:
        return 0, 0, f"timeout after {TIMEOUT:.0f} s"
    except OSError as error:
        return 0, 0, str(error)


class Client:
    """Every request of a run: paced, counted, capped, and the same request asked once."""

    def __init__(self, send=send, ws=open_socket, clock=time.monotonic, sleep=time.sleep,
                 budget=BUDGET, deadline=DEADLINE, interval=INTERVAL):
        self._send, self._ws, self._clock, self._sleep = send, ws, clock, sleep
        self.budget, self.deadline, self.interval = budget, deadline, interval
        self.start = clock()
        self.count = 0
        self._last = None
        self._cache = {}

    def _slot(self):
        now = self._clock()
        wait = 0.0 if self._last is None else max(0.0, self._last + self.interval - now)
        # A request may take TIMEOUT: it starts only when that still ends inside the deadline.
        if self.count >= self.budget or now + wait + TIMEOUT - self.start > self.deadline:
            raise OutOfBudget()
        if wait:
            self._sleep(wait)
        self._last = self._clock()
        self.count += 1

    def fetch(self, url: str, method: str = "GET", headers: dict | None = None,
              body: bytes | None = None, limit: int = MAX_BODY) -> Answer:
        key = (method, url, body)
        if key in self._cache:
            return self._cache[key]
        headers = {"User-Agent": "jc-smoke-catalogue", **(headers or {})}
        self._slot()
        answer = self._send(method, url, headers, body, limit)
        for _ in range(RETRIES):
            if answer.status not in (429, 503):
                break
            # The server's Retry-After, waited out inside the same budget and deadline.
            pause = min(float(answer.retry_after) if answer.retry_after.isdigit() else 5.0, 60.0)
            if self._clock() + pause + TIMEOUT - self.start > self.deadline:
                break
            self._sleep(pause)
            self._slot()
            answer = self._send(method, url, headers, body, limit)
        if answer.status == 429:
            # A rate limit says nothing about the interface: what it held back is not this run.
            raise OutOfBudget()
        self._cache[key] = answer
        return answer

    def elapsed(self) -> float:
        return self._clock() - self.start

    def socket(self, url: str, entity_type: str) -> tuple[int, int, str]:
        key = ("WS", url, entity_type)
        if key not in self._cache:
            self._slot()
            self._cache[key] = self._ws(url, entity_type)
        return self._cache[key]


def ok(why: str = "") -> str:
    return f"ok: {why}" if why else "ok"


def ko(why: str) -> str:
    return f"ko: {why}"


def skip(why: str) -> str:
    return f"skip: {why}"


def verdict(cell: str) -> str:
    return cell.split(":", 1)[0].split(" ", 1)[0]


@dataclass
class Dataset:
    name: str
    slug: str = ""
    type: str = ""
    formats: dict = None
    datastore: list = None
    part_of: str = ""
    foreign: list = None
    why: str = ""


def endpoint_slug(url: str) -> str:
    match = re.search(r"/api/endpoint/([a-z0-9]+)", url or "")
    return match.group(1) if match else ""


def describe(package: dict, domain: str) -> Dataset:
    """What one CKAN dataset says about itself: its Endpoint, type, distributions, datastore."""
    data = Dataset(package["name"], formats={}, datastore=[], foreign=[])
    for resource in package.get("resources", []):
        url, fmt = resource.get("url") or "", resource.get("format") or ""
        if resource.get("datastore_active"):
            data.datastore.append(resource["id"])
        if "/api/endpoint/" not in url:
            continue
        host = urllib.parse.urlsplit(url).hostname or ""
        if host != f"api.{domain}":
            data.foreign.append(host)
        data.slug = data.slug or endpoint_slug(url)
        if url.rstrip("/").endswith("schema/index.json"):
            fmt = "MODEL"
        elif fmt == "CSV" and not url.split("?")[0].endswith("file.csv"):
            continue
        data.formats.setdefault(fmt, url)
        found = (re.search(r"/odata/v4/([A-Za-z][\w]*)$", url.split("?")[0])
                 or re.search(r"/collections/([A-Za-z][\w]*)/items", url)
                 or re.search(r"\(([A-Za-z][\w]*)\)$", resource.get("name") or ""))
        data.type = data.type or (found.group(1) if found else "")
        if fmt == "OGCFEAT":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            data.part_of = (query.get("isPartOf") or [""])[0]
    return data


def mcp_tools(answer: Answer) -> int:
    """The number of tools in a tools/list answer, plain JSON or an event stream."""
    text = answer.body.decode(errors="replace")
    if "text/event-stream" in answer.ctype:
        text = "\n".join(line[5:] for line in text.splitlines() if line.startswith("data:"))
    try:
        return len(json.loads(text)["result"]["tools"])
    except (ValueError, KeyError, TypeError):
        return 0


class Run:
    def __init__(self, client: Client, domain: str, previous: dict, previous_at: str, now: str):
        self.client, self.domain = client, domain
        self.previous, self.previous_at, self.now = previous, previous_at, now
        self.counts = {}  # dataset -> (platform count, how)
        self.shared = {}  # (slug, type) -> datasets without isPartOf

    def base(self, data: Dataset) -> str:
        return f"https://api.{self.domain}/api/endpoint/{data.slug}/"

    def entity_type(self, data: Dataset) -> str:
        """The dataset's type, else the Endpoint's first; '' with the reason in `data.why`."""
        if not data.type:
            answer = self.client.fetch(self.base(data) + "ngsi-ld/v1/types")
            types = (answer.json() or {}).get("typeList") if answer.status == 200 else None
            data.type = types[0] if isinstance(types, list) and types else ""
            data.why = "the Endpoint lists no type" if answer.status == 200 else f"types answered {answer.why()}"
        return data.type

    def ngsi_ld(self, data: Dataset) -> str:
        url = self.base(data) + "ngsi-ld/v1/entities?" + urllib.parse.urlencode({"type": data.type, "limit": 1})
        answer = self.client.fetch(url)
        if answer.status != 200 or "json" not in answer.ctype:
            return ko(f"entities answered {answer.why()}")
        body = answer.json()
        return ok() if isinstance(body, list) and body else ko(f"no {data.type} entity")

    def mcp(self, data: Dataset) -> str:
        answer = self.client.fetch(self.base(data) + "mcp", "POST", {
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, MCP_LIST)
        if answer.status != 200:
            return ko(f"tools/list answered {answer.why()}")
        tools = mcp_tools(answer)
        return ok(f"{tools} tools") if tools else ko("tools/list lists no tool")

    def odata(self, data: Dataset) -> str:
        url = self.base(data) + f"odata/v4/{data.type}?" + urllib.parse.urlencode({"$top": 1, "$count": "true"})
        answer = self.client.fetch(url)
        count = (answer.json() or {}).get("@odata.count") if answer.status == 200 else None
        if not isinstance(count, int):
            return ko(f"{data.type} answered {answer.why()}, no @odata.count")
        if not data.part_of:
            self.counts.setdefault(data.name, (count, "OData @odata.count"))
        return ok(f"{count} rows") if count >= 1 else ko(f"@odata.count is {count}")

    def ogc(self, data: Dataset) -> str:
        if "OGCFEAT" not in data.formats:
            return skip("the dataset lists no OGC distribution (its type has no location)")
        query = {"limit": 1, **({"isPartOf": data.part_of} if data.part_of else {})}
        url = self.base(data) + f"ogc/features/collections/{data.type}/items?" + urllib.parse.urlencode(query)
        answer = self.client.fetch(url)
        if answer.status != 200 or "geo+json" not in answer.ctype:
            return ko(f"items answered {answer.why()}")
        body = answer.json() or {}
        if data.part_of and isinstance(body.get("numberMatched"), int):
            self.counts[data.name] = (body["numberMatched"], "OGC numberMatched of its isPartOf")
        return ok() if body.get("features") else ko(f"no {data.type} feature")

    def model(self, data: Dataset) -> str:
        answer = self.client.fetch(self.base(data) + "schema/index.json")
        if answer.status != 200:
            return ko(f"schema/index.json answered {answer.why()}")
        listed = {t for m in (answer.json() or {}).get("models", []) for t in m.get("types", [])}
        return ok() if data.type in listed else ko(f"no model lists {data.type}")

    def datastore(self, data: Dataset) -> str:
        # ponytail: the first datastore table only; a dataset of several tables compares one.
        url = f"https://opendata.{self.domain}/api/3/action/datastore_search?" + urllib.parse.urlencode(
            {"resource_id": data.datastore[0], "limit": 0})
        answer = self.client.fetch(url)
        total = ((answer.json() or {}).get("result") or {}).get("total") if answer.status == 200 else None
        if not isinstance(total, int):
            return ko(f"datastore_search answered {answer.why()}")
        if total < 1:
            return ko("the datastore table is empty")
        others = self.shared.get((data.slug, data.type), [])
        if not data.part_of and len(others) > 1:
            return ok(f"{total} rows; not compared, {data.type} is shared by {len(others)} datasets")
        if data.name not in self.counts:
            return skip(f"{total} rows; no platform count to compare (OData or OGC ko)")
        count, how = self.counts[data.name]
        if abs(total - count) > TOLERANCE * max(count, 1):
            return ko(f"{total} rows, the platform holds {count} ({how})")
        return ok(f"{total} rows = {count}")

    def websocket(self, data: Dataset) -> str:
        url = "wss" + (self.base(data) + "ws")[5:]
        status, result, error = self.client.socket(url, data.type)
        if "WebSocket" in data.formats:
            if status == 101 and result == 201:
                return ok()
            return ko(f"upgrade {status}, subscribe {result or '-'}{' (' + error + ')' if error else ''}")
        if status == 404:
            return ok("not served, refused 404 as API/02 names")
        return ko(f"not served, but the upgrade answered {status}{' (' + error + ')' if error else ''}")

    def map(self, data: Dataset) -> str:
        if "OGCFEAT" not in data.formats:
            return skip("no OGC distribution, no map")
        answer = self.client.fetch(f"https://opendata.{self.domain}/map/{urllib.parse.quote(data.name)}")
        if answer.status != 200:
            return ko(f"map page answered {answer.why()}")
        found = re.search(r"data-jc-map='([^']*)'", answer.body.decode(errors="replace"))
        try:
            layers = json.loads(html.unescape(found.group(1))).get("layers") if found else None
        except ValueError:
            layers = None
        return ok() if layers else ko("the map page has no map layer")

    def csv(self, data: Dataset) -> str:
        # file.csv takes the entities query (API/02): one row is enough for a header line.
        url = self.base(data) + "file.csv?" + urllib.parse.urlencode({"type": data.type, "limit": 1})
        answer = self.client.fetch(url)
        header = answer.body.decode(errors="replace").split("\n", 1)[0].strip()
        if answer.status != 200 or "text/csv" not in answer.ctype:
            return ko(f"file.csv answered {answer.why()}")
        return ok() if header else ko("file.csv has no header line")

    def last(self, name: str, column: str) -> tuple[str, str]:
        """When the previous tables last ran this cell, and its verdict; ('', '') for never."""
        cell = self.previous.get(name, {}).get(column, "")
        carried = NOT_THIS_RUN.match(cell)
        if carried:
            return carried.group(1), carried.group(2)
        if cell and not cell.startswith("not this run"):
            return self.previous_at, verdict(cell)
        return "", ""

    def not_this_run(self, name: str, column: str) -> str:
        at, was = self.last(name, column)
        return f"not this run (last: {at} {was})" if at else "not this run (never)"

    def table(self, datasets: list, public: set) -> list:
        rows = {}
        for data in datasets:
            row = rows[data.name] = {"dataset": data.name, "endpoint": data.slug}
            if not data.slug:
                row["inventory"] = ko("the dataset lists no Endpoint distribution")
            elif data.foreign:
                row["inventory"] = ko(f"API on another installation's host {sorted(set(data.foreign))[0]}")
            elif data.slug not in public:
                row["inventory"] = ko("its Endpoint is not in the public DCAT feed")
            else:
                row["inventory"] = ok()
            if not data.datastore:
                row["datastore"] = ko("no datastore table")
        # Least recently checked first, the core as the slow checks: a run that ends early leaves
        # other datasets for the next one, not the same ones every time.
        checkable = sorted((d for d in datasets if d.slug),
                           key=lambda d: min(self.last(d.name, c)[0] for c in CORE))
        try:
            for data in checkable:
                row = rows[data.name]
                if not self.entity_type(data):
                    row.update({c: ko(f"no entity type: {data.why}") for c in CORE})
                    continue
                row["type"] = data.type
                for column in CORE:
                    row[column] = getattr(self, column.replace("-", "_"))(data)
            for data in checkable:
                if not data.part_of:
                    self.shared.setdefault((data.slug, data.type), []).append(data.name)
            # The rotating checks, the datasets whose oldest one ran longest ago first.
            order = sorted(checkable, key=lambda d: min(self.last(d.name, c)[0] for c in ROTATING))
            for data in order:
                if not data.type:
                    continue
                row = rows[data.name]
                for column in ROTATING:
                    if column not in row:
                        row[column] = getattr(self, column)(data)
        except OutOfBudget:
            pass
        for row in rows.values():
            for column in COLUMNS:
                row.setdefault(column, self.not_this_run(row["dataset"], column))
        for slug in sorted(public - {d.slug for d in datasets}):
            rows[f"(no dataset) {slug}"] = {"dataset": "(no dataset)", "endpoint": slug,
                                            "inventory": ko("a public Endpoint that no dataset names"),
                                            **{c: "-" for c in COLUMNS[1:]}}
        return list(rows.values())


def inventory(client: Client, domain: str) -> tuple[list, set]:
    packages, start = [], 0
    while True:
        query = urllib.parse.urlencode({"rows": 1000, "start": start})
        answer = client.fetch(f"https://opendata.{domain}/api/3/action/package_search?{query}", limit=MAX_INVENTORY)
        result = (answer.json() or {}).get("result") if answer.status == 200 else None
        if not isinstance(result, dict):
            raise SystemExit(f"  FAIL  catalogue: package_search answered {answer.why()}")
        packages += result.get("results", [])
        start += 1000
        if start >= result.get("count", 0) or not result.get("results"):
            break
    answer = client.fetch(f"https://api.{domain}/catalog.jsonld", limit=MAX_INVENTORY)
    feed = answer.json() if answer.status == 200 else None
    if not isinstance(feed, dict):
        raise SystemExit(f"  FAIL  catalogue: catalog.jsonld answered {answer.why()}")
    public = {endpoint_slug(d.get("@id", "")) for d in feed.get("dcat:dataset", [])} - {""}
    return [describe(p, domain) for p in packages], public


def previous_table(out: Path, env: str) -> tuple[dict, str]:
    tables = sorted(out.glob(f"smoke-catalogue-{env}-*.tsv"))
    if not tables:
        return {}, ""
    at = tables[-1].stem.rsplit("-", 1)[1]
    with tables[-1].open(newline="") as handle:
        return {r["dataset"]: r for r in csv.DictReader(handle, delimiter="\t")}, at


def run(domain: str, env: str, out: Path, client: Client | None = None, now: str | None = None) -> int:
    client = client or Client()
    now = now or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    previous, previous_at = previous_table(out, env)
    datasets, public = inventory(client, domain)
    rows = Run(client, domain, previous, previous_at, now).table(datasets, public)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"smoke-catalogue-{env}-{now}.tsv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, ["dataset", "endpoint", "type", *COLUMNS], delimiter="\t",
                                extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    bad = 0
    for row in rows:
        kos = [f"{c} {row[c][4:]}" for c in COLUMNS if verdict(row[c]) == "ko"]
        bad += bool(kos)
        if kos:
            print(f"  FAIL  catalogue {row['dataset']} ({row['endpoint']}): {'; '.join(kos)}")
    named = [r for r in rows if r["dataset"] != "(no dataset)"]
    complete = sum(all(verdict(r[c]) != "ko" for c in COLUMNS) for r in named)
    seconds = client.elapsed()
    summary = (f"catalogue: {len(named)} datasets, {complete} complete, {len(named) - complete} ko, "
               f"{len(rows) - len(named)} public Endpoints without a dataset; "
               f"{client.count} requests in {int(seconds // 60)} min {int(seconds % 60)} s; {path}")
    print(f"  {'FAIL' if bad else 'ok  '}  {summary}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    # One lookup per host for the whole run: the smoke host's resolver can stall seconds per
    # lookup (T-3420), which a 500-request run would pay 500 times.
    socket.getaddrinfo = functools.lru_cache(maxsize=64)(socket.getaddrinfo)
    return run(argv[1], argv[2], Path(argv[3] if len(argv) == 4 else DEFAULT_OUT))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
