# Agent Runner

The credential proxy of the builder runs (docs Architecture/19, AG-49…AG-52): `jc-agent-proxy`
from the platform image, one Deployment. A `static` application is built by the Portal itself
from one model call (the kit pass, AP-56…AP-60) and reaches the data, the model and its own
run through this proxy; the workspace namespace, the runner Jobs and the `app-from-prompt`
Blueprint of T-0540 come later and plug into the same part.

Deploy the component with:
```bash
helmfile apply -i --selector component=agent-runner
```

## What it wires

- **Portal**: `JC_AGENTS_NAMESPACE`, `JC_AGENT_PROXY_BASE` and
  `JC_PORTAL_AGENT_PROXY_CLIENT_ID`, and the internal listener on Service port 9090, rendered by
  the portal component when this component is in the environment's list. There is no shared bearer:
  `JC_AGENT_PROXY_TOKEN` and the generated `agent-proxy-token` Secret were retired in T-2271, and
  the callbacks answer the proxy's own ServiceAccount token instead.
- **Keycloak**: the confidential client `{project}-agent-proxy` (client_credentials, one
  audience mapper per endpoint of the project, plus `portal-internal` for the Portal's internal
  listener); the gateway resolves its token to the
  ServiceAccount manifest `agent-proxy` of that project, whose role is `public`.
- **Forge seed**: `agentprofiles/app-builder.yaml`, the builder profile every run names.
- **Secrets**: `agent-proxy-token` (generated, both namespaces), the Keycloak client secret
  (generated), the forge token (the Portal's, minted by the bootstrap Job).

## The model key

`agent-runner.proxy.modelKeySecret` (default `agent-runner-model-key`) is an operator-supplied
Secret with one key, `key`: the API key of the model provider named by `modelBase` and
`modelProvider`. Encrypt it with SOPS + age as docs/secrets describes, or create it before the
first apply:

```bash
kubectl -n <namespace> create secret generic agent-runner-model-key --from-file=key=./openrouter-api-key
```

Without it the proxy pod waits in `CreateContainerConfigError` and every run fails at its
first model call.
