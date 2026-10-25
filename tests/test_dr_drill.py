"""T-0046: the monthly restore drill (OPS-11, OPS-12).

The script under test is read out of the rendered ConfigMap, so what runs here is the text that
reaches the cluster. `kubectl` is a stub: it answers the source's primary, the clusters' row
counts and the replay lag from a fixture, records every Cluster it is asked to apply or delete
and keeps the last result patched into the result ConfigMap.
"""

import gzip
import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

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


@pytest.fixture(scope="module")
def smartcity(rendered):
    return rendered("smartcity")


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def env_of(cronjob: dict) -> dict[str, str]:
    container = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in container["env"]}


TARGET = "2026-10-21T21:00:00Z"


def run(docs: list[dict], tmp_path: Path, rows: dict[str, tuple[str, str]], mem_mib: int = 8192,
        ready: bool = True, tables: dict[str, tuple[str, str]] | None = None,
        people: str = "3", schema: tuple[str, str] = ("20261001", "20261001"),
        dump: dict | None = None, **extra) -> tuple[int, dict, list[str]]:
    """Runs the drill with a stub kubectl. `rows` maps a database to (source, copy) totals, a
    copy of "" meaning the database is missing from the copy; `tables` maps a database to the
    (source, point-in-time copy) per-table answers, `name|count` lines, and defaults to one
    table holding the source's total in both. `people` is what the copy's realm answers and
    `schema` the Portal's (source, copy) migration. Returns the exit code, the result the
    script patched into its ConfigMap, and the stub's log of creates and deletes; the
    manifest of the n-th create is in `tmp_path / f"created.{n}"`.

    `dump` stands for the nightly dump's volume (T-5556): `counts` the file the dump job wrote
    beside it, `restored` the per-database `name|count` answers of the restore pod, `data` the
    gzip bytes (a real gzip of a line by default) and `psql_error` a line the restore's psql
    prints before it fails. The stub runs the drill's `sh -c` commands for real, with /backup
    under `tmp_path`, so gzip judges the file."""
    script = one(docs, "ConfigMap", f"{NAME}-script")["data"]["dr-drill.sh"]
    pitr = one(docs, "ConfigMap", f"{NAME}-script")["data"]["cluster-pitr.yaml"]
    (tmp_path / "cluster-pitr.yaml").write_text(pitr)
    (tmp_path / "meminfo").write_text(f"MemTotal: 16000000 kB\nMemAvailable: {mem_mib * 1024} kB\n")
    if tables is None:
        tables = {db: (f"public.t|{source}", f"public.t|{source}") for db, (source, _) in rows.items()}
    for db, (source, copy) in rows.items():
        (tmp_path / f"postgres-cluster-1.{db}").write_text(source)
        (tmp_path / f"postgres-cluster-1.{db}.tables").write_text(tables[db][0])
        (tmp_path / f"postgres-cluster-1.{db}.schema").write_text(schema[0])
        if copy != "":
            (tmp_path / f"postgres-cluster-drill-1.{db}").write_text(copy)
            (tmp_path / f"postgres-cluster-drill-1.{db}.tables").write_text(tables[db][1])
            (tmp_path / f"postgres-cluster-drill-1.{db}.schema").write_text(schema[1])
    backup = tmp_path / "backup"
    backup.mkdir()
    if dump is not None:
        newest = backup / "2026-10-24T0230Z.sql.gz"
        (backup / "2026-10-23T0230Z.sql.gz").write_bytes(gzip.compress(b"-- older"))
        newest.write_bytes(dump.get("data", gzip.compress(b"SELECT 1;\n")))
        (backup / f"{newest.name}.counts").write_text(dump["counts"])
        for db, answer in dump.get("restored", {}).items():
            (tmp_path / f"postgres-cluster-drill-dump.{db}.tables").write_text(answer)
        psql = tmp_path / "psql"
        fail = dump.get("psql_error")
        psql.write_text("#!/bin/sh\ncat >/dev/null\n" + (f"echo '{fail}' >&2; exit 3\n" if fail else ""))
        psql.chmod(0o755)
    stub = tmp_path / "kubectl"
    stub.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        d={tmp_path}
        case "$1" in
          create) echo "create" >> $d/log; n=$(grep -c create $d/log); cp "$3" $d/created.$n ;;
          delete) echo "delete $3" >> $d/log ;;
          wait) {"exit 0" if ready else "exit 1"} ;;
          get) echo postgres-cluster-1 ;;
          patch) printf '%s' "$7" > $d/result ;;
          exec)
            if [ "$6" = sh ]; then
              script=$(printf '%s' "$8" | sed "s|/backup|$d/backup|g")
              exec sh -c "$script" "$9" "${{10:-}}"
            fi
            pod=$2; shift 9; db=$1; query=$3
            case "$query" in
              *pg_last_xact_replay_timestamp*) echo 42 ;;
              *"FROM pg_database"*) printf '%s\\n' {" ".join(rows)} ;;
              *clock_timestamp*) echo "{TARGET}|0/5000000" ;;
              *"FROM realm"*) echo {people} ;;
              *_sqlx_migrations*) cat "$d/$pod.$db.schema" ;;
              *"ORDER BY 1") cat "$d/$pod.$db.tables" 2>/dev/null || {{ echo "no database $db" >&2; exit 2; }} ;;
              *) cat "$d/$pod.$db" 2>/dev/null || {{ echo "no database $db" >&2; exit 2; }} ;;
            esac ;;
          *) echo "stub kubectl: unexpected $*" >&2; exit 64 ;;
        esac
        """))
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, **env_of(one(docs, "CronJob", NAME)),
           "PATH": f"{tmp_path}:{os.environ['PATH']}", "MEMINFO": str(tmp_path / "meminfo"),
           "POLL_SECONDS": "0", "TARGET_SETTLE_SECONDS": "0", **extra}
    script = script.replace("/opt/drill/cluster-pitr.yaml", str(tmp_path / "cluster-pitr.yaml"))
    script = script.replace("/opt/drill/dump-pod.yaml", "/dev/null")
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
    assert log[0] == "delete postgres-cluster-drill" and log.count("create") == 2
    assert log[-1] == "delete postgres-cluster-drill", "the copy is deleted when the drill ends"
    assert result["pitrTarget"] == TARGET and result["pitrRtoSeconds"].isdigit()
    assert result["pitrDetail"] == "2 tables match"


def test_the_second_restore_goes_back_to_the_instant_of_the_counts(production, tmp_path):
    code, result, log = run(production, tmp_path, {"portal": ("5", "5")})
    assert code == 0, result
    first = (tmp_path / "created.1").read_text()
    second = (tmp_path / "created.2").read_text()
    assert first == "" and "recoveryTarget" not in first, "the first restore is the latest"
    assert f'targetTime: "{TARGET}"' in second and "__TARGET_TIME__" not in second
    assert log == ["delete postgres-cluster-drill", "create", "delete postgres-cluster-drill",
                   "create", "delete postgres-cluster-drill"], "one copy at a time"


def test_a_table_the_point_in_time_restore_lost_fails_the_drill(production, tmp_path):
    tables = {"portal": ("public.a|100\npublic.b|7\npublic.c|1000", "public.a|100\npublic.c|985"),
              "antares": ("public.entities|0", "public.entities|1")}
    code, result, log = run(production, tmp_path, {"portal": ("1107", "1107"), "antares": ("0", "0")},
                            tables=tables)
    assert code != 0 and result["result"] == "failed"
    assert result["pitrDetail"] == "short: portal.public.b(missing)", "one row and 1.5 % are within tolerance"
    assert log[-1] == "delete postgres-cluster-drill"


def test_a_copy_without_people_or_at_another_schema_fails(production, tmp_path):
    code, result, _ = run(production, tmp_path, {"portal": ("9", "9"), "keycloak": ("9", "9")},
                          people="0", schema=("20261001", "20260901"))
    assert code != 0 and result["result"] == "failed"
    assert "keycloak(no enabled person in an enabled realm)" in result["detail"]
    assert "portal(schema 20260901 of 20261001)" in result["detail"]
    assert result["pitrTarget"] == TARGET and result["pitrRtoSeconds"] == "", "no second restore"


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
    clusters = [r for r in role["rules"] if r["resources"] == ["clusters"] and r.get("resourceNames")]
    on_source = {v for r in clusters if "postgres-cluster" in r["resourceNames"] for v in r["verbs"]}
    assert on_source == {"get"}, f"the source Cluster is only read, got {on_source}"
    on_copy = {v for r in clusters if "postgres-cluster-drill" in r["resourceNames"] for v in r["verbs"]}
    assert "delete" in on_copy and "patch" not in on_copy
    exec_names = next(r for r in role["rules"] if r["resources"] == ["pods/exec"])["resourceNames"]
    assert "postgres-cluster-drill-1" in exec_names and "postgres-cluster-1" in exec_names
    assert not [d for d in production if d.get("kind") in ("ClusterRole", "ClusterRoleBinding")
                and d["metadata"]["name"].endswith("dr-drill")]
    copy = one(production, "ConfigMap", f"{NAME}-script")["data"]["cluster.yaml"]
    assert "ACCESS_SECRET_KEY" in copy and "serverName: postgres-cluster" in copy
    assert "joinedcontext.com/drill" in copy
    assert "recoveryTarget" not in copy
    pitr = one(production, "ConfigMap", f"{NAME}-script")["data"]["cluster-pitr.yaml"]
    pitr = yaml.safe_load(pitr)
    assert pitr["spec"]["bootstrap"]["recovery"].pop("recoveryTarget") == {"targetTime": "__TARGET_TIME__"}
    assert pitr == yaml.safe_load(copy), "the two restores differ only in their target"


# ---- the nightly local dump (T-5556)

COUNTS = "portal.public.a|100\nportal.public.b|7\nkeycloak.public.user_entity|3\n"


def test_prod_restores_its_local_dump_and_still_says_it_has_no_off_site_backup(smartcity, tmp_path):
    env = env_of(one(smartcity, "CronJob", NAME))
    assert env["BACKUPS_ENABLED"] == "false" and env["LOCAL_BACKUP"] == "true"
    restored = {"portal": "public.a|101\npublic.b|7", "keycloak": "public.user_entity|3"}
    code, result, log = run(smartcity, tmp_path, {}, dump={"counts": COUNTS, "restored": restored})
    assert code == 0, result
    assert result["result"] == "no-backup", "the dump is no off-site backup, the alert keeps saying so"
    assert result["localDump"] == "local-dump-passed"
    assert result["localDumpDetail"] == "2026-10-24T0230Z.sql.gz: 3 tables match", "the newest dump"
    assert result["localDumpRtoSeconds"].isdigit()
    newest = tmp_path / "backup" / "2026-10-24T0230Z.sql.gz"
    assert result["localDumpBytes"] == str(newest.stat().st_size)
    assert log.count("create") == 1, "only the restore pod: no Cluster without an archive"
    assert log[-1] == "delete postgres-cluster-drill-dump", "the pod goes however the drill ends"
    assert log.count("delete postgres-cluster-drill-dump") >= 2, "a pod a crashed drill left goes first"


def test_dev_restores_the_dump_and_then_the_archive(dev, tmp_path):
    restored = {"portal": "public.a|100\npublic.b|7", "keycloak": "public.user_entity|3"}
    code, result, log = run(dev, tmp_path, {"portal": ("10", "10"), "keycloak": ("3", "3")},
                            dump={"counts": COUNTS, "restored": restored})
    assert code == 0, result
    assert result["result"] == "passed" and result["localDump"] == "local-dump-passed"
    assert log.count("create") == 3, "the dump's pod, then the latest and the point-in-time copy"


def test_a_dump_missing_a_table_fails_the_drill_and_names_the_table(smartcity, tmp_path):
    restored = {"portal": "public.a|100", "keycloak": "public.user_entity|3"}
    code, result, log = run(smartcity, tmp_path, {}, dump={"counts": COUNTS, "restored": restored})
    assert code != 0
    assert result["result"] == "failed" and result["localDump"] == "failed"
    assert result["localDumpDetail"] == "2026-10-24T0230Z.sql.gz short: portal.public.b(missing)"
    assert log[-1] == "delete postgres-cluster-drill-dump"


def test_a_truncated_dump_fails_the_drill(smartcity, tmp_path):
    whole = gzip.compress(os.urandom(4096))
    code, result, log = run(smartcity, tmp_path, {}, dump={"counts": COUNTS, "data": whole[:2000]})
    assert code != 0 and result["result"] == "failed" and result["localDump"] == "failed"
    assert "did not restore: gzip:" in result["localDumpDetail"]
    assert "unexpected end of file" in result["localDumpDetail"]
    assert result["localDumpRtoSeconds"] == ""
    assert log[-1] == "delete postgres-cluster-drill-dump"


def test_a_refused_statement_fails_without_copying_a_value_into_the_result(smartcity, tmp_path):
    error = 'psql:<stdin>:812: ERROR:  invalid input syntax for type integer: "4111 1111 1111 1111"'
    code, result, _ = run(smartcity, tmp_path, {}, dump={"counts": COUNTS, "psql_error": error})
    assert code != 0 and result["localDump"] == "failed"
    assert result["localDumpDetail"] == ("2026-10-24T0230Z.sql.gz did not restore: "
                                         "psql:<stdin>:812: ERROR:  invalid input syntax for type integer: ")
    assert "4111" not in json.dumps(result)


def test_a_dump_without_its_counts_fails(smartcity, tmp_path):
    code, result, _ = run(smartcity, tmp_path, {}, dump={"counts": ""})
    assert code != 0 and result["localDump"] == "failed"
    assert result["localDumpDetail"] == "no table counts beside 2026-10-24T0230Z.sql.gz"


def test_without_the_local_dump_the_stage_is_skipped_not_failed(production, tmp_path):
    assert env_of(one(production, "CronJob", NAME))["LOCAL_BACKUP"] == "false"
    code, result, log = run(production, tmp_path, {"portal": ("5", "5")})
    assert code == 0 and result["result"] == "passed"
    assert result["localDump"] == "off" and result["localDumpDetail"] == ""
    assert "create" in log and not [line for line in log if "drill-dump" in line]
    script = one(production, "ConfigMap", f"{NAME}-script")["data"]
    assert "dump-pod.yaml" not in script
    role = one(production, "Role", NAME)
    assert not [r for r in role["rules"] if r["resources"] == ["pods"]], "no pod rights without the dump"


def test_the_restore_pod_holds_the_dump_closed(smartcity):
    pod = yaml.safe_load(one(smartcity, "ConfigMap", f"{NAME}-script")["data"]["dump-pod.yaml"])
    spec = pod["spec"]
    assert pod["metadata"]["name"] == "postgres-cluster-drill-dump"
    assert pod["metadata"]["annotations"]["linkerd.io/inject"] == "disabled"
    assert spec["automountServiceAccountToken"] is False and spec["enableServiceLinks"] is False
    container = spec["containers"][0]
    assert "listen_addresses= " in container["command"][2], "Postgres listens on no port"
    assert "ports" not in container
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert spec["securityContext"]["runAsNonRoot"] is True and spec["securityContext"]["runAsUser"] == 26
    backup = next(v for v in spec["volumes"] if v["name"] == "backup")
    assert backup["persistentVolumeClaim"] == {"claimName": "postgres-cluster-local-backup", "readOnly": True}
    assert next(m for m in container["volumeMounts"] if m["name"] == "backup")["readOnly"] is True
    label = pod["metadata"]["labels"]["app.kubernetes.io/component"]
    selectors = [d for d in smartcity if d.get("kind") == "Service"
                 and label in json.dumps(d["spec"].get("selector") or {})]
    assert selectors == [], "no Service selects the restored copy"
    role = one(smartcity, "Role", NAME)
    pods = [r for r in role["rules"] if r["resources"] == ["pods"]]
    assert {tuple(r["verbs"]) for r in pods if not r.get("resourceNames")} == {("create",)}
    assert [r["resourceNames"] for r in pods if r.get("resourceNames")] == [["postgres-cluster-drill-dump"]]


def test_the_dump_job_writes_the_counts_and_fails_a_dump_over_80_percent(smartcity):
    job = one(smartcity, "Job", "postgres-cluster-local-backup-now")["spec"]["template"]["spec"]
    container = job["containers"][0]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["VOLUME_SIZE"] == "10Gi"
    script = container["command"][2]
    assert script.index('"$file.counts"') < script.index('mv "$file.part" "$file"')
    assert "over 80 % of the" in script and "-name '*.sql.gz.counts'" in script
