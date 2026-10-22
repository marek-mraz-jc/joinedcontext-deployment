"""T-4933: every client's pool ceiling fits the shared Postgres's max_connections.

On 2026-10-21 dev ran max_connections 50 with only the broker's pool sized against it. Keycloak's
pool (ceiling 100 by default) grew to 10 and Gitea's has no ceiling, the 47 slots left after
CNPG's superuser reserve filled, and Postgres refused Gitea's token lookups (53300) until every
Gitea token answered 401.

For each role the Cluster manages, this test reads the ceiling of the workload that logs in as
it from the render (or, where the ceiling is compiled into the program, from the constant
below with its source), multiplies by replicas, and asserts

    sum x 1.2 + superuser_reserved_connections <= max_connections

The 20 % headroom covers short-lived logins: a rolling update's second pod (pools open
lazily, so it starts near empty), init containers and Jobs that run a CLI, the CNPG operator's
own checks. A role this test does not know fails it: name its ceiling here before it ships.

T-5125: the ceilings also stay at or under ALERT_SHARE of max_connections, the threshold of the CNPG
chart's CNPGClusterHighConnectionsWarning, so that alert fires only for a client nobody counted.
"""

import math
import re

import pytest

ENVIRONMENTS = ["local", "dev", "smartcity", "staging", "production", "minimal", "broker-only"]
HEADROOM = 1.2
ALERT_SHARE = 0.8  # CNPGClusterHighConnectionsWarning, charts/cluster prometheus_rules (cnpg/cluster 0.7.0)
SUPERUSER_RESERVED_DEFAULT = 3
# Ceilings compiled into the programs (sqlx PgPoolOptions::max_connections):
# joinedcontext-portal src/db.rs and joinedcontext-platform crates/assistant/src/bin/jc-assistant.rs.
COMPILED = {"portal": ("portal", 5), "assistant": ("jc-assistant", 4)}
# Drivers' own defaults, used when the render sets nothing.
ANTARES_DEFAULT = 20  # antares-broker main.rs parse_pg_pool
KEYCLOAK_DEFAULT = 100  # Quarkus/Agroal KC_DB_POOL_MAX_SIZE
SQLALCHEMY_DEFAULT = (5, 10)  # QueuePool pool_size, max_overflow
CKAN_UWSGI_PROCESSES = 2  # ckan/ckan-base start_ckan.sh: `-p 2`, one thread each


def workloads(docs: list[dict]) -> list[dict]:
    return [d for d in docs if d.get("kind") in ("Deployment", "StatefulSet")]


def named(docs: list[dict], name: str) -> list[dict]:
    return [d for d in workloads(docs) if d["metadata"]["name"] == name]


def env_of(workload: dict) -> dict[str, str]:
    return {
        e["name"]: e["value"]
        for c in workload["spec"]["template"]["spec"]["containers"]
        for e in c.get("env", [])
        if "value" in e
    }


def replicas(workload: dict) -> int:
    return int(workload["spec"].get("replicas", 1))


def antares(docs: list[dict]) -> int:
    return sum(
        replicas(w) * int(env_of(w).get("ANTARES_PG_POOL", ANTARES_DEFAULT))
        for w in workloads(docs)
        if "ANTARES_DATABASE_URL" in env_of(w)
    )


def keycloak(docs: list[dict]) -> int:
    return sum(
        replicas(w) * int(env_of(w).get("KC_DB_POOL_MAX_SIZE", KEYCLOAK_DEFAULT))
        for w in workloads(docs)
        if "KC_DB_URL_DATABASE" in env_of(w)
    )


def ckan(docs: list[dict]) -> int:
    # Each CKAN process holds a main engine and two DataStore engines (write, read).
    total = 0
    for w in workloads(docs):
        env = env_of(w)
        if "CKAN_SQLALCHEMY_URL" not in env:
            continue
        assert "UWSGI_OPTS" not in env, "count the uWSGI processes UWSGI_OPTS starts"
        main = int(env.get("CKAN___SQLALCHEMY__POOL_SIZE", SQLALCHEMY_DEFAULT[0])) + int(
            env.get("CKAN___SQLALCHEMY__MAX_OVERFLOW", SQLALCHEMY_DEFAULT[1])
        )
        datastore = int(env.get("CKAN__DATASTORE__SQLALCHEMY__POOL_SIZE", SQLALCHEMY_DEFAULT[0])) + int(
            env.get("CKAN__DATASTORE__SQLALCHEMY__MAX_OVERFLOW", SQLALCHEMY_DEFAULT[1])
        )
        total += replicas(w) * CKAN_UWSGI_PROCESSES * (main + 2 * datastore)
    return total


def gitea(docs: list[dict]) -> int:
    config = [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "gitea-inline-config"]
    assert len(config) == 1, "the Gitea chart's inline config Secret is not in the render"
    match = re.search(r"^MAX_OPEN_CONNS=(\d+)$", config[0]["stringData"]["database"], re.MULTILINE)
    ceiling = int(match[1]) if match else 0
    assert ceiling > 0, "Gitea's [database] MAX_OPEN_CONNS is unset or 0: Gitea then opens connections without a ceiling"
    return sum(replicas(w) for w in named(docs, "gitea")) * ceiling


def compiled(role: str):
    def count(docs: list[dict]) -> int:
        workload, ceiling = COMPILED[role]
        found = named(docs, workload)
        assert found, f"role {role} has a database but no {workload} workload in the render"
        return sum(replicas(w) for w in found) * ceiling

    return count


# A catalogue beside `catalogue` logs in as ckan_<name>; every CKAN is counted once, under `ckan`.
CLIENTS = {
    "antares": antares,
    "keycloak": keycloak,
    "gitea": gitea,
    "portal": compiled("portal"),
    "assistant": compiled("assistant"),
    "ckan": ckan,
}


def budget(docs: list[dict]) -> tuple[dict[str, int], int, int]:
    found = [d for d in docs if d.get("kind") == "Cluster" and d["metadata"]["name"] == "postgres-cluster"]
    assert len(found) == 1
    spec = found[0]["spec"]
    parameters = spec["postgresql"].get("parameters", {})
    roles = [r["name"] for r in spec.get("managed", {}).get("roles", [])]
    clients = {"ckan" if r.startswith("ckan_") else r for r in roles}
    unknown = sorted(clients - CLIENTS.keys())
    assert not unknown, f"no pool ceiling known for role(s) {unknown}: add them to CLIENTS"
    pools = {client: CLIENTS[client](docs) for client in clients}
    reserved = int(parameters.get("superuser_reserved_connections", SUPERUSER_RESERVED_DEFAULT))
    return pools, reserved, int(parameters.get("max_connections", 100))


def fits(pools: dict[str, int], reserved: int, max_connections: int) -> bool:
    total = sum(pools.values())
    return math.ceil(total * HEADROOM) + reserved <= max_connections and total <= ALERT_SHARE * max_connections


def test_the_sum_counts_what_starved_gitea():
    # dev at 07:02Z on 2026-10-21 (deployment 13097d3, Keycloak not yet capped): the broker's
    # 16 and the counted pools fit 50, the ceilings nobody had set did not.
    t13097d3 = {"antares": 16, "keycloak": KEYCLOAK_DEFAULT, "ckan": 2 * sum(SQLALCHEMY_DEFAULT) * 3,
                "portal": 5, "assistant": 4, "gitea": 0}
    assert not fits(t13097d3, SUPERUSER_RESERVED_DEFAULT, 50)
    assert fits({"antares": 16, "keycloak": 7, "ckan": 8, "portal": 5, "assistant": 4, "gitea": 3}, 3, 55)
    # 45 of 55 passes the headroom (54 + 0) but holds the warning alert's 80 % (44) at every peak.
    assert not fits({"antares": 18, "keycloak": 7, "ckan": 8, "portal": 5, "assistant": 4, "gitea": 3}, 0, 55)


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_client_pool_fits_max_connections(rendered, env):
    docs = rendered(env)
    if not any(d.get("kind") == "Cluster" and d["metadata"]["name"] == "postgres-cluster" for d in docs):
        pytest.skip(f"{env} renders no postgres-cluster")
    pools, reserved, max_connections = budget(docs)
    need = math.ceil(sum(pools.values()) * HEADROOM) + reserved
    assert need <= max_connections, f"{env}: pools {pools} x {HEADROOM} + {reserved} reserved = {need} > max_connections {max_connections}"
    total = sum(pools.values())
    assert total <= ALERT_SHARE * max_connections, f"{env}: pools {pools} = {total} pass {ALERT_SHARE:.0%} of max_connections {max_connections}, where CNPGClusterHighConnectionsWarning fires"


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_cnpg_cluster_is_scraped_and_alerts_on_connections_where_prometheus_watches(rendered, env):
    # cluster.monitoring.enabled follows global.metrics.enabled. Production 2026-10-22 set the key
    # the chart does not read (monitoring.enablePodMonitor) and rendered neither (T-5125).
    docs = rendered(env)
    clusters = [d["metadata"]["name"] for d in docs if d.get("kind") == "Cluster" and d["apiVersion"].startswith("postgresql.cnpg.io/")]
    if not clusters:
        pytest.skip(f"{env} renders no CNPG Cluster")
    watched = any(d.get("kind") == "ServiceMonitor" for d in docs)
    for name in clusters:
        monitors = [d for d in docs if d.get("kind") == "PodMonitor" and d["spec"]["selector"]["matchLabels"].get("cnpg.io/cluster") == name]
        rules = {
            r["alert"]: r["expr"]
            for d in docs if d.get("kind") == "PrometheusRule" and d["metadata"]["name"] == f"{name}-alert-rules"
            for g in d["spec"]["groups"] for r in g["rules"]
        }
        if not watched:
            # No Prometheus Operator CRDs where metrics are off: a PodMonitor would fail the apply.
            assert not monitors and not rules, f"{env}: {name} renders monitoring while global.metrics.enabled is false"
            continue
        assert [e["port"] for m in monitors for e in m["spec"]["podMetricsEndpoints"]] == ["metrics"], f"{env}: {name} has no PodMonitor"
        warning = rules.get("CNPGClusterHighConnectionsWarning", "")
        assert "max_connections" in warning and warning.rstrip().endswith(f"> {ALERT_SHARE * 100:.0f}"), f"{env}: {name} has no 80 % connection alert"
