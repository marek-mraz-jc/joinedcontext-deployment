"""scripts/smoke-catalogue.py against recorded answers (T-4716): every verdict of Testing/05 §4.1,
the owner's limits (pace, budget, deadline, Retry-After) and the rotation of the slow checks."""

import csv
import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/smoke-catalogue.py"
spec = importlib.util.spec_from_file_location("smoke_catalogue", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

DOMAIN = "smartcity.example.org"
API = f"https://api.{DOMAIN}/api/endpoint"
CKAN = f"https://opendata.{DOMAIN}"
JSON, GEO, CSV = "application/json", "application/geo+json", "text/csv; charset=utf-8"


def answer(status=200, body=b"", ctype=JSON, **kw):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    return smoke.Answer(status, ctype, body, **kw)


def package(name, slug, typ, ogc=True, ws=True, datastore="ds-" , host=None):
    base = f"https://{host or 'api.' + DOMAIN}/api/endpoint/{slug}/"
    resources = [
        {"format": "NGSI-LD", "url": base + "ngsi-ld/v1/entities", "name": f"NGSI-LD API ({typ})"},
        {"format": "OData", "url": base + f"odata/v4/{typ}"},
        {"format": "MCP", "url": base + "mcp"},
        {"format": "CSV", "url": base + "file.csv"},
        {"format": "JSON", "url": base + "schema/index.json"},
    ]
    if ogc:
        resources.append({"format": "OGCFEAT", "url": base + f"ogc/features/collections/{typ}/items"})
    if ws:
        resources.append({"format": "WebSocket", "url": "wss" + base[5:] + "ws"})
    if datastore:
        resources.append({"format": "CSV", "url": f"{CKAN}/datastore/dump/{datastore}{name}",
                          "datastore_active": True, "id": f"{datastore}{name}"})
    return {"name": name, "resources": resources}


def world(packages, public, rows=10, datastore_total=10, overrides=None):
    """The answers of a healthy installation for these datasets, with `overrides` by URL."""
    answers = {
        f"{CKAN}/api/3/action/package_search?rows=1000&start=0":
            answer(body={"result": {"count": len(packages), "results": packages}}),
        f"https://api.{DOMAIN}/catalog.jsonld":
            answer(body={"dcat:dataset": [{"@id": f"{API}/{s}"} for s in public]}),
    }
    for p in packages:
        data = smoke.describe(p, DOMAIN)
        base, t = f"{API}/{data.slug}/", data.type
        answers.update({
            base + "ngsi-ld/v1/entities?" + urllib.parse.urlencode({"type": t, "limit": 1}):
                answer(body=[{"id": f"urn:ngsi-ld:{t}:1", "type": t}], ctype="application/ld+json"),
            base + "mcp": answer(body={"result": {"tools": [{"name": "query"}]}}),
            base + f"odata/v4/{t}?%24top=1&%24count=true": answer(body={"@odata.count": rows, "value": [{}]}),
            base + f"ogc/features/collections/{t}/items?limit=1": answer(body={"features": [{}]}, ctype=GEO),
            base + "schema/index.json": answer(body={"models": [{"types": [t]}]}),
            base + "file.csv?" + urllib.parse.urlencode({"type": t, "limit": 1}): answer(body=b"id,type\nurn:1,T\n", ctype=CSV),
            f"{CKAN}/map/{p['name']}": answer(body=b"<div data-jc-map='{&#34;layers&#34;: [{}]}'>", ctype="text/html"),
        })
        for ds in data.datastore:
            answers[f"{CKAN}/api/3/action/datastore_search?resource_id={ds}&limit=0"] = answer(
                body={"result": {"total": datastore_total}})
    answers.update(overrides or {})
    return answers


class Fake:
    """send, ws, clock and sleep of a Client, recording every request and every pause."""

    def __init__(self, answers, sockets=None):
        self.answers, self.sockets = answers, sockets or {}
        self.now, self.sent, self.pauses = 0.0, [], []

    def send(self, method, url, headers, body, limit):
        self.sent.append((method, url))
        got = self.answers.get(url, answer(404, {"type": "resource-not-found"}))
        return got.pop(0) if isinstance(got, list) else got

    def ws(self, url, typ):
        self.sent.append(("WS", url))
        return self.sockets.get(url, (101, 201, ""))

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds

    def client(self, **kw):
        return smoke.Client(self.send, self.ws, self.clock, self.sleep, **kw)


def table(answers, sockets=None, tmp_path=None, now="20261019T060000Z", **kw):
    fake = Fake(answers, sockets)
    client = fake.client(**kw)
    previous, at = smoke.previous_table(tmp_path, "prod") if tmp_path else ({}, "")
    datasets, public = smoke.inventory(client, DOMAIN)
    rows = smoke.Run(client, DOMAIN, previous, at, now).table(datasets, public)
    return {r["dataset"] + ("" if r["dataset"] != "(no dataset)" else " " + r["endpoint"]): r for r in rows}, fake


def test_a_complete_dataset_is_ok_on_every_interface():
    rows, _ = table(world([package("air", "a1", "AirQualityObserved")], ["a1"]))
    row = rows["air"]
    assert {c: smoke.verdict(row[c]) for c in smoke.COLUMNS} == {c: "ok" for c in smoke.COLUMNS}
    assert row["type"] == "AirQualityObserved"


def test_a_missing_model_is_a_ko():
    p = package("air", "a1", "AirQualityObserved")
    rows, _ = table(world([p], ["a1"], overrides={f"{API}/a1/schema/index.json": answer(404)}))
    assert rows["air"]["model"].startswith("ko: schema/index.json answered 404")


def test_a_model_that_lacks_the_type_is_a_ko():
    p = package("air", "a1", "AirQualityObserved")
    rows, _ = table(world([p], ["a1"], overrides={
        f"{API}/a1/schema/index.json": answer(body={"models": [{"types": ["Other"]}]})}))
    assert rows["air"]["model"] == "ko: no model lists AirQualityObserved"


def test_a_dataset_without_a_datastore_table_is_a_ko():
    rows, _ = table(world([package("air", "a1", "AirQualityObserved", datastore="")], ["a1"]))
    assert rows["air"]["datastore"] == "ko: no datastore table"


def test_a_datastore_ten_percent_off_is_a_ko_and_within_one_percent_is_ok():
    off, _ = table(world([package("air", "a1", "AirQualityObserved")], ["a1"], rows=100, datastore_total=90))
    assert off["air"]["datastore"] == "ko: 90 rows, the platform holds 100 (OData @odata.count)"
    near, _ = table(world([package("air", "a1", "AirQualityObserved")], ["a1"], rows=100, datastore_total=101))
    assert near["air"]["datastore"] == "ok: 101 rows = 100"


def test_a_shared_type_is_compared_by_its_own_is_part_of_or_not_at_all():
    a, b = package("one", "s1", "Person"), package("two", "s1", "Person")
    rows, _ = table(world([a, b], ["s1"], rows=50, datastore_total=7))
    assert rows["one"]["datastore"] == "ok: 7 rows; not compared, Person is shared by 2 datasets"
    c = package("three", "s2", "Road")
    c["resources"] = [dict(r, url=r["url"] + "?isPartOf=https%3A%2F%2Fx%2Fdataset%2Fthree")
                      if r["format"] == "OGCFEAT" else r for r in c["resources"]]
    url = f"{API}/s2/ogc/features/collections/Road/items?limit=1&isPartOf=https%3A%2F%2Fx%2Fdataset%2Fthree"
    rows, _ = table(world([c], ["s2"], rows=500, datastore_total=7,
                          overrides={url: answer(body={"features": [{}], "numberMatched": 7}, ctype=GEO)}))
    assert rows["three"]["datastore"] == "ok: 7 rows = 7"


def test_a_dev_host_in_the_production_catalogue_is_a_ko():
    p = package("bb", "d1", "CouncilMeeting", host="api.dev.example.org")
    rows, _ = table(world([p], ["d1"]))
    assert rows["bb"]["inventory"] == "ko: API on another installation's host api.dev.example.org"


def test_a_public_endpoint_without_a_dataset_and_a_dataset_without_an_endpoint_are_ko():
    lonely = {"name": "lonely", "resources": [{"format": "CSV", "url": "https://example.org/x.csv"}]}
    rows, _ = table(world([package("air", "a1", "AirQualityObserved"), lonely], ["a1", "z9"]))
    assert rows["(no dataset) z9"]["inventory"] == "ko: a public Endpoint that no dataset names"
    assert rows["lonely"]["inventory"] == "ko: the dataset lists no Endpoint distribution"
    assert rows["air"]["inventory"] == "ok"


def test_an_endpoint_missing_from_the_feed_is_a_ko():
    rows, _ = table(world([package("air", "a1", "AirQualityObserved")], []))
    assert rows["air"]["inventory"] == "ko: its Endpoint is not in the public DCAT feed"


def test_a_websocket_not_served_is_ok_only_with_the_documented_404():
    p = package("air", "a1", "AirQualityObserved", ws=False)
    ws = f"wss://api.{DOMAIN}/api/endpoint/a1/ws"
    refused, _ = table(world([p], ["a1"]), {ws: (404, 0, "")})
    assert refused["air"]["websocket"] == "ok: not served, refused 404 as API/02 names"
    wrong, _ = table(world([p], ["a1"]), {ws: (405, 0, "")})
    assert wrong["air"]["websocket"] == "ko: not served, but the upgrade answered 405"
    served, _ = table(world([package("air", "a1", "AirQualityObserved")], ["a1"]), {ws: (101, 403, "")})
    assert served["air"]["websocket"] == "ko: upgrade 101, subscribe 403"


def test_a_type_without_location_skips_ogc_and_the_map():
    rows, fake = table(world([package("budget", "b1", "Budget", ogc=False)], ["b1"]))
    assert rows["budget"]["ogc"].startswith("skip: the dataset lists no OGC distribution")
    assert rows["budget"]["map"].startswith("skip:")
    assert not any("/ogc/" in url or "/map/" in url for _, url in fake.sent)


def test_a_timeout_is_a_ko_with_its_time():
    p = package("air", "a1", "AirQualityObserved")
    url = f"{API}/a1/odata/v4/AirQualityObserved?%24top=1&%24count=true"
    rows, _ = table(world([p], ["a1"], overrides={url: answer(0, error="timeout after 20 s")}))
    assert rows["air"]["odata"] == "ko: AirQualityObserved answered timeout after 20 s, no @odata.count"


def test_an_mcp_event_stream_answer_counts_its_tools():
    stream = b'event: message\ndata: {"result": {"tools": [{"name": "a"}, {"name": "b"}]}}\n\n'
    assert smoke.mcp_tools(answer(body=stream, ctype="text/event-stream")) == 2
    assert smoke.mcp_tools(answer(body=b"<html>", ctype="text/html")) == 0


def test_requests_are_paced_counted_and_asked_once():
    a, b = package("one", "s1", "Person"), package("two", "s1", "Person")
    rows, fake = table(world([a, b], ["s1"]))
    urls = [url for _, url in fake.sent]
    assert len(urls) == len(set(urls)), "a shared answer is fetched once"
    assert all(p >= smoke.INTERVAL - 1e-9 for p in fake.pauses)
    assert smoke.verdict(rows["two"]["mcp"]) == "ok"


def test_a_spent_budget_leaves_cells_not_this_run_and_never_ko():
    packages = [package(f"d{i}", f"e{i}", "Thing") for i in range(5)]
    rows, fake = table(world(packages, [f"e{i}" for i in range(5)]), budget=12)
    assert len([s for s in fake.sent]) <= 12
    cells = [r[c] for r in rows.values() for c in smoke.COLUMNS]
    assert "not this run (never)" in cells
    assert not any(smoke.verdict(c) == "ko" for c in cells)


def test_the_deadline_stops_the_run_at_ten_minutes():
    packages = [package(f"d{i}", f"e{i}", "Thing") for i in range(200)]
    fake = Fake(world(packages, [f"e{i}" for i in range(200)]))
    client = fake.client()
    datasets, public = smoke.inventory(client, DOMAIN)
    smoke.Run(client, DOMAIN, {}, "", "now").table(datasets, public)
    assert client.count <= smoke.BUDGET and fake.now <= smoke.DEADLINE


def test_a_429_waits_its_retry_after_and_the_retry_is_counted():
    fake = Fake({"https://x/": [answer(429, retry_after="7"), answer(200, {"ok": True})]})
    client = fake.client()
    got = client.fetch("https://x/")
    assert got.status == 200 and client.count == 2 and 7 in fake.pauses


def test_the_slow_checks_rotate_least_recently_checked_first(tmp_path):
    packages = [package(f"d{i}", f"e{i}", "Thing") for i in range(3)]
    previous = tmp_path / "smoke-catalogue-prod-20261019T050000Z.tsv"
    with previous.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, ["dataset", "endpoint", "type", *smoke.COLUMNS], delimiter="\t")
        writer.writeheader()
        writer.writerow({"dataset": "d0", **{c: "ok" for c in smoke.COLUMNS}})
        writer.writerow({"dataset": "d1", **{c: "ok" for c in smoke.COLUMNS},
                         **{c: "not this run (last: 20261019T030000Z ko)" for c in smoke.ROTATING}})
    # 2 inventory + 3 × 5 core shared nothing: 17, then room for one dataset's 4 slow checks.
    rows, fake = table(world(packages, ["e0", "e1", "e2"]), tmp_path=tmp_path, budget=21)
    assert smoke.verdict(rows["d2"]["csv"]) == "ok", "never checked goes first"
    assert rows["d1"]["csv"] == "not this run (last: 20261019T030000Z ko)", "the carried time stays"
    assert rows["d0"]["csv"] == "not this run (last: 20261019T050000Z ok)"


def test_a_run_writes_one_table_and_exits_one_on_a_ko(tmp_path, capsys):
    p = package("air", "a1", "AirQualityObserved", datastore="")
    fake = Fake(world([p], ["a1"]))
    assert smoke.run(DOMAIN, "prod", tmp_path, fake.client(), "20261019T060000Z") == 1
    table_path = tmp_path / "smoke-catalogue-prod-20261019T060000Z.tsv"
    rows = list(csv.DictReader(table_path.open(), delimiter="\t"))
    assert rows[0]["datastore"] == "ko: no datastore table"
    out = capsys.readouterr().out
    assert "  FAIL  catalogue air (a1): datastore no datastore table" in out
    assert "1 datasets, 0 complete, 1 ko" in out


def test_a_clean_run_exits_zero(tmp_path, capsys):
    fake = Fake(world([package("air", "a1", "AirQualityObserved")], ["a1"]))
    assert smoke.run(DOMAIN, "prod", tmp_path, fake.client(), "20261019T060000Z") == 0
    assert "1 datasets, 1 complete, 0 ko" in capsys.readouterr().out


@pytest.mark.parametrize("status", [500, 0])
def test_an_unreadable_catalogue_stops_the_run_red(status, tmp_path):
    fake = Fake({})
    fake.answers[f"{CKAN}/api/3/action/package_search?rows=1000&start=0"] = answer(status, error="x" if not status else "")
    with pytest.raises(SystemExit, match="package_search answered"):
        smoke.run(DOMAIN, "prod", tmp_path, fake.client(), "t")


def test_a_rate_limit_that_lasts_is_not_this_run_never_a_ko():
    p = package("air", "a1", "AirQualityObserved")
    url = f"{API}/a1/mcp"
    rows, fake = table(world([p], ["a1"], overrides={url: answer(429, retry_after="2")}))
    assert rows["air"]["mcp"] == "not this run (never)"
    assert [u for _, u in fake.sent].count(url) == 1 + smoke.RETRIES
    assert not any(smoke.verdict(rows["air"][c]) == "ko" for c in smoke.COLUMNS)


def test_a_503_that_lasts_is_a_ko():
    p = package("air", "a1", "AirQualityObserved")
    rows, _ = table(world([p], ["a1"], overrides={f"{API}/a1/schema/index.json": answer(503)}))
    assert rows["air"]["model"].startswith("ko: schema/index.json answered 503")


def test_slow_answers_still_end_inside_ten_minutes():
    packages = [package(f"d{i}", f"e{i}", "Thing") for i in range(200)]
    fake = Fake(world(packages, [f"e{i}" for i in range(200)]))
    send = fake.send

    def slow(*args):
        fake.now += 19.0
        return send(*args)

    client = smoke.Client(slow, fake.ws, fake.clock, fake.sleep)
    datasets, public = smoke.inventory(client, DOMAIN)
    smoke.Run(client, DOMAIN, {}, "", "now").table(datasets, public)
    assert fake.now <= smoke.DEADLINE


def test_a_run_that_ends_early_starts_the_next_with_the_datasets_it_missed(tmp_path):
    packages = [package(f"d{i}", f"e{i}", "Thing") for i in range(3)]
    previous = tmp_path / "smoke-catalogue-prod-20261019T050000Z.tsv"
    with previous.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, ["dataset", "endpoint", "type", *smoke.COLUMNS], delimiter="\t")
        writer.writeheader()
        for name in ("d0", "d1"):
            writer.writerow({"dataset": name, **{c: "ok" for c in smoke.COLUMNS}})
        writer.writerow({"dataset": "d2", **{c: "not this run (never)" for c in smoke.COLUMNS}})
    rows, _ = table(world(packages, ["e0", "e1", "e2"]), tmp_path=tmp_path, budget=7)
    assert smoke.verdict(rows["d2"]["ngsi-ld"]) == "ok"
    assert rows["d0"]["ngsi-ld"] == "not this run (last: 20261019T050000Z ok)"


def test_a_dataset_without_a_type_reads_the_endpoint_s_types_and_names_a_failure():
    p = package("stats", "v1", "Thing")
    p["resources"] = [dict(r, url=r["url"].rsplit("/odata/v4/", 1)[0] + "/odata/v4/" if "odata" in r["url"] else r["url"],
                           name="") for r in p["resources"] if r["format"] != "OGCFEAT"]
    types = f"{API}/v1/ngsi-ld/v1/types"
    search = {f"{CKAN}/api/3/action/package_search?rows=1000&start=0":
              answer(body={"result": {"count": 1, "results": [p]}})}
    healthy = world([package("stats", "v1", "Thing", ogc=False)], ["v1"])
    rows, _ = table({**healthy, **search, types: answer(body={"typeList": ["Thing"]})})
    assert rows["stats"]["type"] == "Thing" and smoke.verdict(rows["stats"]["odata"]) == "ok"
    rows, _ = table({**healthy, **search, types: answer(500)})
    assert rows["stats"]["ngsi-ld"] == "ko: no entity type: types answered 500 application/json"


def test_a_trickling_answer_is_cut_at_the_timeout_in_total(monkeypatch):
    import socket
    import threading
    import time

    monkeypatch.setattr(smoke, "TIMEOUT", 1.0)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve():
        conn, _ = listener.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 100000\r\n\r\n")
        for _ in range(30):
            try:
                conn.sendall(b"x" * 1000)
                time.sleep(0.2)
            except OSError:
                break
        conn.close()
        listener.close()

    threading.Thread(target=serve, daemon=True).start()
    started = time.monotonic()
    got = smoke.send("GET", f"http://127.0.0.1:{listener.getsockname()[1]}/", {}, None)
    assert got.error == "timeout after 1 s" and time.monotonic() - started < 3


def test_the_tables_live_where_an_apply_leaves_them_and_git_ignores_them():
    root = SCRIPT.parent.parent
    justfile = (root / "justfile").read_text()
    removed = [line.split("rm -rf", 1)[1].split() for line in justfile.splitlines() if "rm -rf" in line]
    assert all(smoke.DEFAULT_OUT not in words and "." not in words for words in removed)
    assert f"/{smoke.DEFAULT_OUT}/" in (root / ".gitignore").read_text().splitlines()
