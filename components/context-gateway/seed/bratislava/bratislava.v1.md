# Bratislava, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space bratislava carries (DM-01, DM-61): the open data of the City of Bratislava (data.bratislava.sk) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per air-quality station in the city with the PM10 concentration the city publishes for it; each batch of the ranked matrix adds its own classes: the city districts, places and services, and the hub's district tables as key performance indicators (T-5274).

- Namespace: `https://joinedcontext.com/models/bratislava/bratislava`
- Rendered by: `linkml-1.12.0`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### AirQualityObserved

One air-quality station of Bratislava and its PM10 mean.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name of the station, district, place or indicator as the city publishes it. |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's reading covers, UTC. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the period's mean at the station. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AdministrativeArea

One of the 17 city districts (mestské časti) of Bratislava, its outline and its ZÚJ code, as the Smart Data Model extension AdministrativeArea (PointOfInterest base).

IRI: `jc:AdministrativeArea`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name of the station, district, place or indicator as the city publishes it. |
| `districtCode` | Property | `string` | yes |  | `jc:districtCode` | The district's ZÚJ code (základná územná jednotka), the key the national registers use. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The hub page of the dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PointOfInterest

One place a resident goes to: a barrier-free place, a lifelong-learning provider, a needle drop point or a service for homeless people, with its own coordinates from the hub.

IRI: `sdm:PointOfInterest`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name of the station, district, place or indicator as the city publishes it. |
| `category` | Property | `string` (list) |  |  | `sdm:category` | The kind of place (its table's code first, then the table's own word, such as `barrier-free`, `Kultúra, kostoly`), or of indicator (`quantitative`). |
| `description` | Property | `string` |  |  | `schema:description` | What the place offers or how it is reached, or the hub table an indicator comes from. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The Smart Data Models PostalAddress of the place, its street, district and city. |
| `url` | Property | `uri` |  |  | `schema:url` | The place's own web page. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The hub page of the dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### KeyPerformanceIndicator

One figure of one hub table for one city district and one period: a count, a rate or an area, such as the offences the city police recorded in Nové Mesto in 2025.

IRI: `sdm:KeyPerformanceIndicator`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name of the station, district, place or indicator as the city publishes it. |
| `description` | Property | `string` |  |  | `schema:description` | What the place offers or how it is reached, or the hub table an indicator comes from. |
| `process` | Property | `string` |  |  | `sdm:process` | What the indicator counts or measures, in the hub's words, with its unit. |
| `category` | Property | `string` (list) |  |  | `sdm:category` | The kind of place (its table's code first, then the table's own word, such as `barrier-free`, `Kultúra, kostoly`), or of indicator (`quantitative`). |
| `kpiValue` | Property | `float` |  |  | `sdm:kpiValue` | The figure for the district and period, as the hub's table states it. |
| `calculationPeriod` | Property | [`KpiPeriod`](#kpiperiod) |  |  | `sdm:calculationPeriod` | The period the figure covers, its first and last day. |
| `calculationFrequency` | Property | `string` |  |  | `sdm:calculationFrequency` | How often the hub publishes the figure (yearly, quarterly, every five years). |
| `area` | Property | `string` |  |  | `sdm:area` | The city district the figure describes, by its name. |
| `organization` | Property | `string` |  |  | `sdm:organization` | The body the figure describes, the City of Bratislava. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The hub page of the dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PostalAddress

The value of `address`: a postal address, never an entity of its own (Smart Data Models' common schema).

IRI: `schema:PostalAddress`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `streetAddress` | Property | `string` |  |  | `schema:streetAddress` | The street and number as the publisher writes them. |
| `district` | Property | `string` |  |  | `sdm:district` | The city district (mestská časť) as the publisher writes it. |
| `addressLocality` | Property | `string` |  |  | `schema:addressLocality` | The city, Bratislava. |
| `addressCountry` | Property | `string` |  |  | `schema:addressCountry` | The country, as an ISO 3166-1 alpha-2 code. |

### KpiPeriod

The value of `calculationPeriod`, never an entity of its own.

IRI: `jc:KpiPeriod`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `from` | Property | `date` | yes |  | `sdm:from` | The first day of the period. |
| `to` | Property | `date` | yes |  | `sdm:to` | The last day of the period. |

### Entity

The root every NGSI-LD entity class specialises.

IRI: `ngsi-ld:Entity`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |
