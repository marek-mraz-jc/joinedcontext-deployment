# Helsinki city context

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the Helsinki demonstration space carries side by side (DM-01, DM-09): the events of the city's Linked Events register, the HSL city bike docking stations, the HSL buses of four trunk lines, the city's news, Fintraffic's road weather stations and its traffic alerts, and FMI's air quality stations. One model, one space, four endpoints that each publish a slice of it. The IRIs are Smart Data Models' and ETSI's, cited rather than minted, so a reader who knows those vocabularies reads the same terms here (DM-04, DM-16).

- Namespace: `https://hel.fi/models/helsinki/helsinki`
- Rendered by: `linkml-1.11.1`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### Event

One event of the City of Helsinki's Linked Events register.

IRI: `sdm:Event`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `startDate` | Property | `datetime` |  |  | `schema:startDate` | When the event starts, ISO 8601 with a time zone. |
| `endDate` | Property | `datetime` |  |  | `schema:endDate` | When the event ends; absent while the register does not say. |
| `eventStatus` | Property | `string` |  |  | `schema:eventStatus` | The register's status of the event, EventScheduled, EventCancelled or EventPostponed. |
| `address` | Property | `string` |  |  | `schema:address` | The street address of the venue, one line. |
| `contactPoint` | Property | `string` |  |  | `schema:contactPoint` | The organizer's contact line as the register carries it, often a named person with a phone number. The space keeps it for the city's own coordination; no public endpoint serves it. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### BikeHireDockingStation

One HSL city bike station, its position and what it holds right now.

IRI: `sdm:BikeHireDockingStation`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `availableBikeNumber` | Property | `integer` |  |  | `sdm:availableBikeNumber` | Bikes ready to rent at the station right now. |
| `freeSlotNumber` | Property | `integer` |  |  | `sdm:freeSlotNumber` | Empty docks a bike can be returned to right now. |
| `totalSlotNumber` | Property | `integer` |  |  | `sdm:totalSlotNumber` | Bikes plus free docks, the station's working size. |
| `status` | Property | `string` |  |  | `sdm:status` | working while the station rents and takes returns, otherwise outOfService. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the station last reported. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Vehicle

One HSL bus on a trunk line, where it is and how fast it moves.

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

### NewsArticle

One item of the City of Helsinki's news feed.

IRI: `schema:NewsArticle`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `url` | Property | `uri` |  |  | `schema:url` | Where the item is published in full. |
| `datePublished` | Property | `datetime` |  |  | `schema:datePublished` | When the item was published, ISO 8601 with a time zone. |
| `image` | Property | `uri` |  |  | `schema:image` | The item's picture, when the feed carries one. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WeatherObserved

One Fintraffic road weather station around Helsinki and its latest readings.

IRI: `sdm:WeatherObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the station's readings were taken. |
| `temperature` | Property | `float` |  | Cel | `sdm:temperature` | Air temperature at the station. |
| `roadSurfaceTemperature` | Property | `float` |  | Cel | `sdm:roadSurfaceTemperature` | Temperature of the road surface at the station. |
| `relativeHumidity` | Property | `float` |  |  | `sdm:relativeHumidity` | Relative humidity of the air, 0 to 1. |
| `windSpeed` | Property | `float` |  | m/s | `sdm:windSpeed` | Mean wind speed at the station. |
| `windDirection` | Property | `float` |  | deg | `sdm:windDirection` | Where the wind comes from, degrees clockwise from north. |
| `precipitation` | Property | `float` |  | mm/h | `sdm:precipitation` | Precipitation intensity at the station, millimetres per hour. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Alert

One road work or traffic announcement of Fintraffic in the capital region.

IRI: `sdm:Alert`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `category` | Property | `string` |  |  | `sdm:category` | The alert's domain; traffic for everything Fintraffic publishes. |
| `subCategory` | Property | `string` |  |  | `sdm:subCategory` | Fintraffic's situation type, ROAD_WORK or TRAFFIC_ANNOUNCEMENT. |
| `address` | Property | `string` |  |  | `schema:address` | The street address of the venue, one line. |
| `dateIssued` | Property | `datetime` |  |  | `sdm:dateIssued` | When the situation was published. |
| `validFrom` | Property | `datetime` |  |  | `sdm:validFrom` | When the situation starts. |
| `validTo` | Property | `datetime` |  |  | `sdm:validTo` | When the situation ends; absent while open-ended. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AirQualityObserved

One air quality station around Helsinki and its newest hourly readings: FMI's stations, and the stations a steward adds by hand, which carry no source.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the station's readings were taken. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `airQualityIndex` | Property | `float` |  |  | `sdm:airQualityIndex` | FMI's hourly air quality index, 1 (good) to 5 (very poor). |
| `stewardNote` | Property | `string` |  |  | `jc:stewardNote` | A note by the person who keeps this data: what was checked, what looks wrong, whom to ask. No pipeline writes it and no pipeline overwrites it, so an application may offer it for editing without the next run taking the words back (AP-62). At most 500 characters and no angle brackets, because it is a note and not a document. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
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
