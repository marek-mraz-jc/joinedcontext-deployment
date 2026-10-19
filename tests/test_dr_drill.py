"""T-0046: the monthly restore drill (OPS-11, OPS-12).

The script under test is read out of the rendered ConfigMap, so what runs here is the text that
reaches the cluster. `kubectl` is a stub: it answers the source's primary, the clusters' row
counts and the replay lag from a fixture, records every Cluster it is asked to apply or delete
and keeps the last result patched into the result ConfigMap.
"""

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

NAME = "postgres-cluster-dr-drill"


def one(docs: list[dict], kind: str, name: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected exactly one {kind}/{name}, got {len(found)}"
    return found[0]


@pytest.fixture(scope="module")
def local(rendered):
    return rendered("local")


@pytest.fixture(scope="module")
def production(rendered):
    return rendered("production")


def env_of(cronjob: dict) -> dict[str, str]:
    container = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in container["env"]}


def run(docs: list[dict], tmp_path: Path, rows: dict[str, tuple[str, str]], mem_mib: int = 8192,
        ready: bool = True, **extra) -> tuple[int, dict, list[str]]:
    """Runs the drill with a stub kubectl. `rows` maps a database to (source, copy) counts, a
    copy of "" meaning the database is missing from the copy. Returns the exit code, the result
    the script patched into its ConfigMap, and the stub's log of applies and deletes."""
    script = one(docs, "ConfigMap", f"{NAME}-script")["data"]["dr-drill.sh"]
    (tmp_path / "meminfo").write_text(f"MemTotal: 16000000 kB\nMemAvailable: {mem_mib * 1024} kB\n")
    for db, (source, copy) in rows.items():
        (tmp_path / f"postgres-cluster-1.{db}").write_text(source)
        if copy != "":
            (tmp_path / f"postgres-cluster-drill-1.{db}").write_text(copy)
    stub = tmp_path / "kubectl"
    stub.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        d={tmp_path}
        case "$1" in
          apply) echo "apply" >> $d/log ;;
          delete) echo "delete $3" >> $d/log ;;
          wait) {"exit 0" if ready else "exit 1"} ;;
          get) echo postgres-cluster-1 ;;
          patch) printf '%s' "$7" > $d/result ;;
          exec)
            pod=$2; shift 9; db=$1; query=$3
            case "$query" in
              *pg_last_xact_replay_timestamp*) echo 42 ;;
              *"FROM pg_database"*) printf '%s\\n' {" ".join(rows)} ;;
              *) cat "$d/$pod.$db" 2>/dev/null || {{ echo "no database $db" >&2; exit 2; }} ;;
            esac ;;
          *) echo "stub kubectl: unexpected $*" >&2; exit 64 ;;
        esac
        """))
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, **env_of(one(docs, "CronJob", NAME)),
           "PATH": f"{tmp_path}:{os.environ['PATH']}", "MEMINFO": str(tmp_path / "meminfo"),
           "POLL_SECONDS": "0", **extra}
    result = subprocess.run(["sh", "-"], input=script.replace("/opt/drill/cluster.yaml", "/dev/null"),
                            text=True, capture_output=True, env=env, timeout=30)
    patched = json.loads((tmp_path / "result").read_text())["data"]
    log = (tmp_path / "log").read_text().split("\n") if (tmp_path / "log").exists() else []
    line = [json.loads(l) for l in result.stdout.splitlines() if l.startswith("{")]
    assert len(line) == 1 and line[0]["result"] == patched["result"], result.stdout + result.stderr
    return result.returncode, patched, [l for l in log if l]


def test_without_an_archive_the_drill_restores_nothing_and_says_so(local, tmp_path):
    assert env_of(one(local, "CronJob", NAME))["BACKUPS_ENABLED"] == "false"
    code, result, log = run(local, tmp_path, {"portal": ("10", "10")})
    assert code == 0
    assert result["result"] == "no-backup" and "no off-site backup to drill" in result["detail"]
    assert log == [], "nothing is created or deleted without an archive"


def test_a_full_restore_passes_with_rto_rpo_and_counts_read_from_the_clusters(production, tmp_path):
    code, result, log = run(production, tmp_path, {"portal": ("1000", "990"), "keycloak": ("50", "50")})
    assert code == 0, result
    assert result["result"] == "passed"
    assert result["rpoSeconds"] == "42" and result["rtoSeconds"].isdigit()
    assert result["detail"] == "portal=990/1000 keycloak=50/50"
    assert log[0] == "delete postgres-cluster-drill" and "apply" in log
    assert log[-1] == "delete postgres-cluster-drill", "the copy is deleted when the drill ends"


def test_a_database_short_of_rows_or_missing_fails_the_drill(production, tmp_path):
    code, result, log = run(production, tmp_path, {"portal": ("1000", "900"), "gitea": ("7", "")})
    assert code != 0
    assert result["result"] == "failed"
    assert "portal(900 of 1000 rows)" in result["detail"] and "gitea(missing)" in result["detail"]
    assert log[-1] == "delete postgres-cluster-drill"


def test_a_restore_that_never_becomes_ready_fails_and_is_deleted(production, tmp_path):
    code, result, log = run(production, tmp_path, {"portal": ("1", "1")}, ready=False)
    assert code != 0 and result["result"] == "failed"
    assert "did not become ready" in result["detail"]
    assert log[-1] == "delete postgres-cluster-drill"


def test_a_full_node_skips_the_drill_visibly_and_restores_nothing(production, tmp_path):
    code, result, log = run(production, tmp_path, {"portal": ("1", "1")}, mem_mib=900,
                            TIMEOUT_MINUTES="0")
    assert code != 0 and result["result"] == "skipped"
    assert "900 MiB" in result["detail"]
    assert log == []


def test_the_job_is_held_to_its_own_names(production):
    role = one(production, "Role", NAME)
    named = [r for r in role["rules"] if r["verbs"] != ["create"] or r["resources"] != ["clusters"]]
    assert all(r.get("resourceNames") for r in named), "every verb but create is held to names"
    exec_names = next(r for r in role["rules"] if r["resources"] == ["pods/exec"])["resourceNames"]
    assert "postgres-cluster-drill-1" in exec_names and "postgres-cluster-1" in exec_names
    assert not [d for d in production if d.get("kind") in ("ClusterRole", "ClusterRoleBinding")
                and d["metadata"]["name"].endswith("dr-drill")]
    copy = one(production, "ConfigMap", f"{NAME}-script")["data"]["cluster.yaml"]
    assert "ACCESS_SECRET_KEY" in copy and "serverName: postgres-cluster" in copy
    assert "joinedcontext.com/drill" in copy
