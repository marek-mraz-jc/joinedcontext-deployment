# Assistant

`jc-assistant` from the platform image (docs Architecture/22 §1, ADR-N-040, T-3052): the
knowledge assistant's crawl worker. Once a minute it reads the organization's `KnowledgeSource`
manifests, queues every website source its schedule names, crawls the public site, extracts
pages and PDFs and stores the passages in its own database. One Deployment, no Service:
nothing calls it, the kubelet probes `/healthz` and `/readyz` on 8080.

Deploy the component with:
```bash
helmfile apply -i --selector component=assistant
```

## Turning it on

No environment lists `assistant` yet. The platform image pinned in `images.yaml` is the
gateway's, which predates the binary; pin a digest whose build contains
`/usr/local/bin/jc-assistant` (platform T-3052 and later), then add `assistant` after
`functions` in the environment's component list.

## What it wires

- **PostgreSQL**: the `assistant` database and role (`databases.yaml`), the password in
  `db-assistant`, the `vector` extension created by the role job. The worker runs its own
  migrations as that role, so the forced row-level security of every tenant table holds.
- **Forge**: git-sync and, in layout 2, the checkouts sidecar, both with the read-only
  `gitea-token-gateway`; the forge bootstrap mints that token into this namespace and
  restarts `jc-assistant` when it mints it again.
- **Network**: no ingress; egress to PostgreSQL, the forge, CoreDNS, and TCP 80/443 on every
  public address. Every private range is excepted, so a source URL never reaches the cluster.

## Sizing

One crawl at a time; a PDF and its text sit in memory while it is extracted, so the limit is
1Gi and the request what the idle loop uses.
