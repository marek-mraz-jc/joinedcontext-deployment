"""The demo NATS broker and feed publisher for dev (T-0477, PL-50).

Proves a broker input end to end on dev by providing a live feed on a subject
every ten seconds. Dev only, never in production.
"""

import json
from pathlib import Path

import pytest
import yaml

import open_data

NATS_IMAGE_DIGEST = "sha256:54eac64d71b1b04360c2bba312a6b652ff7da0b7e7328865c977518aa5e29d11"
FEED_IMAGE_DIGEST = "sha256:656c55de3f8deddd4ee743f3c76f3b497e67324e940f2bc1769693cd8b906364"


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


@pytest.fixture(scope="module")
def local(rendered):
    return rendered("local")


def by_name(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d.get("metadata", {}).get("name") == name)


def test_both_deployments_exist_with_pinned_images(dev):
    nats = by_name(dev, "Deployment", "demo-nats")
    feed = by_name(dev, "Deployment", "demo-feed")

    nats_container = nats["spec"]["template"]["spec"]["containers"][0]
    feed_container = feed["spec"]["template"]["spec"]["containers"][0]

    assert nats_container["image"] == f"docker.io/library/nats:2.14.6-scratch@{NATS_IMAGE_DIGEST}"
    assert feed_container["image"] == f"ghcr.io/warpstreamlabs/bento:1.21.1@{FEED_IMAGE_DIGEST}"


def test_nats_pod_template_security_and_opaque_ports(dev):
    nats = by_name(dev, "Deployment", "demo-nats")
    pod = nats["spec"]["template"]

    annotations = pod.get("metadata", {}).get("annotations", {})
    assert annotations.get("config.linkerd.io/opaque-ports") == "4222"

    pod_security = pod["spec"].get("securityContext", {})
    container_security = pod["spec"]["containers"][0].get("securityContext", {})

    assert pod_security.get("runAsNonRoot") is True
    assert container_security.get("readOnlyRootFilesystem") is True


def test_nats_service_carries_the_opaque_port(dev):
    # The client proxy resolves the Service, not the pod: without this the feed's proxy waited
    # for the client to speak first and the connect timed out on dev.
    service = by_name(dev, "Service", "demo-nats")
    assert service["metadata"].get("annotations", {}).get("config.linkerd.io/opaque-ports") == "4222"


def test_feed_installs_after_nats():
    # The feed is ready only once NATS answers, so a first install of both in parallel failed.
    component = yaml.safe_load((Path(__file__).parent.parent / "components/demo-feeds/component.yaml").read_text())
    feed = next(p for p in component["parts"] if p["name"] == "feed")
    assert feed.get("needs") == ["demo-feeds.nats"]


def test_feed_configmap_content_and_service_target(dev):
    cm = by_name(dev, "ConfigMap", "demo-feed")
    assert "feed.yaml" in cm.get("data", {})

    feed_yaml = yaml.safe_load(cm["data"]["feed.yaml"])
    nats_output = feed_yaml.get("output", {}).get("nats", {})

    assert nats_output.get("subject") == "helsinki.demo.counters"
    # T-1464: every reading is an entity the gateway accepts, never a bare id.
    mapping = feed_yaml["input"]["generate"]["mapping"]
    assert 'root.id = "urn:ngsi-ld:DemoCounter:' in mapping
    assert ':helsinki:demo-counter-%d"' in mapping
    assert 'root.type = "DemoCounter"' in mapping

    nats_dep = by_name(dev, "Deployment", "demo-nats")
    nats_ns = nats_dep["metadata"]["namespace"]

    expected_url = f"nats://demo-nats.{nats_ns}.svc.cluster.local:4222"
    assert nats_output.get("urls") == [expected_url]


def test_runner_namespace_networkpolicy_allows_egress_to_nats(dev):
    runner_dep = by_name(dev, "Deployment", "pipeline-runner")
    runner_ns = runner_dep["metadata"]["namespace"]

    policies = [
        d for d in dev
        if d.get("kind") == "NetworkPolicy" and d.get("metadata", {}).get("namespace") == runner_ns
    ]

    nats_egress_rules = []
    for p in policies:
        for rule in p.get("spec", {}).get("egress", []):
            has_4222 = any(port.get("port") == 4222 and port.get("protocol") == "TCP" for port in rule.get("ports", []))
            if has_4222:
                nats_egress_rules.append((p, rule))

    assert len(nats_egress_rules) > 0, f"No egress TCP 4222 rule found in runner namespace {runner_ns}"

    policy, rule = nats_egress_rules[0]
    matched = False
    for to_peer in rule.get("to", []):
        pod_selector = to_peer.get("podSelector", {})
        labels = pod_selector.get("matchLabels", {})
        if labels.get("app.kubernetes.io/name") == "demo-feeds-nats":
            matched = True
            break
    assert matched, f"Egress rule {rule} in {policy['metadata']['name']} does not target demo-feeds-nats pods"


def test_demo_feeds_not_in_local_environment(local):
    names = {d.get("metadata", {}).get("name") for d in local if isinstance(d, dict)}
    assert "demo-nats" not in names
    assert "demo-feed" not in names


# T-2960: the Helsinki pipeline that reads the feed. The feed publishes `DemoCounter`, which no
# Helsinki model has, so without a mapping the runner refused every message (DM-61). The
# pipeline is seeded, mapped onto the KPI space's `KeyPerformanceIndicator`, only where the feed
# runs.
DEMO_SEED = Path(__file__).parent.parent / "components/context-gateway/seed/helsinki-demo-feeds"
KPI_MODEL = Path(__file__).parent.parent / "components/context-gateway/seed/helsinki/helsinki-kpi.linkml.yaml"
PIPELINE_PATH = "projects/helsinki/pipelines/demo-counters/pipeline.yaml"


def forge_seed(docs):
    configmap = next(
        (d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"].endswith("bootstrap-seed")),
        None,
    )
    return {} if configmap is None else {k.replace("__", "/"): v for k, v in configmap["data"].items()}


@open_data.requires_docker
def test_a_feed_message_becomes_one_indicator_of_the_kpi_space():
    """DM-61, PL-15: the message exactly as the feed's mapping writes it, through the seeded
    Bento processors: a KeyPerformanceIndicator minted in the pipeline's own space, whose every
    attribute is a slot of that class, so the gateway's model check passes."""
    message = {
        "id": "urn:ngsi-ld:DemoCounter:hel.fi:helsinki:demo-counter-3",
        "type": "DemoCounter",
        "note": "synthetic demo reading, not a city measurement",
        "count": 42,
        "observedAt": "2026-09-25T16:00:00.123456789Z",
    }
    (entity,) = open_data.run(DEMO_SEED / "pipeline-demo-counters-bento.yaml", json.dumps(message).encode(), "helsinki-kpi")
    assert entity["id"] == "urn:ngsi-ld:KeyPerformanceIndicator:hel.fi:helsinki-kpi:demo-counter-3"
    assert entity["type"] == "KeyPerformanceIndicator"
    assert entity["currentValue"] == {"type": "Property", "value": 42, "observedAt": "2026-09-25T16:00:00Z"}
    assert "synthetic" in entity["name"]["value"] and "synthetic" in entity["calculationFormula"]["value"]
    slots = set(yaml.safe_load(KPI_MODEL.read_text())["classes"]["KeyPerformanceIndicator"]["slots"])
    assert set(entity) - {"id", "type"} <= slots, sorted(set(entity) - {"id", "type"} - slots)


def test_dev_seeds_the_demo_pipeline_against_the_feeds_own_broker(dev):
    """T-2960: the forge seed carries the pipeline, its NATS source at the demo broker's
    namespace and the feed's subject, writing through the KPI endpoint the seed declares."""
    seed = forge_seed(dev)
    pipeline = yaml.safe_load(seed[PIPELINE_PATH])
    source = yaml.safe_load(seed["projects/helsinki/datasources/demo-feed-counters.yaml"])
    assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == source["metadata"]["name"]
    assert pipeline["spec"]["output"]["type"] == "KeyPerformanceIndicator"
    assert "projects/helsinki/pipelines/demo-counters/bento.yaml" in seed

    nats_ns = by_name(dev, "Deployment", "demo-nats")["metadata"]["namespace"]
    assert source["spec"]["type"] == "nats"
    assert source["spec"]["input"]["urls"] == [f"nats://demo-nats.{nats_ns}.svc.cluster.local:4222"]
    feed = yaml.safe_load(by_name(dev, "ConfigMap", "demo-feed")["data"]["feed.yaml"])
    assert source["spec"]["input"]["subject"] == feed["output"]["nats"]["subject"]
    assert "secrets" not in source["spec"], "the demo broker has no authentication"

    # urn:ngsi-ld:Endpoint:{org}:{space}:{name} names an endpoint the seed declares.
    *_, space, name = pipeline["spec"]["targetEndpoint"].split(":")
    assert f"projects/helsinki/spaces/{space}/endpoints/{name}.yaml" in seed


def test_an_installation_without_the_feed_seeds_no_demo_pipeline(local):
    seed = forge_seed(local)
    assert seed, "the local seed renders"
    assert PIPELINE_PATH not in seed
    assert not any("DEMO_FEEDS_NAMESPACE" in text for text in seed.values())
