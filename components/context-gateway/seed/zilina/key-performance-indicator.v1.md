# One computed indicator (`key-performance-indicator` 1.0.0)

The model the indicator spaces of `bbsk` and `banskabystrica` publish, generated from
`key-performance-indicator.linkml.yaml`. One class, `KeyPerformanceIndicator`, specialising the
shared `Entity` of `ngsi-ld-core`. It states the contract the platform already enforces:
`schemas/kinds/KeyPerformanceIndicator.json` closes the object and requires every attribute
below (Development/10 §4).

| Attribute | NGSI-LD kind | Range | Unit | IRI |
|---|---|---|---|---|
| `id` | Property | uri | | `ngsi-ld:hasId` |
| `type` | Property | string | | `ngsi-ld:hasType` |
| `location` | GeoProperty | GeoJSON geometry | | `geojson:geometry` |
| `observedAt` | Property | datetime | | `ngsi-ld:observedAt` |
| `name` | Property | string | | `jc:name` |
| `currentValue` | Property | number or string | on the Property as `unitCode` | `jc:currentValue` |
| `calculationPeriod` | Property | `{ start, end }` | RFC 3339 instants | `jc:calculationPeriod` |
| `calculationFormula` | Property | string | | `jc:calculationFormula` |
| `derivedFrom` | Relationship | uri | | `jc:derivedFrom` |
| `computedBy` | Relationship | uri | | `jc:computedBy` |
| `updatedAt` | Property | datetime | | `jc:updatedAt` |

All seven own attributes are required, as are `id` and `type`.

`state` and `threshold` are absent by decision. A threshold is the judgement of whoever reads the
number: it changes without the number changing, and two departments may hold different ones for
the same indicator. It lives in the configuration of the view, and the lane a view paints is what
that view computes from the value and its own threshold. An entity carrying either is rejected by
`jc-core` and by the gateway before it is stored.

The territory is the last segment of `{localId}`, and therefore of `name`. There is no attribute
for it: the region has roughly eight times the city's population, so the same question gives two
very different answers and the territory is what separates them (Development/11 §1).

A window with no reading in it carries `not measured` in `currentValue.value` and keeps its
`calculationPeriod`. It is never a zero — a zero reads as a measurement, and an empty 24-hour
mean shown as one reads as clean air (Development/10 §5).
