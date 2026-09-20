# Portal

Joinedcontext Portal: Axum API, embedded React UI, and in-process reconciler.

## APISIX Route Mapping

The Portal is served on `portal.{domain}` behind the edge login (docs ADR-N-019): APISIX's
`openid-connect` plugin logs the person in with the `edge` client and hands the Portal
`X-Userinfo` and `X-Access-Token`; `JC_TRUST_EDGE_TOKEN: "true"` makes the Portal accept the
token header as it accepts a bearer, and `JC_PORTAL_PUBLIC_URL` names the Portal host. The
apex keeps `/apps/*` (`apps-surface`, static apps served by the Portal behind the same login)
and redirects everything else to the Portal host (`portal-redirect`).

APISIX standalone mode derives upstream, route, and plugin_config IDs from the same map key.
While architecture docs describe shared `pc-*` plugin configs, each route in `apisix-plugins.yaml`
defines its dedicated plugin configuration under the matching route ID (`portal-ui`,
`portal-api`, `portal-metrics`, `apps-surface`, `portal-redirect`).

Deploy the component with:
```bash
helmfile apply -i --selector component=portal
```

## Image

`ghcr.io/marek-mraz/joinedcontext-portal`, pinned by digest. Distroless, entrypoint
`/usr/local/bin/joinedcontext-portal`, listening on 8080 — the component sets no `command`
and lets the entrypoint run.

## The secret backend a pipeline's `secretRef` resolves through

A `Pipeline` names its credentials, it never carries them (CC-06, PL-15). The reconciler
resolves every `secretRef` of every pipeline on each sync and writes one `pipeline-secrets`
Secret into the runner's namespace; the runner takes it as environment, so a stream reads
`${MQTT_PASSWORD}` and nothing in Git, in a ConfigMap or in a log line holds the value.

An installation configures **one** backend, never both:

- **SOPS** (`portal.portal.sopsAgeSecret`, what `dev` uses): the reconciler decrypts the
  `*.enc.yaml` files of the configuration repository it staged, with an age identity mounted
  read-only at `/etc/jc/age/keys.txt`. One tenant, one node, nothing else to run.
- **OpenBao** (`JC_PORTAL_OPENBAO_ADDR`, `JC_PORTAL_OPENBAO_ROLE`): a server of its own and the
  Kubernetes auth method bound to this ServiceAccount. The multi-tenant answer (ADR-N-012).

With neither, every reference is refused with `no secret backend is configured`, the pipeline
carries the reason on its `StreamDeployed` condition, and nothing runs half-credentialed.

### Handing an installation its age identity

The private half is operator-supplied: generated once, kept out of Git, and copied into the
Portal's namespace by hand. The public half is a recipient anyone may read.

```bash
age-keygen -o .secrets/age-dev.key            # mode 600, never committed
age-keygen -y .secrets/age-dev.key            # the recipient, for encrypting
kubectl -n dev create secret generic portal-age-identity \
  --from-file=keys.txt=.secrets/age-dev.key
```

Then encrypt what a pipeline needs to the same recipient and commit the result — ciphertext —
to the configuration repository, beside the manifests that name it:

```bash
sops --encrypt --age "$recipient" plain.yaml \
  > projects/{project}/secrets/{name}.enc.yaml
```

The file's top-level keys are the `secretRef.name`s, one level of keys below them the
`secretRef.key`s. The mount is `optional`: an installation that names the Secret and has not
created it yet runs and refuses every reference with a reason, rather than never starting.
