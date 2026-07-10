# Ephemera hardening handoff

Date: 2026-07-10

## Goal

Make Ephemera useful to Hal for discovering NYC classes, workshops, lectures,
talks, and similar programs, while returning enough structured scheduling data
for Hal to compare an event against the user's Google Calendar or add it when
asked.

The implementation spans two repositories:

- Ephemera: `/Users/adnanakil/Project/Ephemera`
- Hal/AgentGate: `/Users/adnanakil/Project/agentlist`

The work is implemented and tested locally. It has **not been committed,
deployed, or followed by a production scrape**.

## What changed in Ephemera

### 1. Canonical calendar-ready event schema

Added `lib/event-schema.ts`. It defines the backward-compatible event contract
and normalizes both newly extracted and legacy cached events.

New structured fields include:

- `eventType`: `class`, `workshop`, `lecture`, `talk`, `tour`, `conference`,
  `performance`, `exhibition`, `market`, `social`, or `other`
- `startAt` and `endAt`: RFC3339 timestamps
- `timezone`: defaults to `America/New_York`
- `format`: `in_person`, `online`, `hybrid`, or `unknown`
- `organizer` and `instructor`
- `audience` and `topics`
- `price`
- `registrationRequired`, `registrationStatus`, and `registrationUrl`
- `recurrence` and `sessionCount`
- `durationMinutes`
- `calendar`: a stable scheduling block:

```json
{
  "ready": true,
  "start": "2026-07-13T19:00:00-04:00",
  "end": "2026-07-13T21:00:00-04:00",
  "timezone": "America/New_York",
  "endIsEstimated": false
}
```

Important behavior:

- Existing Redis records do not need a migration. `GET /api/events` normalizes
  them at read time.
- A legacy `date` plus human-readable `time` is converted to RFC3339.
- Timezone conversion uses `Intl.DateTimeFormat`, including New York DST.
- If the listing provides an explicit end time, it is preserved and
  `endIsEstimated` is false.
- If the end is missing, a type-specific duration is used and
  `endIsEstimated` is true. Defaults are 120 minutes for classes/workshops, 90
  for lectures/talks/tours, 480 for conferences, and conservative defaults for
  the remaining event types.
- Events without a resolvable start have `calendar.ready=false`.
- Legacy event type and format classification is heuristic. Newly scraped
  events receive declared values from the extraction model.

### 2. More class and lecture sources

Expanded `EVENT_URLS` in `app/api/events/fetch/route.ts` with:

- New York Public Library classes
- Brooklyn Public Library calendar
- Queens Public Library calendar
- Brooklyn Brainery
- 92NY
- The Center for Fiction
- Thought Gallery
- Neue Galerie lectures
- New York Botanical Garden lectures, talks, and symposia

These are added alongside the university event sources that already existed.

### 3. Richer extraction contract

All three Claude extraction paths in `app/api/events/fetch/route.ts` now ask for
the scheduling and enrollment fields above.

For multi-session courses:

- `startAt`/`endAt` represent the first upcoming session.
- `recurrence` describes the schedule in human language.
- `sessionCount` records the number of sessions when stated.
- The model is explicitly told not to invent end times, prices, or enrollment
  details.

Newly extracted events are normalized before they are merged into Redis.

### 4. New API filters

`GET /api/events` now accepts:

- `event_type`
- `format`
- `calendar_ready`

Existing filters remain supported: `since`, `until`, `near`, `radius_km`,
`category`, `q`, and `limit`.

Semantic type families are intentional:

- `event_type=class` matches `class` and `workshop`.
- `event_type=lecture` matches `lecture`, `talk`, and `conference`.

Example:

```text
GET /api/events?since=2026-07-10&until=2026-07-31&event_type=class&format=in_person&calendar_ready=true&limit=10
```

Free-text `q` now also searches organizer, instructor, audience, topics, and
event type. Results sort by exact normalized start time when available.

### 5. TypeScript/test support

- `lib/event-filters.ts` now normalizes records before filtering.
- `tsconfig.json` enables `allowImportingTsExtensions` so the same pure modules
  work in Next.js and the standalone Node tests.
- Added `tests/event-schema.test.mjs`.
- Extended `tests/filters.test.mjs` with learning-event, format, metadata search,
  and calendar-readiness cases.

## What changed in Hal

### 1. `nyc_events` tool output

Updated:

`services/hal-orchestrator/hal_orchestrator/tools/nyc_events.py`

The tool now forwards `event_type`, `format`, and `calendar_ready`. Each event
can render:

- Event type and delivery format
- Venue and neighborhood
- Instructor and organizer
- Price and registration status
- Recurrence and session count
- Exact `Calendar: start → end (timezone)` values
- `[end estimated]` when Ephemera inferred the duration
- Direct registration URL, preferred over a generic listing URL

Example internal tool result:

```text
- Mon Jul 13, July 13, 7:00 PM - 9:00 PM: Writing the Story Only You Can Tell [workshop, in person]
  The Center for Fiction, 15 Lafayette Ave, Brooklyn — Fort Greene
  with Vanessa Walters · by The Center for Fiction
  $75 · registration open
  Series: Weekly Mondays through July 27 (3 sessions)
  Calendar: 2026-07-13T19:00:00-04:00 → 2026-07-13T21:00:00-04:00 (America/New_York)
  https://example.com/register
```

The duplicated date in the human-readable heading is inherited from the older
formatter. The exact `Calendar:` line is the source of truth for scheduling.

### 2. Tool schema and routing instructions

Updated:

- `services/hal-orchestrator/hal_orchestrator/prompts/tool_defs.py`
- `services/hal-orchestrator/hal_orchestrator/prompts/system.py`
- `services/hal-orchestrator/hal_orchestrator/skills/nyc-events/SKILL.md`

Hal is now told to:

- Use Ephemera first for NYC classes, workshops, lectures, and talks.
- Use `event_type=class` or `event_type=lecture` with
  `calendar_ready=true` for those requests.
- Use the exact Calendar interval when checking Google Calendar or creating an
  event.
- Disclose or verify an estimated end rather than presenting it as a sourced
  fact.
- Create the Google Calendar event when the user explicitly asks, following
  the existing low-risk calendar-write behavior.

### 3. Documentation and tests

- Updated the Ephemera API section in
  `services/hal-orchestrator/architecture.md`.
- Added `services/hal-orchestrator/tests_nyc_events.py`, covering rich rendering,
  estimated-end disclosure, registration-link preference, and query forwarding.

## End-to-end behavior

The intended Hal flow is:

1. User asks for a class, workshop, lecture, or talk in NYC.
2. Hal calls `nyc_events` with dates and an `event_type`; it can require
   `calendar_ready=true`.
3. Ephemera returns normalized events from either the legacy cache or the richer
   post-scrape schema.
4. Hal presents suitable options with registration links.
5. If the user asks which option fits, Hal checks `google_calendar` using the
   exact interval.
6. If the user says to add it, Hal calls `google_calendar(create_event)` with
   the title, exact start/end, location, and listing/registration details.
7. If Ephemera marked the end as estimated, Hal states the assumption or verifies
   the listing first.

## Verification completed

Ephemera:

```text
node tests/event-schema.test.mjs  # 16 passed
node tests/filters.test.mjs       # 29 passed
npm run build                     # production Next.js build passed
```

Hal:

```text
.venv/bin/python services/hal-orchestrator/tests_nyc_events.py
# all focused tests passed

.venv/bin/python services/hal-orchestrator/tests_group_hardening.py
# all existing regression checks passed

uv run ruff check --ignore E501,E402,T201,UP017,SIM102 \
  services/hal-orchestrator/hal_orchestrator/tools/nyc_events.py \
  services/hal-orchestrator/hal_orchestrator/prompts/tool_defs.py \
  services/hal-orchestrator/hal_orchestrator/prompts/system.py \
  services/hal-orchestrator/tests_nyc_events.py
# passed
```

Python compilation and `git diff --check` also passed.

## Remaining work for the next agent

1. Review and commit the changes in both repositories separately. The new,
   currently untracked files must be included:
   - Ephemera: `lib/event-schema.ts`, `tests/event-schema.test.mjs`
   - AgentGate: `services/hal-orchestrator/tests_nyc_events.py`
2. Deploy Ephemera and Hal using the existing Railway process in
   `services/hal-orchestrator/architecture.md`.
3. Do not trigger a full scrape casually: it is long-running and consumes
   Firecrawl/Scrapfly/Anthropic credits. Let the scheduled refresh run or trigger
   it intentionally after deployment.
4. Verify the live endpoint with both class and lecture queries, including
   `calendar_ready=true`.
5. Inspect several real results for explicit versus estimated end times,
   multi-session recurrence, price, and registration status.
6. Run a live Hal conversation such as:
   - “Find me an in-person writing class this month.”
   - “Which of those fits my calendar?”
   - “Put the second one on my calendar.”

## Known limitations and follow-ups

- No production scrape has validated the new extraction prompt against all nine
  new source shapes.
- Large source calendars may paginate or exceed the scraper/model content window;
  source-specific adapters would be more reliable if coverage is incomplete.
- Recurrence is descriptive text, not an RRULE. Hal currently creates one
  calendar event, not an entire recurring series.
- Estimated end times are useful for planning but are not authoritative.
- Registration availability is only as fresh as the daily scrape and is not a
  live inventory guarantee.
- The default timezone is New York because Ephemera is currently an NYC engine.
- The old human heading can repeat the date; use the Calendar line for machine
  scheduling and consider cleaning the display formatter separately.
- Adding nine sources increases daily scrape time and API-credit use. Watch the
  scrape status, failure rate, and event yield after deployment.

## Dirty-worktree warning

Both repositories already contained unrelated user-owned changes and untracked
research files. They were deliberately left alone.

Notable unrelated Ephemera state includes the deleted `.npmrc`, an Xcode user
state change, `.gemini-clipboard/`, venue/license datasets, and research scripts.
In AgentGate, `manhattan_outdated_websites.xlsx` is unrelated. Do not stage or
revert those as part of this feature without checking with the user.
