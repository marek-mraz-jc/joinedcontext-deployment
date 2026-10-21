# BBSK events: source inventory

Who publishes events in Banskobystrický kraj, where, and in what format. Each row of `sources.csv`
was read by hand on 2026-10-20 (column `read_on`) with one polite request per page and the
User-Agent `joinedcontext-platform-events-inventory/1.0`. The pipelines of T-4896 are built from
this file; the rest of Slovakia is T-4899.

## Coverage

- All 24 towns of the kraj (Banská Bystrica, Banská Štiavnica, Brezno, Detva, Dudince, Fiľakovo,
  Hnúšťa, Hriňová, Jelšava, Kremnica, Krupina, Lučenec, Modrý Kameň, Nová Baňa, Poltár, Revúca,
  Rimavská Sobota, Sliač, Tisovec, Tornaľa, Veľký Krtíš, Žarnovica, Žiar nad Hronom, Zvolen).
  Each town's own website was opened and confirmed as the official town site. The Statistical
  Office register itself was not fetched; this list matches the kraj's 24 towns as the task names
  them.
- Three towns have moved off the obvious domain: Tisovec is `tisovec.com`, Tornaľa is
  `mestotornala.sk` and Veľký Krtíš is `velky-krtis.sk`. Dudince's official site is
  `dudince-mesto.sk`; `dudince.sk` is a Wix spa page.
- The region `bbsk.sk`, the regional tourism organisation (KOCR Stredné Slovensko,
  `centralslovakia.eu`), the tourism and culture sites the town pages link to (Visit Banská
  Bystrica, Región Banská Štiavnica, Supervulkán Štiavnica, visitkremnica.com, the Ticketware
  culture centres of Banská Štiavnica and Tornaľa, Dom kultúry Rimavská Sobota, MsKC Žiar), and
  the national catalogue (data.gov.sk now redirects to data.slovensko.sk).

## Decisions

| decision | rows | meaning |
|---|---|---|
| `pipeline` | 16 | machine-readable feed (REST JSON, iCal, RSS/Atom) lists the events |
| `pipeline-html` | 8 | no feed exists; one HTML template per CMS, fragile, built after the feed rows |
| `skip` | 11 | no events calendar, robots.txt refuses it, broken TLS, or a catalogue only (reason in the row) |

20 of the 24 towns have at least one source (feed or HTML); Kremnica's is a WEBY feed that was
empty on the read day. Hnúšťa, Modrý Kameň and Nová Baňa publish no dated events today. Žiar nad
Hronom's own calendar is closed by robots.txt and its culture centre's calendar loads by JavaScript.

## Formats that repeat: one Bento template each

| feed_kind | rows | sources | GPS in the source |
|---|---|---|---|
| `weby-feed` | 11 | WEBY PORTÁL (WEBY GROUP, Zvolen): Detva, Fiľakovo, Jelšava, Kremnica, Lučenec, Revúca, Rimavská Sobota, Tornaľa, Veľký Krtíš, Žarnovica, Zvolen | no |
| `lego-html` | 4 | Lego CMS: Dudince, Hriňová, Poltár, Tisovec | no |
| `eventphp-html` | 1 | event.php CMS: Brezno (visitkremnica.com and kino.mskcentrum.sk run the same CMS but fill the month by JavaScript: skip) | no |
| `tribe-rest` / `ical` | 2 | The Events Calendar: visitbanskabystrica.sk (REST), centralslovakia.eu (iCal; its robots.txt disallows /wp-json/) | no (venue has no geo_lat) |
| `ticketware-html` | 2 | Ticketware culture centres: Banská Štiavnica, Tornaľa | no |
| `wp-rest-sc` | 1 | Banská Bystrica (WP REST `/wp/v2/events`, also on data.gov.sk, CC-BY-4.0) | **yes**, 58 of 58 upcoming |
| `wp-rss` | 1 | Sliač, same smart-city theme as Banská Bystrica but REST closed (401): RSS `?post_type=event` + detail page | yes, in the page (static-map lat/lon) |
| `mec-rest` | 1 | Modern Events Calendar: banskastiavnica.travel (REST list + schema.org Event JSON-LD per page) | no (address only) |
| `krupina-html` | 1 | Krupina (ID-SK template) | no |

The WEBY template alone serves 11 towns. A WEBY feed carries only title, link and publication
date; the `/akcia/` detail page has the labelled fields `Dátum`, `Čas`, `Miesto` and
`Usporiadateľ`. Zvolen serves RSS 1.0 at `get_rss.php?id=3`; the other WEBY towns serve Atom at
`id=3_atom`. Six WEBY feeds were empty on 2026-10-20 but well formed, so their pipelines run and
report 0.

## GPS: what T-4896 needs

The owner rule (name, startDate and a GPS point required, no town centroids) means only
Banská Bystrica and Sliač give events a location straight from the source. Every other kept row
names its venue as text (`Miesto`, `Kde`, LOCATION, Place address). Those rows need the seeded
venue table with hand-checked coordinates, or their events are rejected.

## Terms and personal data

- Only public pages; no source needs a login. `robots.txt` was read per host with the
  standard parser, by user-agent group: `ziar.sk` disallows `/event.php` and `centralslovakia.eu`
  disallows `/wp-json/`. Neither path is used.
- Only Banská Bystrica states a licence (CC-BY-4.0 in its data.gov.sk record, which also flags
  personal data). Its feed holds the organiser's e-mail and phone: the pipeline drops both. No
  other site states a licence, so pipelines keep only the facts of an event (name, time, place,
  category, the source link and an image URL), never copy texts or image files, and attribute the
  source page.
- `bbsk.sk` sends its certificate without the GeoTrust intermediate, so curl and Go refuse it.
  The row stays `skip` until the region fixes the chain; TLS verification is never turned off.

## Re-check

`check-sources.py` re-fetches every kept row's `check_url` (robots.txt first, 1 request per
second) and checks that the format still parses: JSON shape, RSS/Atom XML, VCALENDAR, or the
row's `item_pattern` on an HTML list. Exit 1 when a kept row fails; an empty feed is only reported.

```sh
python3 seeds/bbsk-events/check-sources.py          # kept rows
python3 seeds/bbsk-events/check-sources.py --all    # skip rows too
```

## Related

- T-4895 events space and Event model, T-4896 pipelines, T-4897 dashboard, T-4899 Slovakia.
- docs Requirements PL-19, PL-47, PL-50, PL-72, DM-83; iCalendar SurfaceRequirement in
  platform `crates/jc-core/src/kinds/endpoint.rs`.

## Pipelines (T-4896)

`generate.py` writes one DataSource, Pipeline and Bento mapping per `pipeline` row whose feed kind has a template, into
`components/context-gateway/seed/bbsk/bbsk-{datasource,pipeline}-podujatia-<host>.yaml` and their lines in that folder's
`index.yaml`. Change a template, `sources.csv` or `venues.csv`, then run `python3 seeds/bbsk-events/generate.py`;
`tests/test_bbsk_events_pipelines.py` fails while the seed differs from what the script writes.

Every Pipeline writes through `bbsk-podujatia-zapis` (T-5033): audience `organization`, no `policyRef`, so the gateway
binds each pipeline's derived write Policy (`pl-<pipeline>`, PL-20) there. The public Endpoints `bbsk-podujatia` and
`bbsk-podujatia-slovensko` name a read `policyRef` and serve no write; a pipeline aimed at one gets 404 on every upsert.
`tests/test_pipeline_write_path.py` holds every seeded Pipeline to that rule.

| Template (`pipelines/`) | Feed kind | Sources | Where the date and the place come from |
|---|---|---|---|
| `wp-rest-sc.yaml` | wp-rest-sc | Banská Bystrica | Meta Box fields, GPS included |
| `tribe-rest.yaml` | tribe-rest | visitbanskabystrica.sk | The Events Calendar REST, venue GPS when set |
| `ical.yaml` | ical | centralslovakia.eu | DTSTART/DTEND, GEO, else LOCATION in the venue table |
| `weby-feed.yaml` | weby-feed | 11 towns | the feed's /akcia/ links, each page read once, 1 s apart |
| `mec-jsonld.yaml` | mec-rest | banskastiavnica.travel | the event page's schema.org Event JSON-LD, 1 s apart |

`common.yaml` closes every template: it keeps events whose end is now or later, the 100 soonest by start; finds the
point in the feed or in `venues.csv`; mints the id from name, start and town, so one event announced by two sources is
one entity; writes `expiresAt` at the event's end (start + 1 day without an end) and scope `/SK/BB/<town>`.

- `venues.csv` holds venues checked by hand against OpenStreetMap (the object's id in `osm`), matched by the place
  text in lower case without parentheses and commas, per town; `regional=y` rows also serve the region's iCal feed.
  A venue nobody checked gives no point, and the Event model refuses the event into the run's rejected list.
  Not found as the named building on 2026-10-20: Kultúrny dom Veľký Krtíš, Kultúrny dom v Žarnovici, Dom kultúry
  Podborová (Zvolen), Športová hala Arena (Lučenec).
- A source with no licence stated gives facts only (name, time, place, link back), never its description;
  Banská Bystrica's feed is CC BY 4.0 and keeps the text, without organiser e-mail or phone.
- Each run is daily, staggered 00:00-02:34 UTC (01:00-05:00 in Bratislava, winter and summer); the Portal's
  run-now button starts one source.
- Not built yet: `wp-rss` (Sliač writes its dates only in free text) and every `pipeline-html` row (one parser per CMS).

## The national store (T-5047)

Since 2026-10-21 (owner: "a second store of all events across the whole Slovakia ... at least 100 sources ...
synchronized, up to date") `generate.py` writes two stores from the same inventory:

| store | project / space | sources | cadence | an event leaves |
|---|---|---|---|---|
| region | `bbsk` / `bbsk-podujatia` | the BBSK rows | daily, 00:00-02:59 UTC | at its end |
| national | `slovensko` / `slovensko-podujatia` | every kept row | feeds every 3 h; Lego and WEBY calendars daily, spread over the day | a day after its end, or 8 h (daily: 52 h) after the last run that listed it |

The national store's pipelines write through `slovensko-podujatia-zapis` (audience organization, no policyRef);
people read `slovensko-podujatia` (NGSI-LD, OGC, iCal, CSV, OData, WebSocket, MCP; CKAN dataset "Podujatia na
Slovensku" in the `slovensko` catalogue). The lease ends an event its source dropped or cancelled, because
`spec.expiry` is refused where several pipelines write one space.

One template per source kind, a source is one DataSource + one Pipeline naming its kind:

| feed kind | templates (`pipelines/`) | what it reads |
|---|---|---|
| `lego-html` | `lego-html` | Lego CMS calendar list; each event page's `data-date-start`/`data-date-end` and `class="venue"`, 3 s apart (the CMS's robots.txt asks Crawl-Delay 3) |
| `lsvr-rest`, `eventon-rest`, `mec-rest`, `wp-rest-jsonld` | `wp-list` + `jsonld-pages` | WordPress REST list (50 newest), each event page's schema.org Event JSON-LD, 1 s apart |
| `wp-rss-jsonld` | `rss-list` + `jsonld-pages` | RSS/Atom of event posts, each post's JSON-LD |
| `jsonld` | `page-jsonld` | the events page's own JSON-LD; a page without any JSON-LD fails the run |
| `tribe-rest`, `ical`, `weby-feed`, `wp-rest-sc` | as above (T-4896) | |

The 182 rows marked `found by T-5047 from Wikidata P856` come from probing the website of every Slovak
municipality on Wikidata (2,859 sites, `P782` LAU code, region from its NUTS 3 prefix) and 254 museums,
galleries, theatres, libraries and culture centres: robots.txt first, then `/wp-json/` (The Events Calendar, LSVR,
EventON, MEC routes), `get_rss.php?id=3_atom` (WEBY) and the Lego `bundles/kalendar` calendar page. A row was
kept only when its feed parsed and listed at least one event on 2026-10-21. 89 WEBY sites serve an empty
`id=3` feed and stay out.

Decisions (worker-t5047, owner may override):

- GPS stays required with no town centroids (owner 2026-10-20): most new sources give a venue name only, so their
  events reach the space once `venues.csv` holds their venue; until then the run report lists them as refused.
- No conditional GET: a one-shot run keeps no state between runs to remember an ETag, and each run is one list
  request plus at most 50 page reads at 1-3 s.
- No paging: a store keeps the 100 soonest events per source; The Events Calendar answers upcoming events by start
  (`start_date=now`) and a WordPress list its newest posts, which hold the upcoming ones.
- Duplicates collapse by id (name, start, town hash, as T-4895's model states): one entity, the last source's link.
  A sameAs relation across sources within 200 m needs a cross-source pass over the space, which a per-source
  one-shot run cannot do.
- Free-text dates stay out: `wp-rest` (detail HTML), `wp-rss` and `joomla-rss` rows need one parser per site.

## Organizer and link (T-5081)

Both stores require `organizer` (schema:organizer: `name`, maybe `url`) and `url` (an http(s) link) beside
name, start and GPS; a record without one is refused into the run report. `source` and `dataProvider` stay as
provenance: who published the feed is not who runs the event.

- The organizer comes from the feed where it names one: The Events Calendar's `organizer` and `website`,
  schema.org `organizer` (Organization or Person, the first of a list) on JSON-LD pages, WEBY's `Usporiadateľ`
  field, iCal `ORGANIZER;CN=`. Only the name and the web site are kept; an e-mail, a phone number or a
  `tel.`/`kontakt` label typed into the name is cut, and a `mailto:` is no web site.
- Else the body whose calendar it is (`generate.py organizer()`): the name in `org_type (Name)`, `Mesto {town}`
  for a town, `Obec {town}` for a municipality, with the inventory's site. A tourism organisation or a region
  announces other bodies' events, so its rows name none: their events without a feed organizer are refused.
- `url` is the event's page, else the source's events page (`events_url`). A link that is no absolute http(s)
  URL (a `javascript:` or relative link) counts as none.

Sources (2026-10-21): 143 BBSK candidates beyond T-5047's (museums, galleries, theatres, libraries, osvetové
strediská, culture centres, UMB/AU/TUZVO and their faculties, gymnáziá, OOCR, clubs and venues) were probed
with `/workspace/evidence/T-5081/probe.py` (robots.txt first, 1 s per host, the pipelines' User-Agent): The
Events Calendar REST, `/wp-json/` namespaces, `?ical=1`, WEBY `get_rss.php?id=3_atom`, Lego calendars and
schema.org Event JSON-LD on the home page and on up to four event-looking pages. 81 answered over https; 10
showed a machine-readable event list, 6 of them already kept. One new source is kept (Verejná knižnica
Mikuláša Kováča, WEBY, its address in the venue table); Šahy and Modrý Kameň list only past or 2028 items and
Teatro Tatro's EventON only past summer shows; `muzeum.sk` is the national museum in Bratislava. The other
museums, galleries, theatres, universities and schools publish HTML only (UMB's six faculty sites share one
CMS with `kalendar-udalosti`, TUZVO's five one with `kalendar-podujati`): those need an HTML kind per CMS.
