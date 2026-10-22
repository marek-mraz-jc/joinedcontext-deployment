# Decidim harvester: citizen participation as NGSI-LD (T-5065)

The towns' participation platforms (Decidim) as the space `slovensko-participacia` of the Slovakia
project: participatory processes and assemblies, proposals, participatory budget projects, results,
meetings, debates and surveys. Read anonymously, no login, no personal data.

## Files

| file | role |
|---|---|
| `instances.csv` | one row per Decidim instance: name, base URL, language, scope, town, provider |
| `pipeline.yaml` | the Bento mapping every instance runs, unchanged (comments in it explain each step) |
| `generate.py` | writes each row's DataSource, daily Pipeline, hourly budgets-only Pipeline, both mappings, the index lines and the catalogue source; `--check` fails on a stale file |
| `../../tests/test_decidim.py` | the mapping run in Bento against a stand-in Decidim (0.29 and 0.27 answers), the model's JSON Schema, robots.txt, the personal-data filter, the seed |

Add an instance: one row in `instances.csv`, then `python3 seeds/decidim/generate.py`. Nothing else
changes; the space, its model, Endpoints and Policy are shared.

## How a run reads an instance

1. `robots.txt` (a 5xx fails the run; `/api` disallowed for `*` or `joinedcontext-platform` fails it).
2. `{ decidim { version } }`; 0.28 and later add `withdrawn` to proposals and meetings.
3. `participatoryProcesses` and `assemblies`, then per space its components by type, then each
   component's records 100 a page by cursor.
4. A component whose records the API answers as `null` is read from its public list page instead
   (title, state label, support, votes, amount only).

Every request waits a second after the last one and carries the User-Agent
`joinedcontext-platform/1.0 (+https://dev.joinedcontext.com; public participation data)`. Every URL is
the row's base URL plus a path the mapping builds, never a link taken from an answer. The daily pass
reads everything; the hourly pass reads only the budgets of processes running that day, so vote counts
move within an hour during a vote. Each entity carries `expiresAt` three days ahead, so a record the
platform hides or deletes leaves within three days.

## Instances found (2026-10-21)

| instance | Decidim | API | note |
|---|---|---|---|
| tvormespolu.banskabystrica.sk (Banská Bystrica, "Spoločne tvorme Banskú Bystricu") | 0.29.5 | public `/api` | 19 processes, 0 assemblies. Proposals and budget projects answer `null` to an anonymous client, so they come from the list pages. `/open-data/download` redirects to a blob that answers `NoSuchKey`. The old host spolupracovna.banskabystrica.sk redirects here. |
| Trnava ("Tvorme spoločne Trnavu") | n/a | n/a | not found: participacia.trnava.sk answers 404 on `/api`, tvormespolocnetrnavu.sk does not resolve. |
| bbsk.sk/participativne-planovanie | n/a | n/a | the region runs no Decidim. |

GLOBSEC's 2025 report on participatory democracy in Slovakia names Banská Bystrica as the Slovak town
on Decidim. A further instance goes in as a row once its host answers `{ decidim { version } }`.

## Not in the data, and why

- Authors, profiles, comments and endorsement lists: personal data, never asked for.
- A Result's linked proposals: Decidim's API has no field for them (0.27 to 0.29).
- Proposal coordinates and body on 0.29.5: the API hides the proposal, and the list page shows neither.
- Survey questions and answers: only the survey's title and link.
- Meetings as calendar Events of the events store (T-5047): not done here; the Meeting entities carry
  `startDate`, `endDate`, `address` and `location`, ready for a later mapping.
