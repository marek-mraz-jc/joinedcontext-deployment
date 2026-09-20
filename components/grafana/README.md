# grafana

Operational dashboards for the edge, the gateway surfaces, the Portal and the broker
(OPS-16, ADR-N-011).

An add-on, not a core component: it is deployed only where an environment lists it
(`components:` in `deployment/environments/<env>/global.yaml.gotmpl`, docs Deployment/04
section 2), and even then only where a Prometheus is named. `.ci/example-deployments/environments/addons`
is the worked example and the render this component is tested against.

- **It deploys no Prometheus and does not want to.** The monitoring component writes scrape
  configuration and alert rules for an Operator that is already on the cluster; this reads the
  same Prometheus back. `grafana.grafana.prometheusUrl` is that address, and the render is
  refused without it rather than serving a login page in front of panels that all say "No data".
- **Nothing is authored here.** The datasource and all four dashboards are provisioned from
  files in this repository and marked non-editable, so a dashboard is changed by a merge
  request like everything else (CC-02). One replica and no volume follow from that: what a
  restart loses is what nobody wrote down.
- **The dashboards are a ConfigMap of this component's own** (`charts/dashboards`), mounted
  through `dashboardsConfigMaps`. The chart's own `dashboards:` values would work too, and add
  an init container that curls each dashboard: one more image to pin, running a shell script
  with nothing to fetch.
- **Login is the realm's** (`keycloak-clients.yaml`): authorization code with PKCE, the local
  form disabled, `platform-admin` mapped to Admin and everyone else to Viewer. The generated
  `grafana-admin` Secret exists for the hour when Keycloak is the thing that is broken.
- **The browser's hop to the realm is public, the pod's is not.** `auth_url` is
  `idm.{domain}`; the code exchange and the userinfo call take the in-cluster Service, which is
  the split the gateway already makes between its issuer and its JWKS URL.

## What the dashboards read

| Dashboard | Source | Notes |
|---|---|---|
| Edge — APISIX | `apisix_http_status`, `apisix_http_latency_bucket`, `apisix_yaml_configuration_load_status` | The 5xx panel draws the expression `APISIXHigh5xxRate` fires on; the load-status panel is the failure nothing else reports (docs Deployment/10 section 7) |
| Context Gateway — traffic | `jc_gateway_requests_total`, `jc_gateway_request_duration_seconds`, `jc_gateway_pdp_decisions_total`, `jc_gateway_broker_request_duration_seconds`, plus `apisix_http_status` for the last two panels | The gateway's own since T-0463. The two only it can answer are the policy verdict and the broker round trip; the edge panels stay because APISIX is the only place that sees a request the gateway never received (T-0464) |
| Portal — traffic and proposals | `jc_portal_requests_total`, `jc_portal_request_duration_seconds`, `jc_portal_changes_total`, plus `apisix_http_status` | The lane a change was classified into is known only inside the Portal (CC-63) |
| Context Broker — Antares | `antares_http_requests_total`, `antares_http_request_duration_seconds`, `antares_notifications_*`, `antares_pg_*` | The broker serves these at `/q/metrics` |

## Checklist

- [x] Runs as non-root (472:472) with `readOnlyRootFilesystem`; `/tmp` and the log directory
      are emptyDirs, and so is the data directory
- [x] Health probes — the chart's `/api/health`
- [x] Standard labels — the chart's
- [x] ServiceAccount with least privilege — no RBAC, no API access, no mounted token
- [x] Published through APISIX with TLS at the edge (`apisix-routes.yaml`), never an Ingress
      of its own
- [x] Image pinned by digest (`images.yaml`)

## Reading a duration

Every `*_duration_seconds` on this platform is a Prometheus **histogram**, so a latency panel
is written `histogram_quantile(0.95, sum(rate(<series>_bucket[5m])) by (le, route))`. A summary
would export a quantile already computed inside one replica, and two replicas' quantiles cannot
be combined — the p95 of a gateway the HPA has scaled to three pods would be whichever pod
Prometheus labelled last. `tests/test_grafana.py` refuses a panel that reads `quantile=`.
