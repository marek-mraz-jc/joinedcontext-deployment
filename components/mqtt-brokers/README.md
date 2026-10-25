# mqtt-brokers

The MQTT edge brokers of the projects (`docs/Decisions/adr-n-048-mqtt-edge-brokers.md`,
MF-54, PL-74, PL-76, PL-77): RMQTT 0.24.0 as published, one Deployment per `MqttBroker`,
named `mqtt-{project}-{name}`. That name is also the broker's ServiceAccount, so its mesh
identity, and its Keycloak audience.

A broker keeps nothing. Each CONNECT goes to the gateway's `POST /internal/mqtt/auth` on
port 8082 (rmqtt-auth-http, `deny_if_error`); the answer carries the client's subscriptions and
the end of its session, the token's `exp` or its credential's `expiresAt`, whichever comes
first. Each publish topic goes to `POST /internal/mqtt/acl`, which decides it against the
repository as it is now; the broker keeps an allow for 10 s (`X-Cache`) and disconnects a client
whose publish is refused, so a device whose role or account is removed stops within about 10 s
(T-5560). The broker's own last rule, `["deny", "all"]`, refuses whatever the gateway did not
allow. No retainer, no session or message storage, sessions end with the connection.

| Port | Listener | Who reaches it |
|---|---|---|
| 1883 | `internal`, plain MQTT | the pipeline runner only (NetworkPolicy and a Linkerd Server) |
| 1884 | `external`, PROXY protocol v2 | the ingress controller only |
| 8883 | Traefik entrypoint `mqtts`, TLS | devices, `HostSNI(<name>.<project>.mqtt.<domain>)`, one HTTP-01 certificate per host |
| 6060 | RMQTT HTTP API, under the mesh only | the Portal's identity, `GET /api/v1/metrics/history/sum` and `GET /api/v1/clients` only (Linkerd `Server` + `HTTPRoute`, ADR-N-048 §2.8, T-4043) |

RMQTT opens TLS, WebSocket and QUIC listeners on its own; the chart turns each of them off, and
binds the cluster gRPC to loopback. Its HTTP API runs only where the instance runs the mesh and
names the Portal; elsewhere the chart turns it off too and the Portal shows "not measured".

`brokers` is empty in every environment: the Portal's reconciler stamps one broker per
`MqttBroker` manifest (T-3994). The chart renders a broker's objects once more with sentinels
(`__RELEASE__`, `__PROJECT__`, `__NAME__`, `__MAX_BYTES__`, `__PER_SECOND__`, `__CONNECTIONS__`,
`__CONFIG_HASH__`) into the ConfigMap `broker-template`; the Portal fills them from the manifest,
applies the objects by server-side apply with `app.kubernetes.io/managed-by: joinedcontext-portal`,
and deletes those of a broker whose manifest is gone. The Role `portal-mqtt-brokers` lets it do
that here and nowhere else, and `JC_PORTAL_MQTT_NAMESPACE` tells it where. An entry under
`mqtt-brokers.brokers.brokers` still runs one by hand, from the same template.

## Preconditions on the cluster

The `mqtts` entrypoint is part of the cluster's Traefik, not of this repository: an entrypoint
on 8883, published on the node with `externalTrafficPolicy: Local`, and its container port in
Traefik's `config.linkerd.io/skip-inbound-ports`. Without the last one, Traefik sees every
client as 127.0.0.1, writes that into the PROXY header, and the gateway reads a device as a
client inside the cluster.

## Not here yet

- A dedicated `port` (18830-18849) per broker: on the node behind klipper and the Linkerd
  inbound proxy, the broker would see every such client as a loopback address.
- A per-publisher rate: RMQTT 0.24 has none. `messagesPerSecond` caps delivery to each
  subscriber (`mqueue_rate_limit`).
