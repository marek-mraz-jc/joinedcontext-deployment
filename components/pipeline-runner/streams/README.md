# Shared resources of the development profile's resident runner

`resources.yaml` holds the caches and the rate limit every stream on the `pipeline-runner`
shares: streams mode rejects a `*_resources` block inside a stream file, so the runner loads
it with `-r` (`values/runner/base-values.yaml.gotmpl`). The streams themselves are no longer
files here: the Portal's reconciler renders each seeded Pipeline manifest and the `bento.yaml`
beside it (`../../context-gateway/seed/helsinki/`) into a resident stream over the runner's
API (PL-47, T-0647), so one pipeline runs once and the Portal shows it Live from the runner.

Every value a rendered stream needs comes in as an environment variable
(`values/runner/development-values.yaml.gotmpl`): `JC_ORG_DOMAIN`, `JC_GATEWAY_URL`, `JC_GATEWAY_HOST` (the same host, for a manifest URL),
`JC_TOKEN_URL`, `JC_CLIENT_ID` and, from the client's Secret, `JC_CLIENT_SECRET`.

The entities go out as `application/json` under the NGSI-LD core context, with no remote
`@context`: the broker has no egress to the internet, so a payload naming
`smartdatamodels.org` is a 504 `LdContextNotAvailable` per entity, not a write.

## inflate.wasm (PL-72, T-3953)

The module of the `wasm` step a rendered zip archive read runs: it inflates a deflated member
and stops at the size the archive's directory declares, so a deflate bomb behind a lying
directory never inflates past it. The runner's ConfigMap carries it as `binaryData`
(`values/runner/base-values.yaml.gotmpl`), mounted at `/streams/inflate.wasm`, the path
`jcctl::bento` renders. It is built from joinedcontext-platform `tools/bento-inflate`:

    cd tools/bento-inflate && cargo build --release --locked --target wasm32-unknown-unknown
    cp target/wasm32-unknown-unknown/release/bento_inflate.wasm <here>/inflate.wasm

The copy here was built with rustc 1.99.0 from platform bd784b6, and its sha256
is `3eeaf3ce4a8f58371ac6439b51225c3a24b8cbed9ac24680279a760188cc3b25`.
`tests/test_runner_inflate.py` runs it in the pinned Bento.
