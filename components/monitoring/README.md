# monitoring

Prometheus Operator scrape configuration and edge alerting for the platform (OPS-16, TS-22).

The component deploys no workload. It renders one `ServiceMonitor` per platform component that
exports Prometheus metrics on its Service and has no monitor of its own, and the `PrometheusRule` of the edge runbook.

APISIX is not in the target list: its own chart renders a `ServiceMonitor` for port 9091
(`/apisix/prometheus/metrics`) as soon as metrics are enabled, so a second monitor here would
scrape the edge twice and double every counter. The alert rules are still this component's,
because the chart ships none.

- Enabled by `global.metrics.enabled`. Off, the component renders nothing: scrape configuration
  without a Prometheus watching is dead configuration.
- Every monitor is rendered into the namespace of the component it scrapes and selects that one
  namespace, so a second instance on the same cluster is never scraped by the first one's monitor.
- Ports are named, never numbered. A renamed port breaks the monitor loudly instead of scraping
  whatever now sits on that number.
- Metrics endpoints stay inside the cluster: they carry no APISIX route and no ingress.

Targets and rules live in `values/monitoring/base-values.yaml.gotmpl`; each is guarded by the
component it belongs to, so an instance that omits a component carries no monitor for it.
