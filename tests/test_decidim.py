"""Citizen participation from Decidim (T-5065): the harvester (seeds/decidim/pipeline.yaml) run in Bento
against a stand-in Decidim that answers as 0.29.5 (tvormespolu.banskabystrica.sk on 2026-10-21: proposals
and budget projects come back null to an anonymous client, so their list pages are read) and as 0.27 (all
records in the API, no `withdrawn` field, a second page). The entities must fit the model's JSON Schema,
carry no author, e-mail or phone, reach only the instance's host, and respect robots.txt. The seed cases
check the space, its two Endpoints, the read Policy and that generate.py wrote what instances.csv says.
"""
import copy
import http.server
import json
import re
import shutil
import subprocess
import sys
import threading
import typing
from pathlib import Path
from urllib.parse import urlparse

import jsonschema
import pytest
import yaml
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-decidim")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/slovensko"
HERE = ROOT / "seeds/decidim"
MAPPING = HERE / "pipeline.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures/decidim"
SPACE = "slovensko-participacia"
SCHEMA = json.loads((SEED / f"{SPACE}.v1.schema.json").read_text())
TYPES = {"ParticipatoryProcess", "Proposal", "BudgetProject", "Result", "Meeting", "Debate", "Survey"}
# NGSI-LD members the broker keeps beside the model's attributes.
SYSTEM = {"scope", "expiresAt"}
PERSONAL = ("author", "authors", "nickname", "profiles", "comments", "Ján Vzorový", "navrhovatel@example.sk", "0900 123 456", "00421900123456")


def tr(text):
    return {"translation": text}


PROCESSES = [
    {"id": "219", "slug": "participatorybudget2026", "reference": "BB-PART-2024-03-219", "startDate": "2024-03-01", "endDate": "2099-12-31",
     "updatedAt": "2026-09-01T10:00:00+02:00", "title": tr("Participatívny rozpočet 2025/2026"),
     "shortDescription": tr("<p>Navrhnite projekt. Kontakt: rozpocet@example.sk, 048 4330 999</p>"),
     "steps": [{"title": tr("Zber návrhov"), "startDate": "2024-03-01T00:00:00+01:00", "endDate": "2025-09-30T00:00:00+02:00", "active": False},
               {"title": tr("Hlasovanie"), "startDate": "2025-10-01T00:00:00+02:00", "endDate": "2099-01-31T00:00:00+01:00", "active": True}]},
    {"id": "1", "slug": "programrozvojamesta", "reference": "BB-PART-2021-09-1", "startDate": "2021-09-01", "endDate": "2022-12-31",
     "updatedAt": "2026-01-09T09:14:43+01:00", "title": tr("Program rozvoja mesta"), "shortDescription": None, "steps": []},
]
COMPONENTS = {
    "219": {"Proposals": [{"id": "587", "__typename": "Proposals", "name": tr("Návrhy")}, None],
            "Budgets": [{"id": "687", "__typename": "Budgets", "name": tr("Hlasovanie")}],
            "Accountability": [{"id": "700", "__typename": "Accountability", "name": tr("Výsledky")}],
            "Meetings": [{"id": "583", "__typename": "Meetings", "name": tr("Stretnutia")}],
            "Debates": [{"id": "512", "__typename": "Debates", "name": tr("Diskusie")}],
            "Surveys": [{"id": "833", "__typename": "Surveys", "name": tr("Dotazník o ihrisku")}]},
    "1": {},
}


def proposal(n, **kw):
    base = {"id": str(n), "reference": f"BB-PROP-2026-05-{n}", "title": tr(f"Návrh {n}"),
            "body": tr("<p>Lavičky pri ihrisku. Píšte na navrhovatel@example.sk alebo volajte 0900 123 456.</p>"),
            "state": "accepted", "address": "Tatranská 10", "coordinates": {"latitude": 48.7363, "longitude": 19.1462},
            "voteCount": 12, "endorsementsCount": 3, "official": False, "publishedAt": "2025-05-01T10:00:00+02:00",
            "updatedAt": "2025-06-01T10:00:00+02:00", "category": {"name": tr("Zeleň")},
            "author": {"name": "Ján Vzorový", "nickname": "vzorovy_jan"}}
    base.update(kw)
    return base


def records(version):
    """The nodes of each component as that version's API gives them, in pages of `first`."""
    v27 = version.startswith("0.27")
    if v27:
        proposals = [proposal(1), proposal(2, state="withdrawn"), proposal(3, state=None, coordinates=None)]
        projects = [{"id": "100", "reference": "BB-PROJ-1", "title": tr("Literárne záhradky"), "description": tr("Kontakt navrhovatel@example.sk"),
                     "budget_amount": 10000, "selected": True, "updatedAt": "2026-01-20T10:00:00+01:00", "category": None}]
    else:
        proposals = [None, None]
        projects = [None, None]
    return {
        "587": proposals,
        "687": [{"id": "104", "title": tr("Online hlasovanie 2025/2026"), "total_budget": 40000, "projects": projects}],
        "700": [{"id": "9", "reference": "BB-RES-9", "title": tr("Ihrisko Lazovná"), "description": tr("Realizácia"), "progress": 45.5,
                 "startDate": "2026-04-01", "endDate": "2026-11-30", "updatedAt": "2026-09-01T10:00:00+02:00",
                 "status": {"name": tr("Realizuje sa")}, "parent": {"id": "8"}, "category": None}],
        "583": [{"id": "77", "reference": "BB-MEET-77", "title": tr("Stretnutie k rozpočtu"), "description": tr("Komunitné centrum"),
                 "startTime": "2025-01-28T17:00:00+01:00", "endTime": "2025-01-28T19:00:00+01:00", "address": "Tatranská 10",
                 "location": tr("Komunitné centrum"), "coordinates": {"latitude": 48.74, "longitude": 19.15}, "onlineMeetingUrl": "",
                 "typeOfMeeting": "in_person", "closed": False, "privateMeeting": False, "transparent": True, "updatedAt": "2025-01-23T18:04:19+01:00",
                 "category": None, "author": {"name": "Ján Vzorový"}},
                {"id": "78", "title": tr("Súkromné"), "startTime": "2025-02-01T17:00:00+01:00", "privateMeeting": True, "transparent": False}],
        "512": [{"id": "41", "title": tr("Vízia bývania"), "description": tr("Diskusia"), "startTime": None, "endTime": None,
                 "createdAt": "2025-01-14T14:52:27+01:00", "updatedAt": "2026-02-09T15:50:36+01:00", "category": None}],
        "833": [{"id": "3", "createdAt": "2024-03-25T16:53:12+01:00", "updatedAt": "2024-03-25T16:53:12+01:00", "questionnaire": {"title": tr("")}}],
    }


class Stand(http.server.BaseHTTPRequestHandler):
    version = "0.29.5"
    robots = (200, "User-agent: *\nDisallow: /profiles/\nDisallow: /search\n")
    page = 2
    seen: typing.ClassVar[list[tuple[str, str, bytes]]] = []

    def answer(self, status, body, kind="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Stand.seen.append(("GET", self.path, b""))
        path = urlparse(self.path).path
        if path == "/robots.txt":
            return self.answer(Stand.robots[0], Stand.robots[1], "text/plain")
        if path.endswith("/f/587/proposals"):
            return self.answer(200, (FIXTURES / "proposals-0.29.html").read_bytes(), "text/html")
        if path.endswith("/f/687/budgets/104/projects"):
            return self.answer(200, (FIXTURES / "projects-0.29.html").read_bytes(), "text/html")
        return self.answer(404, "")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Stand.seen.append(("POST", self.path, body))
        q = json.loads(body)
        query, var = q["query"], q.get("variables") or {}
        if "decidim { version }" in query:
            return self.answer(200, json.dumps({"data": {"decidim": {"version": Stand.version}}}))
        if "participatoryProcesses" in query:
            return self.answer(200, json.dumps({"data": {"participatoryProcesses": PROCESSES, "assemblies": []}}))
        if "components(filter" in query:
            found = COMPONENTS.get(var["id"], {})
            return self.answer(200, json.dumps({"data": {"s": {t: found.get(t, []) for t in ("Proposals", "Budgets", "Accountability", "Meetings", "Debates", "Surveys") if f"{t}: components" in query}}}))
        if "component(id" in query:
            nodes = records(Stand.version)[var["id"]]
            start = int(var.get("after") or 0)
            chunk = nodes[start:start + Stand.page]
            more = start + Stand.page < len(nodes)
            items = {"pageInfo": {"hasNextPage": more, "endCursor": str(start + Stand.page) if more else None}, "nodes": chunk}
            return self.answer(200, json.dumps({"data": {"c": {"items": items}}}))
        return self.answer(400, json.dumps({"errors": [{"message": "unknown query"}]}))

    def log_message(self, *_):
        pass


def run(version="0.29.5", robots=None, light=False):
    Stand.version, Stand.seen = version, []
    Stand.robots = robots or (200, "User-agent: *\nDisallow: /profiles/\nDisallow: /search\n")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stand)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        config = yaml.safe_load(MAPPING.read_text().replace("__BASE__", base))
        # The waits are the politeness rule, tested apart; here they would only slow the run.
        text = json.dumps(config).replace('"duration": "1s"', '"duration": "0s"')
        config = json.loads(text)
        cfg = {"instance": "tvormespolu", "base": base, "locale": "sk", "scope": "/SK/BB/banska_bystrica",
               "locality": "Banská Bystrica", "provider": "Mesto Banská Bystrica", "light": light}
        config["input"] = {"generate": {"mapping": "root = " + json.dumps(cfg), "count": 1, "interval": ""}}
        # The runner rejects an errored message and the run fails (portal reconciler/streams.rs); a reject
        # here would replay forever, so the stand-in logs it and drops it.
        config["pipeline"]["processors"].append({"switch": [{"check": "errored()", "processors": [
            {"log": {"level": "ERROR", "message": "RUN FAILED: ${! error() }"}}, {"mapping": "root = deleted()"}]}]})
        config["output"] = {"stdout": {"codec": "lines"}}
        config["logger"] = {"level": "WARN", "format": "logfmt"}
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", "host", "-e", f"JC_SPACE={SPACE}", "-e", f"CONFIG={json.dumps(config)}",
             "--entrypoint", "sh", BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
            capture_output=True, text=True, timeout=180, check=False)
    finally:
        server.shutdown()
    entities = [e for line in done.stdout.splitlines() if line.startswith("[") for e in json.loads(line)]
    return entities, done, list(Stand.seen)


def plain(entity):
    """The entity as the model's JSON Schema reads it: each attribute its value or object."""
    out = {}
    for key, value in entity.items():
        if key in SYSTEM:
            continue
        if isinstance(value, dict) and value.get("type") in ("Property", "GeoProperty"):
            out[key] = value["value"]
        elif isinstance(value, dict) and value.get("type") == "Relationship":
            out[key] = value["object"]
        else:
            out[key] = value
    return out


def validator(kind):
    schema = copy.deepcopy(SCHEMA)
    schema["$ref"] = f"#/definitions/{kind}"
    return jsonschema.Draft7Validator(schema)


@pytest.fixture(scope="module")
def v29():
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    return run("0.29.5")


@pytest.fixture(scope="module")
def v27():
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    return run("0.27.6")


def by_type(entities):
    found = {}
    for e in entities:
        found.setdefault(e["type"], []).append(e)
    return found


@requires_docker
@pytest.mark.parametrize("shape", ["v29", "v27"])
def test_every_entity_fits_the_model(shape, request):
    entities, done, _ = request.getfixturevalue(shape)
    assert entities, done.stderr[-2000:]
    for e in entities:
        assert e["type"] in TYPES
        assert e["id"].startswith(f"urn:ngsi-ld:{e['type']}:{SPACE}:tvormespolu-")
        assert e["scope"] == "/SK/BB/banska_bystrica"
        errors = [f"{list(x.path)}: {x.message}" for x in validator(e["type"]).iter_errors(plain(e))]
        assert errors == [], (e["id"], errors)


@requires_docker
def test_0_29_reads_the_records_the_api_hides_from_their_pages(v29):
    entities, _, _ = v29
    found = by_type(entities)
    assert sorted(len(found[t]) for t in found) and {t: len(v) for t, v in found.items()} == {
        "ParticipatoryProcess": 2, "Proposal": 2, "BudgetProject": 2, "Result": 1, "Meeting": 1, "Debate": 1, "Survey": 1}
    proposals = {e["name"]["value"]: e for e in found["Proposal"]}
    assert set(proposals) == {'"Pri jednom stole". spájanie generácií', "Malý Kulturák na Sídlisku SNP"}
    one = next(iter(proposals.values()))
    assert one["stateLabel"]["value"] == "Postupuje do hlasovania"
    assert "proposalState" not in one, "a page shows no state token"
    assert one["refParticipatoryProcess"]["object"] == f"urn:ngsi-ld:ParticipatoryProcess:{SPACE}:tvormespolu-p219"
    projects = {e["name"]["value"]: e for e in found["BudgetProject"]}
    assert projects["Detské dopravné ihrisko – 2.etapa"]["voteCount"]["value"] == 307
    assert all(p["budgetAmount"]["value"] > 0 and p["budgetTotal"]["value"] == 40000 for p in projects.values())
    assert all(p["url"]["value"].endswith("/processes/participatorybudget2026/f/687/budgets/104/projects/" + p["sourceId"]["value"]) for p in projects.values())


@requires_docker
def test_0_27_reads_everything_from_the_api_across_pages_without_the_0_28_fields(v27):
    entities, _, seen = v27
    found = by_type(entities)
    proposals = {e["sourceId"]["value"]: e for e in found["Proposal"]}
    assert set(proposals) == {"1", "2", "3"}, "the third proposal sits on the second page"
    assert proposals["2"]["proposalState"]["value"] == "withdrawn"
    assert proposals["3"]["proposalState"]["value"] == "not_answered"
    assert proposals["1"]["location"]["value"] == {"type": "Point", "coordinates": [19.1462, 48.7363]}
    assert "location" not in proposals["3"]
    assert found["BudgetProject"][0]["selected"]["value"] is True
    queries = [json.loads(b)["query"] for m, _, b in seen if m == "POST"]
    assert queries and not any("withdrawn" in q for q in queries), "0.27 has no withdrawn field"
    assert not any(m == "GET" and "/f/" in p for m, p, _ in seen), "nothing hidden, no page read"


@requires_docker
def test_the_process_carries_its_phases_and_status(v29):
    found = by_type(v29[0])
    procs = {e["sourceId"]["value"]: e for e in found["ParticipatoryProcess"]}
    assert procs["219"]["status"]["value"] == "active"
    assert procs["219"]["activeStep"]["value"] == "Hlasovanie"
    assert [s["title"] for s in procs["219"]["steps"]["value"]] == ["Zber návrhov", "Hlasovanie"]
    assert procs["1"]["status"]["value"] == "past"
    assert procs["219"]["url"]["value"].endswith("/processes/participatorybudget2026")


@requires_docker
@pytest.mark.parametrize("shape", ["v29", "v27"])
def test_no_personal_data_passes(shape, request):
    entities, _, _ = request.getfixturevalue(shape)
    text = json.dumps(entities, ensure_ascii=False)
    for needle in PERSONAL:
        assert needle not in text, needle
    assert not any(e["sourceId"]["value"] == "78" for e in entities if e["type"] == "Meeting"), "a private meeting stays out"


@requires_docker
def test_every_request_goes_to_the_instance_and_asks_for_no_person(v29):
    for method, path, body in v29[2]:
        assert path.startswith("/"), "a relative path on the instance's own host"
        if method == "POST":
            q = json.loads(body)["query"]
            for field in ("author", "comments", "endorsements ", "nickname", "user"):
                assert field not in q, (field, q)


@requires_docker
def test_a_robots_txt_that_disallows_the_api_stops_the_run():
    entities, done, _ = run(robots=(200, "User-agent: *\nDisallow: /api\n"))
    assert entities == []
    assert "RUN FAILED" in done.stderr and "disallows /api" in done.stderr
    assert [p for m, p, _ in Stand.seen] == ["/robots.txt"]


@requires_docker
def test_a_robots_txt_that_disallows_the_pages_keeps_the_fallback_off():
    entities, _, _ = run(robots=(200, "User-agent: joinedcontext-platform\nDisallow: /processes/\n"))
    assert not any(m == "GET" and p.startswith("/processes/") for m, p, _ in Stand.seen)
    assert "Proposal" not in by_type(entities) and "Meeting" in by_type(entities)


@requires_docker
def test_a_robots_txt_that_fails_on_the_server_stops_the_run_and_a_missing_one_allows():
    entities, done, _ = run(robots=(503, ""))
    assert entities == [] and "RUN FAILED" in done.stderr
    entities, _, _ = run(robots=(404, ""))
    assert "Proposal" in by_type(entities)


@requires_docker
def test_the_hourly_pass_reads_only_the_budgets_of_running_processes():
    entities, _, _ = run(light=True)
    assert {e["type"] for e in entities} == {"BudgetProject"}
    posts = [json.loads(b) for m, _, b in Stand.seen if m == "POST" and b"components(filter" in b]
    assert [p["variables"]["id"] for p in posts] == ["219"], "process 1 ended in 2022"


def test_every_site_request_waits_a_second_first():
    """At most one request a second (T-5065): each http step runs right after its own 1 s sleep."""
    text = MAPPING.read_text()
    assert text.count("- http:") == text.count("- sleep: { duration: 1s }") == 6
    assert "pipeline_egress" not in text, "the site gets its own pace, not the gateway's budget"


def test_generate_check_is_clean_and_one_row_is_one_instance():
    done = subprocess.run([sys.executable, str(HERE / "generate.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
    rows = (HERE / "instances.csv").read_text().strip().splitlines()[1:]
    names = sorted(p.name for p in SEED.glob("slovensko-*-decidim-*.yaml"))
    # Per instance: two DataSources, two Pipelines, two mappings and the full pass's Policy (T-5717).
    assert len(names) == 7 * len(rows)
    index = yaml.safe_load((SEED / "index.yaml").read_text())
    for name in names:
        assert name in index, name
    for row in rows:
        inst = row.split(",")[0]
        bento = (SEED / f"slovensko-pipeline-decidim-{inst}-bento.yaml").read_text()
        base = row.split(",")[1]
        assert bento.endswith(MAPPING.read_text().replace("__BASE__", base))
        assert "__BASE__" not in bento and bento.count(f"url: {base}") == 6


def seed(name):
    return yaml.safe_load((SEED / name).read_text())


def test_the_space_reads_publicly_and_only_pipelines_write():
    space = seed("slovensko-space-participacia.yaml")
    assert space["spec"]["dataModelRef"]["name"] == SPACE
    assert {r["entityType"] for r in space["spec"]["retention"]} == TYPES
    model = seed("slovensko-datamodel-participacia.yaml")
    assert set(model["spec"]["classes"]) == TYPES
    public = seed("slovensko-endpoint-participacia.yaml")["spec"]
    assert public["audience"] == "public" and public["policyRef"].endswith(f":{SPACE}:participacia-read")
    assert public["catalog"]["personalData"] == "does-not-contain"
    write = seed("slovensko-endpoint-participacia-zapis.yaml")["spec"]
    assert write["audience"] == "organization" and "policyRef" not in write
    policy = seed("slovensko-policy-participacia-read.yaml")["spec"]
    assert policy["assignee"] == {"kind": "role", "id": "public"}
    assert not [op for op in policy["operations"] if op.startswith(("create", "update", "delete", "append", "merge", "replace", "batch")) and "Subscription" not in op]
    assert {e["type"] for i in policy["information"] for e in i["entities"]} == TYPES
    for path in SEED.glob("slovensko-pipeline-decidim-*.yaml"):
        if path.name.endswith("-bento.yaml"):
            continue
        assert seed(path.name)["spec"]["targetEndpoint"] == f"urn:ngsi-ld:Endpoint:joinedcontext.com:{SPACE}:{SPACE}-zapis"


def test_the_dataset_is_filed_under_the_town_while_it_is_the_only_instance():
    # T-6098: one instance files the dataset under its town's CKAN organization, keeping the dataset
    # name (the Endpoint's) and the slovensko instance; several fall back to the slovensko
    # organization and a Slovakia title.
    endpoint = seed("slovensko-endpoint-participacia.yaml")
    ckan = endpoint["spec"]["publish"]["ckan"]
    assert ckan == {"instanceRef": {"kind": "CkanInstance", "name": "slovensko"}, "organization": "banskabystrica", "license": "cc-by"}
    assert endpoint["metadata"]["name"] == "slovensko-participacia" and "name" not in ckan
    assert endpoint["metadata"]["title"]["sk"].endswith("Banská Bystrica")
    sys.path.insert(0, str(HERE))
    try:
        import generate
    finally:
        sys.path.remove(str(HERE))
    one = generate.rows()
    assert len(one) == 1 and generate.organization(one) == ["      organization: banskabystrica"]
    two = one + [dict(one[0], name="trnava", locality="Trnava", organization="trnava")]
    assert generate.organization(two) == []
    assert "na Slovensku" in generate.title(two)[0] and "Trnava" not in generate.title(two)[0]
    assert generate.organization([dict(one[0], organization="")]) == []


def test_every_http_step_writes_its_host_out():
    # The runner refuses a pipeline whose URL takes any part of its host from a message (PL-07,
    # jc-core data_source.rs refused_target): `https://host${! @path }` ran as RunnerRefused on dev
    # since 2026-10-22T06:12Z, since a path not starting with "/" would extend the host.
    authority = re.compile(r"://([^/?#\"'`\s]*)")
    for bento in sorted(SEED.glob("*-bento.yaml")):
        for host in authority.findall(bento.read_text()):
            assert "${!" not in host, (bento.name, host)
