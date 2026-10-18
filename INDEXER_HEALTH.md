# Indexer startup and health

The API serves public reads while its indexer initializes or catches up. Health
reports actual committed progress against a **confirmation-depth target**. It does
not label the latest chain head finalized, or treat a running thread as proof of
current data. Production indexing remains disabled pending its separate enablement.

## Endpoints

| Endpoint | HTTP 200 | HTTP 503 | Work performed |
| --- | --- | --- | --- |
| `/health/live` | API process responds | Process unavailable | No database, RPC or blocking request-pool work |
| `/health/ready` | Database responds and enabled indexer is current | Database unavailable/timeout, startup, backfill, stopped or degraded worker | Bounded, single-flight database probe; cached worker observations |
| `/health/indexer` | Current worker, progressing backfill, or explicitly disabled indexing | Missing/failed/stalled/stopping worker | Cached observations only |
| `/health` | Compatibility readiness summary | Not ready | Same bounded database probe; no separate RPC request |

Typed responses include the environment, chain and public `RENDER_GIT_COMMIT`
release identity. Indexer details include initialization error class, safe reason,
last poll/success/progress timestamps, observed head, confirmation target, database
cursor, confirmed lag, finality gap, freshness ages, policy and retry delay. Raw
provider exceptions, RPC endpoints and database credentials are never returned or
logged. All health responses include `Cache-Control: no-store`.

`disabled` is intentional and API-ready when the database works; the indexer itself
has `enabled=false` and `ready=false`. It is not mislabeled as a healthy running
indexer. A missing enabled worker is never reported as disabled.

## Worker behavior

- Startup validates the HTTP(S) RPC, chain, nonzero contract addresses, deployed
  bytecode, bundled ABIs and the tracker's registry link. Only a fully validated
  connection is published to the worker.
- First and runtime connection failures retry with capped exponential backoff.
  Provider-internal retries are disabled so they cannot multiply the RPC timeout.
  A successful committed poll resets the retry counter.
- Startup has a separate deadline. Successful polls, cursor progress and head
  changes have separate monotonic clocks. Repeated reads of an unchanged cursor
  or stale RPC head cannot keep readiness green forever.
- Lag is `max(0, confirmed_target - committed_cursor)`, not distance from the
  unconfirmed head. The default allowed lag is zero. If an increased confirmation
  depth leaves a cursor above the target, readiness waits for confirmations;
  existing canonical history is not deleted to satisfy the new depth.
- Quiet Hardhat chains mine on demand and are exempt from head-stall detection.
  A live Sepolia RPC that keeps returning the same head eventually degrades.
- Shutdown checks cancellation between RPC operations, during journaling and before
  commit. Interrupted batches roll back. A thread still stopping is reported as
  stopping and cannot be overlapped by a second thread on the same instance.
- Safe structured `indexer_state_changed` logs are emitted on transitions rather
  than every poll. Notification failure after commit does not undo successful
  indexing or manufacture an RPC failure.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `INDEXER_ENABLED` | Explicitly false in hosted image | Keep production false until its enablement gate |
| `INDEXER_POLL_INTERVAL` | 15 seconds | Poll interval, range 1–3600 |
| `INDEXER_RPC_TIMEOUT` | 10 seconds | Per RPC request, range 1–20; no hidden provider retries |
| `INDEXER_RETRY_INTERVAL` | 5 seconds | Initial retry delay |
| `INDEXER_RETRY_MAX_INTERVAL` | 60 seconds | Retry cap, at least the initial delay |
| `INDEXER_STARTUP_TIMEOUT` | 120 seconds | Maximum starting period without a successful committed poll |
| `INDEXER_STALE_AFTER` | 120 seconds | Poll/progress threshold, effectively at least three poll intervals |
| `INDEXER_HEAD_STALE_AFTER` | 300 seconds | Time without a changed live chain head; zero disables; exempt for chain 31337 |
| `INDEXER_MAX_LAG_BLOCKS` | 0 | Explicit allowed distance behind the confirmation target |
| `INDEXER_CONFIRMATIONS` | 12 | Confirmation-depth policy; local testing uses zero |
| `HEALTH_DATABASE_TIMEOUT` | 2 seconds | HTTP probe wait, greater than zero and at most four |

The database probe permits only one background database check per process and
returns on its deadline. PostgreSQL checks use a transaction-local one-second
statement timeout. Connection timeout/TCP keepalives bound connection recovery;
probe threads are daemon threads and cannot delay process shutdown. A failed
probe does not run DDL, update rows or consume an indexer lease.

## User-visible status

The app shows a compact notice when blockchain data is syncing, delayed or paused,
or when readiness cannot be checked. Current data shows no notice. The public
request has a five-second timeout, runs every 30 seconds only with an active UI,
pauses background-tab polling, and sends no auth token. HTTP 503 remains readable
status data rather than an application crash or a counterfeit claim.

## Render HTTP checks

Use **`/health/live`** as the platform HTTP health-check path for both existing
services. This keeps expected backfill and transient RPC/database outages from
creating restart loops. Use `/health/ready` for release/operational monitoring.

Both existing services were configured through the Dashboard and independently
verified through the Render service API on **October 18, 2026**. Each reports
`serviceDetails.healthCheckPath=/health/live`. The settings pages are:

- [Production settings](https://dashboard.render.com/web/srv-d7rc4opj2pic73f7uudg/settings)
- [Testing settings](https://dashboard.render.com/web/srv-db9sd1vbtjjs73ct4240/settings)

For future changes, use **Health Checks**, save `/health/live`, and read back
`healthCheckPath` through the service API after rollout. Editing the YAML templates
alone does not change these existing services. No paid instance upgrade, new
service or pre-deploy migration is needed. Startup still checks the separately
released schema head.

## Readiness probes and notifications

```bash
python backend/check_health.py --url http://localhost:18000 \
  --environment testing --chain-id 31337 --confirmations 0
python backend/check_health.py --url https://veritras-api-testing.onrender.com \
  --environment testing --expect-indexer enabled
python backend/check_health.py --url https://chainlens-4qvy.onrender.com \
  --environment production --expect-indexer disabled
```

Default is one read-only bounded check. Add `--expected-commit <40-char-sha>` and
`--deadline 600` to wait for a specific release. Exit status is 0 for ready, 1 for
not ready/deadline and 2 for invalid arguments. Output is restricted safe JSON;
URLs, raw HTTP bodies and provider exceptions are not printed.

`Hosted API Readiness` runs on backend changes pushed to `testing`/`main` and by
manual workflow dispatch. It waits up to ten minutes for the exact deployed
commit and the environment's indexing policy, then fails visibly if not ready.
GitHub Actions notification preferences govern notifications from failed runs.
This is a post-deployment observation, not a replacement for PR merge gates or a
guarantee that hosting waits for CI. Continuous runtime alerting remains an opt-in
operations step; no scheduled keep-alive requests or paid monitoring were added.
Free Render services can sleep, so an on-demand cold-start check can initially fail.

## Diagnosis

- `rpc_not_configured` / `invalid_rpc_url`: check the RPC secret's configuration.
- `invalid_contract_address` / `contract_not_deployed` / `chain_mismatch` /
  `tracker_registry_mismatch`: check the environment and deployment manifest.
- `startup_timeout`: inspect initialization, RPC latency and deployment anchor.
- `poll_stale`: a poll has not committed recently; inspect provider/database access.
- `progress_stalled`: successful polls are not advancing a lagging cursor.
- `chain_head_stalled`: compare a second provider's head before switching RPCs.
- `writer_busy`: another process owns the transaction; allow rollout draining, then
  inspect duplicate instances rather than clearing the database lock manually.
- `reconciliation_required`: review canonical identity/history and the anchor using
  the existing dry-run tools. Do not reset cursors or delete journal records.
- Database `timed_out` / `disconnected`: check connectivity and pool saturation.

A progressing backfill can be healthy while not yet API-ready. Wait or extend an
explicit operator probe deadline; do not change the platform path to readiness,
weaken confirmation depth or enable production indexing to silence the signal.

## Acceptance and release evidence

- Release tracked by [PR #20](https://github.com/Oionos/Veritras/pull/20).
- Local: 337 backend tests passed with 3 intentional dialect-specific skips;
  228 frontend tests passed with coverage thresholds. The existing 23 browser
  regressions and three new synchronization-state checks passed. TypeScript and
  production builds passed.
- Real local API/PostgreSQL/Hardhat round trip, chain reorganization and browser
  wallet ownership checks passed. A separate isolated database and controlled RPC
  proxy proved both initial and runtime RPC failure recovery, persisted cursor
  progress and graceful shutdown without changing hosted data.
- Hosted testing source `e100325df5cbe6371c1a02c40cc8915a8f162be2`:
  Render `dep-dba7mn1srm7s73a5p2ig` live; Vercel
  `dpl_DoLNa1adbEHd21aNtki5JfQ4Pkz5` ready. Exact-commit health workflow
  [39109458594](https://github.com/Oionos/Veritras/actions/runs/39109458594) passed.
- The protected preview reported current data with zero confirmed lag and depth
  12, returned no-store health responses, verified the existing delivered product,
  and displayed injected catching-up/degraded/disabled UI states with no browser
  errors or production requests. Structured current-state logs were verified.
- Render HTTP setup completed October 18, 2026: both service settings read back
  `/health/live`. Production and testing each returned HTTP 200 and
  `Cache-Control: no-store` from `/health/live` and `/health/ready`. Production
  served release `664e929` with indexing intentionally disabled; testing served
  `e5d2943` with its indexer current, zero confirmed-target lag and depth 12.
  This independently verifies the platform settings and endpoint responses.
- Final tested source, complete CI results and production deployment references
  are recorded in PR #20. No schema migration or production backfill is included.
