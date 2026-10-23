# The Barcelona seed: one Organization, one project, one space

Ajuntament de Barcelona is an Organization of its own (ADR-N-058, T-5260), set up as Mesto Žilina
is in `../zilina/` (T-5242): `organizations/barcelona.yaml` (barcelona.cat, locales ca, es, en),
its org-admin `demo.barcelona` and its readers, the members of the Keycloak group `/barcelona`.
`index.yaml` maps each file to its path in the configuration repository.

| space | model | holds |
|---|---|---|
| `barcelona` | `barcelona` | Open Data BCN (CC BY 4.0) as Smart Data Models: `AirQualityObserved`, `AdministrativeArea` (10 districts, 73 barris), `CityWork` (works on the public space), `PedestrianCrossing` (the street inventory's crossings) |

The pipelines' account `pipelines` writes the space through the Endpoint `barcelona` and the
Policy `pipelines-write`, which lists the model's types and no other. Each Open Data BCN batch
(T-5262..T-5266) adds its classes to `barcelona.linkml.yaml`, the same types to both Policies and
its retention and `in-area` rows to the space. The datasets publish to the CKAN organisation
`barcelona`, titled "Ajuntament de Barcelona": jcctl opens it with the first Endpoint that
publishes. Which Open Data BCN dataset goes where, and why, is the ranked matrix of T-5261.

Batch 2 (T-5263) adds the pipeline `air-quality`: Open Data BCN's hourly file
Qualitat_Aire_Detall.csv, twice an hour, one `AirQualityObserved` per station of the city's network
with the newest valid hour of each pollutant, published as the CKAN dataset of the Endpoint
`air-quality`. Black carbon arrives in ng/m³ under a µg/m³ label and is divided by 1000; the
mapping's header lists what it drops and why. The pipeline `weather` reads Meteocat's daily values
of the three stations in the city (`WeatherObserved`, Endpoint `weather`), the pipeline
`groundwater` the city's well readings (`PhreaticObserved`, one per well read in the last five
years, Endpoint `groundwater`).

Regenerate the model's artifacts after editing its LinkML as `../zilina/README.md` shows, with
`m=barcelona`.
