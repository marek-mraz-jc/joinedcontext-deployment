# demo-feeds

A demo NATS broker and live feed publisher for the `dev` cluster (T-0477, PL-50).
This is a demonstration broker for development only — it is not a platform component
and must never be deployed to production.

It provides a lightweight NATS server and a generator stream so that a `nats`
`DataSource` on dev has data to read end to end without external broker infrastructure.

## Parts

- **nats**: A stateless NATS broker (`demo-nats`) running in-memory without persistence or JetStream.
- **feed**: A Bento publisher (`demo-feed`) that emits a counter reading to the broker on a configured interval.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `demo-feeds.nats.enabled` | `true` | Enable the demo NATS broker. |
| `demo-feeds.nats.namespace` | `<demo-feeds namespace>` | Namespace for the NATS broker deployment. |
| `demo-feeds.feed.enabled` | `true` | Enable the demo feed publisher. |
| `demo-feeds.feed.namespace` | `<demo-feeds namespace>` | Namespace for the feed publisher deployment. |
| `demo-feeds.feed.subject` | `helsinki.demo.counters` | NATS subject to which readings are published. |
| `demo-feeds.feed.interval` | `10s` | Interval between published messages. |

## How a DataSource reads it

A pipeline's `DataSource` manifest reads the published readings using the runner's native `nats` input:

```yaml
spec:
  type: nats
  input:
    urls: [ "nats://demo-nats.dev.svc.cluster.local:4222" ]
    subject: helsinki.demo.counters
```
