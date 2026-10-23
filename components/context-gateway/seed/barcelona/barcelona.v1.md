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
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading. |
| `pm10` | Property | `float` |  | ug/m3 | `sdm:pm10` | Particulate matter up to 10 µm, the hour's mean at the station. |
| `pm25` | Property | `float` |  | ug/m3 | `sdm:pm25` | Particulate matter up to 2.5 µm, the hour's mean at the station. |
| `no2` | Property | `float` |  | ug/m3 | `sdm:no2` | Nitrogen dioxide, the hour's mean at the station. |
| `o3` | Property | `float` |  | ug/m3 | `sdm:o3` | Ozone, the hour's mean at the station. |
| `so2` | Property | `float` |  | ug/m3 | `sdm:so2` | Sulphur dioxide, the hour's mean at the station. |
| `co` | Property | `float` |  | mg/m3 | `sdm:co` | Carbon monoxide, the hour's mean at the station, in mg/m³ as the city measures it. |
| `no` | Property | `float` |  | ug/m3 | `sdm:no` | Nitrogen monoxide, the hour's mean at the station. |
| `nox` | Property | `float` |  | ug/m3 | `sdm:nox` | Nitrogen oxides (NO + NO2 as NO2), the hour's mean at the station. |
| `blackCarbon` | Property | `float` |  | ug/m3 | `jc:blackCarbon` | Black carbon, the hour's mean at the station. A property of this model: the Smart Data Model AirQualityObserved names no black carbon attribute. The city's file gives it in ng/m³ under a µg/m³ label; the pipeline divides by 1000. |
| `stationCode` | Property | `string` |  |  | `jc:stationCode` | The station's code in the network that runs it: the Catalan air-quality network (XVPCA, the city's codi_eoi, such as `8019043`), the Meteocat weather network (such as `D5`) or the Catalan water agency's well register (ACA, such as `08019-0148`). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event or the facility is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### WeatherObserved

One Meteocat weather station in Barcelona and its newest day's values.

IRI: `sdm:WeatherObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan. |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading. |
| `temperature` | Property | `float` |  | Cel | `sdm:temperature` | The day's mean air temperature at the station. |
| `maxTemperature` | Property | `float` |  | Cel | `jc:maxTemperature` | The day's highest air temperature at the station. A property of this model: the Smart Data Model WeatherObserved names only the mean. |
| `minTemperature` | Property | `float` |  | Cel | `jc:minTemperature` | The day's lowest air temperature at the station. A property of this model: the Smart Data Model WeatherObserved names only the mean. |
| `relativeHumidity` | Property | `float` |  | 1 | `sdm:relativeHumidity` | The day's mean relative humidity, as a fraction (0.57 is 57 %). |
| `atmosphericPressure` | Property | `float` |  | hPa | `sdm:atmosphericPressure` | The day's mean air pressure at the station's height (not reduced to sea level). |
| `precipitation` | Property | `float` |  | mm | `sdm:precipitation` | The day's precipitation, in millimetres (litres per square metre). |
| `windSpeed` | Property | `float` |  | m/s | `sdm:windSpeed` | The day's mean wind speed at 10 m. |
| `windDirection` | Property | `float` |  | deg | `sdm:windDirection` | The day's mean wind direction at 10 m, in degrees from north. |
| `gustSpeed` | Property | `float` |  | m/s | `sdm:gustSpeed` | The day's strongest gust at 10 m. |
| `solarRadiation` | Property | `float` |  | W/m2 | `sdm:solarRadiation` | The day's mean global solar irradiance: the day's irradiation the city gives in MJ/m², times 10^6 / 86400. |
| `stationCode` | Property | `string` |  |  | `jc:stationCode` | The station's code in the network that runs it: the Catalan air-quality network (XVPCA, the city's codi_eoi, such as `8019043`), the Meteocat weather network (such as `D5`) or the Catalan water agency's well register (ACA, such as `08019-0148`). |
| `altitude` | Property | `float` |  |  | `jc:altitude` | The station's height above sea level in metres, as the weather service lists it. A fixed property of the station, written without a unit code so its rows are never read as a measurement stamped on receipt. |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event or the facility is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PhreaticObserved

One piezometer or well of Barcelona and its newest groundwater reading.

IRI: `sdm:PhreaticObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan. |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading. |
| `measurementType` | Property | [`MeasurementType`](#measurementtype) (list) |  |  | `sdm:measurementType` | What the well's readings measure; `depth` for each of the city's wells. |
| `waterTable` | Property | `float` |  | m | `sdm:waterTable` | The depth from the surface to the water in the well at the newest reading. |
| `piezometricLevel` | Property | `float` |  | m | `jc:piezometricLevel` | The height of the water above sea level at the newest reading (below 0 where the sea draws the aquifer down). A property of this model: PhreaticObserved has only the depth. |
| `investigationDepth` | Property | `float` |  |  | `sdm:investigationDepth` | The depth of the well or piezometer in metres. A fixed property of the well, written without a unit code so its rows are never read as a measurement stamped on receipt. |
| `aquifer` | Property | `string` |  |  | `jc:aquifer` | The groundwater body (massa d'aigua) the well reaches, as the water agency names it. |
| `stationCode` | Property | `string` |  |  | `jc:stationCode` | The station's code in the network that runs it: the Catalan air-quality network (XVPCA, the city's codi_eoi, such as `8019043`), the Meteocat weather network (such as `D5`) or the Catalan water agency's well register (ACA, such as `08019-0148`). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event or the facility is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event or the facility is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `contactPoint` | Property | [`ContactPoint`](#contactpoint) |  |  | `schema:contactPoint` | The public telephone line the agenda or the facility register lists. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event or the facility is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `contactPoint` | Property | [`ContactPoint`](#contactpoint) |  |  | `schema:contactPoint` | The public telephone line the agenda or the facility register lists. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### PostalAddress

The value of `address`: a postal address, never an entity of its own (Smart Data Models' common schema).

IRI: `schema:PostalAddress`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `streetAddress` | Property | `string` |  |  | `schema:streetAddress` | The street and the house number, or for a station its square, park or street corner. |
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

### MeasurementType

What a PhreaticObserved measures (Smart Data Models' enum).

| Value | Meaning |
|---|---|
| `depth` |  |
| `volume` |  |
| `quality` |  |
| `other` |  |
