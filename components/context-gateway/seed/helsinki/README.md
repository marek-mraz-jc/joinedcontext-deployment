# The Helsinki seed: one space, four endpoints

The demonstration instance's context data, as the development profile seeds it into the
gateway's `/repo` (T-0263) and, through the forge bootstrap, into the configuration repository
the Portal reads (T-0478). Both consumers read the files in this folder, so they cannot drift:
`index.yaml` maps each file to its path in the repository (jc-core `PATH_TEMPLATE`s), and the
gateway mounts each under its own name in the flat `/repo`.

One ContextSpace, `helsinki`, holds three things side by side: `Event` from the city's Linked
Events register, `BikeHireDockingStation` from the HSL city bike GBFS feeds, `Vehicle` from HSL's
high-frequency positioning of four trunk lines. Four public Endpoints publish it: `helsinki-events`,
`helsinki-bikes` and `helsinki-transport` each carry `spec.policyRef` to the Policy that grants
one type, so the gateway evaluates that Policy alone (EP-14, GW8); `helsinki-all` carries none
and evaluates every Policy of the space, which is also why the pipelines write through it: the
`pipelines-write` Policy is bound to the `pipelines` ServiceAccount there and nowhere else.

The streams the resident runner executes are `components/pipeline-runner/streams/`; the
`DataSource` and `Pipeline` manifests here describe the same fetches for the Portal, until the
reconciler renders the one from the other on this cluster (T-0421).

Regenerate the model artifacts after editing `helsinki.linkml.yaml`:

```sh
T=../../../../../joinedcontext-platform/tools/model-tools/src   # the platform checkout
for g in json_schema context example docs; do python3 $T/gen_$g.py helsinki.linkml.yaml -o helsinki.v1.$( [ $g = json_schema ] && echo schema.json || [ $g = context ] && echo context.jsonld || [ $g = example ] && echo example.jsonld || echo md ); done
```

## Smart Data Models validation (T-3889)

`tests/helsinki/validate_sdm.py <public endpoint>` reads up to 50 entities of every Helsinki type
that claims a Smart Data Model (`class_uri: sdm:…`) as key-values in Finnish and validates them
against the model's official `schema.json`. Each type the SDM catalogue has no model for, and
each attribute that knowingly differs, carries its written reason in the script (`EXCEPTIONS`,
`ACCEPTED`), and `tests/test_helsinki_sdm.py` fails when a class of the model is neither validated
nor excepted. Run on dev 2026-10-12 against the `all` endpoint: BikeHireDockingStation, GtfsStop
and WeatherObserved pass; Alert, Event, PointOfInterest and WaterQualityObserved pass except for
the written gaps (address as text, T-3949; Alert's alertSource and subCategory codes, T-3950;
Event's single eventStatus; a beach sensor with no reading this season); AirQualityObserved,
Vehicle and GtfsRoute had no entities to read.

## HSL sources and the load budget (T-3889)

Measured 2026-10-12 00:28Z (03:28 in Helsinki, so the realtime feeds are at their night size) with
one `GET` each from the sandbox; the sizes are bytes received, the times the whole request.

| Source | URL | Licence | Size | Time | Update | Key | Ingest under the budget |
|---|---|---|---|---|---|---|---|
| GTFS static | `https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip` | CC BY 4.0 (HSL open data) | 79 101 306 B zip; `stop_times.txt` 1.0 GB, 11 219 195 rows; `trips.txt` 400 064 rows; `shapes.txt` 456 964 points in 1 192 shapes (median 350, max 1 360); `routes.txt` 459; `stops.txt` 8 385 (8 263 stops, 122 stations) | 6.1 s | the feed's `feed_version` 2026-10-10, valid 2026-10-09..2026-12-07: daily | no | yes, T-3890: agency, 459 routes, 1 192 shapes, 8 385 stops and stations, read once a day from the zip's members; never `stop_times`, `trips`, `translations` or `calendar` whole |
| GTFS-RT trip updates | `https://realtime.hsl.fi/realtime/trip-updates/v2/hsl` | CC BY 4.0 | 7 630 B (night) | 0.26 s | continuous | no | yes, T-3891: departures for a curated stop set only, as a property of those stops; no entity per trip |
| GTFS-RT vehicle positions | `https://realtime.hsl.fi/realtime/vehicle-positions/v2/hsl` | CC BY 4.0 | 1 231 B (night) | 0.26 s | continuous | no | no: HFP below carries the same positions with less work; T-3893 widens HFP to every mode inside the vehicle cap |
| GTFS-RT service alerts | `https://realtime.hsl.fi/realtime/service-alerts/v2/hsl` | CC BY 4.0 | 21 615 B | 0.32 s | on change | no | yes, T-3892: one Alert per HSL alert, beside the Digitraffic ones |
| HFP (MQTT) | `mqtts://mqtt.hsl.fi:8883/hfp/v2/journey/ongoing/vp/#` | CC BY 4.0 | a stream, not a document: not measured by `GET` | — | one `vp` message a second per vehicle (HSL HFP documentation) | no | yes, in place: 30 vehicle slots over 4 trunk lines, every position of an admitted vehicle written (`helsinki-pipeline-hfp-bento.yaml`, T-3906); T-3893 keeps the cap |
| Park and ride (Liipi) | `https://p.hsl.fi/api/v1` (`/facilities`, `/utilizations`, `/hubs`) | CC BY 4.0 | the host did not resolve (`Could not resolve host: p.hsl.fi`) | — | — | no | not until the host answers; T-3894 re-checks the address first |
| City bikes (GBFS) | the `citybikes-gbfs` pipelines | CC BY 4.0 | in place | — | 1 min | no | in place |
| Digitransit GraphQL | `https://api.digitransit.fi/routing/v2/hsl/gtfs/v1` | CC BY 4.0 | `401` without a key | 0.09 s | live | **yes** | Owner action: a Digitransit subscription key, never committed; nothing waits for it, because GTFS and GTFS-RT above carry the same data |

The budget (supervisor, 2026-10-11): dev is one 16 GB node near 90 % memory. Live vehicles stay
capped; departures only for a curated stop set; no `stop_times` or `trips` table is ingested
whole; each task above measures pipeline-runner and broker memory (`kubectl top pod`, 10 min
average) before and after and stays under +150 MiB. This task adds no ingest, so it changes
neither.

### GTFS static (T-3890)

Three DataSources read `hsl.zip` by its members (PL-72): the runner fetches the zip's directory
and then each named member by its byte range, so `stop_times.txt` (1.0 GB inflated), `trips.txt`
and `translations.txt` are never fetched. Measured 2026-10-12 with Bento 1.22.0 locally over the
member alone, peak resident memory over Bento's own baseline (about 140 MB), and entities written:

| Pipeline | Source | Members | Entities | Peak over baseline | Time | Schedule |
|---|---|---|---|---|---|---|
| `transit-stops` | `hsl-gtfs-stops` | `stops.txt` (8 385 rows) | 8 263 GtfsStop, 122 GtfsStation | 120 to 135 MB | 2 s | daily 04:20 |
| `gtfs-routes` | `hsl-gtfs-routes` | `agency.txt` (1), `routes.txt` (459) | 1 GtfsAgency, 459 GtfsRoute | under 5 MB | 1 s | daily 04:30 |
| `gtfs-shapes` | `hsl-gtfs-shapes` | `shapes.txt` (456 964 points, 1 192 shapes) | 1 192 GtfsShape, about 200 points each | 180 to 225 MB | 4 s | paused |

The row counts are `wc -l` minus the header of each member; the entity counts are the mappings'
output over those members, every entity valid against `helsinki.v1.schema.json`. `gtfs-shapes`
is paused because the runner reads a deflated member only when 1032 times its packed size fits
the 256 MiB bound (T-3951), and `shapes.txt` is 4.2 MB packed; T-3953 bounds the inflate on its
output instead. `stops.txt` (197 kB packed) fits that rule with 256 MiB, until it passes 260 kB
packed. A line's stops in order and its direction stay with TransitRoute from the ArcGIS "stops by
line" register (`transit-routes`), which transit-reach reads: GTFS gives them only through
`trips.txt` and `stop_times.txt`. The ArcGIS stop register is gone; it named stops by the same
GTFS stop ids, so the first run updates those entities in place, and a stop it held that the
GTFS feed lacks stays on dev until someone deletes it. The 10-minute averages on dev (`kubectl top pod`) are the deployer's to
record after the first runs.
