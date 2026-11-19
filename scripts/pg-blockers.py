#!/usr/bin/env python3
"""The rollout preflight of postgres-cluster: no session may hold the module databases (T-7383).

The jc-prod rollout of c5405e24 (2026-11-19) hung 6 min: two ad-hoc pg_dump sessions from
2026-11-11 sat idle in transaction for 8 days and held locks on jc_daiya and jc_kaisatsu, so the
modules' migrations waited until someone terminated them. `--sql` prints the read-only query;
`just jc-apply` runs it as psql in the primary and pipes its rows (unit-separated, see SQL) here.
A session is a blocker when it sits idle in a transaction longer than `--minutes`, in any
database, or holds a granted lock inside a transaction older than `--minutes` in a database
whose name starts with `--prefix`. Each blocker prints one FAIL line with pid, role, database,
state, backend and transaction start, application and client, and the script exits 1. It kills
nothing: whoever applies reads the lines and decides (pg_terminate_backend by hand).
Exits 0 silently when no session blocks; a row it cannot read fails it.
"""
import argparse
import sys

SEP = "\x1f"
FIELDS = ("pid", "role", "database", "state", "application", "client", "backend_start", "xact_start",
          "xact_seconds", "state_seconds", "locks")
SQL = f"""select concat_ws(E'\\x1f', a.pid, coalesce(a.usename, ''), coalesce(a.datname, ''),
 coalesce(a.state, ''), replace(coalesce(a.application_name, ''), E'\\x1f', ' '),
 coalesce(host(a.client_addr), 'local'),
 coalesce(to_char(a.backend_start at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''),
 coalesce(to_char(a.xact_start at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''),
 coalesce(extract(epoch from now() - a.xact_start)::bigint, -1),
 coalesce(extract(epoch from now() - a.state_change)::bigint, -1),
 (select count(*) from pg_locks l where l.pid = a.pid and l.granted))
from pg_stat_activity a where a.backend_type = 'client backend' and a.pid <> pg_backend_pid()"""
INTS = ("pid", "xact_seconds", "state_seconds", "locks")


def parse(lines):
    """One dict per row of SQL's output; ValueError names a row that is not one."""
    rows = []
    for line in lines:
        if not line.strip():
            continue
        cols = line.split(SEP)
        if len(cols) != len(FIELDS):
            raise ValueError(f"{len(cols)} fields, not {len(FIELDS)}: {line!r}")
        row = dict(zip(FIELDS, cols))
        for key in INTS:
            row[key] = int(row[key])
        rows.append(row)
    return rows


def blockers(rows, minutes, prefix):
    limit = minutes * 60
    return [r for r in rows
            if (r["state"].startswith("idle in transaction") and r["state_seconds"] > limit)
            or (r["database"].startswith(prefix) and r["xact_seconds"] > limit and r["locks"] > 0)]


def main():
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--sql", action="store_true", help="print the query for psql -At and exit")
    args.add_argument("--minutes", type=int, default=5, help="how long a transaction may hold (default 5)")
    args.add_argument("--prefix", default="jc_", help="the module databases' name prefix (default jc_)")
    opts = args.parse_args()
    if opts.sql:
        print(SQL)
        return
    try:
        rows = parse(sys.stdin.read().splitlines())
    except ValueError as err:
        print(f"  FAIL  postgres sessions: unreadable row ({err})")
        sys.exit(1)
    found = blockers(rows, opts.minutes, opts.prefix)
    for r in found:
        print(f"  FAIL  pid {r['pid']} role {r['role'] or '-'} database {r['database'] or '-'} '{r['state']}'"
              f" since backend {r['backend_start']} transaction {r['xact_start'] or '-'}"
              f" ({r['locks']} locks, app '{r['application']}', client {r['client']})")
    if found:
        print(f"refusing: {len(found)} session(s) hold a transaction over {opts.minutes} min. Check what each"
              " is, then end it by hand (select pg_terminate_backend(<pid>)) and run the apply again.")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
