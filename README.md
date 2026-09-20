# joinedcontext-deployment

[![ci](https://github.com/marek-mraz/joinedcontext-deployment/actions/workflows/ci.yml/badge.svg)](https://github.com/marek-mraz/joinedcontext-deployment/actions/workflows/ci.yml)
[![ci-full](https://github.com/marek-mraz/joinedcontext-deployment/actions/workflows/ci-full.yml/badge.svg)](https://github.com/marek-mraz/joinedcontext-deployment/actions/workflows/ci-full.yml)

Helmfile deployment of the **joinedcontext platform**. Forked from the CIVITAS/CORE v2 deployment
repository (EUPL 1.2, see `LICENSE` and `CONTRIBUTORS.md`) and stripped to the components the
platform keeps. Specification and operating docs live in [`../docs`](../docs)
(`Deployment/`, `Operations/`, ADR-N-007 for APISIX standalone mode).

## Components in this repository

| Component | Role | Origin |
|---|---|---|
| `prepare` | namespaces, Linkerd annotations, CA distribution | kept |
| `secrets` | generated platform secrets (once, replicated per namespace) | kept |
| `networkpolicies` | default-deny per component + explicit allow rules | kept (egress default-deny to be added, OPS-26) |
| `runtime-policies` | Kyverno ClusterPolicies (Linkerd, CNPG label protection) | kept, Strimzi rules removed |
| `postgres` | CloudNativePG operator, cluster, databases | kept |
| `keycloak` | identity, OIDC, realm import via keycloak-config-cli | kept, legacy service users removed |
| `apisix` | edge gateway in **standalone file mode** (ConfigMap `apisix-standalone-config`, no etcd, no Admin API) | reworked |

Removed from the legacy repository: `authz` (OPA), `config-adapters`, `etcd`, `frost`, `geoserver`,
`kafka`, `nifi`, `portal`, `superset`, `valkey`, the Java/Robot system tests and the demo seeding
scripts.

## Components still to be added

Each lands as `components/<name>/` (scaffold with `just new-component`) once its image exists:

| Component | Repository | Chapter |
|---|---|---|
| `context-broker` | AntaresBroker | Architecture/14, ADR-N-008 |
| `context-gateway`, `portal-api`, `jcctl` | joinedcontext-platform | Architecture/05, 09, 06 |
| `portal-ui` | joinedcontext-portal-ui | Architecture/09 |
| `gitea` | upstream chart | Architecture/06, ADR-N-004 |
| `artifact-store` (RustFS) | upstream chart | Architecture/17, ADR-N-015 |
| `pipeline-runner` (Bento) | upstream image | Architecture/08, ADR-N-006 |
| `model-tools` | joinedcontext-platform/tools | Architecture/11 |
| addons: `openbao`, `grafana`, `agent-runner`, `dataspace-connector` | upstream | Deployment/04 |

## Usage

```bash
just deploy-k3d                 # local k3d cluster (dev-deployment/)
just deploy-operators local     # shared operators once per cluster
just deploy-instance local      # one instance (namespace = global.instanceSlug)
just template local             # render everything without a cluster
```

Environment values live in `deployment/environments/<env>/` of your own deployment checkout
(see `.ci/example-deployments/` for the layout). Global defaults: `defaults/environment/global.yaml`
(`domain: joinedcontext.test`, `instanceSlug: dev`, Linkerd mandatory mTLS, Kyverno Enforce).

## Security baseline

The phase-1 baseline, the APISIX route table and the acceptance checklist are specified in
`docs/Deployment/08-security-hardening.md` and `docs/Deployment/10-edge-routing-apisix.md`.
