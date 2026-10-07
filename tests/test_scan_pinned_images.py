"""T-3289: every image the deployment pins is scanned, and a fixable CRITICAL (or a fixable HIGH
CISA lists as exploited) fails the job. The fixture is trivy's own report of the Gitea pin before
T-3286 (1.27.0-rootless), which carries CVE-2026-60004 fixed in 1.27.1."""

import datetime
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/pinned-images/gitea-1.27.0-trivy.json"
_spec = importlib.util.spec_from_file_location("scan_pinned_images", ROOT / "scripts/scan-pinned-images.py")
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

TODAY = datetime.date(2026, 10, 7)


def test_every_pin_of_every_component_is_listed_by_digest():
    images = scan.pinned()
    assert len(images) >= 20
    assert all("@sha256:" in image for image in images), images
    assert "docker.gitea.com/gitea@sha256:36cce26be71609091e1236d5b5de2c66a81fb8a7d45756a5fd3b7a28c11733b7" in images, "the chart's registry joins its repository"


def test_the_known_vulnerable_gitea_pin_fails_on_its_fixable_critical(tmp_path):
    found = scan.judge([FIXTURE], None, tmp_path / "none.yaml", TODAY)
    assert any("CVE-2026-60004 CRITICAL" in line and "fixed in 1.27.1" in line for line in found), found


def test_a_fixable_high_blocks_only_when_it_is_known_exploited(tmp_path):
    report = {"ArtifactName": "example.org/x@sha256:1", "Results": [{"Vulnerabilities": [
        {"VulnerabilityID": "CVE-2026-1", "Severity": "HIGH", "FixedVersion": "2", "PkgName": "p", "InstalledVersion": "1"},
        {"VulnerabilityID": "CVE-2026-2", "Severity": "CRITICAL", "FixedVersion": None, "PkgName": "q", "InstalledVersion": "1"},
    ]}]}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    kev = tmp_path / "kev.json"
    kev.write_text(json.dumps({"vulnerabilities": []}))
    assert scan.judge([path], kev, tmp_path / "none.yaml", TODAY) == [], "a HIGH nobody exploits and a CRITICAL with no fix wait"
    kev.write_text(json.dumps({"vulnerabilities": [{"cveID": "CVE-2026-1"}]}))
    assert scan.judge([path], kev, tmp_path / "none.yaml", TODAY) == [
        "example.org/x: CVE-2026-1 HIGH in p 1, fixed in 2"
    ]


def test_an_excuse_needs_a_reason_a_task_and_an_expiry_and_lapses(tmp_path):
    ignores = tmp_path / "ignore.yaml"
    entry = "- {image: docker.gitea.com/gitea, cve: CVE-2026-60004, reason: upgrade scheduled, task: T-3286, expires: %s}\n"
    ignores.write_text(entry % "2026-10-14")
    found = scan.judge([FIXTURE], None, ignores, TODAY)
    assert not any("CVE-2026-60004" in line for line in found), found
    ignores.write_text(entry % "2026-10-01")
    assert any("expired on 2026-10-01" in line for line in scan.judge([FIXTURE], None, ignores, TODAY))
    ignores.write_text("- {image: docker.gitea.com/gitea, cve: CVE-2026-60004, expires: 2026-10-14}\n")
    found = scan.judge([FIXTURE], None, ignores, TODAY)
    assert any("an excuse names its reason, a task" in line for line in found)
    assert any("CVE-2026-60004 CRITICAL" in line for line in found), "an incomplete excuse excuses nothing"
