"""T-2559: Model Tools' one way out is HTTPS to the public internet, never into the cluster (DM-10, OPS-19)."""

import pytest

PRIVATE_RANGES = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8"}


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def one(docs: list[dict], kind: str, name: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected exactly one {kind}/{name}, got {len(found)}"
    return found[0]


def test_its_https_way_out_never_reaches_an_address_inside_the_cluster(dev):
    """DM-10: the import fetches from the public internet; a name the person typed must not
    steer it at the Kubernetes API, a node, a webhook, another pod or a metadata service."""
    policy = one(dev, "NetworkPolicy", "model-tools")["spec"]
    blocks = [to["ipBlock"] for rule in policy["egress"] for to in rule["to"] if "ipBlock" in to]
    assert blocks, "no HTTPS rule at all"
    for block in blocks:
        assert PRIVATE_RANGES <= set(block.get("except", [])), block
