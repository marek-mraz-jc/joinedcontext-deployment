# Barcelona, open data

<!-- Generated from the LinkML source by Model Tools. Do not edit: `jcctl model
     generate` overwrites this file and CI fails on any difference (DM-01, DM-02). -->

What the space barcelona carries (DM-01, DM-61): the open data of Barcelona City Council (Open Data BCN) as Smart Data Models types, their IRIs cited rather than minted (DM-04, DM-16). The first type is AirQualityObserved, one entity per station of the city's air-quality network with the hourly mean of each pollutant it measures; Event holds the city's activity agendas (cultural, daily and sports); PointOfInterest the city's register of facilities (equipaments); each Open Data BCN batch adds its own classes. Transport: TrafficFlowObserved, the traffic state of each street section and each route of sections the city reports every five minutes, OnStreetParking, each regulated surface parking section (blue, green, loading and bus zones), and EVChargingStation, each public charging point of the Endolla Barcelona network with its live socket states. Urbanism: the districts and barris as AdministrativeArea, the works on the public space as CityWork and the street inventory's crossings as PedestrianCrossing. Statistics: the city's statistics per barri, district and city as KeyPerformanceIndicator.

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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading, a traffic state's report, a charging point's newest port change. |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | Where the entity is as the city names it: the barri of a station or well, the place of a work (a street and number, a square, a park). |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading, a traffic state's report, a charging point's newest port change. |
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
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | Where the entity is as the city names it: the barri of a station or well, the place of a work (a street and number, a square, a park). |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading, a traffic state's report, a charging point's newest port change. |
| `measurementType` | Property | [`MeasurementType`](#measurementtype) (list) |  |  | `sdm:measurementType` | What the well's readings measure; `depth` for each of the city's wells. |
| `waterTable` | Property | `float` |  | m | `sdm:waterTable` | The depth from the surface to the water in the well at the newest reading. |
| `piezometricLevel` | Property | `float` |  | m | `jc:piezometricLevel` | The height of the water above sea level at the newest reading (below 0 where the sea draws the aquifer down). A property of this model: PhreaticObserved has only the depth. |
| `investigationDepth` | Property | `float` |  |  | `sdm:investigationDepth` | The depth of the well or piezometer in metres. A fixed property of the well, written without a unit code so its rows are never read as a measurement stamped on receipt. |
| `aquifer` | Property | `string` |  |  | `jc:aquifer` | The groundwater body (massa d'aigua) the well reaches, as the water agency names it. |
| `stationCode` | Property | `string` |  |  | `jc:stationCode` | The station's code in the network that runs it: the Catalan air-quality network (XVPCA, the city's codi_eoi, such as `8019043`), the Meteocat weather network (such as `D5`) or the Catalan water agency's well register (ACA, such as `08019-0148`). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | Where the entity is as the city names it: the barri of a station or well, the place of a work (a street and number, a square, a park). |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### TrafficFlowObserved

One street section of the city's traffic-state network with its line, its state now and the state forecast for 15 minutes, every five minutes (Open Data BCN trams and transit-relacio-trams).

IRI: `sdm:TrafficFlowObserved`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading, a traffic state's report, a charging point's newest port change. |
| `congested` | Property | `boolean` |  |  | `sdm:congested` | Whether the section is congested now: true for the city's states 4 (very dense) and 5 (congestion), false otherwise, as SDM reads an absent flag (no data and closed included; trafficState tells those apart). |
| `trafficState` | Property | [`TrafficState`](#trafficstate) |  |  | `jc:trafficState` | The city's own traffic state of the section (custom: TrafficFlowObserved has only `congested`), its code 1 to 6 named in English; Open Data BCN dataset trams. |
| `trafficStateForecast` | Property | [`TrafficState`](#trafficstate) |  |  | `jc:trafficStateForecast` | The state the city forecasts for the section in 15 minutes, same codes as trafficState (custom). |
| `travelTime` | Property | `integer` |  | s | `jc:travelTime` | How long a vehicle takes now to drive the route, in seconds (custom: TrafficFlowObserved has no travel time); Open Data BCN dataset itineraris, its fourth field. Absent while the city reports no reading for the route. |
| `usualTravelTime` | Property | `integer` |  | s | `jc:usualTravelTime` | The time the city expects for the route now from its history of the same kind of day, in seconds (custom; itineraris, its fifth field, temps previst). travelTime above it means slower traffic than usual. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### OnStreetParking

One regulated surface parking section of B:SM (blue, green, residents, loading or coach zone), its curb lines, its places and its rate and timetable codes (Open Data BCN trams-aparcament-superficie).

IRI: `sdm:OnStreetParking`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `category` | Property | [`StreetParkingCategory`](#streetparkingcategory) (list) |  |  | `sdm:category` | An Event's main category first, one of the platform's fifteen event codes (music, theatre-dance, film, exhibition-museum, festival-fair, sport, outdoor-nature, education-talk, children-family, hobby-workshop, food-market, history-heritage, faith-tradition, health-wellness, community-civic), then the Smart Data Models category it falls under where one fits, read from the first words of the Catalan name and absent when no rule matches. A PointOfInterest's family in the city's facility register first (culture-leisure, sports, education, social-services, public-administration, markets-shopping, information-centres, religious-services, environment, animals-plants, cemeteries, media, utility-companies, restaurants), then the register's own kind in Catalan (Biblioteques, Poliesportius). An OnStreetParking's kind of regulated parking, from the section type (AZL blue zone, VM green zone, VR residents, DUM loading, BUS coaches). |
| `allowedVehicleType` | Property | `string` (list) |  |  | `sdm:allowedVehicleType` | What may park there, the section's own kind first; at a charging point, what its sockets serve (car for Type 2, CCS and CHAdeMO and for a car park's household sockets, motorcycle for the 3.6 kW household sockets). |
| `totalSpotNumber` | Property | `integer` |  |  | `sdm:totalSpotNumber` | The parking places of the section as B:SM counts them (PLACES). |
| `zoneCode` | Property | `string` |  |  | `jc:zoneCode` | The section type as B:SM codes it (AZL, VM, VR, DUM, BUS), kept as published (custom). |
| `tariffCode` | Property | `string` |  |  | `jc:tariffCode` | The B:SM rate (ID_TARIFA) and timetable (ID_HORARIO) codes of the section, joined as rate/timetable, kept as published (custom; Open Data BCN tarifes- and horaris-aparcament-superficie). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### EVChargingStation

One public charging point of the Endolla Barcelona network run by B:SM, its ports, socket kinds and how many are free now, every five minutes (Open Data BCN informacio-punts-recarrega-electric, which carries the port states of estat-ports-recarrega-electric too).

IRI: `sdm:EVChargingStation`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `dateObserved` | Property | `datetime` | yes |  | `sdm:dateObserved` | The end of the period the entity's newest readings cover, UTC: the hour of an air-quality mean, the local day of a weather station's values, the day of a well's reading, a traffic state's report, a charging point's newest port change. |
| `capacity` | Property | `integer` |  |  | `sdm:capacity` | How many vehicles the charging point charges at once, one per port the city lists. |
| `socketNumber` | Property | `integer` |  |  | `sdm:socketNumber` | The ports of the charging point. |
| `availableCapacity` | Property | `integer` |  |  | `sdm:availableCapacity` | The ports free now (port status AVAILABLE); never more than capacity. |
| `socketType` | Property | [`SocketType`](#sockettype) (list) |  |  | `sdm:socketType` | The kinds of socket, in Smart Data Models' words: CCS_TYPE_2 is CCS/SAE, CHADEMO CHAdeMO, MENNEKES and a wall outlet over 3.7 kW Type2, a wall outlet up to 3.7 kW Wall_Euro. |
| `allowedVehicleType` | Property | `string` (list) |  |  | `sdm:allowedVehicleType` | What may park there, the section's own kind first; at a charging point, what its sockets serve (car for Type 2, CCS and CHAdeMO and for a car park's household sockets, motorcycle for the 3.6 kW household sockets). |
| `status` | Property | [`ChargingStationStatus`](#chargingstationstatus) |  |  | `sdm:status` | The state of the charging point from its ports: working while one is free, full when none is free and one charges, outOfService when every port is out of order, unavailable or unknown. |
| `network` | Property | `string` |  |  | `sdm:network` | The brand of the charging network (Endolla Barcelona). |
| `operator` | Property | `string` |  |  | `sdm:operator` | Who runs the charging point (Barcelona de Serveis Municipals S.A.). |
| `openingHours` | Property | `string` |  |  | `schema:openingHours` | When the charging point may be used, in schema.org's syntax (Mo-Su 00:00-24:00). |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `districtCode` | Property | `string` | yes |  | `jc:districtCode` | The city's own two-digit code of the area: the district number 01..10, or for a barri its number 01..73, which runs across the whole city. |
| `divisionLevel` | Property | [`DivisionLevel`](#divisionlevel) | yes |  | `jc:divisionLevel` | Which of the city's two divisions the area belongs to; for a statistics indicator also the whole city. |
| `refParentDistrict` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refParentDistrict` | The district a barri belongs to. |
| `neighbourhoods` | Relationship | [`AdministrativeArea`](#administrativearea) (list) |  |  | `jc:neighbourhoods` | The barris of this district, computed from their refParentDistrict and never stored. |
| `cityWorks` | Relationship | [`CityWork`](#citywork) (list) |  |  | `jc:cityWorks` | The works that lie in this district only, computed from their refDistrict and never stored. |
| `pedestrianCrossings` | Relationship | [`PedestrianCrossing`](#pedestriancrossing) (list) |  |  | `jc:pedestrianCrossings` | The crossings in this barri, computed from their refNeighbourhood and never stored. |
| `indicators` | Relationship | [`KeyPerformanceIndicator`](#keyperformanceindicator) (list) |  |  | `jc:indicators` | The statistics indicators of this district or barri, computed from their refArea and never stored. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `description` | Property | `string` |  |  | `schema:description` | The description as the city publishes it, in Catalan (a work, a statistics dataset). |
| `workNumber` | Property | `string` | yes |  | `sdm:workNumber` | The city's code of the work, such as 05-2025G0074 (district, year, number). |
| `workState` | Property | [`WorkState`](#workstate) | yes |  | `sdm:workState` | Where the work stands, in the Smart Data Model's terms. |
| `workStateLabel` | Property | `string` |  |  | `jc:workStateLabel` | The work's state as the city writes it, in Catalan (En execució, Aturada, Finalitzada). |
| `workCategory` | Property | `string` |  |  | `jc:workCategory` | The city's kind of work, in Catalan (Urbanització, Serveis, Clavegueram...). |
| `startDate` | Property | `datetime` | yes |  | `schema:startDate` | The first day, local midnight in Europe/Madrid: of an event (the agenda publishes the day, its hours sit in a free-text timetable) or of a work on the public space. |
| `endDate` | Property | `datetime` | yes |  | `schema:endDate` | The last day, local midnight in Europe/Madrid: of an event (absent when the agenda gives none) or the planned last day of a work on the public space. |
| `contractingAuthority` | Property | `string` |  |  | `sdm:contractingAuthority` | The work's promoter, a public body, utility or company; left out when it may name a person. |
| `tenderAmount` | Property | `float` |  |  | `jc:tenderAmount` | The budget the work was put out to tender with, in euros. |
| `awardAmount` | Property | `float` |  |  | `jc:awardAmount` | The budget the work was awarded for, in euros. |
| `areaServed` | Property | `string` |  |  | `sdm:areaServed` | Where the entity is as the city names it: the barri of a station or well, the place of a work (a street and number, a square, a park). |
| `territorialArea` | Property | `string` |  |  | `sdm:territorialArea` | Every district the work touches, by name, separated by "; ". |
| `refDistrict` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refDistrict` | The district the work lies in, when it lies in one district only. |
| `seeAlso` | Property | `uri` |  |  | `sdm:seeAlso` | The work's page on the city's works site. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `startDate` | Property | `datetime` | yes |  | `schema:startDate` | The first day, local midnight in Europe/Madrid: of an event (the agenda publishes the day, its hours sit in a free-text timetable) or of a work on the public space. |
| `endDate` | Property | `datetime` |  |  | `schema:endDate` | The last day, local midnight in Europe/Madrid: of an event (absent when the agenda gives none) or the planned last day of a work on the public space. |
| `category` | Property | `string` (list) |  |  | `sdm:category` | An Event's main category first, one of the platform's fifteen event codes (music, theatre-dance, film, exhibition-museum, festival-fair, sport, outdoor-nature, education-talk, children-family, hobby-workshop, food-market, history-heritage, faith-tradition, health-wellness, community-civic), then the Smart Data Models category it falls under where one fits, read from the first words of the Catalan name and absent when no rule matches. A PointOfInterest's family in the city's facility register first (culture-leisure, sports, education, social-services, public-administration, markets-shopping, information-centres, religious-services, environment, animals-plants, cemeteries, media, utility-companies, restaurants), then the register's own kind in Catalan (Biblioteques, Poliesportius). An OnStreetParking's kind of regulated parking, from the section type (AZL blue zone, VM green zone, VR residents, DUM loading, BUS coaches). |
| `subCategory` | Property | `string` (list) |  |  | `sdm:subCategory` | The Smart Data Models sub-category where the name says it (music, theater). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
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
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `category` | Property | `string` (list) |  |  | `sdm:category` | An Event's main category first, one of the platform's fifteen event codes (music, theatre-dance, film, exhibition-museum, festival-fair, sport, outdoor-nature, education-talk, children-family, hobby-workshop, food-market, history-heritage, faith-tradition, health-wellness, community-civic), then the Smart Data Models category it falls under where one fits, read from the first words of the Catalan name and absent when no rule matches. A PointOfInterest's family in the city's facility register first (culture-leisure, sports, education, social-services, public-administration, markets-shopping, information-centres, religious-services, environment, animals-plants, cemeteries, media, utility-companies, restaurants), then the register's own kind in Catalan (Biblioteques, Poliesportius). An OnStreetParking's kind of regulated parking, from the section type (AZL blue zone, VM green zone, VR residents, DUM loading, BUS coaches). |
| `address` | Property | [`PostalAddress`](#postaladdress) |  |  | `schema:address` | Where the station, the well, the event, the facility or the charging point is, as the city publishes it, field by field (Smart Data Models' common PostalAddress); a field the source leaves out is absent. |
| `contactPoint` | Property | [`ContactPoint`](#contactpoint) |  |  | `schema:contactPoint` | The public telephone line the agenda or the facility register lists. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### KeyPerformanceIndicator

One indicator of the city's statistics (Departament d'Estadística, Open Data BCN) for one barri, district or the whole city: the newest period's value, its history one row per period. Read daily from Open Data BCN.

IRI: `sdm:KeyPerformanceIndicator`

Specialises `Entity`.

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `name` | Property | `string` |  |  | `schema:name` | The name as the city publishes it, in Catalan (a station, an event, a facility, a street section and its stretch, a street address, a district or barri, a work). |
| `description` | Property | `string` |  |  | `schema:description` | The description as the city publishes it, in Catalan (a work, a statistics dataset). |
| `kpiValue` | Property | `float` | yes |  | `sdm:kpiValue` | The indicator's value for its period, with the unit as `unitCode` (UN/CEFACT: C62 a count, EUR euros, MTK square metres) and the period's last day as `observedAt`, so the history holds one value per period. |
| `calculationPeriod` | Property | [`KpiPeriod`](#kpiperiod) | yes |  | `sdm:calculationPeriod` | The period the value covers, its first and last day. |
| `calculationFrequency` | Property | [`CalculationFrequency`](#calculationfrequency) |  |  | `sdm:calculationFrequency` | How often the source publishes a new period. |
| `area` | Property | `string` |  |  | `sdm:area` | The name of the area the value describes, a barri, a district or the whole city. |
| `districtCode` | Property | `string` |  |  | `jc:districtCode` | The city's own two-digit code of the area: the district number 01..10, or for a barri its number 01..73, which runs across the whole city. |
| `divisionLevel` | Property | [`DivisionLevel`](#divisionlevel) | yes |  | `jc:divisionLevel` | Which of the city's two divisions the area belongs to; for a statistics indicator also the whole city. |
| `refArea` | Relationship | [`AdministrativeArea`](#administrativearea) |  |  | `jc:refArea` | The district or barri (AdministrativeArea) the value describes; none for the whole city. |
| `process` | Property | `string` |  |  | `sdm:process` | The statistics dataset the value comes from, its Open Data BCN title in Catalan. |
| `statisticsTable` | Property | `string` |  |  | `jc:statisticsTable` | The Open Data BCN dataset the value comes from, such as pad_mdbas, which `source` links to. |
| `dimensionKey` | Property | `string` |  |  | `jc:dimensionKey` | Which breakdown of the dataset the value is: each kept column and its value as the source writes it, such as SEXE=2; total when the dataset has no breakdown. |
| `calculatedBy` | Property | `string` |  |  | `sdm:calculatedBy` | The organization that computes the value. |
| `organization` | Property | `string` |  |  | `sdm:organization` | The organization the indicator describes. |
| `dataProvider` | Property | `string` |  |  | `sdm:dataProvider` | Who publishes the data the entity was read from, with the credit its licence asks for. |
| `source` | Property | `uri` |  |  | `sdm:source` | The open-data file or the Open Data BCN dataset the entity was read from. |
| `id` | Property | `string` | yes |  | `ngsi-ld:hasId` | The entity id, urn:ngsi-ld:{Type}:{orgDomain}:{space}:{localId}. |
| `type` | Property | `string` | yes |  | `ngsi-ld:hasType` | The entity type, one class of a published data model. |
| `location` | GeoProperty | `string` |  |  | `geojson:geometry` | Where the entity is, as GeoJSON geometry. |
| `observedAt` | Property | `datetime` |  |  | `ngsi-ld:observedAt` | When the observation the entity reports was made. |

### KpiPeriod

The value of `calculationPeriod`, never an entity of its own.

IRI: `jc:KpiPeriod`

| Attribute | NGSI-LD kind | Range | Required | Unit | IRI | Description |
|---|---|---|---|---|---|---|
| `from` | Property | `date` | yes |  | `sdm:from` | The first day of the period. |
| `to` | Property | `date` | yes |  | `sdm:to` | The last day of the period. |

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

### TrafficState

Open Data BCN's traffic state codes 0 to 6, named in English, the Catalan name in each description.

| Value | Meaning |
|---|---|
| `noData` | 0 sense dades: no reading this period. |
| `veryFluid` | 1 molt fluid. |
| `fluid` | 2 fluid. |
| `dense` | 3 dens. |
| `veryDense` | 4 molt dens. |
| `congestion` | 5 congestió. |
| `closed` | 6 tallat. |

### SocketType

The EVChargingStation `socketType` values the Endolla connector types map to, a subset of the Smart Data Model's enum.

| Value | Meaning |
|---|---|
| `CCS/SAE` | CCS_TYPE_2, the combined DC socket. |
| `CHAdeMO` | CHADEMO. |
| `Type2` | MENNEKES, and a WALL_OUTLET above 3.7 kW (the 22 kW AC outlets). |
| `Wall_Euro` | A WALL_OUTLET up to 3.7 kW, the household socket. |

### ChargingStationStatus

The EVChargingStation `status` values the port states map to, a subset of the Smart Data Model's enum.

| Value | Meaning |
|---|---|
| `working` | At least one port AVAILABLE. |
| `full` | No port free and at least one IN_USE. |
| `outOfService` | Every port OUT_OF_ORDER, UNAVAILABLE or UNKNOWN. |

### StreetParkingCategory

The OnStreetParking `category` values the B:SM section types map to, a subset of the Smart Data Model's enum.

| Value | Meaning |
|---|---|
| `blueZone` | AZL, the blue zone anyone parks in for a fee. |
| `greenZone` | VM and VR, the green zone. |
| `feeCharged` | Parking costs by the time parked (AZL, VM, BUS). |
| `forResidents` | VR, residents of the area only. |
| `forLoadUnload` | DUM, urban goods distribution. |
| `onlyWithPermit` | VR and DUM, a resident permit or the DUM app registration is needed. |

### CalculationFrequency

| Value | Meaning |
|---|---|
| `monthly` | A new value every month. |
| `yearly` | A new value every year. |

### DivisionLevel

| Value | Meaning |
|---|---|
| `city` | The whole city (statistics only). |
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
