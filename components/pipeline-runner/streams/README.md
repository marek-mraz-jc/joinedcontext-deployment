# Shared resources of the development profile's resident runner

`resources.yaml` holds the caches and the rate limit every stream on the `pipeline-runner`
shares: streams mode rejects a `*_resources` block inside a stream file, so the runner loads
it with `-r` (`values/runner/base-values.yaml.gotmpl`). The streams themselves are no longer
files here: the Portal's reconciler renders each seeded Pipeline manifest and the `bento.yaml`
beside it (`../../context-gateway/seed/helsinki/`) into a resident stream over the runner's
API (PL-47, T-0647), so one pipeline runs once and the Portal shows it Live from the runner.

It also holds one processor resource, `events_tail`: the shared tail of every events pipeline
(`seeds/bbsk-events/pipelines/common.yaml`), which `seeds/bbsk-events/generate.py` writes between
its BEGIN and END lines; edit common.yaml and rerun the generator, never the block (T-5555).

Every value a rendered stream needs comes in as an environment variable
(`values/runner/development-values.yaml.gotmpl`): `JC_ORG_DOMAIN`, `JC_GATEWAY_URL`, `JC_GATEWAY_HOST` (the same host, for a manifest URL),
`JC_TOKEN_URL`, `JC_CLIENT_ID` and, from the client's Secret, `JC_CLIENT_SECRET`.

The entities go out as `application/json` under the NGSI-LD core context, with no remote
`@context`: the broker has no egress to the internet, so a payload naming
`smartdatamodels.org` is a 504 `LdContextNotAvailable` per entity, not a write.
