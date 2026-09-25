# Open data of Banská Bystrica

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the city's public space carries side by side (DM-01, DM-61): the events the city announces, every school and school facility of the national school map in the city, and the hourly particulate readings of the city's urban-background station as the European Environment Agency republishes them. One model, one space, one public endpoint. Where Smart Data Models has the class, its IRI is cited rather than minted (DM-04, DM-16).

- Namespace: `https://joinedcontext.com/models/banskabystrica/banskabystrica-verejne`
- Rendered by: `linkml-1.11.1`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### Event

One event the city announces on its web site, where and when it takes place.

IRI: `schema:Event`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `startDate` | Property | `date` | yes |  | `schema:startDate` | The day the event starts, in the city's local calendar. |
| `startTime` | Property | `string` |  |  | `jc:startTime` | The time the event starts, local time in Banská Bystrica (Europe/Bratislava), `HH:MM`. |
| `endDate` | Property | `date` |  |  | `schema:endDate` | The day the event ends, in the city's local calendar. |
| `endTime` | Property | `string` |  |  | `jc:endTime` | The time the event ends, local time in Banská Bystrica (Europe/Bratislava), `HH:MM`. |
| `eventCategory` | Property | [`EventCategory`](#eventcategory) | yes |  | `jc:eventCategory` | The kind of event, from the city's own categories. |
| `address` | Property | `string` |  |  | `schema:address` | The street address or the venue, one line, as the publisher writes it. |
| `url` | Property | `string` |  |  | `schema:url` | The web page the publisher gives for it. |
| `dateModified` | Property | `datetime` |  |  | `sdm:dateModified` | When the publisher last changed the record. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### School

One school or school facility in the city, from the national school map: its pupils, its staff and its budget, counts only.

IRI: `jc:School`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `schoolCode` | Property | `string` | yes |  | `jc:schoolCode` | The school's EDUID in the national register of schools and school facilities. |
| `address` | Property | `string` |  |  | `schema:address` | The street address or the venue, one line, as the publisher writes it. |
| `url` | Property | `string` |  |  | `schema:url` | The web page the publisher gives for it. |
| `teachingLanguage` | Property | `string` |  |  | `jc:teachingLanguage` | The language of instruction, in the register's words. |
| `pupilCount` | Property | `integer` |  |  | `jc:pupilCount` | How many pupils or children the school or facility has, a count and never a name. |
| `teachingStaff` | Property | `float` |  |  | `jc:teachingStaff` | Teaching staff, in full-time equivalents. |
| `nonTeachingStaff` | Property | `float` |  |  | `jc:nonTeachingStaff` | Non-teaching staff, in full-time equivalents. |
| `annualBudget` | Property | `float` |  |  | `jc:annualBudget` | The school's budget for `budgetYear`, in euro. |
| `budgetYear` | Property | `integer` |  |  | `jc:budgetYear` | The year `annualBudget` is for, as the school map's column names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for, as an application shows it beside the data. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data service the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AirQualityObserved

One air-quality station in the city and the latest hourly means it reported.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the publisher writes it. |
| `stationCode` | Property | `string` | yes |  | `jc:stationCode` | The station's EoI code in the European air-quality network, such as `SK0263A`. |
| `dateObserved` | Property | `datetime` |  |  | `sdm:dateObserved` | The end of the latest hour a reading of the entity covers. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
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

### EventCategory

| Value | Meaning |
|---|---|
| `musicDanceTheatre` | Music, dance and theatre (Hudba, tanec, divadlo). |
| `museumsGalleriesLibraries` | Museums, galleries and libraries (Múzeá, galérie, knižnice). |
| `sport` | Sport (Športové). |
| `exhibition` | Exhibitions (Výstavy). |
| `other` | Any other event (Iné podujatia). |
