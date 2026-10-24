# Prague city data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the Prague city space carries side by side (DM-01, DM-61): the nextbike docking stations and what they hold now, ČHMÚ's hourly air quality at the city's stations, the city districts, the schools, cultural venues, public toilets and sorted-waste points of the city's geoportal (IPR Praha), the park-and-ride car parks and how full they are now, the monitored sorted-waste containers and their fill level and the PID vehicles in service (Golemio), the PID ticket points, and the city budget line by line. One model, one space, one public endpoint. Where Smart Data Models has the class, its IRI is cited rather than minted (DM-04, DM-16).

- Namespace: `https://joinedcontext.com/models/praha/praha-mesto`
- Rendered by: `linkml-1.11.1`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### BikeHireDockingStation

One nextbike station in and around Prague, its docks and what it holds right now.

IRI: `sdm:BikeHireDockingStation`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `totalSlotNumber` | Property | `integer` |  |  | `sdm:totalSlotNumber` | The number of docks the station has. |
| `availableBikeNumber` | Property | `integer` |  |  | `sdm:availableBikeNumber` | Bikes ready to rent at the station right now. |
| `freeSlotNumber` | Property | `integer` |  |  | `sdm:freeSlotNumber` | Empty docks a bike can be returned to right now. |
| `status` | Property | [`StationStatus`](#stationstatus) |  |  | `sdm:status` | Whether the station rents bikes right now. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher's station, counter or sensor last reported the values beside it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AirQualityObserved

One of ČHMÚ's air quality stations in Prague and the hour's means it last published.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the values were observed: the start of the hour the air quality readings average, the time of a vehicle's last position report, or the end of a weather station's newest 10 minutes. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `no2` | Property | `float` |  | ug/m3 | `sdm:no2` | Nitrogen dioxide, the hour's mean at the station. |
| `o3` | Property | `float` |  | ug/m3 | `sdm:o3` | Ozone, the hour's mean at the station. |
| `so2` | Property | `float` |  | ug/m3 | `sdm:so2` | Sulphur dioxide, the hour's mean at the station. |
| `co` | Property | `float` |  | ug/m3 | `sdm:co` | Carbon monoxide, the hour's mean at the station. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PointOfInterest

One place a resident goes to: a school, a cultural venue, a public toilet, a public transport ticket point, a library, a municipal office or police station, a garden, a playground, a waste collection yard, or one of the city's amenities the IPR geoportal maps: a health centre, a university, a place of worship, a community centre, an accommodation, a grocery store, a cool spot, an animal corner, a landmark, a hazardous or bio-waste collection point or a nature trail stop.

IRI: `sdm:PointOfInterest`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `serviceCategory` | Property | [`ServiceCategory`](#servicecategory) | yes |  | `jc:serviceCategory` | Which kind of place it is. |
| `facilityType` | Property | `string` |  |  | `jc:facilityType` | The publisher's own word for the kind of place, such as Mateřská škola or ticketMachine. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The Smart Data Models PostalAddress: the street address as the publisher writes it, one line, in `streetAddress`, and the city and country every Prague source shares. |
| `url` | Property | `uri` |  |  | `schema:url` | The place's own web page. |
| `capacity` | Property | `integer` |  |  | `jc:capacity` | How many pupils the school may take, as the school register states it. |
| `pupilCount` | Property | `integer` |  |  | `jc:pupilCount` | How many pupils the school has, a count the register publishes and never a name. |
| `openingHours` | LanguageProperty | `string` |  |  | `schema:openingHours` | The opening hours, per language, one line per group of days. |
| `wheelchairAccessible` | Property | `boolean` |  |  | `jc:wheelchairAccessible` | Whether the publisher states the place is reachable in a wheelchair; absent when it does not say. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher's station, counter or sensor last reported the values beside it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WasteContainerIsle

One sorted-waste collection point of the city, where its containers stand.

IRI: `sdm:WasteContainerIsle`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `stationCode` | Property | `string` | yes |  | `jc:stationCode` | The collection point's number in the city's waste register, such as 0022/ 001, or the ČHMÚ weather station's WIGOS id, such as 0-20000-0-11518. |
| `accessRestriction` | Property | [`WasteAccess`](#wasteaccess) |  |  | `jc:accessRestriction` | Who may use the collection point. |
| `refDistrict` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refDistrict` | The city district the record lies in. |
| `wasteContainers` | Relationship | [`WasteContainer`](#wastecontainer) (list) |  |  | `jc:wasteContainers` | The monitored containers at this collection point, computed from their refWasteContainerIsle and never stored. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WasteContainer

One sensor-monitored sorted-waste container of the city and how full it is.

IRI: `sdm:WasteContainer`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `containerCode` | Property | `string` | yes |  | `jc:containerCode` | The container's number in the city's waste register (KSNKO). |
| `wasteKind` | Property | [`WasteKind`](#wastekind) | yes |  | `jc:wasteKind` | What the container takes, as the city's waste register sorts it. |
| `fillingLevel` | Property | `float` |  |  | `sdm:fillingLevel` | How full the container was at its sensor's last reading, 0 empty to 1 full. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher's station, counter or sensor last reported the values beside it. |
| `refWasteContainerIsle` | Relationship | [`WasteContainerIsle`](#wastecontainerisle) | yes |  | `sdm:refWasteContainerIsle` | The collection point the container stands at. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### OffStreetParking

One park-and-ride car park at the edge of the city.

IRI: `sdm:OffStreetParking`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `totalSpotNumber` | Property | `integer` |  |  | `sdm:totalSpotNumber` | The number of cars the car park holds. |
| `availableSpotNumber` | Property | `integer` |  |  | `sdm:availableSpotNumber` | The free spaces of the car park right now, as its entry counters report them. |
| `occupiedSpotNumber` | Property | `integer` |  |  | `sdm:occupiedSpotNumber` | The cars parked in the car park right now, as its entry counters report them. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher's station, counter or sensor last reported the values beside it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AdministrativeArea

One of the 57 city districts (městské části) of Prague, its outline and its code, as the Smart Data Model extension AdministrativeArea (PointOfInterest base).

IRI: `jc:AdministrativeArea`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `districtCode` | Property | `string` | yes |  | `jc:districtCode` | The district's RÚIAN code, the key the national registers and the waste register use. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `wasteContainerIsles` | Relationship | [`WasteContainerIsle`](#wastecontainerisle) (list) |  |  | `jc:wasteContainerIsles` | The waste-container isles in this city district, computed from their refDistrict and never stored. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### BudgetLine

One line of the city budget of the City of Prague (Magistrát hl. m. Prahy), in the national budget classification, with the approved and the adjusted amount, as the Smart Data Model extension BudgetLine (CPSV-AP Cost base).

IRI: `jc:BudgetLine`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `identifier` | Property | `string` | yes |  | `sdm:dataModel.CPSV-AP/identifier` | The budget line's own key, the year and its codes of area, function, item and purpose (`mhmp-2026-00-612100-5011-000000000`), the identifier the BudgetLine extension requires. |
| `fiscalYear` | Property | `integer` | yes |  | `jc:fiscalYear` | The budget year. |
| `budgetArea` | Property | `string` |  |  | `jc:budgetArea` | The city's own area of the line (oblast), its code and name joined, such as 09 Školství; absent on a correction line the city files under none. |
| `budgetFunction` | Property | `string` | yes |  | `jc:budgetFunction` | The section of the national budget classification (paragraf, ODPA), code and name. |
| `budgetItem` | Property | `string` | yes |  | `jc:budgetItem` | The item of the national budget classification (položka), code and name. Items 1xxx to 4xxx are revenue, 5xxx and 6xxx expenditure, 8xxx financing. |
| `budgetPurpose` | Property | `string` |  |  | `jc:budgetPurpose` | The earmark of the line (účelový znak), code and name. |
| `approvedAmount` | Property | `float` | yes |  | `jc:approvedAmount` | The amount the council approved, as the city publishes it. The city's documentation names no unit; the 2026 expenditure lines add up to 119 054 085, which is the size of Prague's budget in thousands of CZK. |
| `adjustedAmount` | Property | `float` | yes |  | `jc:adjustedAmount` | The amount after the year's budget changes so far, in the same unit as the approved one. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Vehicle

One PID bus, tram, trolleybus, metro train or train in service in Prague: where it is, its line, where it heads, its next stop and how late it runs (Golemio vehicle positions).

IRI: `sdm:Vehicle`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `vehicleType` | Property | [`VehicleKind`](#vehiclekind) |  |  | `sdm:vehicleType` | The Smart Data Models kind of vehicle (tram, bus, trolley); other for a metro train, a train, a ferry and the funicular, which transportMode names. |
| `category` | Property | [`VehicleCategory`](#vehiclecategory) (list) |  |  | `sdm:category` | The Smart Data Models vehicle category, public and tracked for a PID vehicle in service. |
| `transportMode` | Property | [`TransportMode`](#transportmode) |  |  | `jc:transportMode` | What the line runs, as the GTFS route type names it (tram, metro, train, bus, ferry, funicular, trolleybus). |
| `lineName` | Property | `string` |  |  | `jc:lineName` | The PID line the vehicle runs, its short name (17, A, S9, 331). |
| `direction` | Property | `string` |  |  | `jc:direction` | Where the trip heads, its headsign (Libuš, Dolní Břežany,Zálepy). |
| `nextStop` | Property | `string` |  |  | `jc:nextStop` | The PID (GTFS) id of the stop the vehicle reaches next (U1509Z1). |
| `delay` | Property | `integer` |  | s | `jc:delay` | Seconds behind the timetable, negative when ahead (Golemio's delay.actual). |
| `speed` | Property | `float` |  | km/h | `sdm:speed` | Ground speed of the vehicle in km/h, as Smart Data Models states it; absent when the vehicle does not report one. |
| `heading` | Property | `integer` |  | deg | `sdm:heading` | Where the vehicle points, degrees clockwise from north (0 to 359). |
| `fleetVehicleId` | Property | `string` |  |  | `sdm:fleetVehicleId` | The operator's fleet number of the vehicle (9099); absent for the metro and trains, which report none. |
| `operatorName` | Property | `string` |  |  | `jc:operatorName` | The carrier that runs the vehicle, as PID names it (DP PRAHA, ARRIVA CITY (Kladno)). |
| `wheelchairAccessible` | Property | `boolean` |  |  | `jc:wheelchairAccessible` | Whether the publisher states the place is reachable in a wheelchair; absent when it does not say. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the values were observed: the start of the hour the air quality readings average, the time of a vehicle's last position report, or the end of a weather station's newest 10 minutes. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### EmissionSource

One stationary source of air pollution of the Prague emission register (REZZO 1 or REZZO 2): where it is, its fuel and its yearly emissions, as the Smart Data Model extension EmissionSource (PointOfInterest base). The operator is not read: some are private persons.

IRI: `jc:EmissionSource`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `registerCategory` | Property | [`EmissionRegister`](#emissionregister) | yes |  | `jc:registerCategory` | Which part of the Prague emission register lists the source: REZZO 1 (large stationary sources, rezzo1) or REZZO 2 (medium sources, rezzo2), as IPR Praha publishes them. |
| `fuelType` | Property | `string` |  |  | `jc:fuelType` | The fuel group that dominates the source as the register writes it, such as zemní plyn, nafta or technologie (a process, not a fuel). |
| `pm10Emission` | Property | `float` |  | t/a | `jc:pm10Emission` | The source's yearly emission of PM10, in tonnes a year, as the register states it. |
| `pm25Emission` | Property | `float` |  | t/a | `jc:pm25Emission` | The source's yearly emission of PM2.5, in tonnes a year (REZZO 2 only). |
| `so2Emission` | Property | `float` |  | t/a | `jc:so2Emission` | The source's yearly emission of sulphur dioxide, in tonnes a year. |
| `noxEmission` | Property | `float` |  | t/a | `jc:noxEmission` | The source's yearly emission of nitrogen oxides (NOx), in tonnes a year. |
| `coEmission` | Property | `float` |  | t/a | `jc:coEmission` | The source's yearly emission of carbon monoxide, in tonnes a year. |
| `vocEmission` | Property | `float` |  | t/a | `jc:vocEmission` | The source's yearly emission of volatile organic compounds, in tonnes a year. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The Smart Data Models PostalAddress: the street address as the publisher writes it, one line, in `streetAddress`, and the city and country every Prague source shares. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### RadonRiskArea

One area of Prague's radon risk map and the risk category of its ground, as the Smart Data Model extension RadonRiskArea (PointOfInterest base).

IRI: `jc:RadonRiskArea`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `radonRiskCategory` | Property | [`RadonRisk`](#radonrisk) | yes |  | `jc:radonRiskCategory` | The radon risk category of the ground in the area, as the Czech Geological Survey's radon index map gives it (transitional, low, medium, high). |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### FloodZone

One designated flood area of Prague: the ground a 5, 20, 50 or 100-year flood covers, or a zone of the Vltava and Berounka flood area, as the Smart Data Model extension FloodZone (PointOfInterest base).

IRI: `jc:FloodZone`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `floodReturnPeriod` | Property | `integer` |  |  | `jc:floodReturnPeriod` | The return period of the flood the area is flooded by, in years: 5, 20, 50 or 100 for the designated flood areas Q5, Q20, Q50 and Q100. |
| `floodZoneCategory` | Property | [`FloodZoneCategory`](#floodzonecategory) |  |  | `jc:floodZoneCategory` | The kind of zone of the Vltava and Berounka flood area: the active zone, where water flows through, where it stands, or ground the city or its owners protect. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### FloodDefence

One line of Prague's flood defences: a fixed barrier, a mobile wall or a sandbag line, who keeps it and the flood it is designed for, as the Smart Data Model extension FloodDefence (PointOfInterest base).

IRI: `jc:FloodDefence`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `defenceType` | Property | [`FloodDefenceType`](#flooddefencetype) | yes |  | `jc:defenceType` | The kind of flood defence line, a fixed barrier, a mobile wall or sandbags. |
| `protectedBy` | Property | [`FloodDefenceKeeper`](#flooddefencekeeper) |  |  | `jc:protectedBy` | Who sets the line up and keeps it, the city or the owner of the ground behind it. |
| `designFlood` | Property | [`FloodDesignLevel`](#flooddesignlevel) |  |  | `jc:designFlood` | The flood the line is designed to hold back, the 100-year flood (q100) or the August 2002 flood (flood2002). |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WeatherObserved

One of ČHMÚ's weather stations in Prague and the newest 10-minute values it published.

IRI: `sdm:WeatherObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `stationCode` | Property | `string` | yes |  | `jc:stationCode` | The collection point's number in the city's waste register, such as 0022/ 001, or the ČHMÚ weather station's WIGOS id, such as 0-20000-0-11518. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | When the values were observed: the start of the hour the air quality readings average, the time of a vehicle's last position report, or the end of a weather station's newest 10 minutes. |
| `temperature` | Property | `float` |  | Cel | `sdm:temperature` | The air temperature 2 m above ground, ČHMÚ's newest 10-minute value. |
| `relativeHumidity` | Property | `float` |  | 1 | `sdm:relativeHumidity` | The relative humidity as a fraction (0.57 is 57 %), the newest 10-minute value. |
| `atmosphericPressure` | Property | `float` |  | hPa | `sdm:atmosphericPressure` | The air pressure at the station's height (not reduced to sea level), the newest 10-minute value. |
| `precipitation` | Property | `float` |  | mm | `sdm:precipitation` | The precipitation of the newest 10 minutes, in millimetres (litres per square metre). |
| `windSpeed` | Property | `float` |  | m/s | `sdm:windSpeed` | The mean wind speed 10 m above ground over the newest 10 minutes. |
| `windDirection` | Property | `float` |  | deg | `sdm:windDirection` | The mean wind direction over the newest 10 minutes, in degrees from north. |
| `gustSpeed` | Property | `float` |  | m/s | `sdm:gustSpeed` | The strongest gust of the newest 10 minutes, 10 m above ground. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
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
| `streetAddress` | Property | `string` |  |  | `schema:streetAddress` | The street address line as the publisher writes it. |
| `addressLocality` | Property | `string` |  |  | `schema:addressLocality` | The town, Praha. |
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

### VehicleKind

| Value | Meaning |
|---|---|
| `tram` | A tram. |
| `bus` | A bus. |
| `trolley` | A trolleybus. |
| `other` | A metro train, a train, a ferry or the funicular. |

### VehicleCategory

| Value | Meaning |
|---|---|
| `public` | A public transport vehicle. |
| `tracked` | A vehicle whose position its operator tracks. |

### TransportMode

| Value | Meaning |
|---|---|
| `tram` | Tram (GTFS route type 0). |
| `metro` | Metro (GTFS route type 1). |
| `train` | Train (GTFS route type 2). |
| `bus` | Bus (GTFS route type 3). |
| `ferry` | Ferry (GTFS route type 4). |
| `funicular` | Funicular (GTFS route type 7). |
| `trolleybus` | Trolleybus (GTFS route type 11). |

### StationStatus

| Value | Meaning |
|---|---|
| `working` | The station rents bikes and takes them back. |
| `outOfService` | The station neither rents nor takes back bikes right now. |

### ServiceCategory

| Value | Meaning |
|---|---|
| `school` | A school or a school facility of the city's school register. |
| `culture` | A theatre, a museum, a gallery or another cultural venue. |
| `publicToilet` | A public toilet. |
| `ticketSale` | A place that sells public transport tickets. |
| `library` | A branch of the Municipal Library of Prague. |
| `municipalAuthority` | The office of a city district or of the city (úřad městské části). |
| `police` | A station or desk of the Municipal Police of Prague (Městská policie). |
| `garden` | A public garden or park of the city. |
| `playground` | A public children's playground. |
| `wasteCollectionYard` | A waste collection yard (sběrný dvůr) that takes bulky and hazardous waste. |
| `healthCentre` | A polyclinic or health centre. |
| `university` | A university, faculty or university workplace. |
| `placeOfWorship` | A church, chapel, prayer room or other place of worship. |
| `communityCentre` | A cultural or community centre, a local library, a youth or senior club. |
| `accommodation` | A hotel, guest house, hostel, campsite or other accommodation. |
| `groceryStore` | A full-range grocery store or supermarket. |
| `drinkingFountain` | A public drinking fountain. |
| `fountain` | A fountain or ornamental pool. |
| `spring` | A well or spring. |
| `waterPump` | A public water pump. |
| `mistShower` | A mist shower that cools passers-by in summer. |
| `bathingPlace` | A swimming pool, natural pool or other place to swim. |
| `animalCorner` | A petting zoo, farm, terrarium or animal rescue station. |
| `landmark` | A notable building or place of the city. |
| `wasteCollectionPoint` | A collection point for hazardous waste or bio-waste that is not a collection yard. |
| `trailStop` | A stop of a nature trail. |

### WasteAccess

| Value | Meaning |
|---|---|
| `public` | Anyone may use it (volně). |
| `residents` | Only the residents of the house may use it (obyvatelům domu). |

### WasteKind

| Value | Meaning |
|---|---|
| `colouredGlass` | Coloured glass (barevné sklo). |
| `clearGlass` | Clear glass (čiré sklo). |
| `paper` | Paper (papír). |
| `plastic` | Plastic (plast). |
| `metal` | Metal (kovy). |
| `beverageCartons` | Beverage cartons (nápojové kartony). |
| `electronics` | Small electrical appliances (elektrozařízení). |
| `edibleOil` | Edible fats and oils (jedlé tuky a oleje). |
| `mixedRecyclables` | Paper, plastic and cartons in one container (multikomoditní sběr). |

### EmissionRegister

| Value | Meaning |
|---|---|
| `rezzo1` | REZZO 1, a large stationary source (kategorie 1). |
| `rezzo2` | REZZO 2, a medium stationary source (kategorie 2). |

### RadonRisk

| Value | Meaning |
|---|---|
| `transitional` | Transitional, on variable Quaternary soils (přechodná). |
| `low` | Low (nízká). |
| `medium` | Medium (střední). |
| `high` | High (vysoká). |

### FloodZoneCategory

| Value | Meaning |
|---|---|
| `active` | The active zone, where a flood flows fastest (aktivní). |
| `flowThrough` | Ground the flood flows through (průtočná). |
| `nonFlowThrough` | Ground where the flood water stands (neprůtočná). |
| `protectedByCity` | Ground the city's flood defences protect (určená k ochraně městem). |
| `protectedIndividually` | Ground its owners protect themselves (určená k ochraně individuálně). |

### FloodDefenceType

| Value | Meaning |
|---|---|
| `unknown` | The register does not say (neznámo). |
| `fixed` | A fixed barrier or wall (pevné opatření). |
| `mobileWall` | A mobile wall put up before a flood (mobilní stěna). |
| `sandbags` | A line of sandbags (pytle s pískem). |

### FloodDefenceKeeper

| Value | Meaning |
|---|---|
| `city` | The city sets it up and keeps it (zajišťovaná městem). |
| `individual` | The owner of the ground behind it does (zajišťovaná individuálně). |

### FloodDesignLevel

| Value | Meaning |
|---|---|
| `q100` | The 100-year flood (Q100). |
| `flood2002` | The level of the August 2002 flood (Q2002). |
