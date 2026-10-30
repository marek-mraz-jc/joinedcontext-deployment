"""T-5899: the release gate on dev and the prod-apply step that refuses a candidate without its record."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_the_committed_known_reds_park_todays_dev_smoke_reds_and_nothing_else(tmp_path):
    # the lines dev-smoke prints on every run since 2026-10-27 (deployer, T-5899 09:4xZ), as the scripts print them;
    # the source links budget line left with T-5903
    log = (
        "  FAIL  catalogue catalog (wna4brinxxxxxxxxxxxxxxxxxxxx): count 0 entities of Catalog\n"
        "  FAIL  catalogue (no dataset) (emzask3oxxxxxxxxxxxxxxxxxxxx): ckan no dataset lists this Endpoint\n"
        "  FAIL  catalogue (no dataset) (y5jpwu6fxxxxxxxxxxxxxxxxxxxx): ckan no dataset lists this Endpoint\n"
        "  FAIL  catalogue: 626 datasets, 625 complete, 1 ko, 2 public Endpoints without a dataset; 482 requests\n"
    )
    known = gate.known_red()
    assert all(task.startswith("T-") for task, _ in known)

    def smoke(text):
        argv = ["bash", "-c", f"printf %s {gate.quote(text)}; exit 1"]
        return gate.run_stage("dev-smoke", argv, {}, tmp_path, tmp_path / "out", known)

    held = smoke("  ok    portal: 200\n" + log)
    assert held["verdict"] == "pass", held
    assert len(held["known_red"]) == 4
    # T-5903: the sweep finishes, so a budget cut is a red again
    assert smoke(log + "  FAIL  source links: the run's budget ended after 482 requests\n")["verdict"] == "fail"
    # a catalogue outage or another Endpoint's red is not parked
    assert smoke(log + "  FAIL  catalogue: package_search answered 503\n")["verdict"] == "fail"
    assert smoke(log + "  FAIL  catalogue bbsk-x (abcdefgh): count 0 entities\n")["verdict"] == "fail"
    assert smoke(log + "  FAIL  source link e1 T: resolved a, expected b\n")["verdict"] == "fail"


def test_the_first_live_runs_reds_are_parked_by_case_and_a_suite_row_does_not_hide_them(tmp_path):
    # c97c4488 on dev (deployer 2026-10-28T14:1xZ): the helsinki-feedback catalogue row is parked
    known = gate.known_red()
    feedback = ("  FAIL  catalogue helsinki-feedback (gv24bicwway4foznuszsagmzydzk3e2z): data urn:ngsi-ld:ServiceRequest:"
                "hel.fi:helsinki:open311-3379243 has no name; urn:ngsi-ld:ServiceRequest:hel.fi:helsinki:open311-1 has no name"
                " (+17 more)\n")
    argv = ["bash", "-c", f"printf %s {gate.quote(feedback)}; exit 1"]
    assert gate.run_stage("dev-smoke", argv, {}, tmp_path, tmp_path / "s", known)["verdict"] == "pass"
    other = feedback.replace("has no name", "has no location", 1)
    argv = ["bash", "-c", f"printf %s {gate.quote(other)}; exit 1"]
    assert gate.run_stage("dev-smoke", argv, {}, tmp_path, tmp_path / "s2", known)["verdict"] == "fail"

    def ws(reds: dict[str, list[str]]):
        out = tmp_path / f"ws{len(list(tmp_path.iterdir()))}"
        rows = ["endpoint\tsuite\tverdict\tdetail\tlog"]
        for ep, names in reds.items():
            (out / "ws" / ep / "ws").mkdir(parents=True)
            body = "".join(f'<testcase classname="tests.ws.test_gateway_ws" name="{n}"><failure/></testcase>' for n in names)
            (out / "ws" / ep / "ws" / "pytest.xml").write_text(f'<testsuite><testcase classname="c" name="ok"/>{body}</testsuite>')
            rows.append(f"{ep}\tws\t{'fail' if names else 'pass'}\tx\ty")
        (out / "ws" / "results.tsv").write_text("\n".join(rows) + "\n")
        return gate.run_stage("ws", ["false"], {}, tmp_path, out, known)

    a, b = "hqgmj6ieuq57y37g5g4ckz5eyhebklox", "mluyob4nz52lok3ssk7pgn5vwt"
    flood = "test_a_subscribe_flood_closes_with_1008_and_another_socket_stays"
    upgrade = "test_a_plain_get_answers_426_naming_the_upgrade"
    # T-5931 fixed both ws cases (the edge advertises the upgrade, the gateway ends a flood with a close
    # handshake): neither is parked any more, on either Endpoint.
    assert ws({a: [upgrade]})["verdict"] == "fail", "the 426 without Upgrade is red again"
    assert ws({b: [flood]})["verdict"] == "fail", "the flood without its 1008 is red again"


def test_the_roundtrip_stage_writes_only_on_the_seeded_conformance_endpoint(tmp_path, monkeypatch):
    # T-5914: the write-here read-everywhere stage targets the conformance space's own Endpoint
    args = argparse.Namespace(conformance=tmp_path, portal=tmp_path, requests=None, rate=1000,
                              duration="5m", only=["roundtrip"])
    monkeypatch.delenv("WRITE_ENDPOINT", raising=False)
    [(name, argv, env, cwd)] = gate.stages(args, tmp_path)
    seeded = re.search(r"slug: (\w+)", gate.CONFORMANCE_ENDPOINT.read_text()).group(1)
    assert name == "roundtrip" and cwd == tmp_path and env == {}
    assert argv[argv.index("--endpoint") + 1] == f"https://api.dev.joinedcontext.com/api/endpoint/{seeded}"
    assert "contextSpaceRef: conformance" in gate.CONFORMANCE_ENDPOINT.read_text()
    monkeypatch.setenv("WRITE_ENDPOINT", "abc")
    assert gate.stages(args, tmp_path)[0][1][argv.index("--endpoint") + 1].endswith("/api/endpoint/abc")
    monkeypatch.setenv("WRITE_ENDPOINT", "../x")
    try:
        gate.stages(args, tmp_path)
    except gate.Refused as e:
        assert "not an Endpoint slug" in str(e)
    else:
        raise AssertionError("a WRITE_ENDPOINT that is no slug must refuse")


def test_a_red_roundtrip_case_blocks_the_record(tmp_path):
    # the deliberate break: the suite's red line, as roundtrip.py prints it, turns the stage and the record red
    line = "  FAIL  current OData: OData: pm10.value: want 21.5 got 22"
    script = f"print('  ok  current NGSI-LD retrieve'); print({line!r}); raise SystemExit(1)"
    stage = gate.run_stage("roundtrip", [sys.executable, "-c", script], {}, tmp_path, tmp_path, known=[])
    assert stage["verdict"] == "fail"
    assert stage["cases"]["roundtrip::current OData"] == "fail"
    assert stage["cases"]["roundtrip::current NGSI-LD retrieve"] == "pass"
    green = [{"name": n, "verdict": "pass"} for n in gate.REQUIRED if n != "roundtrip"]
    assert not gate.verdict([*green, stage], [])
    assert gate.verdict([*green, {**stage, "verdict": "pass"}], [])


def test_the_sweep_leaves_the_critic_walks_out_and_gets_its_own_cap(tmp_path, monkeypatch):
    # first record b629a881: the sweep hit the 3600 s stage cap at spec 79 of 330, 1,619 s of it critic-* walks
    args = argparse.Namespace(conformance=tmp_path, portal=tmp_path, requests=None, rate=8,
                              duration="5m", only=["portal-sweep", "ws"], stage_timeout=3600,
                              sweep_timeout=18000, rev="HEAD", records=tmp_path)
    env = {name: env for name, _, env, _ in gate.stages(args, tmp_path)}["portal-sweep"]
    skip = re.compile(env["SWEEP_SKIP"])
    assert skip.search("e2e/live/critic-policy.spec.ts") and not skip.search("e2e/live/mqtt-device.spec.ts")
    seen = {}
    monkeypatch.setattr(gate, "candidate", lambda rev: {"sha": "a" * 40, "images": {}})
    monkeypatch.setattr(gate, "preflight", lambda rev, names: {})
    monkeypatch.setattr(gate, "run_stage", lambda name, *a: seen.setdefault(name, a[-1]) and
                        {"name": name, "verdict": "pass", "problems": [], "cases": {}})
    monkeypatch.setattr(gate, "record_of", lambda *a: {"green": False, "sha": "a" * 40})
    monkeypatch.setattr(gate, "write", lambda rec, root: tmp_path)
    gate.run(args)
    assert seen == {"portal-sweep": 18000, "ws": 3600}, seen


def test_the_per_apply_smoke_leaves_the_two_data_sweeps_to_the_hourly_recipe_and_the_gate():
    # T-6148: the catalogue (~15 min) and source-link (~5 min) sweeps held every apply ~20 min;
    # the per-apply smoke keeps every other check, the release gate and prod-smoke keep the sweeps.
    sweeps = ("smoke-catalogue.py", "smoke-source-links.py")
    per_apply = recipe("_smoke") + recipe("dev-smoke")
    assert not [s for s in sweeps if s in per_apply]
    for check in ("scripts/smoke.sh", "smoke-public-apps.py", "failed-jobs.py", "smoke-edge-wave.py",
                  "smoke-forge-login.sh", "disk-full.py"):
        assert check in per_apply, check
    assert all(s in recipe("_smoke-sweeps") for s in sweeps)
    assert "just _dev-guard" in recipe("dev-smoke-sweeps")
    assert 'just _smoke-sweeps "{{ dev_domain }}" dev' in recipe("dev-smoke-sweeps")
    full = recipe("dev-smoke-full")
    assert "just dev-smoke " in full and 'just _smoke-sweeps "{{ dev_domain }}" dev' in full
    assert 'just _smoke-sweeps "{{ prod_domain }}" smartcity' in recipe("prod-smoke")
    plan = [p for p in gate.stages(argparse.Namespace(conformance=ROOT, portal=ROOT, only=None, requests=None,
                                                             rate=1, duration="1s"), ROOT) if p[0] == "dev-smoke"]
    assert plan[0][1] == ["just", "dev-smoke-full"]


@pytest.mark.parametrize("name", ["dev-smoke", "dev-smoke-sweeps", "dev-smoke-full", "prod-smoke"])
def test_the_smoke_recipes_parse(name):
    run = subprocess.run(["just", "--dry-run", name], cwd=ROOT, capture_output=True, text=True, check=False,
                         env={**os.environ, "JUST_NO_DOTENV": "true"})
    assert run.returncode == 0, run.stderr


def broker_repo(tmp_path, sha="abc1234"):
    """A deployment checkout whose broker pin names Antares commit `sha` (T-6151)."""
    repo = tmp_path / "deploy"
    (repo / "components/context-broker").mkdir(parents=True)
    (repo / gate.BROKER_IMAGES).write_text(f"x:\n  # Antares dev {sha} (dev-120, over aaaaaaa)\n    tag: 'dev-120'\n")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pin"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


class FakeGh:
    """gh for the sweep stage: answers the runs list from `pages` (one per call, the last repeats), records calls."""

    def __init__(self, *pages):
        self.pages, self.calls = list(pages), []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "api":
            return json.dumps({"workflow_runs": self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]})
        return ""


def sweep_run(run_id, title, status="completed", conclusion="success"):
    return {"id": run_id, "display_title": title, "status": status, "conclusion": conclusion,
            "created_at": f"2026-10-30T0{run_id % 10}:00:00Z", "html_url": f"https://github.com/x/runs/{run_id}"}


def test_the_antares_sweep_stage_is_last_and_runs_this_script(tmp_path):
    args = argparse.Namespace(conformance=tmp_path, portal=tmp_path, requests=None, rate=1, duration="1s",
                              only=None, rev="v1.2.3")
    name, argv, env, _ = gate.stages(args, tmp_path)[-1]
    assert name == "antares-sweep" == gate.REQUIRED[-1]
    assert argv[1:] == [str(SCRIPT), "antares-sweep", "v1.2.3"] and env == {}


def test_a_green_sweep_of_the_pinned_commit_passes_and_is_named_in_the_record(tmp_path, capsys):
    repo = broker_repo(tmp_path)
    fake = FakeGh([sweep_run(7, "sweep abc0000"), sweep_run(5, "sweep abc1234def0"), sweep_run(3, "sweep nothex1")])
    assert gate.antares_sweep("HEAD", wait=True, call=fake, cwd=repo) == 0
    out = capsys.readouterr().out
    assert "  ok  sweep run 5 of Antares abc1234: https://github.com/x/runs/5" in out
    assert [c[0] for c in fake.calls] == ["api"], "a green run dispatches nothing"
    # the run lands in the record as a case of the stage
    assert "antares-sweep::sweep run 5 of Antares abc1234" in gate.cases("antares-sweep", tmp_path, out)


def test_a_red_sweep_refuses_and_says_how_to_go_on(tmp_path, capsys):
    repo = broker_repo(tmp_path)
    fake = FakeGh([sweep_run(9, "sweep abc1234", conclusion="failure"), sweep_run(4, "sweep abc1234", conclusion="cancelled")])
    assert gate.antares_sweep("HEAD", wait=True, call=fake, cwd=repo) == 1
    out = capsys.readouterr().out
    assert "FAIL  sweep run 9 of Antares abc1234: failure" in out and "gh run rerun 9" in out
    assert gate.cases("antares-sweep", tmp_path, out) == {"antares-sweep::sweep run 9 of Antares abc1234": "fail"}


def test_without_a_sweep_the_gate_dispatches_one_and_waits_for_it(tmp_path, capsys):
    repo = broker_repo(tmp_path)
    fake = FakeGh([], [], [sweep_run(11, "sweep abc1234", status="in_progress", conclusion=None)],
                  [sweep_run(11, "sweep abc1234")])
    naps = []
    assert gate.antares_sweep("HEAD", wait=True, call=fake, sleep=naps.append, cwd=repo) == 0
    dispatches = [c for c in fake.calls if c[0] == "workflow"]
    assert dispatches == [("workflow", "run", "sweep.yml", "-R", gate.ANTARES_REPO, "--ref", "dev", "-f", "sha=abc1234")]
    assert len(naps) == 3 and "ok  sweep run 11" in capsys.readouterr().out
    # started by `run` without waiting: one dispatch, then back
    fake = FakeGh([])
    assert gate.antares_sweep("HEAD", wait=False, call=fake, cwd=repo) == 0
    assert [c[0] for c in fake.calls] == ["api", "workflow"]


def test_a_running_sweep_is_never_dispatched_twice(tmp_path):
    repo = broker_repo(tmp_path)
    fake = FakeGh([sweep_run(12, "sweep abc1234", status="queued", conclusion=None)])
    assert gate.antares_sweep("HEAD", wait=False, call=fake, cwd=repo) == 0
    assert [c[0] for c in fake.calls] == ["api"]
