"""T-7383: no rollout hangs behind a session idle in a transaction.

The jc-prod c5405e24 rollout waited 6 min on two pg_dump sessions idle in transaction for 8 days.
postgres-cluster times such sessions out on every environment (a server default, no role
changed), and `just jc-apply` runs scripts/pg-blockers.py first, which lists them and kills
nothing. The rows below are what the script's own query prints (checked once against the
role-job image's Postgres, evidence in the task).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/pg-blockers.py"
SEP = "\x1f"


def row(pid, state, database="jc_daiya", xact=0, idle=0, locks=1, role="postgres", app="pg_dump"):
    xact_start = "2026-11-11T08:27:00Z" if xact >= 0 else ""
    return SEP.join(str(c) for c in (pid, role, database, state, app, "local", "2026-11-11T08:27:00Z",
                                     xact_start, xact, idle, locks))


def run(*rows, args=()):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input="\n".join(rows) + "\n",
                          capture_output=True, text=True, check=False)


def postgres_cluster(docs):
    found = [d for d in docs if d.get("kind") == "Cluster" and d["metadata"]["name"] == "postgres-cluster"]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("env", ["jc-prod", "jc-dev"])
def test_postgres_cluster_times_out_idle_transactions(rendered, env):
    params = postgres_cluster(rendered(env))["spec"]["postgresql"]["parameters"]
    assert params["idle_in_transaction_session_timeout"] == "5min"
    # A server default: the superuser keeps its rights, and no managed role carries settings.
    roles = postgres_cluster(rendered(env))["spec"]["managed"]["roles"]
    assert not [r for r in roles if r.get("superuser")]


def test_the_8_day_dump_session_refuses_the_apply_and_names_it():
    eight_days = 8 * 86400
    out = run(row(4711, "idle in transaction", xact=eight_days, idle=eight_days, locks=7),
              row(4712, "active", database="jc_portal", xact=1, idle=1))
    assert out.returncode == 1
    lines = out.stdout.splitlines()
    assert lines[0].strip() == ("FAIL  pid 4711 role postgres database jc_daiya 'idle in transaction' since backend"
                                " 2026-11-11T08:27:00Z transaction 2026-11-11T08:27:00Z (7 locks, app 'pg_dump',"
                                " client local)")
    assert "pg_terminate_backend" in lines[-1] and len(lines) == 2


def test_idle_in_transaction_counts_in_any_database_and_aborted_too():
    out = run(row(1, "idle in transaction (aborted)", database="keycloak", xact=400, idle=301, locks=0))
    assert out.returncode == 1 and "pid 1 " in out.stdout


def test_an_old_transaction_holding_a_module_database_blocks():
    out = run(row(2, "active", database="jc_kaisatsu", xact=301, idle=301, locks=1))
    assert out.returncode == 1 and "pid 2 " in out.stdout


def test_short_transactions_idle_sessions_and_other_databases_pass_silently():
    out = run(row(3, "idle in transaction", xact=299, idle=299),
              row(4, "idle", xact=-1, idle=86400, locks=0),
              row(5, "active", database="keycloak", xact=86400, idle=86400),
              row(6, "active", database="jc_daiya", xact=86400, idle=86400, locks=0))
    assert (out.returncode, out.stdout) == (0, "")


def test_minutes_and_prefix_are_honoured():
    one = row(7, "active", database="ckan", xact=61, idle=61)
    assert run(one).returncode == 0
    assert run(one, args=("--minutes", "1", "--prefix", "ckan")).returncode == 1


def test_an_unreadable_row_fails_instead_of_passing():
    out = run("94|postgres|jc_daiya")
    assert out.returncode == 1 and "unreadable row" in out.stdout


def test_no_rows_pass():
    assert run().returncode == 0


def test_the_query_only_reads():
    sql = run(args=("--sql",)).stdout.lower()
    assert "pg_stat_activity" in sql and "pg_locks" in sql
    assert not any(word in sql for word in ("pg_terminate_backend", "pg_cancel_backend", "update ", "delete ", "insert "))


def test_jc_apply_runs_the_preflight_before_the_sync():
    justfile = (ROOT / "justfile").read_text()
    body = justfile.split("\njc-apply env", 1)[1].split("\n\n", 1)[0]
    assert body.index("just pg-blockers") < body.index("helmfile")
    preflight = justfile.split("\npg-blockers env:", 1)[1].split("\n\n", 1)[0]
    assert "jc-dev|jc-prod" in preflight and "_dev-guard" in preflight
    assert "pg_terminate_backend" not in preflight
