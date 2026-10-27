"""The seeded MQTT demo (T-4857, MF-54, PL-76, ADR-N-048): every MqttBroker the seeds declare fits
its project's allowance, names only device ServiceAccounts of its own project that carry no
credential, lets each device publish under its own client id only, and is read by a pipeline
whose mapping writes the device's own entity and drops whatever else arrives."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from open_data import BENTO, requires_docker

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
# The ports the edge serves (hetzner-kit Traefik entrypoints mqtt-18830..18839, T-5856).
SERVED_PORTS = range(18830, 18840)
# Fields a credential could be written into: a seeded device signs in with a secret an approver
# issues in the Portal (PF-37), never one from the repository.
SECRET_KEYS = {"secret", "clientSecret", "password", "passwordRef", "privateKey", "token"}


def manifests(kind: str) -> list[dict]:
    found = []
    for index in sorted(SEED.glob("*/index.yaml")):
        for name in yaml.safe_load(index.read_text()):
            if not name.endswith(".yaml") or name.endswith(".linkml.yaml"):
                continue
            doc = yaml.safe_load((index.parent / name).read_text())
            if isinstance(doc, dict) and doc.get("kind") == kind:
                found.append(doc)
    return found


def by_name(kind: str) -> dict[tuple[str, str], dict]:
    return {(m["metadata"]["namespace"], m["metadata"]["name"]): m for m in manifests(kind)}


BROKERS = manifests("MqttBroker")
PROJECTS = {m["metadata"]["name"]: m for m in manifests("Project")}


def keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def test_the_demo_projects_each_seed_a_broker_and_helsinki_two():
    per_project = {}
    for broker in BROKERS:
        per_project.setdefault(broker["metadata"]["namespace"], []).append(broker["metadata"]["name"])
    assert sorted(per_project.get("helsinki", [])) == ["sensors", "vehicles"]
    assert per_project.get("banskabystrica") == ["ovzdusie"]


@pytest.mark.parametrize("project", sorted({b["metadata"]["namespace"] for b in BROKERS}))
def test_each_projects_brokers_fit_its_allowance(project):
    allowance = PROJECTS[project]["spec"]["quotas"]["mqtt"]
    assert allowance["enabled"] is True
    mine = [b["spec"] for b in BROKERS if b["metadata"]["namespace"] == project]
    limits = [s["limits"] for s in mine]
    assert len(mine) <= allowance["brokers"], "PF-118: one broker more than the allowance"
    assert sum(lim["maxConnections"] for lim in limits) <= allowance["connections"]
    assert sum(lim["maxConnections"] * lim["messagesPerSecond"] for lim in limits) <= allowance["messagesPerSecond"]
    assert all(lim["maxMessageBytes"] <= allowance["maxMessageBytes"] for lim in limits)
    for spec in mine:
        if "port" in spec:
            assert spec["port"] in allowance.get("ports", []), "PF-119: a port the org admin did not assign"
            assert "dedicatedPort" in allowance.get("addresses", [])
            assert spec["port"] in SERVED_PORTS, "a port the edge does not serve is never applied (T-5856)"


def test_no_dedicated_port_is_assigned_twice():
    assigned = [p for m in PROJECTS.values() for p in (m["spec"].get("quotas") or {}).get("mqtt", {}).get("ports", [])]
    held = [b["spec"]["port"] for b in BROKERS if "port" in b["spec"]]
    assert len(assigned) == len(set(assigned))
    assert len(held) == len(set(held))


@pytest.mark.parametrize("broker", BROKERS, ids=lambda b: f'{b["metadata"]["namespace"]}/{b["metadata"]["name"]}')
def test_a_device_publishes_only_under_its_own_client_id(broker):
    accounts = by_name("ServiceAccount")
    project = broker["metadata"]["namespace"]
    for role in broker["spec"]["roles"]:
        assert not role.get("sharedTopics"), "a demo device never publishes as another"
        assert not role.get("subscribe"), "an ingest broker's devices only publish (ADR-N-048 §2.10)"
        for topic in role["publish"]:
            levels = topic.split("/")
            assert "${clientid}" in levels, topic
            first_wildcard = next((i for i, lv in enumerate(levels) if lv in ("+", "#")), len(levels))
            assert levels.index("${clientid}") < first_wildcard, topic
            assert not topic.startswith("$")
        for name in role["serviceAccounts"]:
            account = accounts.get((project, name))
            assert account, f"{project}/{name}: the role names a ServiceAccount the project lacks"
            credentials = account["spec"]["credentials"]
            assert [c["kind"] for c in credentials] == ["oauth-client"]
            assert not keys(credentials) & SECRET_KEYS, "no credential in a seed (secretRef only)"
            assert all(r["role"] == "space-reader" for r in account["spec"]["roles"]), "a device writes only over MQTT"


@pytest.mark.parametrize("broker", BROKERS, ids=lambda b: f'{b["metadata"]["namespace"]}/{b["metadata"]["name"]}')
def test_each_broker_is_read_by_a_pipeline_of_its_project(broker):
    project, name = broker["metadata"]["namespace"], broker["metadata"]["name"]
    sources = [s for (p, _), s in by_name("DataSource").items()
               if p == project and (s["spec"].get("mqtt") or {}).get("brokerRef", {}).get("name") == name]
    assert len(sources) == 1, f"{project}/{name}: one DataSource reads the broker"
    mqtt = sources[0]["spec"]["mqtt"]
    assert "urls" not in mqtt and "passwordRef" not in mqtt, "PL-76: the internal listener, no credential"
    pipelines = [p for (ns, _), p in by_name("Pipeline").items() if ns == project
                 and p["spec"].get("source", {}).get("dataSourceRef", {}).get("name") == sources[0]["metadata"]["name"]]
    assert len(pipelines) == 1


def mapping(project: str, pipeline: str) -> str:
    return by_name("Pipeline")[(project, pipeline)]["spec"]["compute"]["bloblang"]


def bento(project: str, pipeline: str, domain: str, space: str, messages: list[tuple[str, object]]) -> list[dict]:
    """The pipeline's mapping over (topic, payload) pairs, as the runner reads them from the broker."""
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": {"processors": [
            {"mapping": "meta mqtt_topic = this.topic\nroot = this.payload"},
            {"mapping": mapping(project, pipeline)},
        ]},
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    lines = "".join(json.dumps({"topic": t, "payload": p}) + "\n" for t, p in messages)
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", f"JC_ORG_DOMAIN={domain}", "-e", f"JC_SPACE={space}",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        check=False, input=lines, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "error" not in result.stderr.lower(), result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


AIR = [
    ("helsinki", "mqtt-sensors", "hel.fi", "helsinki", "sensors/helsinki-sensor-kallio/air", "helsinki-sensor-kallio"),
    ("banskabystrica", "mqtt-ovzdusie", "banskabystrica.sk", "ovzdusie", "ovzdusie/banskabystrica-senzor-namestie/air",
     "banskabystrica-senzor-namestie"),
]


@requires_docker
@pytest.mark.parametrize(("project", "pipeline", "domain", "space", "topic", "client"), AIR, ids=lambda v: str(v))
def test_an_air_sensor_writes_its_own_entity_and_anything_else_is_dropped(project, pipeline, domain, space, topic, client):
    written = bento(project, pipeline, domain, space, [
        (topic, {"pm10": 12.5, "pm25": 4}),
        (topic, {"pm10": "12", "pm25": 4}),
        (topic, {"pm10": 1001, "pm25": 4}),
        (topic, {"pm10": -1, "pm25": 4}),
        (topic, {"pm25": 4}),
        (topic, "not json"),
        (topic, [1, 2]),
        (topic, {"pm10": 1, "pm25": 1, "observedAt": "2020-01-01T00:00:00Z"}),
        (topic, {"pm10": 1, "pm25": 1, "observedAt": "yesterday"}),
        (topic.replace(client, "Other Client"), {"pm10": 1, "pm25": 1}),
    ])
    assert len(written) == 1, written
    entity = written[0]
    assert entity["id"] == f"urn:ngsi-ld:AirQualityObserved:{domain}:{space}:mqtt-{client}"
    assert entity["pm10"]["value"] == 12.5 and entity["pm10"]["observedAt"] == entity["dateObserved"]["value"]
    assert "(test data)" in entity["name"]["languageMap"]["en"], "a demo reading says it is one"


@requires_docker
def test_a_tracker_writes_its_vehicle_inside_the_hsl_area_only():
    topic = "vehicles/helsinki-vehicle-demo/position"
    good = {"lat": 60.17, "lon": 24.94, "speed": 8.5, "heading": 90}
    written = bento("helsinki", "mqtt-vehicles", "hel.fi", "helsinki", [
        (topic, good),
        (topic, {**good, "lat": 48.7}),
        (topic, {**good, "speed": 45}),
        (topic, {**good, "heading": 361}),
        (topic, {k: v for k, v in good.items() if k != "heading"}),
        (topic, "{}"),
    ])
    assert [e["id"] for e in written] == ["urn:ngsi-ld:Vehicle:hel.fi:helsinki:mqtt-helsinki-vehicle-demo"]
    assert written[0]["location"]["value"]["coordinates"] == [24.94, 60.17]
