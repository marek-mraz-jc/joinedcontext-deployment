#!/usr/bin/env python3
"""Every image the deployment pins, and what a vulnerability scan of them decides (T-3289).

    scan-pinned-images.py list                         one reference per line, registry/repository@digest
    scan-pinned-images.py judge REPORT... [--kev KEV]  exit 1 when a finding blocks, naming each

`list` reads every `components/*/images.yaml`: an entry with `repository`, `tag` and `digest`
(and `registry` when the chart joins it) is one pinned image, scanned by its digest.

`judge` reads trivy's JSON reports (`trivy image --format json`). A finding blocks when a fixed
version exists and it is CRITICAL, or HIGH and listed in CISA's Known Exploited Vulnerabilities
catalogue (`--kev`, its JSON feed). `.ci/pinned-images-ignore.yaml` may excuse one, and only with
a reason, a task id and an expiry date; an entry that lacks one, or has expired, excuses nothing.
"""

import datetime
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORES = ROOT / ".ci" / "pinned-images-ignore.yaml"
TASK = re.compile(r"^T-\d{4}$")


def pinned(root: pathlib.Path = ROOT) -> list[str]:
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "repository" in node and "digest" in node:
                repository = str(node["repository"])
                if node.get("registry"):
                    repository = f"{node['registry']}/{repository}"
                found.add(f"{repository}@{node['digest']}")
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(root.glob("components/*/images.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            walk(document)
    return sorted(found)


def ignores(path: pathlib.Path, today: datetime.date) -> tuple[set[tuple[str, str]], list[str]]:
    """The (image repository, CVE) pairs excused today, and what is wrong with the file."""
    if not path.exists():
        return set(), []
    excused, problems = set(), []
    for entry in yaml.safe_load(path.read_text()) or []:
        cve, image = entry.get("cve"), entry.get("image")
        reason, task, expires = entry.get("reason"), str(entry.get("task", "")), entry.get("expires")
        if not (cve and image and reason and TASK.match(task) and isinstance(expires, datetime.date)):
            problems.append(f"{cve or '?'} on {image or '?'}: an excuse names its reason, a task (T-nnnn) and an expiry date")
            continue
        if expires < today:
            problems.append(f"{cve} on {image}: the excuse expired on {expires} ({task})")
            continue
        excused.add((image, cve))
    return excused, problems


def blocking(report: dict, kev: set[str], excused: set[tuple[str, str]]) -> list[str]:
    image = str(report.get("ArtifactName", "?")).split("@")[0]
    found = []
    for result in report.get("Results") or []:
        for vulnerability in result.get("Vulnerabilities") or []:
            cve = vulnerability.get("VulnerabilityID", "")
            severity = vulnerability.get("Severity", "")
            fixed = vulnerability.get("FixedVersion")
            if not fixed or (image, cve) in excused:
                continue
            if severity == "CRITICAL" or (severity == "HIGH" and cve in kev):
                line = (
                    f"{image}: {cve} {severity} in {vulnerability.get('PkgName', '?')} "
                    f"{vulnerability.get('InstalledVersion', '?')}, fixed in {fixed}"
                )
                # One finding per package, however many targets of the image carry it.
                if line not in found:
                    found.append(line)
    return found


def judge(reports: list[pathlib.Path], kev_path: pathlib.Path | None, ignore_path: pathlib.Path = IGNORES,
          today: datetime.date | None = None) -> list[str]:
    kev = set()
    if kev_path is not None:
        kev = {entry["cveID"] for entry in json.loads(kev_path.read_text()).get("vulnerabilities", [])}
    excused, problems = ignores(ignore_path, today or datetime.date.today())
    found = list(problems)
    for path in reports:
        found += blocking(json.loads(path.read_text()), kev, excused)
    return found


def main(argv: list[str]) -> int:
    if argv[1:2] == ["list"]:
        print("\n".join(pinned()))
        return 0
    if argv[1:2] == ["judge"]:
        args = argv[2:]
        kev = None
        if "--kev" in args:
            at = args.index("--kev")
            kev = pathlib.Path(args[at + 1])
            args = args[:at] + args[at + 2:]
        found = judge([pathlib.Path(a) for a in args], kev)
        for line in found:
            print(line)
        print(f"{len(found)} blocking finding(s) in {len(args)} image(s)")
        return 1 if found else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
