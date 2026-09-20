"""T-0019: the CNPG cluster archives WAL to object storage and speaks TLS only.

T-0262 adds the image it runs: no Kyverno policy judges a Cluster resource, so the
digest of the database image is only ever checked here."""

import pytest


@pytest.fixture(scope="module")
def production(rendered):
    return rendered("production")


@pytest.fixture(scope="module")
def local(rendered):
    return rendered("local")


def only(docs: list[dict], kind: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind]
    assert len(found) == 1, f"expected exactly one {kind}, got {len(found)}"
    return found[0]


def test_cluster_requires_tls(production, local):
    """CNPG appends its own `host all all all scram-sha-256`, so the reject rule — not the
    hostssl rule — is what stops a client that refuses TLS (BSI TR-03187 CT-9)."""
    for docs in (production, local):
        pg_hba = only(docs, "Cluster")["spec"]["postgresql"]["pg_hba"]
        assert pg_hba == [
            "hostnossl all all all reject",
            "hostssl all all all scram-sha-256",
        ]


def test_production_archives_wal_to_object_storage(production):
    backup = only(production, "Cluster")["spec"]["backup"]
    store = backup["barmanObjectStore"]
    assert store["destinationPath"].startswith("s3://")
    assert store["endpointURL"]
    assert backup["retentionPolicy"] == "30d"
    assert store["wal"]["compression"] == "gzip" and store["wal"]["encryption"] == "AES256"
    assert store["data"]["compression"] == "gzip" and store["data"]["encryption"] == "AES256"


def test_object_storage_credentials_are_a_reference_only(production):
    """No access key may reach a manifest: barman gets a Secret name, and the chart
    must not have created that Secret from values it could only have read in plaintext."""
    store = only(production, "Cluster")["spec"]["backup"]["barmanObjectStore"]
    creds = store["s3Credentials"]
    assert creds["accessKeyId"]["name"] == "postgres-backup-s3"
    assert creds["accessKeyId"]["key"] == "ACCESS_KEY_ID"
    assert creds["secretAccessKey"]["name"] == "postgres-backup-s3"
    assert creds["secretAccessKey"]["key"] == "ACCESS_SECRET_KEY"
    rendered_secrets = [d["metadata"]["name"] for d in production if d.get("kind") == "Secret"]
    assert not [n for n in rendered_secrets if "s3-creds" in n or n == "postgres-backup-s3"]


def test_production_has_a_daily_scheduled_backup(production):
    schedule = only(production, "ScheduledBackup")["spec"]
    assert schedule["method"] == "barmanObjectStore"
    # CNPG cron carries a leading seconds field, so a five-field expression is silently wrong.
    assert len(schedule["schedule"].split()) == 6, schedule["schedule"]


def test_backups_stay_off_without_an_object_store(local):
    """A half-configured backup is worse than an honestly absent one."""
    assert only(local, "Cluster")["spec"].get("backup") is None
    assert not [d for d in local if d.get("kind") == "ScheduledBackup"]


def test_the_database_image_is_pinned_by_digest(production, local):
    """The Cluster is a custom resource, not a workload: the pods it produces are built by
    the operator, long after any admission policy has looked at this manifest. A tag here
    would be the one image reference nothing else can catch (BSI TR-03187 AR-4)."""
    for docs in (production, local):
        image = only(docs, "Cluster")["spec"]["imageName"]
        assert "@sha256:" in image, image


@pytest.mark.parametrize("env", ["local", "dev", "production"])
def test_managed_role_names_are_unique(rendered, env):
    """CNPG rejects the whole Cluster when a name repeats in `spec.managed.roles`:

        admission webhook "vcluster.cnpg.io" denied the request:
        spec.managed.roles: Invalid value: "ckan": Role name is duplicate of another

    The roles are generated one per database, but a user may own SEVERAL — CKAN keeps its
    catalogue and its DataStore apart and owns both (EP-65) — so two databases with one user
    used to emit that user twice. Nothing caught it: the render is valid YAML and no Kyverno
    policy judges a Cluster, so the first thing to object was the live webhook, at `dev-apply`.
    """
    cluster = only(rendered(env), "Cluster")
    names = [role["name"] for role in cluster["spec"].get("managed", {}).get("roles", [])]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, (
        f"{env} renders {duplicates} more than once in spec.managed.roles; CNPG refuses the "
        "Cluster. One role per user, not per database."
    )


@pytest.mark.parametrize("env", ["local", "dev", "production"])
def test_every_embedded_database_has_a_role_to_own_it(rendered, env):
    """Deduplicating by user must not drop a user: every embedded database's owner still needs
    a role, or the database is created and nothing can log into it."""
    docs = rendered(env)
    cluster = only(docs, "Cluster")
    roles = {role["name"] for role in cluster["spec"].get("managed", {}).get("roles", [])}
    databases = [d for d in docs if d.get("kind") == "Database"]
    owners = {d["spec"]["owner"] for d in databases if d.get("spec", {}).get("owner")}
    missing = sorted(owners - roles)
    assert not missing, f"{env} declares databases owned by {missing} with no managed role"
