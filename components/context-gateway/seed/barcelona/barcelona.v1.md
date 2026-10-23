# Barcelona, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space barcelona carries (DM-01, DM-61): the open data of Barcelona City Council (Open Data BCN) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per station of the city's air-quality network with the hourly mean of each pollutant it measures; each Open Data BCN batch adds its own classes.

- Namespace: `https://joinedcontext.com/models/barcelona/barcelona`
- Rendered by: `linkml-1.12.0`
- License: https://joinedcontext.com/licenses/cc-by-4.0

## Classes

### PostalAddress

The value of `address`: a postal address, never an entity of its own (Smart Data Models' common schema).

IRI: `schema:PostalAddress`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `streetAddress` | Property | `string` |  |  | `schema:streetAddress` | The square, park or street corner of the station. |
| `addressLocality` | Property | `string` |  |  | `schema:addressLocality` | The municipality. |
| `district` | Property | `string` |  |  | `sdm:district` | The city district (districte) the station is in. |
| `addressCountry` | Property | `string` |  |  | `schema:addressCountry` | The country, as an ISO 3166-1 alpha-2 code. |

### AirQualityObserved

One air-quality station of Barcelona and its hourly means.

IRI: `sdm:AirQualityObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the city publishes it (Catalan for the stations). |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station stands, as the city describes it (Smart Data Models' common PostalAddress). |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file the entity was read from. |
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
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the city publishes it (Catalan for the stations). |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station stands, as the city describes it (Smart Data Models' common PostalAddress). |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file the entity was read from. |
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
| `name` | LanguageProperty | `string` |  |  | `schema:name` | The name, per language, as the city publishes it (Catalan for the stations). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading. |
| `measurementType` | Property | [`MeasurementType`](#measurementtype) (list) |  |  | `sdm:measurementType` | What the well's readings measure; `depth` for each of the city's wells. |
| `waterTable` | Property | `float` |  | m | `sdm:waterTable` | The depth from the surface to the water in the well at the newest reading. |
| `piezometricLevel` | Property | `float` |  | m | `jc:piezometricLevel` | The height of the water above sea level at the newest reading (below 0 where the sea draws the aquifer down). A property of this model: PhreaticObserved has only the depth. |
| `investigationDepth` | Property | `float` |  |  | `sdm:investigationDepth` | The depth of the well or piezometer in metres. A fixed property of the well, written without a unit code so its rows are never read as a measurement stamped on receipt. |
| `aquifer` | Property | `string` |  |  | `jc:aquifer` | The groundwater body (massa d'aigua) the well reaches, as the water agency names it. |
| `stationCode` | Property | `string` |  |  | `jc:stationCode` | The station's code in the network that runs it: the Catalan air-quality network (XVPCA, the city's codi_eoi, such as `8019043`), the Meteocat weather network (such as `D5`) or the Catalan water agency's well register (ACA, such as `08019-0148`). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station stands, as the city describes it (Smart Data Models' common PostalAddress). |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | The neighbourhood (barri) the station or well is in, as the city names it. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file the entity was read from. |
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

### MeasurementType

What a PhreaticObserved measures (Smart Data Models' enum).

| Value | Meaning |
|---|---|
| `depth` |  |
| `volume` |  |
| `quality` |  |
| `other` |  |
