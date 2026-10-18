# Shipment analytics and exports (increment 6)

## Data and metric definitions

Analytics count actual `shipments` rows joined to non-superseded products. Products and untagged legacy checkpoints never create implicit shipments. Active means a shipment record without canonical delivery evidence; it includes planning records and records awaiting indexed departure, and does not assert that goods are moving.

Lifecycle timestamps are read from the persisted canonical event journal in a single SQL snapshot, joined through the product's identity binding, product key, chain and emitting registry/tracker contract. They are exposed as UTC `departed_at` / `delivered_at` in shipment responses, rather than copied into a second projection that could retain orphaned timestamps. Reorganization recovery therefore removes orphaned deliveries from metrics and exports automatically. Confirmation depth remains the indexer's configured policy; these reports do not independently attest physical authenticity.

| Metric | Definition |
| --- | --- |
| Completed transit | First canonical status `1` checkpoint to first canonical delivery (`DeliveryCompleted` or status `3` checkpoint), provided delivery is at/after departure |
| Transit average | Completed transit samples only; `null` with no valid samples |
| Active elapsed | Departure to current UTC time for undelivered journeys; separate average and sample count |
| On-time rate | Completed journeys with a pre-departure expected arrival, delivered at/before that instant, divided by completed journeys with a known expected arrival |
| Unknown/incomplete SLA | Deliveries without expected arrival and deliveries with SLA but missing/invalid departure are counted separately; neither enters the on-time denominator |
| Checkpoint interval | Time between consecutive canonical checkpoints, attributed to the earlier normalized location. Includes travel; **not dwell time** |
| Route | Exact origin/destination after trimming edge spaces and ignoring case; no geographic inference or fuzzy grouping |
| Anomaly | Two-sided sample Z-score strictly greater than the requested threshold (default 2), within one route with **at least 10 completed samples** and nonzero variance |
| Trend | Shipment creation counts in explicit bounded dates versus the immediately preceding equal duration. Missing dates, underflowing dates, or a zero previous baseline give no percentage claim |

Ten samples is a conservative display threshold, not a statistical guarantee. Flags are descriptive outliers and do not establish delay, fault or fraud. Checkpoint intervals average above 24 hours by default. Sample counts accompany KPIs, routes, intervals and flags. Dashboard volume is the last seven UTC creation days; the separately labelled product series counts product **records created**, including drafts, not on-chain registrations.

## SLA planning

`ShipmentCreate` and `ShipmentUpdate` accept nullable `expected_arrival_at`. Non-null input requires an explicit timezone and is normalized to UTC. Only the product owner can write it. Recorded-at is server-controlled; late or unproven plans are reported separately. The server records `expected_arrival_recorded_at`; a plan recorded after the eventual canonical departure is excluded from on-time performance even if indexing was lagging when it was written. Once canonical departure or delivery exists, the API rejects changes (including clearing it) with `409`. Creating a shipment after departure with a retrospective SLA is also rejected. The form labels its optional datetime input as UTC. Historical shipments retain `null`; there is no assumed 72-hour target.

Migration `c62a904df318` follows `b47e203fa951` and adds nullable `TIMESTAMP WITH TIME ZONE` expected-arrival and recorded-at planning columns. There is no lifecycle/SLA data backfill. PostgreSQL deployment uses the migration lock, five-second lock timeout and exact predecessor guard. Follow the existing release workflow: rehearse on a production branch, apply to testing, validate the exact release, preserve a production restore point, apply the reviewed additive migration and release main. Roll back application code if necessary; keeping the nullable column is compatible with the preceding release. Do not downgrade/delete planning data as a routine rollback.

## Cohorts and exports

All analytics endpoints accept the same optional `start_date`, `end_date`, `origin`, `destination`. Dates must be `YYYY-MM-DD`. They select **shipment creation**, not registration or event time. The interval is `[start at 00:00 UTC, day after end at 00:00 UTC)`, including the entire end day. The selected shipment's whole canonical journey is included even when its events happened outside those creation dates. Reversed/invalid dates return `422`. Dashboard is all-time; Analytics queries/charts/exports share its applied filters. Displayed filter edits take effect only after Apply filters.

- `GET /analytics/kpis`: typed metrics, exclusions/sample sizes, normalized routes, filter metadata, as-of UTC and trend comparison.
- `GET /analytics/anomalies`: qualifying flags with route and sample size.
- `GET /analytics/bottlenecks`: compatibility path; returns `avg_interval_hours`, location and interval sample count. The old `min_dwell_hours` query parameter remains for compatibility but means interval threshold. No `avg_dwell_hours` claim remains.
- `GET /analytics/export?format=csv&report=shipments`: one row per actual shipment, including records without events; lifecycle/SLA timestamps, canonical checkpoint/event counts and evidence references.
- `GET /analytics/export?format=csv&report=events`: one row per canonical event belonging to the selected shipments; transaction/block/hash/log/chain/contract references and applicable event fields. Metadata events without an ABI timestamp keep timestamp blank.
- `GET /analytics/export?format=pdf`: shipment summary, sample counts, individual journeys and canonical references. It is a shipment report; product drafts are not labelled as shipments.

CSV has stable headers even for an empty cohort, proper CSV quoting, and apostrophe-prefix protection for formula triggers after whitespace/control characters, including Unicode whitespace. PDF escapes user text and uses flowing paragraphs so long evidence histories can split across pages. The CSV default changes from checkpoint rows to shipment rows; consumers needing events must explicitly choose `report=events`. Generated OpenAPI and TypeScript types describe the new analytics fields.

## Validation

Controlled canonical cohorts exercise matching shipment/API/CSV/PDF totals, full end-day bounds, exact routes, unknown/incomplete SLA, equal-period/zero baselines, same-route sample thresholds, wrong-scope/chain/contract and orphaned events, owner permissions and formula injection. SQLite and the dedicated PostgreSQL regression database cover metric and migration behavior. Real Hardhat/PostgreSQL/API journey and reorganization scripts assert lifecycle timestamps, SLA locks, cohort totals, export counts and removal of orphaned delivery metrics. Browser regressions cover applied filters, missing data, samples and recent pagination.

Production indexing remains disabled under its separate enablement and legacy-history reconciliation gate. Consequently historical production records without canonical evidence show unknown transit/SLA rather than invented performance.
