# Helsinki city context

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the Helsinki demonstration space carries side by side (DM-01, DM-09): the events of the city's Linked Events register, the HSL city bike docking stations, the HSL buses of four trunk lines, HSL's stops, stations, lines and their shapes, the city's news, Fintraffic's road weather stations and its traffic alerts, FMI's air quality stations, and the city's open registers: its services (libraries, health stations, swimming halls, beaches, schools), the beach water sensors, parking areas and zones, the permits for digging, traffic arrangements and events on public areas, and its district division. One model, one space, four endpoints that each publish a slice of it. The IRIs are Smart Data Models' and ETSI's, cited rather than minted, so a reader who knows those vocabularies reads the same terms here (DM-04, DM-16).

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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the source publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent, never guessed from a line of text. |
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
| `status` | Property | `string` |  |  | `sdm:status` | A bike station's working while it rents and takes returns, otherwise outOfService; a park and ride site's open, closed or closedAbnormal (Fintraffic LIIPI's IN_OPERATION, INACTIVE or TEMPORARILY_CLOSED, EXCEPTIONAL_SITUATION). |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher last changed the record, or the station last reported. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Vehicle

One HSL bus, tram, metro, train or ferry in service, where it is, how fast it moves and how late it runs.

IRI: `sdm:Vehicle`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `speed` | Property | `float` |  | m/s | `sdm:speed` | Ground speed of the vehicle. |
| `heading` | Property | `float` |  | deg | `sdm:heading` | Compass heading of the vehicle, degrees clockwise from north. |
| `route` | Property | `string` |  |  | `sdm:route` | The HSL route id the vehicle is serving, as GTFS names it (2550, 1009, 31M1, 3001K). |
| `vehicleType` | Property | `string` |  |  | `sdm:vehicleType` | The Smart Data Models kind of vehicle - bus, tram, passengerVessel for a ferry, other for metro and train; transportMode names HSL's mode. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What serves the stop or runs the line. |
| `fleetVehicleId` | Property | `string` |  |  | `sdm:fleetVehicleId` | The operator and vehicle number HSL publishes, operator-vehicle. |
| `onRoute` | Relationship | `uriorcurie` |  |  | `jc:onRoute` | The line the vehicle is running, the URN of a GtfsRoute of this space. |
| `nextStop` | Relationship | `uriorcurie` |  |  | `jc:nextStop` | The stop the vehicle stands at or comes to next, the URN of a GtfsStop of this space; HSL moves it on at each departure from or passing of a stop. |
| `delay` | Property | `integer` |  | s | `jc:delay` | Seconds behind the timetable, negative when ahead (HSL's dl with the sign turned). |
| `occupancy` | Property | `integer` |  | % | `jc:occupancy` | How full the vehicle is, in percent; HSL sends 0 (room) or 100 (full). |
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
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the readings were taken. |
| `temperature` | Property | `float` |  | Cel | `sdm:temperature` | The temperature the station measures: the air at a road weather station, the water at a beach sensor. |
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

One road work or traffic announcement of Fintraffic in the capital region, or one service alert of HSL with the lines and stops it affects.

IRI: `sdm:Alert`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `category` | Property | `string` |  |  | `sdm:category` | The alert's domain; traffic for everything Fintraffic and HSL publish. |
| `subCategory` | Property | `string` |  |  | `sdm:subCategory` | The Smart Data Models code of the alert, roadWorks for a Fintraffic road work. Left out where no code fits: a Fintraffic traffic announcement and an HSL service alert. |
| `alertSource` | Property | `string` |  |  | `sdm:alertSource` | Who raised the alert, Fintraffic or HSL. |
| `effect` | Property | `string` |  |  | `jc:effect` | What an HSL service alert does to the service, as GTFS-RT names it, such as DETOUR or REDUCED_SERVICE. |
| `cause` | Property | `string` |  |  | `jc:cause` | Why an HSL service alert is in force, as GTFS-RT names it, such as CONSTRUCTION or MAINTENANCE. |
| `severity` | Property | `string` |  |  | `sdm:severity` | How much the alert matters, informational, medium or high (GTFS-RT INFO, WARNING, SEVERE). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the source publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent, never guessed from a line of text. |
| `dateIssued` | Property | `datetime` |  |  | `sdm:dateIssued` | When the situation was published. |
| `validFrom` | Property | `datetime` |  |  | `sdm:validFrom` | When the situation starts. |
| `validTo` | Property | `datetime` |  |  | `sdm:validTo` | When the situation ends; absent while open-ended. |
| `refRoute` | Relationship | [`GtfsRoute`](#gtfsroute) (list) |  |  | `jc:refRoute` | The lines an HSL service alert affects, each a GtfsRoute of this space. |
| `refStop` | Relationship | [`GtfsStop`](#gtfsstop) (list) |  |  | `jc:refStop` | The stops an HSL service alert affects, each a GtfsStop of this space. |
| `unknownReference` | Property | `string` (list) |  |  | `jc:unknownReference` | What an HSL service alert names that this space holds no entity for, as `route:<id>` or `stop:<id>`, kept as text rather than as a relationship that would point at nothing. |
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
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the readings were taken. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `airQualityIndex` | Property | `float` |  |  | `sdm:airQualityIndex` | FMI's hourly air quality index, 1 (good) to 5 (very poor). |
| `stewardNote` | Property | `string` |  |  | `jc:stewardNote` | A note by the person who keeps this data: what was checked, what looks wrong, whom to ask. No pipeline writes it and no pipeline overwrites it, so an application may offer it for editing without the next run taking the words back (AP-62). At most 500 characters and no angle brackets, because it is a note and not a document. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PointOfInterest

One place of the city's service register a resident goes to: a library, a health station, a swimming hall, a beach or a school. The register's contact lines are left out, because they can name a person.

IRI: `sdm:PointOfInterest`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `serviceCategory` | Property | [`ServiceCategory`](#servicecategory) | yes |  | `jc:serviceCategory` | Which of the city's services the place is, from the service register's own codes. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the source publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent, never guessed from a line of text. |
| `url` | Property | `uri` |  |  | `schema:url` | Where the item is published in full. |
| `openingHours` | LanguageProperty | `string` |  |  | `schema:openingHours` | The opening hours as the city's service register words them, per language. Free text, because the register writes exceptions and self-service hours no fixed shape holds. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher last changed the record, or the station last reported. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `waterQualityObservations` | Relationship | [`WaterQualityObserved`](#waterqualityobserved) (list) |  |  | `jc:waterQualityObservations` | The water-quality readings taken at this place, computed from their refPointOfInterest and never stored. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WaterQualityObserved

One of Forum Virium Helsinki's beach sensors and the water temperature it last read. A sensor that has not reported this season carries no reading.

IRI: `sdm:WaterQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `temperature` | Property | `float` |  | Cel | `sdm:temperature` | The temperature the station measures: the air at a road weather station, the water at a beach sensor. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the readings were taken. |
| `refPointOfInterest` | Relationship | [`PointOfInterest`](#pointofinterest) |  |  | `sdm:refPointOfInterest` | The place in the city's service register the sensor stands at. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### ParkingArea

One parking area of the city's parking guide, its outline and the number of cars it holds when the city has estimated it.

IRI: `jc:ParkingArea`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `totalSpotNumber` | Property | `integer` |  |  | `sdm:totalSpotNumber` | The number of vehicles the site holds, as the publisher states or estimates it; for a park and ride site, of its own kind (car or bicycle). |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### OffStreetParking

One park and ride site of the HSL area from Fintraffic's LIIPI register (T-3894), where it is, what it holds, whether it is open, the free spaces when it reports them, and its station.

IRI: `sdm:OffStreetParking`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `status` | Property | `string` |  |  | `sdm:status` | A bike station's working while it rents and takes returns, otherwise outOfService; a park and ride site's open, closed or closedAbnormal (Fintraffic LIIPI's IN_OPERATION, INACTIVE or TEMPORARILY_CLOSED, EXCEPTIONAL_SITUATION). |
| `allowedVehicleType` | Property | `string` (list) |  |  | `sdm:allowedVehicleType` | What may park, the site's own kind first (car or bicycle), then motorcycle where it has spaces for them. |
| `totalSpotNumber` | Property | `integer` |  |  | `sdm:totalSpotNumber` | The number of vehicles the site holds, as the publisher states or estimates it; for a park and ride site, of its own kind (car or bicycle). |
| `capacityByType` | JsonProperty | `string` |  |  | `jc:capacityByType` | The built capacity per kind of space, as LIIPI names them in lower case (car, disabled, bicycle, electricCar, motorcycle, bicycleSecureSpace), each a count. |
| `availableSpotNumber` | Property | `integer` |  |  | `sdm:availableSpotNumber` | Free spaces at the park and ride site when it last reported, LIIPI's spacesAvailable. |
| `refNearestStation` | Relationship | [`GtfsStation`](#gtfsstation) |  |  | `jc:refNearestStation` | The HSL station within 500 m of the park and ride site, the nearest one, a GtfsStation of this space. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### ParkingZone

One parking fee zone or resident parking zone of the city, its outline and its rules.

IRI: `jc:ParkingZone`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `zoneKind` | Property | [`ParkingZoneKind`](#parkingzonekind) | yes |  | `jc:zoneKind` | Whether the zone sets the parking fee or the residents' and businesses' permits. |
| `zoneCode` | Property | `string` | yes |  | `jc:zoneCode` | The zone's own code, a fee zone number or a resident permit letter, as the signs show it. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `url` | Property | `uri` |  |  | `schema:url` | Where the item is published in full. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PublicAreaPermit

One permit of the city's public-area register: an excavation, a temporary traffic arrangement or an event, with every area it covers as one outline. The applicant and the contractor are left out, because they can name a person.

IRI: `jc:PublicAreaPermit`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `permitKind` | Property | [`PermitKind`](#permitkind) | yes |  | `jc:permitKind` | What the permit lets its holder do on the public area. |
| `permitNumber` | Property | `string` | yes |  | `jc:permitNumber` | The application number the city's permit register gives the permit, such as KP1900206-23. |
| `permitStatus` | Property | [`PermitStatus`](#permitstatus) | yes |  | `jc:permitStatus` | Where the permitted work or event stands today. |
| `permitStart` | Property | `date` | yes |  | `jc:permitStart` | The first day the permit covers. |
| `permitEnd` | Property | `date` | yes |  | `jc:permitEnd` | The last day the permit covers. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the source publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent, never guessed from a line of text. |
| `refDistrict` | Relationship | [`CityDistrict`](#citydistrict) |  |  | `jc:refDistrict` | The district the record lies in. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### CityDistrict

One district or sub-district of Helsinki, its outline and its code.

IRI: `jc:CityDistrict`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `districtCode` | Property | `string` | yes |  | `jc:districtCode` | The city's own code of the area: the district number, or for a sub-district the full ten-digit code the city's statistics use for it. |
| `divisionLevel` | Property | [`DivisionLevel`](#divisionlevel) | yes |  | `jc:divisionLevel` | Which of the city's two divisions the area belongs to. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `publicAreaPermits` | Relationship | [`PublicAreaPermit`](#publicareapermit) (list) |  |  | `jc:publicAreaPermits` | The public-area permits that lie in this district, computed from their refDistrict and never stored. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### GtfsStop

One HSL stop or station platform, where it is, its sign's code and its fare zone.

IRI: `sdm:GtfsStop`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `stopCode` | Property | `string` |  |  | `jc:stopCode` | The code on the stop's sign, such as H2014; empty for a stop HSL gives none. |
| `description` | LanguageProperty | `string` |  |  | `schema:description` | A short description, per language. |
| `fareZone` | Property | `string` |  |  | `jc:fareZone` | The HSL fare zone the stop lies in, A to D; none for a stop beyond HSL's zones. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What serves the stop or runs the line. |
| `wheelChairAccessible` | Property | `string` |  |  | `sdm:wheelChairAccessible` | Whether a wheelchair can board here, GTFS's wheelchair_boarding; 0 unknown, 1 possible, 2 not possible. |
| `hasParentStation` | Relationship | [`GtfsStation`](#gtfsstation) |  |  | `sdm:hasParentStation` | The station the stop or platform belongs to; absent for a stop on its own. |
| `departures` | JsonProperty | `string` |  |  | `jc:departures` | The next departures from the stop, at most five, soonest first, each an object with the line (`route`, the GtfsRoute's id, and `routeId`), its `directionId`, the `expected` time and its `status` (scheduled, skipped or canceled), and `delay` in seconds with the `scheduled` time it implies when HSL sends one. Set every 30 s for a curated set of stops from HSL's GTFS-RT trip updates; empty after five minutes without a feed. |
| `stopAlerts` | Relationship | [`Alert`](#alert) (list) |  |  | `jc:stopAlerts` | The HSL service alerts on the stop, computed from their refStop and never stored. |
| `page` | Property | `uri` |  |  | `sdm:page` | The publisher's web page about it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### TransitRoute

One HSL line in one direction: its number, where it runs to, its stops in order and the line through them. A line with several variants has one entity per variant.

IRI: `jc:TransitRoute`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `route` | Property | `string` |  |  | `sdm:route` | The HSL route id the vehicle is serving, as GTFS names it (2550, 1009, 31M1, 3001K). |
| `routeShortName` | Property | `string` |  |  | `jc:routeShortName` | The line number riders see, such as 4 or 550. |
| `headsign` | Property | `string` |  |  | `jc:headsign` | Where the line runs to in this direction, as its sign shows it. |
| `directionId` | Property | `integer` |  |  | `jc:directionId` | HSL's direction of the line, 1 or 2. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What serves the stop or runs the line. |
| `stopSequence` | Property | `string` (list) |  |  | `jc:stopSequence` | The stops the line serves in this direction, in order, each the GTFS stop id that ends the id of a GtfsStop of this space. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### GtfsStation

One HSL station (GTFS location type 1), where it is and the platforms it gathers.

IRI: `sdm:GtfsStation`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `fareZone` | Property | `string` |  |  | `jc:fareZone` | The HSL fare zone the stop lies in, A to D; none for a stop beyond HSL's zones. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What serves the stop or runs the line. |
| `wheelChairAccessible` | Property | `string` |  |  | `sdm:wheelChairAccessible` | Whether a wheelchair can board here, GTFS's wheelchair_boarding; 0 unknown, 1 possible, 2 not possible. |
| `hasStop` | Relationship | [`GtfsStop`](#gtfsstop) (list) |  |  | `sdm:hasStop` | The platforms of the station, computed from their hasParentStation and never stored. |
| `nearbyParking` | Relationship | [`OffStreetParking`](#offstreetparking) (list) |  |  | `jc:nearbyParking` | The park and ride sites whose nearest station this is, computed from their refNearestStation and never stored. |
| `page` | Property | `uri` |  |  | `sdm:page` | The publisher's web page about it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### GtfsAgency

The transit agency HSL's GTFS feed names, HSL itself.

IRI: `sdm:GtfsAgency`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `agencyName` | Property | `string` |  |  | `sdm:agencyName` | The transit agency's full name. |
| `page` | Property | `uri` |  |  | `sdm:page` | The publisher's web page about it. |
| `timezone` | Property | `string` |  |  | `sdm:timezone` | The agency's time zone, an IANA name such as Europe/Helsinki. |
| `language` | Property | `string` |  |  | `sdm:language` | The agency's main language, a two-letter code. |
| `phone` | Property | `string` |  |  | `sdm:phone` | The agency's public customer service number. |
| `routes` | Relationship | [`GtfsRoute`](#gtfsroute) (list) |  |  | `jc:routes` | The lines the agency operates, computed from their operatedBy and never stored. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### GtfsRoute

One HSL line as GTFS gives it, both directions and every variant: its number, its name, what runs it and who operates it. Its stops in order are TransitRoute's.

IRI: `sdm:GtfsRoute`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `shortName` | Property | `string` |  |  | `sdm:shortName` | The line number riders see, such as 4 or 550. |
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `routeType` | Property | `string` |  |  | `sdm:routeType` | GTFS's basic route type: 0 a tram, 1 the metro, 2 a train, 3 a bus, 4 a ferry. HSL's extended codes (109, 700s, 900) are written as the basic one they extend. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What serves the stop or runs the line. |
| `operatedBy` | Relationship | [`GtfsAgency`](#gtfsagency) |  |  | `sdm:operatedBy` | The agency that runs the line. |
| `routeAlerts` | Relationship | [`Alert`](#alert) (list) |  |  | `jc:routeAlerts` | The HSL service alerts on the line, computed from their refRoute and never stored. |
| `page` | Property | `uri` |  |  | `sdm:page` | The publisher's web page about it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### GtfsShape

The line one HSL route variant draws on the map, about 200 of its points, and the distance travelled at each.

IRI: `sdm:GtfsShape`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language. |
| `distanceTravelled` | Property | `float` (list) |  |  | `sdm:distanceTravelled` | The distance along the shape at each point of its line, in kilometres. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0 for every feed of this space). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PostalAddress

The value of `address`: a postal address, never an entity of its own (Smart Data Models' common schema).

IRI: `schema:PostalAddress`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `streetAddress` | Property | `string` |  |  | `schema:streetAddress` | The street and the house number. |
| `postalCode` | Property | `string` |  |  | `schema:postalCode` | The postal code. |
| `addressLocality` | Property | `string` |  |  | `schema:addressLocality` | The town or the municipality. |
| `addressCountry` | Property | `string` |  |  | `schema:addressCountry` | The country, as an ISO 3166-1 alpha-2 code. |

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

### ServiceCategory

| Value | Meaning |
|---|---|
| `library` | A public library. |
| `healthStation` | A health station. |
| `swimmingHall` | An indoor swimming hall. |
| `beach` | A public beach. |
| `school` | A comprehensive school. |

### ParkingZoneKind

| Value | Meaning |
|---|---|
| `fee` | The zone sets what parking costs by the hour. |
| `resident` | Residents and businesses of the zone park on its permit. |

### PermitKind

| Value | Meaning |
|---|---|
| `excavation` | Digging on a street or a park. |
| `trafficArrangement` | A temporary change to traffic, such as a closed lane. |
| `event` | An event held on a public area. |

### PermitStatus

| Value | Meaning |
|---|---|
| `upcoming` | Granted and not started. |
| `ongoing` | The work or the event is going on. |
| `setup` | The event's structures are being built. |
| `teardown` | The event's structures are being taken down. |

### DivisionLevel

| Value | Meaning |
|---|---|
| `district` | A district (kaupunginosa), 60 of them. |
| `subDistrict` | A sub-district (osa-alue), the unit the city's statistics use. |

### TransportMode

| Value | Meaning |
|---|---|
| `bus` | A bus. |
| `tram` | A tram. |
| `metro` | The metro. |
| `train` | A commuter train. |
| `ferry` | A ferry. |
