# probes

Synthetic probes of every public surface, through the public hosts, every minute (T-5103).

One pod per cluster (`probe`, Python standard library on the official slim image) probes its own
environment and each `peers` entry, so a cluster that is down entirely still goes red on the other
one: dev probes smartcity and smartcity probes dev.

## What it checks

Per target and minute, at most `budget` requests (default 120, under the edge's 300 a minute per
address), paced evenly:

| Surface | Request | Holds when |
|---|---|---|
| catalogue | `package_search?rows=1` on the CKAN host | `success` and a count above 0 |
| assistant | `/api/v1/d/{assistantId}/config` (no model call) | a config with `publicId` |
| ngsi-ld | `entities?type={T}&limit=1&count=true` | one entity and `NGSILD-Results-Count` above 0 |
| odata | `odata/v4/{T}?$top=1` | a row in `value` |
| ogc | `ogc/features/collections/{T}/items?limit=1` | a GeoJSON FeatureCollection with a Feature |
| sta | `sta/v1.1/Things?$top=1` | a Thing with `@iot.id` |
| csv | `file.csv`, first 64 KiB | `text/csv`, an `id` column and a row |
| ical | `ical/v1/events.ics` | `BEGIN:VCALENDAR` with a `VEVENT` |
| mcp | `POST mcp` `tools/list` | named tools |
| websocket | `ws` upgrade, subprotocol `ngsi-ld-ws` | `101` and an `x-welcome` first message |

The public Endpoints come from the catalogue's `endpoint` extra; each Endpoint's record lists the
surfaces it serves (`dcat:distribution`), and `ngsi-ld/v1/types` gives the type `{T}`. A record is
read again every `discoverySeconds` (900). Each surface kind probes its next Endpoints round robin:
a kind broken everywhere is red in the first minute; one Endpoint's surface within
`ceil(endpoints x kinds / budget)` minutes (about 6 for 80 Endpoints at 120).

Decided (worker-t5103, owner may override): round robin under a per-target budget instead of every
Endpoint surface every minute, because 80 public Endpoints with 8 surfaces each are 640 requests a
minute, twice the edge's per-address limit; options: every surface every minute (trips the limit
visitors share), one Endpoint per kind (misses a single broken Endpoint for good).

## Results

- `GET :9100/metrics`: `jc_probe_up`, `jc_probe_duration_seconds`, `jc_probe_timestamp_seconds`
  per target, Endpoint and surface; `jc_probe_surface_failing` per target and surface;
  `jc_probe_round_timestamp_seconds` per target. The monitoring component scrapes it and alerts
  `ProbeSurfaceDown` (`jc_probe_up == 0` for 1 minute) and `ProbeStalled`.
- Since T-5104 also `jc_probe_failures_total` and the histogram `jc_probe_request_duration_seconds`
  per target and surface (the SLO's events), and, checked once an hour from the same outside view,
  `jc_probe_tls_cert_expiry_timestamp_seconds` per host (0 when the certificate fails verification)
  and `jc_probe_domain_expiry_timestamp_seconds` per registered domain (RDAP, its server from
  IANA's bootstrap list at data.iana.org).
- `GET :9100/results.json`: the newest result per check with its reason, for the status page
  (T-5102) and the health log (T-5067). A reason is the probe's own sentence, never a response body.
- `GET :9100/healthz`: 503 when a target finished no round for three minutes (the liveness probe).

## Security

Anonymous only: no token, no Secret, no `envFrom`. Every URL is built from the https origins in
`PROBE_TARGETS`, never taken from an answer, except the RDAP server, which the hourly expiry check
takes from IANA's bootstrap answer (https only, no redirects, body capped); redirects are not followed. Egress is 443 to public
addresses and the ingress controller, and CoreDNS; ingress only from Prometheus on 9100.
