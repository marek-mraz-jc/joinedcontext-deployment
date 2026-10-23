# Barcelona, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space barcelona carries (DM-01, DM-61): the open data of Barcelona City Council (Open Data BCN) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per station of the city's air-quality network with the hourly mean of each pollutant it measures; Event holds the city's activity agendas (cultural, daily and sports); PointOfInterest the city's register of facilities (equipaments); batch 3 (T-5264) adds the districts and barris as AdministrativeArea, the works on the public space as CityWork and the street inventory's crossings as PedestrianCrossing; each Open Data BCN batch adds its own classes.

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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a district or barri, a work). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the hour the entity's readings cover, UTC. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `no2` | Property | `float` |  | ug/m3 | `sdm:no2` | Nitrogen dioxide, the hour's mean at the station. |
| `o3` | Property | `float` |  | ug/m3 | `sdm:o3` | Ozone, the hour's mean at the station. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### AdministrativeArea

One district (10) or barri (73) of Barcelona, its outline and its code, as the Smart Data Model extension AdministrativeArea (PointOfInterest base).

IRI: `jc:AdministrativeArea`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a district or barri, a work). |
| `districtCode` | Property | `string` | yes |  | `jc:districtCode` | The city's own two-digit code of the area: the district number 01..10, or for a barri its number 01..73, which runs across the whole city. |
| `divisionLevel` | Property | [`DivisionLevel`](#divisionlevel) | yes |  | `jc:divisionLevel` | Which of the city's two divisions the area belongs to. |
| `refParentDistrict` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refParentDistrict` | The district a barri belongs to. |
| `neighbourhoods` | Relationship | [`AdministrativeArea`](#administrativearea) (list) |  |  | `jc:neighbourhoods` | The barris of this district, computed from their refParentDistrict and never stored. |
| `cityWorks` | Relationship | [`CityWork`](#citywork) (list) |  |  | `jc:cityWorks` | The works that lie in this district only, computed from their refDistrict and never stored. |
| `pedestrianCrossings` | Relationship | [`PedestrianCrossing`](#pedestriancrossing) (list) |  |  | `jc:pedestrianCrossings` | The crossings in this barri, computed from their refNeighbourhood and never stored. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0). |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### CityWork

One work on Barcelona's public space, in execution, stopped or finished within 30 days, with its outline, its dates and its promoter. The constructor is left out.

IRI: `sdm:CityWork`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a district or barri, a work). |
| `description` | Property | `string` |  |  | `schema:description` | The work's description as the city publishes it, in Catalan. |
| `workNumber` | Property | `string` | yes |  | `sdm:workNumber` | The city's code of the work, such as 05-2025G0074 (district, year, number). |
| `workState` | Property | [`WorkState`](#workstate) | yes |  | `sdm:workState` | Where the work stands, in the Smart Data Model's terms. |
| `workStateLabel` | Property | `string` |  |  | `jc:workStateLabel` | The work's state as the city writes it, in Catalan (En execució, Aturada, Finalitzada). |
| `workCategory` | Property | `string` |  |  | `jc:workCategory` | The city's kind of work, in Catalan (Urbanització, Serveis, Clavegueram...). |
| `startDate` | Property | `datetime` | yes |  | `schema:startDate` | The first day, local midnight in Europe/Madrid: of an event (the agenda publishes the day, its hours sit in a free-text timetable) or of a work on the public space. |
| `endDate` | Property | `datetime` | yes |  | `schema:endDate` | The last day, local midnight in Europe/Madrid: of an event (absent when the agenda gives none) or the planned last day of a work on the public space. |
| `contractingAuthority` | Property | `string` |  |  | `sdm:contractingAuthority` | The work's promoter, a public body, utility or company; left out when it may name a person. |
| `tenderAmount` | Property | `float` |  |  | `jc:tenderAmount` | The budget the work was put out to tender with, in euros. |
| `awardAmount` | Property | `float` |  |  | `jc:awardAmount` | The budget the work was awarded for, in euros. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The place of the work as the city writes it (a street and number, a square, a park). |
| `territorialArea` | Property | `string` |  |  | `sdm:territorialArea` | Every district the work touches, by name, separated by "; ". |
| `refDistrict` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refDistrict` | The district the work lies in, when it lies in one district only. |
| `seeAlso` | Property | `uri` |  |  | `sdm:seeAlso` | The work's page on the city's works site. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0). |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PedestrianCrossing

One pedestrian or cycle crossing painted on Barcelona's streets, from the city's street inventory, with its kind, its painted area and its barri. Smart Data Models has no crossing model; the class is the project's own, with SDM's common names where they exist (location, dataProvider, source).

IRI: `jc:PedestrianCrossing`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `crossingType` | Property | [`CrossingType`](#crossingtype) | yes |  | `jc:crossingType` | How the crossing is marked, from the city's typology (infraestructures-tipologia-pas-vianants). |
| `crossingTypeLabel` | Property | `string` |  |  | `jc:crossingTypeLabel` | The crossing's kind as the city writes it, in Catalan (Pas de pastilles, Pas de tacs, Pas de bicicletes). |
| `markedArea` | Property | `float` |  | m2 | `jc:markedArea` | The painted area of the crossing in square metres (unitCode MTK). |
| `refNeighbourhood` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refNeighbourhood` | The barri the crossing lies in; none for a crossing on the city's edge. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, as an application credits it beside the licence (CC BY 4.0). |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### Event

One activity of the Ajuntament's agendas (agenda diària, agenda cultural, agenda d'activitats esportives), the day it starts and ends, where it happens and its category.

IRI: `sdm:Event`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a district or barri, a work). |
| `startDate` | Property | `datetime` | yes |  | `schema:startDate` | The first day, local midnight in Europe/Madrid: of an event (the agenda publishes the day, its hours sit in a free-text timetable) or of a work on the public space. |
| `endDate` | Property | `datetime` |  |  | `schema:endDate` | The last day, local midnight in Europe/Madrid: of an event (absent when the agenda gives none) or the planned last day of a work on the public space. |
| `category` | Property | `string` (list) |  |  | `sdm:category` | An Event's main category first, one of the platform's fifteen event codes (music, theatre-dance, film, exhibition-museum, festival-fair, sport, outdoor-nature, education-talk, children-family, hobby-workshop, food-market, history-heritage, faith-tradition, health-wellness, community-civic), then the Smart Data Models category it falls under where one fits, read from the first words of the Catalan name and absent when no rule matches. A PointOfInterest's family in the city's facility register first (culture-leisure, sports, education, social-services, public-administration, markets-shopping, information-centres, religious-services, environment, animals-plants, cemeteries, media, utility-companies, restaurants), then the register's own kind in Catalan (Biblioteques, Poliesportius). |
| `subCategory` | Property | `string` (list) |  |  | `sdm:subCategory` | The Smart Data Models sub-category where the name says it (music, theater). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the agenda or the facility register publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `contactPoint` | Property | [`ContactPoint`](#contactpoint) |  |  | `schema:contactPoint` | The public telephone line the agenda or the facility register lists. |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PointOfInterest

One facility of the city's register (Guia BCN equipaments): a library, a sports hall, a school, a market, a social services centre; its family, where it is and its telephone.

IRI: `sdm:PointOfInterest`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a district or barri, a work). |
| `category` | Property | `string` (list) |  |  | `sdm:category` | An Event's main category first, one of the platform's fifteen event codes (music, theatre-dance, film, exhibition-museum, festival-fair, sport, outdoor-nature, education-talk, children-family, hobby-workshop, food-market, history-heritage, faith-tradition, health-wellness, community-civic), then the Smart Data Models category it falls under where one fits, read from the first words of the Catalan name and absent when no rule matches. A PointOfInterest's family in the city's facility register first (culture-leisure, sports, education, social-services, public-administration, markets-shopping, information-centres, religious-services, environment, animals-plants, cemeteries, media, utility-companies, restaurants), then the register's own kind in Catalan (Biblioteques, Poliesportius). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | The postal address as the agenda or the facility register publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `contactPoint` | Property | [`ContactPoint`](#contactpoint) |  |  | `schema:contactPoint` | The public telephone line the agenda or the facility register lists. |
| `source` | Property | `uri` |  |  | `sdm:source` | The Open Data BCN dataset the entity was read from. |
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
| `district` | Property | `string` |  |  | `sdm:district` | The city district (districte) the address lies in. |
| `addressCountry` | Property | `string` |  |  | `schema:addressCountry` | The country, as an ISO 3166-1 alpha-2 code. |

### ContactPoint

The value of `contactPoint`: how to reach the organizer, never an entity of its own.

IRI: `schema:ContactPoint`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `telephone` | Property | `string` |  |  | `schema:telephone` | A telephone number as the agenda writes it. |

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

### DivisionLevel

| Value | Meaning |
|---|---|
| `district` | A district (districte), 10 of them. |
| `neighbourhood` | A barri, 73 of them, each inside one district. |

### WorkState

The Smart Data Model CityWork workState values the city's states map to.

| Value | Meaning |
|---|---|
| `open` | In execution (En execució). |
| `other` | Stopped (Aturada). |
| `completed` | Finished (Finalitzada). |

### CrossingType

The three kinds of crossing marking the city's typology names.

| Value | Meaning |
|---|---|
| `stripes` | Painted bars across the road, the zebra crossing (Pas de pastilles). |
| `blocks` | A crossing marked with painted square blocks (Pas de tacs). |
| `cycle` | A crossing for bicycles (Pas de bicicletes). |
