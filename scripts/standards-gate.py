#!/usr/bin/env python3
"""The release gate before every prod apply (T-5899): every standard and a load stage on dev.

  scripts/standards-gate.py run [<rev>] [--rate 1000] [--duration 5m] [--only STAGE ...]
  scripts/standards-gate.py check [<rev>]       # prod-apply: refuse <rev> without a green record
  scripts/standards-gate.py --self-test

`run` gates the deployment commit dev runs (`just dev-apply` of <rev>, default HEAD) and writes one
record to $JC_RELEASE_GATE_DIR/<sha>/ (default /workspace/tasks/evidence/release-gate):
record.json (sha, image pins, every stage and case), report.md and junit.xml. The stages are dev's
smoke, the standards suites of joinedcontext-conformance (NGSI-LD ETSI smoke.robot with writes when
NGSILD_TOKEN and WRITE_ENDPOINT are set, OGC API Features ETS + GeoJSON, OData, SensorThings, iCal,
WebSocket, MCP), DCAT-AP SHACL of dev's CKAN, the Portal live sweep (every journey, MQTT included)
and the k6 API mix at --rate for --duration (p95 < 500 ms, 0 failed requests). A stage passes when it
exits 0, or when every red case it left matches .ci/release-gate-known-red.txt (each line names the
task that owns the red; a stage red with no case to show, a Python traceback or a red load stays red).
A record is green when every stage ran and passed and no case green in the previous green record is
red now, unless the known-red file parks that case.

Every target is dev and nothing else: the gate has no target parameter, so it never writes to prod.
The ETSI TTF suite never runs here (owner rule). Credentials come only from the environment the
caller set from the secrets mount (ANTARES_DIR, NGSILD_TOKEN, the *_PASSWORD of the sweep); the
record holds no environment.

`check` is the step `just prod-apply` runs after `release.py verify`: it passes only when a green
record names the same image pins and either the same commit or an ancestor that differs from it
only in what `release.py cut` writes (releases/, CHANGELOG.md).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDS = Path(os.environ.get("JC_RELEASE_GATE_DIR", "/workspace/tasks/evidence/release-gate"))
DOMAIN = "dev.joinedcontext.com"
API = f"https://api.{DOMAIN}"
# What `release.py cut` adds on top of the gated main commit.
RELEASE_FILES = re.compile(r"^(releases/[^/]+|CHANGELOG\.md)$")
SUITES = ("ngsi-ld", "ogc", "odata", "sta", "ical", "ws", "mcp")
REQUIRED = ("dev-smoke", *SUITES, "dcat", "portal-sweep", "load")
KNOWN_RED = ROOT / ".ci/release-gate-known-red.txt"
TASK_ID = re.compile(r"T-\d{4,}")


class Refused(Exception):
    """The gate does not hold; nothing was applied."""


def git(*args: str, cwd: Path = ROOT) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode:
        raise Refused(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def images_at(rev: str, cwd: Path = ROOT) -> list[str]:
    """The image pins of `rev`, read by release-notes.py from that commit's components/*/images.yaml."""
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/release-notes.py")
    notes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notes)
    with tempfile.TemporaryDirectory() as tmp:
        for path in git("ls-tree", "-r", "--name-only", rev, "components", cwd=cwd).splitlines():
            if re.fullmatch(r"components/[^/]+/images\.yaml", path):
                (Path(tmp) / path).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / path).write_text(git("show", f"{rev}:{path}", cwd=cwd))
        return notes.images(Path(tmp) / "components")


def candidate(rev: str, cwd: Path = ROOT) -> dict:
    return {"sha": git("rev-parse", "--verify", f"{rev}^{{commit}}", cwd=cwd), "images": images_at(rev, cwd)}


# ---------------------------------------------------------------------------- the stages


def stages(args, out: Path) -> list[tuple[str, list[str], dict, Path]]:
    """(name, argv, extra env, cwd) per stage; each writes what it reads back into out/<name>."""
    conf, portal = args.conformance.resolve(), args.portal.resolve()
    std = conf / "tests/standards/run.sh"
    plan = [("dev-smoke", ["just", "dev-smoke"], {"JUST_NO_DOTENV": "true"}, ROOT)]
    for suite in SUITES:
        plan.append((suite, [str(std)], {"TARGET": "dev", "API": API, "SUITES": suite,
                                          "OUT": str(out / suite)}, conf))
    plan.append(("dcat", [str(conf / "tests/prod-nightly/run.sh")],
                 {"API": API, "CATALOGUE": f"https://opendata.{DOMAIN}", "SUITES": "dcat",
                  "OUT": str(out / "dcat"), "PAUSE": "0"}, conf))
    plan.append(("portal-sweep", [str(portal / "ui/e2e/live/sweep.sh")],
                 {"PORTAL_URL": f"https://portal.{DOMAIN}", "SWEEP_OUT": str(out / "portal-sweep"),
                  "TASKS_DIR": ""}, portal / "ui"))
    load = out / "load"
    requests = args.requests or load / "requests.tsv"
    script = (f"set -euo pipefail; [ -s {quote(requests)} ] || python3 tests/k6/make_requests.py "
              f"https://opendata.{DOMAIN} > {quote(requests)}; exec tests/k6/run.sh")
    plan.append(("load", ["bash", "-c", script],
                 {"JC_K6_SCRIPT": "api-mix-100rps.js", "JC_K6_REQUESTS": str(requests),
                  "JC_K6_RATE": str(args.rate), "JC_K6_DURATION": args.duration, "JC_K6_P95_MS": "500",
                  "JC_REPORTS_DIR": str(load)}, conf))
    return [s for s in plan if not args.only or s[0] in args.only]


def quote(path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def known_red(path: Path = KNOWN_RED) -> list[tuple[str, re.Pattern]]:
    """(task id, pattern) per line of the known-red file; a malformed line refuses the whole run."""
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1) if path.exists() else []:
        if not line.strip() or line.startswith("#"):
            continue
        task, _, pattern = line.partition(" ")
        if not TASK_ID.fullmatch(task) or not pattern.strip():
            raise Refused(f"{path.name}:{n}: want '<task id> <regex>', got {line!r}")
        try:
            out.append((task, re.compile(pattern.strip())))
        except re.error as e:
            raise Refused(f"{path.name}:{n}: {e}") from e
    return out


def parked(text: str, known: list[tuple[str, re.Pattern]]) -> str | None:
    """The task that parks this red case, if a known-red line matches it."""
    return next((task for task, pattern in known if pattern.fullmatch(text)), None)


def cases(name: str, folder: Path, log: str, details: dict[str, str] | None = None) -> dict[str, str]:
    """Every case a stage left behind, `<stage>::<case>` -> pass | fail; `details` gets each smoke line's text."""
    found: dict[str, str] = {}
    details = {} if details is None else details
    for xml in sorted(folder.rglob("*.xml")):
        try:
            tree = ET.parse(xml)
        except ET.ParseError:
            continue
        for case in tree.iter("testcase"):
            if case.find("skipped") is not None:
                continue
            red = case.find("failure") is not None or case.find("error") is not None
            key = f"{name}::{xml.relative_to(folder)}::{case.get('classname', '')}::{case.get('name', '')}"
            found[key] = "fail" if red else "pass"
    tsv = folder / "results.tsv"
    if tsv.exists():
        for line in tsv.read_text().splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 3 and cols[2] in ("pass", "fail"):
                found[f"{name}::{cols[0]}/{cols[1]}"] = cols[2]
    summary = folder / "summary.json"
    if summary.exists():
        data = json.loads(summary.read_text())
        for result in data.get("results", []) if isinstance(data, dict) else []:
            if result.get("verdict") in ("pass", "fail", "error"):
                found[f"{name}::{result['key']}"] = "pass" if result["verdict"] == "pass" else "fail"
    for m in re.finditer(r"^  (ok|FAIL)  +([^:\n]+)(?::[ \t]*(.*))?", log, re.MULTILINE):
        key = f"{name}::{m.group(2).strip()}"
        found[key] = "pass" if m.group(1) == "ok" else "fail"
        details[key] = f"{key}: {m.group(3)}" if m.group(3) else key
    return found


def load_verdict(folder: Path) -> list[str]:
    """What the k6 summary breaks of the gate's own rule: 0 failed requests, p95 < 500 ms."""
    path = folder / "summary.json"
    if not path.exists():
        return ["k6 wrote no summary.json"]
    metrics = json.loads(path.read_text()).get("metrics", {})
    failed = metrics.get("http_req_failed", {}).get("values", {}).get("passes")
    p95 = metrics.get("http_req_duration", {}).get("values", {}).get("p(95)")
    problems = []
    if failed != 0:
        problems.append(f"{failed} failed requests (the gate allows 0)")
    if p95 is None or p95 >= 500:
        problems.append(f"p95 {p95} ms (the gate allows < 500)")
    return problems


def run_stage(name, argv, env, cwd, out: Path, known: list | None = None) -> dict:
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    try:
        done = subprocess.run(argv, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True,
                              check=False, timeout=4 * 3600)
        code, log = done.returncode, done.stdout + done.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        code, log = 127, f"{name} did not run: {e}"
    (folder / "output.txt").write_text(log)
    details: dict[str, str] = {}
    found = cases(name, folder, log, details)
    red = {k: details.get(k, k) for k, v in found.items() if v == "fail"}
    excused = {k: parked(text, known or []) for k, text in red.items()}
    problems = [] if code == 0 else [f"exit {code}: {tail(log)}"]
    # A non-zero exit is forgiven only when it shows its reds and a task owns each one.
    explained = bool(red) and all(excused.values()) and name != "load" and "Traceback (most recent" not in log
    if explained:
        problems = []
    if name == "load" and code == 0:
        problems += load_verdict(folder)
    found[name] = "fail" if problems else "pass"
    return {"name": name, "verdict": found[name], "problems": problems, "cases": found,
            "known_red": {k: f"{t}: {red[k]}" for k, t in excused.items() if t},
            "seconds": int((datetime.now(UTC) - started).total_seconds())}


def tail(log: str) -> str:
    lines = [line for line in log.strip().splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:400]


# ---------------------------------------------------------------------------- records


def records(root: Path = RECORDS) -> list[dict]:
    out = []
    for path in root.glob("*/record.json"):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("finished", ""))


def previous_green(root: Path, sha: str) -> dict | None:
    """The newest green record of another candidate: the baseline a regression is measured on."""
    greens = [r for r in records(root) if r.get("green") and r.get("sha") != sha]
    return greens[-1] if greens else None


def regressions(before: dict | None, now: dict[str, str], parked_now: frozenset = frozenset()) -> list[str]:
    if not before:
        return []
    return sorted(k for k, v in before.get("cases", {}).items()
                  if v == "pass" and now.get(k) == "fail" and k not in parked_now)


def verdict(stage_results: list[dict], regressed: list[str]) -> bool:
    ran = {s["name"]: s["verdict"] for s in stage_results}
    return all(ran.get(name) == "pass" for name in REQUIRED) and not regressed


def report(rec: dict) -> str:
    head = "GREEN" if rec["green"] else "RED"
    lines = [f"# Release gate {rec['sha'][:12]}: {head}", "",
             (f"Deployment {rec['sha']} on {DOMAIN}, {rec['started']} to {rec['finished']}; "
             f"load {rec['rate']}/s for {rec['duration']}; baseline {rec.get('baseline') or 'none'}."), "",
             "| Stage | Verdict | Cases | Seconds | Problems |", "|---|---|---|---|---|"]
    for s in rec["stages"]:
        reds = sum(1 for v in s["cases"].values() if v == "fail")
        lines.append(f"| {s['name']} | {s['verdict']} | {len(s['cases'])} ({reds} red) | {s['seconds']} | "
                     f"{'; '.join(s['problems']).replace('|', '/') or ''} |")
    missing = [n for n in REQUIRED if n not in {s["name"] for s in rec["stages"]}]
    if missing:
        lines += ["", f"Not run (a partial record never opens prod): {', '.join(missing)}"]
    held = {k: v for s in rec["stages"] for k, v in s.get("known_red", {}).items()}
    lines += ["", f"## Known reds, each owned by a task ({len(held)})", ""]
    lines += [f"- {v.replace('|', '/')}" for _, v in sorted(held.items())] or ["none"]
    if rec.get("unmatched"):
        lines += ["", "Known-red lines no case matched (fixed? remove them in their task):", ""]
        lines += [f"- `{u}`" for u in rec["unmatched"]]
    lines += ["", f"## Regressions against the previous green record ({len(rec['regressions'])})", ""]
    lines += [f"- {k}" for k in rec["regressions"]] or ["none"]
    lines += ["", "## Image pins", ""] + [f"- `{i}`" for i in rec["images"]]
    return "\n".join(lines) + "\n"


def junit(rec: dict) -> str:
    suites = ET.Element("testsuites", name=f"release-gate {rec['sha'][:12]}")
    for s in rec["stages"]:
        suite = ET.SubElement(suites, "testsuite", name=s["name"], tests=str(len(s["cases"])),
                              failures=str(sum(v == "fail" for v in s["cases"].values())))
        for key, v in sorted(s["cases"].items()):
            case = ET.SubElement(suite, "testcase", classname=s["name"], name=key)
            if v == "fail":
                why = s.get("known_red", {}).get(key)
                ET.SubElement(case, "failure", message="; ".join(s["problems"]) if key == s["name"]
                              else f"known red, owned by {why.split(':', 1)[0]}" if why else "red")
    return ET.tostring(suites, encoding="unicode")


def write(rec: dict, root: Path) -> Path:
    folder = root / rec["sha"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "record.json").write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    (folder / "report.md").write_text(report(rec))
    (folder / "junit.xml").write_text(junit(rec))
    return folder


def run(args) -> int:
    cand = candidate(args.rev)
    root = args.records
    out = root / cand["sha"] / "stages"
    started = datetime.now(UTC).strftime("%FT%TZ")
    known = known_red()
    results = []
    for name, argv, env, cwd in stages(args, out):
        print(f"release gate: {name} ...", flush=True)
        results.append(run_stage(name, argv, env, cwd, out, known))
        print(f"release gate: {name} {results[-1]['verdict']} {'; '.join(results[-1]['problems'])}", flush=True)
    every = {k: v for s in results for k, v in s["cases"].items()}
    base = previous_green(root, cand["sha"])
    held = {k: v for s in results for k, v in s["known_red"].items()}
    regressed = regressions(base, every, frozenset(held))
    texts = [v.split(": ", 1)[1] for v in held.values()]
    unmatched = [f"{t} {p.pattern}" for t, p in known if not any(p.fullmatch(x) for x in texts)]
    rec = {**cand, "unmatched": unmatched, "started": started, "finished": datetime.now(UTC).strftime("%FT%TZ"), "rate": args.rate,
           "duration": args.duration, "baseline": base and base["sha"], "stages": results,
           "cases": every, "regressions": regressed, "green": verdict(results, regressed)}
    folder = write(rec, root)
    print(f"release gate {cand['sha'][:12]}: {'GREEN' if rec['green'] else 'RED'}; report {folder / 'report.md'}")
    return 0 if rec["green"] else 1


# ---------------------------------------------------------------------------- check


def check(rev: str = "HEAD", root: Path = RECORDS, cwd: Path = ROOT) -> dict:
    """The green record that covers `rev`, or Refused naming why none does."""
    cand = candidate(rev, cwd)
    seen = []
    for rec in reversed(records(root)):
        if not rec.get("green"):
            continue
        if rec.get("images") != cand["images"]:
            seen.append(f"{rec['sha'][:12]} pins other images")
            continue
        if rec["sha"] == cand["sha"]:
            return rec
        known = subprocess.run(["git", "merge-base", "--is-ancestor", rec["sha"], cand["sha"]], cwd=cwd,
                               capture_output=True, check=False).returncode == 0
        if not known:
            seen.append(f"{rec['sha'][:12]} is not an ancestor")
            continue
        changed = git("diff", "--name-only", rec["sha"], cand["sha"], cwd=cwd).splitlines()
        other = [p for p in changed if not RELEASE_FILES.match(p)]
        if not other:
            return rec
        seen.append(f"{rec['sha'][:12]} differs in {', '.join(other[:5])}")
    why = "; ".join(seen[:5]) or f"no green record in {root}"
    raise Refused(f"{cand['sha'][:12]} has no green release gate record ({why}): run "
                  f"`just release-gate {cand['sha'][:12]}` on dev after dev-apply of that commit")


# ---------------------------------------------------------------------------- self-test


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo, root = Path(tmp) / "repo", Path(tmp) / "records"
        (repo / "components/portal").mkdir(parents=True)
        pin = "image: {repository: ghcr.io/x/portal, tag: a, digest: sha256:%s}\n"

        def commit(msg, files):
            for path, text in files.items():
                (repo / path).parent.mkdir(parents=True, exist_ok=True)
                (repo / path).write_text(text)
            git("add", "-A", cwd=repo)
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=repo)
            return git("rev-parse", "HEAD", cwd=repo)

        git("init", "-q", cwd=repo)
        main = commit("main", {"components/portal/images.yaml": pin % ("1" * 64)})
        stage = {"name": "x", "verdict": "pass", "problems": [], "cases": {}, "seconds": 0}
        green = [{**stage, "name": n, "cases": {n: "pass"}} for n in REQUIRED]

        def record(sha, ok, cases=None, finished="2026-10-28T00:00:00Z"):
            rec = {**candidate(sha, repo), "green": ok, "finished": finished, "cases": cases or {}}
            (root / sha).mkdir(parents=True, exist_ok=True)
            (root / sha / "record.json").write_text(json.dumps(rec))

        def refused(rev):
            try:
                check(rev, root, repo)
            except Refused as e:
                return str(e)
            return ""

        assert "no green record" in refused(main), "no record must refuse"
        # a red suite blocks the verdict, and so does a stage that never ran
        assert verdict(green, [])
        assert not verdict([*green[:-1], {**green[-1], "verdict": "fail"}], [])
        assert not verdict(green[1:], [])
        # a case green in the previous record and red now blocks
        assert regressions({"cases": {"a": "pass", "b": "fail"}}, {"a": "fail", "b": "fail"}) == ["a"]
        assert not verdict(green, ["a"])
        record(main, False)
        assert refused(main), "a red record must refuse"
        record(main, True)
        assert check(main, root, repo)["sha"] == main
        # the release commit `cut` writes on top of the gated main commit is covered
        tag = commit("release v1", {"releases/v1.md": "notes\n", "CHANGELOG.md": "log\n"})
        assert check(tag, root, repo)["sha"] == main
        # a stale record for another sha blocks: other code, or other image pins
        code = commit("code", {"charts/x.yaml": "a: 1\n"})
        assert "differs in charts/x.yaml" in refused(code)
        pinned = commit("pin", {"components/portal/images.yaml": pin % ("2" * 64)})
        assert "pins other images" in refused(pinned)
        # the stage readers: junit, results.tsv, sweep summary, smoke lines, k6 summary
        folder = Path(tmp) / "stage"
        folder.mkdir()
        (folder / "r.xml").write_text('<testsuite><testcase classname="c" name="ok"/>'
                                      '<testcase classname="c" name="bad"><failure/></testcase>'
                                      '<testcase classname="c" name="skip"><skipped/></testcase></testsuite>')
        (folder / "results.tsv").write_text("endpoint\tsuite\tverdict\tdetail\tlog\ne1\togc\tfail\tx\ty\n")
        (folder / "summary.json").write_text(json.dumps({"results": [{"key": "a.spec.ts › t", "verdict": "pass"}],
                                                          "metrics": {}}))
        got = cases("s", folder, "  ok    portal: 200\n  FAIL  mqtt: refused\n")
        assert got == {"s::r.xml::c::ok": "pass", "s::r.xml::c::bad": "fail", "s::e1/ogc": "fail",
                       "s::a.spec.ts › t": "pass", "s::portal": "pass", "s::mqtt": "fail"}, got
        (folder / "summary.json").write_text(json.dumps({"metrics": {
            "http_req_failed": {"values": {"passes": 3}}, "http_req_duration": {"values": {"p(95)": 120}}}}))
        assert load_verdict(folder) == ["3 failed requests (the gate allows 0)"]
        assert run_stage("load", ["false"], {}, tmp, Path(tmp) / "out")["verdict"] == "fail"
        # a stage red only on known reds passes; an unknown red, a silent exit or a traceback stays red
        listed = Path(tmp) / "known.txt"
        listed.write_text("# parked\nT-0001 s::catalogue \\(no dataset\\) \\(ab\\): .*\n")
        known = known_red(listed)

        def smoke(text):
            return run_stage("s", ["bash", "-c", f"printf %s {quote(text)}; exit 1"], {}, tmp, Path(tmp) / "o", known)

        held = smoke("  ok    portal: 200\n  FAIL  catalogue (no dataset) (ab): no dataset\n")
        assert held["verdict"] == "pass" and held["known_red"] == {
            "s::catalogue (no dataset) (ab)": "T-0001: s::catalogue (no dataset) (ab): no dataset"}, held
        assert smoke("  FAIL  catalogue (no dataset) (cd): no dataset\n")["verdict"] == "fail"
        assert smoke("  FAIL  catalogue (no dataset) (ab): x\n  FAIL  mqtt: refused\n")["verdict"] == "fail"
        assert smoke("  ok    portal: 200\n")["verdict"] == "fail"
        assert smoke("  FAIL  catalogue (no dataset) (ab): x\nTraceback (most recent call last):\n")["verdict"] == "fail"
        assert regressions({"cases": {"a": "pass"}}, {"a": "fail"}, frozenset({"a"})) == []
        for bad in ("catalogue .*\n", "T-1 x\n", "T-0002 (\n"):
            listed.write_text(bad)
            try:
                known_red(listed)
            except Refused:
                continue
            raise AssertionError(f"a malformed known-red line must refuse: {bad!r}")
        assert known_red(), "the committed known-red file parses"
    print("standards-gate self-test: ok")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--self-test"]:
        self_test()
        return 0
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("rev", nargs="?", default="HEAD")
    r.add_argument("--rate", type=int, default=1000, help="k6 arrival rate per second (default 1000)")
    r.add_argument("--duration", default="5m", help="k6 hold time (default 5m)")
    r.add_argument("--requests", type=Path, help="k6 request list (default: make_requests.py of dev's CKAN)")
    r.add_argument("--only", nargs="+", choices=REQUIRED, help="a partial run, never green for prod")
    r.add_argument("--conformance", type=Path, default=ROOT.parent / "joinedcontext-conformance")
    r.add_argument("--portal", type=Path, default=ROOT.parent / "joinedcontext-portal")
    r.add_argument("--records", type=Path, default=RECORDS)
    c = sub.add_parser("check")
    c.add_argument("rev", nargs="?", default="HEAD")
    c.add_argument("--records", type=Path, default=RECORDS)
    args = p.parse_args(argv)
    try:
        if args.command == "run":
            return run(args)
        rec = check(args.rev, args.records)
        print(f"release gate: green record {rec['sha'][:12]} of {rec['finished']} covers {args.rev}")
        return 0
    except Refused as e:
        print(f"refusing: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
