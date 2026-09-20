# Postgres

Central managed PostgreSQL database for the joinedcontext platform, run by the
CloudNativePG operator.

Deploy the component with:

```bash
helmfile apply -i --selector component=postgres -f helmfile.yaml.gotmpl
```

## Transport encryption

CloudNativePG issues the server certificate itself, so `SHOW ssl` is `on` with no extra
configuration. That alone does not make TLS mandatory: the operator appends
`host all all all scram-sha-256` as its own last `pg_hba` rule, and a client that refuses
TLS falls straight through to it. So `pg_hba` opens with

```
hostnossl all all all reject
hostssl   all all all scram-sha-256
```

An unencrypted connection is refused before it can reach the appended catch-all
(BSI TR-03187 CT-9). Clients need nothing beyond libpq's default `sslmode=prefer`, which
negotiates TLS whenever the server offers it — Keycloak (JDBC) and the Antares broker both
connect over TLSv1.3 with no client-side change. Unix-socket clients inside the pod, such
as the instance manager and the metrics exporter, match the `local ... peer` rules and are
unaffected.

## Backups

Continuous WAL archiving and a daily base backup to an S3-compatible object store
(OPS-09, OPS-10). Disabled by default — there is no bucket until someone supplies one, and
a half-configured backup is worse than an honestly absent one. Turn it on per environment:

```yaml
postgres:
  cluster:
    backups:
      enabled: true
      endpointURL: 'https://s3.eu-central-1.example.org'
      destinationPath: 's3://city-backups/postgres'
      region: 'eu-central-1'
      bucket: 'city-backups'
      retentionPolicy: '30d'
      schedule: '0 0 3 * * *'      # CNPG cron has six fields; seconds come first
      existingSecret: 'postgres-backup-s3'
```

WAL and data files are compressed (gzip) and encrypted (AES256) on the way out.

The object-store credentials never appear in these values. `existingSecret` names a Secret
the operator creates with two keys, `ACCESS_KEY_ID` and `ACCESS_SECRET_KEY` — supply it
through SOPS or OpenBao (ADR-N-012, see `components/secrets/README.md`). The chart is
configured with `backups.secret.create: false` so it can never template a credential into
a manifest.

## Point-in-time recovery

Restoring is the operator's decision, never an automatic one (OPS-10, OPS-11). Turning
`recovery.enabled` on bootstraps this cluster from the WAL archive at a chosen instant
instead of from `initdb` — the cluster keeps its name, so every component keeps its
`postgres-cluster-rw` connection string:

```yaml
postgres:
  cluster:
    backups:
      # a fresh path: see below
      destinationPath: 's3://city-backups/postgres-restored-2026-08-15'
    recovery:
      enabled: true
      sourceCluster: 'postgres-cluster'   # the serverName the archive was written under
      targetTime: '2026-08-15T14:30:00Z'  # ISO 8601, quoted; empty = end of the archive
      destinationPath: 's3://city-backups/postgres'
```

The restored cluster carries the source cluster's name, so with the archive left as it is it
would write its own WAL over the history it is reading and there would be nothing to restore
from a second time. The render refuses that: enabling recovery while the backups block still
points at the archive being read stops with an error, and so does a `targetTime` that is not
an ISO 8601 instant. The `recovery-test` environment renders exactly this values change and
`tests/test_postgres_recovery.py` asserts it on every push.

Turn `recovery.enabled` back to `false` once the data is verified, keeping the new
`destinationPath`. Left on, it restores the same old instant again the next time the
`Cluster` object is recreated. The procedure around all of this — stopping the writers,
deleting the damaged cluster, watching the replay — is Runbook 6 in the operations guide.
