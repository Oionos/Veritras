# Operations

## Signals and privacy

`GET /health/live` is process liveness and remains the Render health path. `GET /health/ready` returns 503 for unavailable database or degraded indexing, with actionable bounded reasons, confirmed-target lag and freshness. Production deliberately expects indexing **disabled**; testing expects an enabled, current indexer. A live process is not proof of current chain projections.

`GET /health/operations` returns readiness plus bounded process-local counters: the last 15 minute buckets of requests/business API 5xx, average header-response latency and cumulative ≤100/500/2000 ms buckets; stream active/open/closed/failure/resync/overflow totals; and bounded browser metric/route aggregates. SSE request duration measures response headers, not stream lifetime. Counters reset on restart, are per process, and are not a durable audit, distributed rate or percentile. No database migration, paid metrics service or extra worker is introduced.

Structured application request logs contain environment, full release SHA when Render supplies it, generated request ID, method, route template, status, header duration and exception class. Query strings, concrete product/shipment IDs, IPs, tokens and request bodies are excluded. An unmatched route is labeled `unmatched`; some router versions report the leaf template. Arbitrary logging extras and exception messages are omitted. The request ID is returned as `X-Request-ID` for incident correlation. Review new logging call sites: do not put user input in the message itself.

Browser telemetry accepts only enumerated metric and route names, finite bounded numbers, environment and validated release SHA. It rejects extra fields, never uses auth headers or cookies, is limited to 60 requests/minute per client, and deduplicates each metric/route for 30 seconds in the client. Demo sends no business/telemetry API calls. Browser counts are untrusted and do not trigger operational alerts. No input text, wallet address, signature, bearer token, product ID, shipment ID, query string or arbitrary error message is sent. No browser telemetry is persisted to Postgres.

Vercel Analytics and Speed Insights strip URL parameters/fragments and replace dynamic IDs with route templates. Optional Sentry loads only when `VITE_SENTRY_DSN` is configured; events have release/environment, route, generic exception type and same-origin built asset frame locations. Requests, users, breadcrumbs, arbitrary context and exception text are dropped. Tracing and **all session replay are disabled**, so there is no recording of forms, wallet prompts, notes or DOM input. External Sentry delivery is not claimed when a DSN is absent. The generic browser error counter remains available without Sentry.

## Scheduled checks

[Operations Monitor](.github/workflows/operations-monitor.yml) runs four times a day at 00:15, 06:15, 12:15 and 18:15 UTC (08:15, 14:15, 20:15 and 02:15 Asia/Manila), and supports manual dispatch. It checks both APIs with a four-minute cold-start grace and requires three successive readiness samples, then checks aggregate API errors and a real SSE heartbeat. The stream client checks named heartbeats, reconnects with bounded backoff, pauses while hidden and displays a disconnected notice. A replay/resync refreshes committed queries after recovery.

The workflow exits nonzero with named conditions and runbook actions for sustained readiness failure, three or more business API 5xx in the retained 15-minute window, malformed diagnostics, or missing SSE heartbeat. Existing readiness checks remain separate. Failures appear in GitHub Actions and its native notification settings; no new email, Slack, webhook or external recipient is configured. Owners can enable GitHub Actions failure notifications in their own GitHub notification preferences. Notification delivery was not tested.

These checks are periodic, not a real-time paging SLA. Free-service cold starts are allowed; no continuous keep-alive is used. Errors between samples, on an earlier process, or outside the retained window can be missed. For a paid pilot with an uptime requirement, first define retention, on-call recipient and escalation preferences, then add durable metrics and an appropriate monitor through a reviewed change.

## Incident response

| Condition | Inspect | Recovery acceptance |
| --- | --- | --- |
| `readiness` | `/health/ready`: database, indexer reason, confirmed-target lag and successful poll age; Render logs for the exact release | Three ready samples; testing indexer current/fresh, or production disabled as configured. Investigate RPC/database/scope before restarting. Never advance a cursor to hide lag. |
| `api_errors` | Request `request_id`, route template, status, exception class and release; deployment and DB availability | Fix cause through protected CI; verify business endpoint behavior and monitor a fresh error window. Browser reports are diagnostic, not authorization to mutate data. |
| `event_stream` | `event_stream_unavailable`, stream failures/overflows, database connection and proxy behavior | Actual named heartbeat, browser reconnect/resync, and committed data refresh. Do not treat reconnect alone as proof of indexer health. |
| `diagnostics` | Exact commit, schema admission, environment and operations response | Typed, correct-environment diagnostics and ready API. No fabricated counters or gate bypass. |
| Schema/cold-start failure | Candidate exact-main CI, image admission, current schema and release | Follow coordinated migration window below. Do not restart an incompatible historical image against the new schema. |

Avoid logging error payloads or sharing unreviewed HAR files, wallet storage, screenshots of secret settings, or temporary preview access links. Preserve safe request IDs, commit and provider deployment IDs in the release record.

## Backup, restore and indexer ownership

Follow [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md) and [DURABLE_INDEXING.md](DURABLE_INDEXING.md). Before DDL, retain a restorable database checkpoint and rehearse on an isolated clone. The local rehearsal acquires the writer lock, dumps/restores and compares schema plus full business/journal/cursor/history fingerprints; its actual result is required alongside unit tests. Hosted production restore acceptance and production backfill remain a separate enablement gate. Do not copy production data into a public preview.

Use one intended indexing owner per chain/registry/tracker scope. The PostgreSQL advisory writer lock and transactional cursor are authoritative; another process must report writer contention and retry rather than writing concurrently. Never delete the lock/cursor or import the obsolete file cursor. A restart must resume the last committed batch once; chain reorganizations rewind/replay transactionally. Production remains disabled until reconciliation, deployment anchor, isolated hosted restore and explicit enablement approval are complete.

A separate paid worker is not justified by the current single-instance free-service demo. If uptime or horizontal API scaling becomes required, design a reviewed worker deployment with one intended owner, the same DB lock, explicit health/lag monitoring and tested shutdown/recovery. Do not enable multiple writers as a scaling shortcut.

## Coordinated migration window

Increment 10 has **no DDL**; schema remains `e93a107bd624`. Increment 9 exposed a restart window when DDL was applied before main CI completed while the old free API was asleep. The old artifact correctly refused the newer schema; the replacement later recovered without data loss. Future strict-head migrations must use this sequence:

1. Rehearse additive SQL on an isolated restore, retain a backup and record current/candidate schema compatibility. Stage and test first. Do not apply production DDL while feature/main CI is pending.
2. Merge through the protected PR, wait for every required exact-main push check, and inspect the candidate Render image build admission. Confirm the prior API is already awake and ready on its expected SHA. A cold, incompatible old image cannot be the handoff safety net.
3. Run `backend/check_migration_window.py --candidate FULL_MAIN_SHA --current FULL_SERVING_API_SHA --url https://chainlens-4qvy.onrender.com --sql-file REVIEWED_SQL_PATH`. It checks exact-main admission first, then current liveness/readiness/identity, and hashes reviewed SQL. Its two-minute evidence is read-only and is not authorization to execute DDL. Recheck if delayed.
4. Confirm the admitted replacement is ready for immediate rollout; coordinate reviewed DDL and runtime handoff in the same window. If the provider cannot guarantee the handoff, use an explicitly scheduled maintenance window or a separately reviewed compatibility release. Do not apply early and hope CI finishes. An awake old process reduces the cold-start risk but cannot guarantee uninterrupted service if it crashes.
5. Verify new exact release, schema, `/health/ready`, frontend attestation and unchanged business fingerprints. Retain evidence. Use corrective migrations or a rehearsed isolated restore; never weaken schema admission or run destructive downgrades.
