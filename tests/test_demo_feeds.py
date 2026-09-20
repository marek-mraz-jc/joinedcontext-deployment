"""The demo NATS broker and feed publisher for dev (T-0477, PL-50).

Proves a broker input end to end on dev by providing a live feed on a subject
every ten seconds. Dev only, never in production.
"""

import pytest
import yaml

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
    from pathlib import Path

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
