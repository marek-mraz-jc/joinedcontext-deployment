# Helsinki hub

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

The types the hub answers for, each registered from the space that holds it: Vehicle from the city context, KeyPerformanceIndicator from the indicator space. The IRIs are those spaces' models' own, so a reader of the hub reads the same terms (DM-61).

- Namespace: `https://hel.fi/models/helsinki/helsinki-hub`
- Rendered by: `linkml-1.11.1`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### Vehicle

One HSL bus on a trunk line, registered from the helsinki space.

IRI: `sdm:Vehicle`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `speed` | Property | `float` |  | m/s | `sdm:speed` | Ground speed of the bus. |
| `heading` | Property | `float` |  | deg | `sdm:heading` | Compass heading of the bus, degrees clockwise from north. |
| `route` | Property | `string` |  |  | `sdm:route` | The HSL route id the bus is serving, four digits with the municipality prefix. |
| `vehicleType` | Property | `string` |  |  | `sdm:vehicleType` | The kind of vehicle; bus on every entity of this space. |
| `fleetVehicleId` | Property | `string` |  |  | `sdm:fleetVehicleId` | The operator and vehicle number HSL publishes, operator-vehicle. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### KeyPerformanceIndicator

One computed indicator, registered from the helsinki-kpi space.

IRI: `jc:KeyPerformanceIndicator`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` | yes |  | `jc:name` | The indicator's own name, equal to the `{localId}` of its id, so the territory is legible without parsing the URN. |
| `currentValue` | Property | `string` | yes |  | `jc:currentValue` | The number, with its unit on the Property as `unitCode`, a UN/CEFACT common code, and the instant it describes as `observedAt`. A window with no reading in it carries the string `not measured` instead of a number, and never a zero: a zero reads as a measurement (Development/10 §5). |
| `calculationPeriod` | Property | `string` | yes |  | `jc:calculationPeriod` | The window the value actually covers, as `{ start, end }` RFC 3339 instants. It is the window the pipeline used and not the one it was asked for, so the distance between `calculationPeriod.end` and `updatedAt` is how stale the source is. |
| `calculationFormula` | Property | `string` | yes |  | `jc:calculationFormula` | How the value was computed, in words a reader can check the number against: the measure, the aggregation, the window and any divisor, such as `per km² of the district's own area`. |
| `derivedFrom` | Relationship | `string` | yes |  | `jc:derivedFrom` | The Endpoint the sources were read through, as its URN. The endpoint and not the space: what an indicator could see is what that endpoint's policy let it see. |
| `computedBy` | Relationship | `string` | yes |  | `jc:computedBy` | The Pipeline that computed it, as its URN. |
| `updatedAt` | Property | `datetime` | yes |  | `jc:updatedAt` | When the pipeline last ran, as an NGSI-LD DateTime. It is the run and not the window: an indicator whose source stopped moving keeps its window and gains a newer `updatedAt`, which is the visible fact that the source is static. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Entity

The root every NGSI-LD entity class specialises.

IRI: `ngsi-ld:Entity`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |
