# Prague city data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the Prague city space carries side by side (DM-01, DM-61): the nextbike docking stations and what they hold now, ČHMÚ's hourly air quality at the city's stations, the city districts, the schools, cultural venues, public toilets and sorted-waste points of the city's geoportal (IPR Praha), the park-and-ride car parks and how full they are now, the monitored sorted-waste containers and their fill level (Golemio), the PID ticket points, and the city budget line by line. One model, one space, one public endpoint. Where Smart Data Models has the class, its IRI is cited rather than minted (DM-04, DM-16).

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
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | The start of the hour the readings average. |
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

One place a resident goes to: a school, a cultural venue, a public toilet or a public transport ticket point.

IRI: `sdm:PointOfInterest`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `serviceCategory` | Property | [`ServiceCategory`](#servicecategory) | yes |  | `jc:serviceCategory` | Which kind of place it is. |
| `facilityType` | Property | `string` |  |  | `jc:facilityType` | The publisher's own word for the kind of place, such as Mateřská škola or ticketMachine. |
| `address` | Property | `string` |  |  | `schema:address` | The street address, one line, as the publisher writes it. |
| `url` | Property | `uri` |  |  | `schema:url` | The place's own web page. |
| `capacity` | Property | `integer` |  |  | `jc:capacity` | How many pupils the school may take, as the school register states it. |
| `pupilCount` | Property | `integer` |  |  | `jc:pupilCount` | How many pupils the school has, a count the register publishes and never a name. |
| `openingHours` | LanguageProperty | `string` |  |  | `schema:openingHours` | The opening hours, per language, one line per group of days. |
| `wheelchairAccessible` | Property | `boolean` |  |  | `jc:wheelchairAccessible` | Whether the publisher states the place is reachable in a wheelchair; absent when it does not say. |
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
| `stationCode` | Property | `string` | yes |  | `jc:stationCode` | The collection point's number in the city's waste register, such as 0022/ 001. |
| `accessRestriction` | Property | [`WasteAccess`](#wasteaccess) |  |  | `jc:accessRestriction` | Who may use the collection point. |
| `refDistrict` | Relationship | [`CityDistrict`](#citydistrict) |  |  | `jc:refDistrict` | The city district the record lies in. |
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

### CityDistrict

One of the 57 city districts (městské části) of Prague, its outline and its code.

IRI: `jc:CityDistrict`

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

One line of the city budget of the City of Prague (Magistrát hl. m. Prahy), in the national budget classification, with the approved and the adjusted amount.

IRI: `jc:BudgetLine`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
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
