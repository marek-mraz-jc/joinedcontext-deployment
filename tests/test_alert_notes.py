"""scripts/alert-notes.py: Alertmanager alerts become one note line when they start and one when
they resolve, carrying only allow-listed labels (T-5104)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/alert-notes.py"
spec = importlib.util.spec_from_file_location("alert_notes", SCRIPT)
alert_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert_notes)


def alert(fingerprint, name, state="active", **labels):
    return {"fingerprint": fingerprint, "status": {"state": state},
            "labels": {"alertname": name, "severity": "critical", **labels},
            "annotations": {"summary": f"{name} summary"}}


def test_an_alert_is_noted_once_when_it_fires_and_once_when_it_resolves():
    down = alert("a1", "ProbeSurfaceDown", target="dev", surface="odata", endpoint="parking")
    lines, state = alert_notes.notes([down], {})
    assert lines == ["FIRING ProbeSurfaceDown [critical] endpoint=parking surface=odata target=dev: ProbeSurfaceDown summary"]
    assert alert_notes.notes([down], state)[0] == []
    lines, state = alert_notes.notes([], state)
    assert lines == ["RESOLVED ProbeSurfaceDown [critical] endpoint=parking surface=odata target=dev: ProbeSurfaceDown summary"]
    assert state == {}


def test_silenced_and_inhibited_alerts_are_not_noted():
    assert alert_notes.notes([alert("a1", "NodeMemoryHigh", state="suppressed")], {})[0] == []


def test_only_allow_listed_labels_reach_a_note():
    leaky = alert("a2", "X", target="dev", user="jane@example.org", client_ip="198.51.100.7", authorization="Bearer abc")
    (text,), _ = alert_notes.notes([leaky], {})
    assert "jane" not in text and "198.51" not in text and "Bearer" not in text
    assert "target=dev" in text


def test_the_script_keeps_its_state_between_runs(tmp_path):
    state = tmp_path / "state.json"
    alerts = json.dumps([alert("a3", "TLSCertificateExpiresSoon", host="api.dev.example.org")])

    def run(stdin):
        return subprocess.run([sys.executable, str(SCRIPT), str(state)], input=stdin, capture_output=True, text=True, check=True).stdout

    assert run(alerts).startswith("FIRING TLSCertificateExpiresSoon [critical] host=api.dev.example.org")
    assert run(alerts).strip() == ""
    assert run("[]").startswith("RESOLVED TLSCertificateExpiresSoon")
