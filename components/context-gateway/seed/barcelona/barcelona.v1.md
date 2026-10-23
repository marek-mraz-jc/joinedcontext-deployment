# Barcelona, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space barcelona carries (DM-01, DM-61): the open data of Barcelona City Council (Open Data BCN) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per station of the city's air-quality network with the hourly mean of each pollutant it measures; Event holds the city's activity agendas (cultural, daily and sports); PointOfInterest the city's register of facilities (equipaments); each Open Data BCN batch adds its own classes.

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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan. |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the hour the entity's readings cover, UTC. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `no2` | Property | `float` |  | ug/m3 | `sdm:no2` | Nitrogen dioxide, the hour's mean at the station. |
| `o3` | Property | `float` |  | ug/m3 | `sdm:o3` | Ozone, the hour's mean at the station. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan. |
| `startDate` | Property | `datetime` | yes |  | `schema:startDate` | The first day of the event, local midnight in Europe/Madrid; the agenda publishes the day, its hours sit in a free-text timetable. |
| `endDate` | Property | `datetime` |  |  | `schema:endDate` | The last day of the event, local midnight in Europe/Madrid; absent when the agenda gives none. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan. |
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
