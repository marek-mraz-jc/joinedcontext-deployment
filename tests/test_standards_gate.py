"""T-5899: the release gate on dev and the prod-apply step that refuses a candidate without its record."""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "standards-gate.py"
spec = importlib.util.spec_from_file_location("standards_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
JUSTFILE = (ROOT / "justfile").read_text()


def recipe(name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\b[^\n]*:\n((?:\t.*\n|\n)+)", JUSTFILE, re.MULTILINE)
    assert m, f"{name} recipe not found in the justfile"
    return m.group(1)


def test_the_self_test_passes():
    # a red suite blocks, a stale record for another sha (other code or other pins) blocks
    run = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout + run.stderr


def test_prod_apply_checks_the_record_after_the_tag_and_before_anything_changes():
    body = recipe("prod-apply")
    verify = body.index("./scripts/release.py verify HEAD")
    check = body.index("./scripts/standards-gate.py check HEAD")
    assert verify < check < body.index("just _dev-assemble") < body.index(" sync ")


def test_check_refuses_head_without_a_record_and_passes_with_a_green_one(tmp_path, capsys):
    assert gate.main(["check", "HEAD", "--records", str(tmp_path)]) == 1
    assert "has no green release gate record" in capsys.readouterr().err
    cand = gate.candidate("HEAD")
    folder = tmp_path / cand["sha"]
    folder.mkdir()
    rec = {**cand, "green": False, "finished": "2026-10-28T09:00:00Z"}
    (folder / "record.json").write_text(json.dumps(rec))
    assert gate.main(["check", "HEAD", "--records", str(tmp_path)]) == 1
    (folder / "record.json").write_text(json.dumps({**rec, "green": True}))
    assert gate.main(["check", "HEAD", "--records", str(tmp_path)]) == 0


def test_every_stage_targets_dev_only(tmp_path):
    args = argparse.Namespace(conformance=tmp_path, portal=tmp_path, requests=None, rate=1000,
                              duration="5m", only=None)
    plan = gate.stages(args, tmp_path)
    assert [name for name, *_ in plan] == list(gate.REQUIRED)
    urls = [v for _, argv, env, _ in plan for v in [*argv, *env.values()] if "https://" in v]
    assert urls and all(re.search(r"https://[a-z.]*dev\.joinedcontext\.com", u) for u in urls), urls
    assert "smartcity" not in SCRIPT.read_text()
    assert "just _dev-guard" in recipe("release-gate")


def test_a_partial_run_is_never_green():
    stages = [{"name": n, "verdict": "pass"} for n in gate.REQUIRED if n != "load"]
    assert not gate.verdict(stages, [])
