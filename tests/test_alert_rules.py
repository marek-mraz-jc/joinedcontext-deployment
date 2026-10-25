"""Every alert rule of the monitoring component fires on an injected fault and resolves after it,
in Prometheus' own rule engine (T-5104).

The rules render where `global.metrics.enabled` is set; dev is rendered with it set, because dev
carries every component a rule is guarded by (the probes among them) and production does not.
`tests/promtool/alerts.test.yaml` holds one fault per alert; promtool runs from the pinned
Prometheus image, so the test skips where there is no docker, as the collector's does."""

import os
import shutil
import subprocess

import pytest
import yaml
from conftest import PROJECT_ROOT

pytestmark = pytest.mark.xdist_group("docker-promtool")

# The Prometheus 3.5 LTS line; `promtool` is the image's second binary.
IMAGE = "docker.io/prom/prometheus:v3.5.0@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"
TESTS = PROJECT_ROOT / "tests/promtool/alerts.test.yaml"


@pytest.fixture
def groups(rendered):
    # dev lists the monitoring component with metrics on since T-5154.
    docs = rendered("dev")
    rules = [d for d in docs if d.get("kind") == "PrometheusRule" and d["metadata"]["name"].startswith("monitoring-")]
    assert len(rules) == 1, [d["metadata"]["name"] for d in rules]
    return rules[0]["spec"]["groups"]


def alerts(groups):
    return [r for g in groups for r in g["rules"] if "alert" in r]


def test_every_alert_has_a_fault_that_fires_it_and_a_recovery_that_clears_it(groups):
    cases = yaml.safe_load(TESTS.read_text())["tests"]
    evals = {}
    for case in cases:
        for t in case.get("alert_rule_test", []):
            evals.setdefault(t["alertname"], []).append(bool(t["exp_alerts"]))
    for rule in alerts(groups):
        name = rule["alert"]
        assert True in evals.get(name, []), f"{name}: no promtool case fires it"
        assert False in evals.get(name, []), f"{name}: no promtool case sees it resolve"
    assert set(evals) <= {r["alert"] for r in alerts(groups)}, "a promtool case names an alert the rules no longer have"


def test_slo_and_operations_alerts_are_rendered_where_their_source_is(groups):
    names = {r["alert"] for r in alerts(groups)}
    assert {"SurfaceAvailabilityBudgetBurnFast", "SurfaceAvailabilityBudgetBurnSlow", "SurfaceLatencyBudgetBurnFast",
            "SurfaceLatencyBudgetBurnSlow", "TLSCertificateExpiresSoon", "DomainExpiresSoon", "NodeDiskAlmostFull",
            "VolumeAlmostFull", "NodeMemoryHigh", "PostgresBackupStale", "PostgresBackupFailed", "PipelineDataStale",
            "PipelineErrorRatio"} <= names


def test_alert_payloads_name_no_secret_or_person(groups):
    # T-5104 Security: an alert carries its rule's labels and the series' labels, which are hosts,
    # surfaces, Endpoints, projects and volumes; no rule may template a value that could hold more.
    for rule in alerts(groups):
        text = yaml.safe_dump(rule.get("annotations", {})) + yaml.safe_dump(rule.get("labels", {}))
        for word in ("token", "secret", "password", "email", "user", "client_ip", "remote_addr"):
            assert word not in text.lower(), f"{rule['alert']} templates {word!r}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_promtool_checks_the_rules_and_runs_every_case(groups, tmp_path):
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump({"groups": groups}, sort_keys=False))
    shutil.copy(TESTS, tmp_path / "alerts.test.yaml")
    for args in (["check", "rules", "rules.yaml"], ["test", "rules", "alerts.test.yaml"]):
        result = subprocess.run(
            ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{tmp_path}:/w:ro", "-w", "/w", "--entrypoint", "promtool", IMAGE, *args],
            capture_output=True, text=True, timeout=600, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
