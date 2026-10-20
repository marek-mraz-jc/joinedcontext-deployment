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
