"""The data workspace journey's own Alert grant (T-5092, ui/e2e/live/data-workspace.spec.ts).

The steward adds one Alert through the "Add row" form and deletes it again. The grant reaches
only rows a person marked `journey` and left without `source`; every Helsinki pipeline writes
Alerts with category `traffic` and a `source`, so no pipeline row is deletable through it.
"""

import json
import re
from pathlib import Path

import yaml
from conftest import demo_id

HELSINKI = Path(__file__).resolve().parent.parent / "components/context-gateway/seed/helsinki"
POLICY = HELSINKI / "helsinki-policy-steward-row-journey.yaml"


def test_the_journey_grant_is_seeded_for_the_steward_alone_and_only_creates_and_deletes_journey_alerts():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    assert index[POLICY.name] == "projects/helsinki/spaces/helsinki/policies/steward-row-journey.yaml"
    spec = yaml.safe_load(POLICY.read_text())["spec"]
    assert spec["assignee"] == {"kind": "user", "id": demo_id("demo.steward")}
    assert spec["operations"] == ["createEntity", "deleteEntity"]
    assert spec["information"] == [{"entities": [{"type": "Alert"}]}]
    assert spec.get("effect", "permission") == "permission"
    assert "validity" not in spec
    assert spec["q"].split(";") == ['category=="journey"', "!source"]


def test_every_pipeline_alert_carries_traffic_and_a_source_so_the_journey_grant_reaches_none():
    writers = []
    for mapping in sorted(HELSINKI.glob("helsinki-pipeline-*-bento.yaml")):
        text = mapping.read_text()
        if not re.search(r'"type":\s*"Alert"', text):
            continue
        writers.append(mapping.name)
        categories = re.findall(r'"category":\s*(\{[^}]*\})', text)
        assert categories, f"{mapping.name} writes an Alert without a category"
        assert all(json.loads(c)["value"] == "traffic" for c in categories), mapping.name
        assert re.search(r'"source":', text), f"{mapping.name} writes an Alert without source"
    assert writers, "no Helsinki pipeline writes Alert: the grant's premise changed"
