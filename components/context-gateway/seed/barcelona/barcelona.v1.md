# Barcelona, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space barcelona carries (DM-01, DM-61): the open data of Barcelona City Council (Open Data BCN) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per station of the city's air-quality network with the hourly mean of each pollutant it measures; each Open Data BCN batch adds its own classes. Transport: TrafficFlowObserved, the traffic state of each street section the city reports every five minutes, and OnStreetParking, each regulated surface parking section (blue, green, loading and bus zones).

- Namespace: `https://joinedcontext.com/models/barcelona/barcelona`
- Rendered by: `linkml-1.12.0`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### AirQualityObserved

One air-quality station of Barcelona and its hourly means.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name the city publishes, in Catalan (a station, a street section and its stretch, a street address). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The time the entity's readings refer to, UTC (an air-quality hour's end, a traffic state's report). |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `no2` | Property | `float` |  | ug/m3 | `sdm:no2` | Nitrogen dioxide, the hour's mean at the station. |
| `o3` | Property | `float` |  | ug/m3 | `sdm:o3` | Ozone, the hour's mean at the station. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### TrafficFlowObserved

One street section of the city's traffic-state network with its line, its state now and the state forecast for 15 minutes, every five minutes (Open Data BCN trams and transit-relacio-trams).

IRI: `sdm:TrafficFlowObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name the city publishes, in Catalan (a station, a street section and its stretch, a street address). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The time the entity's readings refer to, UTC (an air-quality hour's end, a traffic state's report). |
| `congested` | Property | `boolean` |  |  | `sdm:congested` | Whether the section is congested now: true for the city's states 4 (very dense) and 5 (congestion), false otherwise, as SDM reads an absent flag (no data and closed included; trafficState tells those apart). |
| `trafficState` | Property | [`TrafficState`](#trafficstate) |  |  | `jc:trafficState` | The city's own traffic state of the section (custom: TrafficFlowObserved has only `congested`), its code 1 to 6 named in English; Open Data BCN dataset trams. |
| `trafficStateForecast` | Property | [`TrafficState`](#trafficstate) |  |  | `jc:trafficStateForecast` | The state the city forecasts for the section in 15 minutes, same codes as trafficState (custom). |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### OnStreetParking

One regulated surface parking section of B:SM (blue, green, residents, loading or coach zone), its curb lines, its places and its rate and timetable codes (Open Data BCN trams-aparcament-superficie).

IRI: `sdm:OnStreetParking`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name the city publishes, in Catalan (a station, a street section and its stretch, a street address). |
| `category` | Property | [`StreetParkingCategory`](#streetparkingcategory) (list) |  |  | `sdm:category` | The kind of regulated parking, from the section type (AZL blue zone, VM green zone, VR residents, DUM loading, BUS coaches). |
| `allowedVehicleType` | Property | `string` (list) |  |  | `sdm:allowedVehicleType` | What may park there, the section's own kind first. |
| `totalSpotNumber` | Property | `integer` |  |  | `sdm:totalSpotNumber` | The parking places of the section as B:SM counts them (PLACES). |
| `zoneCode` | Property | `string` |  |  | `jc:zoneCode` | The section type as B:SM codes it (AZL, VM, VR, DUM, BUS), kept as published (custom). |
| `tariffCode` | Property | `string` |  |  | `jc:tariffCode` | The B:SM rate (ID_TARIFA) and timetable (ID_HORARIO) codes of the section, joined as rate/timetable, kept as published (custom; Open Data BCN tarifes- and horaris-aparcament-superficie). |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
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

## Enumerations

### TrafficState

Open Data BCN's traffic state codes 0 to 6, named in English, the Catalan name in each description.

| Value | Meaning |
|---|---|
| `noData` | 0 sense dades: no reading this period. |
| `veryFluid` | 1 molt fluid. |
| `fluid` | 2 fluid. |
| `dense` | 3 dens. |
| `veryDense` | 4 molt dens. |
| `congestion` | 5 congestió. |
| `closed` | 6 tallat. |

### StreetParkingCategory

The OnStreetParking `category` values the B:SM section types map to, a subset of the Smart Data Model's enum.

| Value | Meaning |
|---|---|
| `blueZone` | AZL, the blue zone anyone parks in for a fee. |
| `greenZone` | VM and VR, the green zone. |
| `feeCharged` | Parking costs by the time parked (AZL, VM, BUS). |
| `forResidents` | VR, residents of the area only. |
| `forLoadUnload` | DUM, urban goods distribution. |
| `onlyWithPermit` | VR and DUM, a resident permit or the DUM app registration is needed. |
