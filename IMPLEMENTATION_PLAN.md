# Veritras implementation plan

Originally prepared October 17, 2026 from [PROJECT_REVIEW.md](PROJECT_REVIEW.md). **Status updated October 18, 2026 from released `main` at `664e929` and the validated registration lifecycle increment in PR #21.** This update includes durable indexing, canonical product identity, indexer startup and health, local and hosted acceptance checks, and independently verified Render HTTP health settings.

## Status at a glance

**The testing environment and wallet security are delivered. The complete reliable-demo milestone is still open.** Durable indexing is complete with local and hosted recovery/persistence coverage; canonical product identity is complete with local and hosted testing acceptance. Hosted rollout evidence is recorded in [DURABLE_INDEXING.md](DURABLE_INDEXING.md).

Status meanings: **Done** = implemented and validated for the stated scope; **Partial** = some work delivered with remaining acceptance criteria; **Pending** = planned work remains; **Deferred** = after the reliable-demo milestone. Partial work is not currently being implemented simply because it is listed here.

Priority meanings: **P0 — release blocker** must be resolved before enabling production indexing/backfill; **P1 — important next** protects correctness or trust; **P2 — later** improves usability and operations after those foundations.

| Workstream | Status | Priority | Delivered / remaining |
| --- | --- | --- | --- |
| Isolated local and hosted testing | **Done** | Maintain | Separate database, API, Sepolia contracts, protected Vercel Preview, exact sign-in origins; full journey checked |
| Wallet sign-in and write permissions | **Done** | Maintain | Persistent SIWE challenges, scoped tokens, owner-only API writes, browser session handling |
| Indexer startup and health | **Done** | **P1 addressed** | Bounded startup/retries/shutdown, confirmed-progress health, app notices and release probes; `/health/live` verified on both existing Render services |
| Canonical product identity (increment 3) | **Done** | **P1 addressed** | Scoped identities, lifecycle timestamps, legacy aliases/reconciliation and one-shipment constraint; see [runbook](CANONICAL_PRODUCT_IDENTITY.md) |
| Durable indexing (increment 4) | **Done** | **P0 addressed** | Transactional journal/cursor, ordered reversible projections, confirmation policy, single-writer lock, metadata events and resilient notifications; production enablement remains a separate gate |
| Registration lifecycle and evidence (increment 5) | **Done** | **P1 addressed** | Persisted submissions, checked replacements/cancellations, reload recovery, typed receipt/journal evidence and signed metadata/history; see [runbook](REGISTRATION_LIFECYCLE.md) |
| Analytics and exports (increment 6) | **Done** | **P1 addressed** | Canonical shipment cohorts/lifecycle, optional locked SLA, real route/sample metrics, UTC filters and safe matching exports; see [runbook](ANALYTICS.md) |
| Integration and release controls (increment 7) | **Partial** | P1 | Real local/browser/Sepolia journeys and CI delivered; failure/reorg coverage, enforced release gates and recovery runbook remain |
| QR verification, shipment detail and guided demo (increment 8) | **Pending** | P2 | Public verification exists; direct product links, QR labels, unified detail and guided/mobile journey remain |
| Shipment exceptions (increment 9) | **Pending** | P2 | Depends on trustworthy lifecycle timestamps, SLA definitions and synchronization |
| Performance and operations (increment 10) | **Pending** | P2 | Existing lazy routes/Lighthouse checks provide a baseline; measured optimization and operational completion remain |
| Business pilot integrations | **Deferred** | Later | Organizations, evidence files, imports, standards integrations and repeated journeys |

### Urgent safeguards and next actions

1. **Keep production `INDEXER_ENABLED=false`.** The new indexer has durable database progress and reorganization recovery. Production enablement still requires its reviewed deployment anchor, identity/history reconciliation and release checks; implementation alone does not authorize a backfill.
2. **Registration lifecycle and evidence are delivered.** Preserve the checked transaction/journal evidence and reload recovery guarantees. Production backfill remains behind its separate enablement gate.
3. **Analytics and exports are implemented.** Preserve canonical evidence and explicit sample/exclusion counts. Historical SLA stays unknown; product creation is labelled separately. See [ANALYTICS.md](ANALYTICS.md) for definitions, UTC creation cohorts and CSV compatibility changes.
4. **Finish release enforcement.** CI workflows exist and passed for the released changes. Required branch checks and hosting behavior when CI fails still need explicit verification/configuration; both production hosts currently auto-deploy from `main`.
5. **Preserve testing isolation and free-tier limits.** Use the stable `testing` preview for full-stack checks. Production and testing Render services share the workspace's 750 free instance hours/month; avoid continuous keep-alive pings. See [HOSTED_TESTING.md](HOSTED_TESTING.md).

### Completed releases and evidence

| Release | Main commit | Completed work |
| --- | --- | --- |
| [PR #15](https://github.com/Oionos/Veritras/pull/15) | `70a4a1e` | Local isolated stack, environment guards, startup/health repairs, initial identity/status matching and receipt verification |
| [PR #16](https://github.com/Oionos/Veritras/pull/16) | `e493afb` | Wallet authentication, ownership enforcement, shared sessions and guarded schema adoption/migration; released to Vercel and Render |
| [PR #17](https://github.com/Oionos/Veritras/pull/17) | `33c4745` | Hosted testing resources, Preview repair, unique source-event identities and replay regressions; released to Vercel and Render |

Latest durable-indexing validation: **236 backend tests, 192 frontend tests, 23 Playwright regressions and 40 contract tests passed**, plus builds, generated-type checks, Lighthouse and real local integration/browser journeys. Hosted Sepolia registration → checkpoints → custody → delivery passed; a same-code testing redeploy preserved event counts. The backend matrix covers SQLite and PostgreSQL, with two intentional skips for PostgreSQL-only checks in the SQLite variant. A real local chain fork/recovery and hosted same-code redeploy also passed.

Released schema before this increment: `c72b53d91e04`. The durable-indexing migration is `f04d9c21a873`, applied in hosted testing and rehearsed on an isolated production copy without changing business counts or granting ownership. Production code/schema rollout is tracked by [PR #18](https://github.com/Oionos/Veritras/pull/18); production indexing remains explicitly disabled. Testing uses a dedicated Neon project/database (`Veritras Testing` / `veritras_preview`), a separate Render API and distinct Sepolia contracts. Setup and resource details: [TESTING.md](TESTING.md), [HOSTED_TESTING.md](HOSTED_TESTING.md), [AUTHENTICATION.md](AUTHENTICATION.md).

## Goal and completion criteria

Deliver a reliable supply chain demonstration in which a manufacturer registers an item, creates its shipment, records checkpoints, transfers custody, completes delivery, and shares independently inspectable registration evidence. The contract, API, user interface, and reports must agree about that item.

The first release is complete when:

- [x] Feature previews use API, database, and contract state isolated from production. Feature previews share one testing backend; they are not isolated from one another.
- [x] Signed login works, and API writes enforce ownership.
- [x] Receipt-backed checks prevent database-only drafts and placeholder transaction fields from receiving verified registration.
- [x] Confirmed events reconcile into one product and one shipment lifecycle under explicit canonical identities and database constraints.
- [x] Journal, projections and cursor commit atomically; restart/replay and reorganization recovery are implemented and validated against SQLite, PostgreSQL and the real local chain. Conflicting legacy data stops for review.
- [ ] Shipment status and analytics reflect indexed events, with no unlabeled example metrics.
- [x] A complete journey passes through the browser, API, database, and local contracts, followed by a Sepolia check in testing.
- [ ] Production indexing/backfill passes identity reconciliation, durable recovery and release-control acceptance checks before enablement.

## Working decisions

1. Retain React/Vite, FastAPI, SQLAlchemy, Neon, Vercel, Render, and the current contracts for the first release.
2. Use `main` for production and short-lived feature branches with pull requests and Vercel Previews.
3. Use the provisioned shared testing API and a dedicated Neon testing project/database. Deploy matching frontend/backend code through the persistent `testing` branch. Introduce per-PR services only when concurrent work requires them.
4. Keep a single indexer owner. API replica scaling requires a separate worker or leadership lock first.
5. Model one shipment lifecycle per tracked item, matching the existing product-keyed contract. Repeated journeys require a separately planned contract version keyed by shipment ID.
6. Preserve existing public product IDs and already registered bytes32 values. Store their relationship explicitly.
7. Treat manufacturer identity and physical-item authenticity as separate evidence from blockchain registration.
8. Keep public verification available without wallet login; require authentication and ownership for mutations.

## Remaining delivery sequence

The numbers below are **plan increment IDs**, not actual GitHub pull request numbers. Initial increments were combined across PRs #15–17. Detailed sections retain the full intended scope; each status note distinguishes delivered work from remaining tasks.

| Increment | Status / priority | Suggested branch | Remaining deliverable | Depends on |
| --- | --- | --- | --- | --- |
| 0 | Partial / P1 | Follow-up release controls | Testing setup done; verify/enforce CI and deployment gates | None |
| 1 | **Done / P1 addressed** | Released in #20 | Maintain startup, recovery and health guarantees; both Render HTTP paths verified; see [health runbook](INDEXER_HEALTH.md) | Finality policy from 4 |
| 2 | **Done** | Released in #16 | Maintain authentication and authorization | 0 environment setup |
| 3 | **Done / P1 addressed** | `codex/canonical-product-identity` | Maintain identity/reconciliation guarantees; release tracked in PR #19 | 2 |
| 4 | **Done / P0 addressed** | `codex/durable-chain-indexing` | Maintain recovery guarantees; production enablement remains a separate gate | Scoped identity binding included; broader increment 3 remains |
| 5 | **Done / P1 addressed** | `codex/registration-lifecycle-evidence` | Maintain durable transaction recovery, checked evidence and metadata history; release tracked in PR #21 | 2–4 |
| 6 | **Done / P1 addressed** | `codex/truthful-analytics-and-exports` | Maintain canonical cohorts, SLA exclusions and safe matching exports; release tracked in PR #22 | 3–5 delivered |
| 7 | Partial / P1 | `test/complete-provenance-flow` | Failure/reorg coverage, enforced gates and recovery runbook | 2–6 for final acceptance |
| 8 | Pending / P2 | `feat/qr-verification-and-demo` | QR links, unified shipment detail, mobile and guided demo | 5 and 7 |
| 9 | Pending / P2 | `feat/shipment-exceptions` | Expected arrival, overdue and dwell exception list | 6–8 |
| 10 | Pending / P2 | `perf/frontend-and-operations` | Measured loading improvements and operational cleanup | Stable reliable-demo milestone |

Tests and migration checks belong in each implementation PR. PR 7 assembles the complete flow and release gates; it is not the first testing work.

## PR 0 — Establish isolated testing

**Status: testing environment done; release controls partial. Priority: P1 for remaining controls.**

Delivered: local Compose isolation; a dedicated hosted Neon project/database and Render testing API; separate Sepolia contracts and manifest; scoped Vercel Preview configuration; exact CORS/SIWE origins; protected preview access; documented `feature → testing → main` workflow. Real hosted writes and chain actions were checked without changing production business data. Remaining: verify/enforce required merge checks and deployment release gates. Production auto-deploy is enabled; successful historical CI alone does not establish enforcement.

**Tasks**

- Record the actual production frontend/backend deployment commits, runtime versions, database migration state, contract addresses, and deployment blocks using logs and non-secret metadata. Reconcile differences from the repository configuration.
- Maintain the dedicated Neon testing project/branch/database and Render testing service with production-like validation, distinct environment identifiers and separate secrets. This was provisioned without copying production rows.
- Deploy the existing contracts to local Hardhat for integration work and separate Sepolia addresses for hosted testing. Record addresses, chain IDs, ABIs, and deployment blocks in a reproducible manifest.
- Configure Vercel Preview variables to target the testing API and contracts. Generate/configure CSP for the selected API origin; configure the testing backend with the intended preview origins. Keep production CORS limited to production clients.
- Ensure SIWE origin configuration follows the same environment selection. Use explicit preview hosts or a narrowly scoped project-specific rule, rather than allowing arbitrary hosted domains.
- Document `main` as the production branch and require relevant CI checks for merges. Set production auto-deployment to respect the chosen release gates on both hosting providers.
- Add an environment setup guide and examples containing placeholders only.

**Primary files:** `frontend/index.html`, `frontend/src/config/env.ts`, `frontend/src/config/contracts.ts`, `frontend/src/config/wagmi.ts`, `backend/app/core/config.py`, `render.yaml`, `.github/workflows/ci.yml`, environment examples, deployment documentation.

**Acceptance:** a preview can read/write a labeled test record without changing live database records or using live contract addresses. API calls, wallet connections, and signed login requests are permitted by the intended CSP/CORS/origin settings.

## PR 1 — Restore indexer startup and truthful health reporting

**Status: Done, including local/hosted acceptance and verified Render HTTP settings. Priority: P1 addressed.**

Delivered: bundled ABI loading and locked dependencies; validated chain/contract startup; capped exponential retries without hidden provider retries; cancellation and transactional shutdown rollback; typed cached confirmed-target health; startup, poll, cursor-progress and head freshness checks; bounded database probing; consistent disabled/failed states; app synchronization notices; structured transition logs; and bounded deployment/manual readiness workflows. Real local startup/runtime RPC failures recovered against Hardhat and PostgreSQL. On October 18, 2026, both existing Render services were independently read back with `healthCheckPath=/health/live` after the Dashboard changes. Both liveness and readiness endpoints returned HTTP 200 with `Cache-Control: no-store`; the testing indexer was current with zero confirmed-target lag. Continuous runtime alerting remains opt-in under the free-tier constraints. See [INDEXER_HEALTH.md](INDEXER_HEALTH.md). Production backfill remains disabled.

**Tasks**

- Decode bundled ABI files with explicit encoding and normalize generated artifacts to UTF-8 without a BOM. Add a check that parses the real bundled ABI files.
- Select a supported Web3.py version, update event-log keyword arguments to that version, and lock compatible backend dependencies. Separate development dependencies from the deployed runtime.
- Add explicit indexer enablement and configuration validation, bounded RPC timeouts, startup retries with backoff, and interruptible shutdown.
- Expose initialization error, last successful poll, indexed block, observed chain head, target confirmed/finalized head, and lag. Redact RPC credentials from errors.
- Define basic liveness separately from dependency/indexer readiness. Report indexing as starting, catching up, current, or degraded; require actual progress rather than only a running thread.
- Configure the platform health check and monitoring so expected initial backfill does not create a restart loop. API/UI readiness should still expose catching-up or failed indexing accurately.
- Immediately remove unconditional “Blockchain Verified” displays and the claim that an unindexed/missing record implies a counterfeit item. Until full evidence checks land, return a conservative unverified/unavailable result rather than trusting database existence or placeholder transaction fields.

**Primary files:** `backend/app/services/indexer.py`, `backend/app/main.py`, `backend/app/core/config.py`, ABI files, backend requirements, `frontend/src/pages/Products.tsx`, `frontend/src/pages/Verify.tsx`, verification schemas.

**Acceptance:** real ABI loading succeeds; simulated initial RPC failure recovers; stopped/stalled indexing is visible in readiness; a database-only product cannot receive a verified badge. Exercise startup recovery against test contracts. Production backfill waits for PRs 3–4.

## PR 2 — Fix authentication and enforce ownership

**Status: done and released in #16. Priority: maintain.**

All tasks below are implemented: persistent single-use scoped SIWE challenges and expiry cleanup, strict token policy and hosted secrets, shared session invalidation, signed ownership and object-level write authorization, legacy read-only handling, and rejection of SQL edits to registered chain-controlled fields. Security regressions, local real-wallet journeys and hosted checks passed. See [AUTHENTICATION.md](AUTHENTICATION.md). Contract-wallet sign-in and server-side token revocation are separate future scope.

**Tasks**

- Consume the API's typed `access_token` response and reject missing/invalid token responses before storing anything. Clear previously persisted invalid token strings.
- Use a maintained SIWE parser/verifier and validate expected domain, URI, chain, issued-at/expiry, nonce, and signature. Issue challenges with server-controlled scope and lifetime; consume valid challenges atomically once.
- Persist challenges in PostgreSQL with expiry and cleanup, avoiding additional infrastructure for this release. Validate signature and scope before atomically consuming the challenge so invalid submissions cannot consume another valid attempt.
- Require an explicit strong JWT secret in production-like environments, validate JWT subject/expiry/issuer/audience, and keep the signing algorithm fixed by server configuration.
- Add a shared frontend auth state so login/logout changes propagate in the same tab. Clear local session state on wallet disconnect, account change, expiry, and rejected credentials. Do not describe local logout as server-side token revocation.
- Add authentication dependencies and object-level authorization to product and shipment mutations. Derive new draft ownership/manufacturer from the authenticated wallet. Use the product owner for shipment planning edits; checkpoint/custody permissions remain enforced by the contracts and are reflected in the UI.
- Distinguish untrusted legacy manufacturer fields from ownership established by a signed draft creation or verified contract event. Existing records need explicit reconciliation before edit rights are granted solely from their stored manufacturer field.
- Keep confirmed on-chain manufacturer/name/description immutable through database edits; direct mutable metadata changes through the contract update flow.

**Primary files:** backend auth/security/config/routes/schemas, a nonce/challenge model and Alembic revision, `frontend/src/hooks/useAuth.ts`, `frontend/src/components/ConnectAndAuth.tsx`, `frontend/src/hooks/useApi.ts`, generated API types.

**Acceptance:** a signed login authorizes an owner action; missing/expired tokens produce 401; another wallet's mutation produces 403; wrong-origin, wrong-chain, expired, and replayed challenges fail. Switching wallets clears the previous session.

## PR 3 — Introduce canonical identity and migration discipline

**Status: done — implementation and local/hosted validation. Priority: P1 addressed.**

Delivered ahead of this increment: frontend/backend bytes32 conversion helpers, display/hex draft lookup with conflict detection, explicit ownership provenance, packaged Alembic migrations, guarded baseline inspection/adoption, startup migrations and disabled hosted `create_all`. Production adoption and additive migrations were rehearsed before release.

Delivered in this increment: persisted chain/registry/tracker/bytes32 identity, scoped uniqueness and collision retries; shared conversion fixtures; atomic dry-run/apply reconciliation with retained duplicate archives and public URL aliases; one-shipment-per-item database enforcement; separate creation/registration timestamps and lifecycle states; stored-identity contract actions; and an explicit schema release stage with read-only API startup checks. Local PostgreSQL/SQLite regressions, real chain round trip, reorganization recovery and browser ownership checks passed. Migration rehearsal on a production Neon copy passed. Hosted testing and main rollout evidence are recorded in [CANONICAL_PRODUCT_IDENTITY.md](CANONICAL_PRODUCT_IDENTITY.md).

**Schema and behavior**

- Retain `product_id` as the stable public/display ID. Add canonical `on_chain_product_id`, `chain_id`, registry address, explicit ownership provenance, and registration lifecycle fields.
- Derive new canonical IDs using the existing UTF-8/right-padded bytes32 convention for compatible display IDs. Accept valid bytes32 input directly; never encode the text of an existing hex value again. Keep one shared frontend conversion utility and an equivalent backend conversion with shared fixtures.
- Uniquely constrain registered identities by chain, registry address, and canonical product ID. Handle display-ID collision retries explicitly.
- Create an idempotent reconciliation command with a dry-run report. Match legacy display/hex rows only when IDs and evidence agree, update dependent relationships, and flag conflicting rows for review rather than merging by name.
- Enforce one shipment per tracked item with a database constraint after inspecting and reconciling existing duplicates. Tie each shipment to the product's chain/tracker configuration.
- Define which fields are editable drafts, operational shipment fields, or chain-derived immutable data. Keep registration timestamps separate from draft creation time.
- Package the Alembic directory in the backend image and run migrations as a distinct release step. Disable automatic schema creation in production-like environments.
- Inspect the real schema before establishing an Alembic baseline: do not blindly stamp or replay the initial migration against tables previously created with `create_all`.

**Primary files:** backend models/schemas/routes, incremental Alembic revisions, reconciliation command, `backend/Dockerfile`, product/shipment pages and ID utilities.

**Acceptance:** a display ID survives a contract round trip, an indexed event updates the same product, legacy URLs remain resolvable, and a second shipment is rejected clearly. Migrations work on a fresh database and a clone of the existing schema/data; reconciliation is safe to rerun.

## PR 4 — Make indexing durable and synchronize shipments

**Status: done — implementation and local/hosted validation. Priority: P0 addressed.**

Delivered: database cursor and canonical block anchors; retained event journal with unique canonical identities; atomic journal/projection/cursor batches; ordered metadata/checkpoint/custody/delivery processing; transaction-level single-writer locking; confirmation-depth policy; canonical ancestor detection and transactional projection rebuild; exact legacy-history attribution with dry-run/apply safeguards; bounded SSE queues, heartbeat/reconnect resync and cross-process commit detection. Old file cursors are ignored.

Validated: interruption/rollback, restart persistence, competing PostgreSQL writers and process-loss lock release, registration re-inclusion, orphan metadata/custody/delivery recovery, malformed delivery pairs, stale RPC heads and bounded-recovery stops. The real local PostgreSQL/API/Hardhat fork/recovery and full journey passed. The additive migration preserved the production copy's product/shipment with zero ownership bindings. See [DURABLE_INDEXING.md](DURABLE_INDEXING.md).

Hosted acceptance passed: 12 canonical journal events, two products, six unique checkpoints, two unique custody transfers and a delivered shipment. Same-code Render redeploy preserved counts and resumed database progress. The protected Vercel preview verified the delivered record without browser errors or production API requests. Code/schema release is tracked by PR #18. Production indexing stays disabled until the separate identity/history reconciliation and explicit enablement checks are complete. Increment 3 now adds canonical public identity and explicit dry-run/apply reconciliation; runtime conflicts still stop the indexer for review.

**Tasks**

- Add a chain-event journal with chain ID, contract, transaction hash, log index, block number/hash, transaction index, event type/payload, canonical flag, and processing metadata.
- Add a database cursor scoped to chain and contract configuration. Initialize from the deployment block inclusively; define the initial last-processed block as deployment block minus one.
- Fetch bounded/adaptive block ranges and merge logs into `(block_number, transaction_index, log_index)` order. Include `ProductMetadataUpdated` events.
- Persist journal entries, product/checkpoint/custody/shipment projections, and cursor progress in the same database transaction for the processed batch. Propagate persistence failures so progress cannot advance past a failed event.
- Deduplicate event identity by chain, contract, transaction hash, and log index. Handle re-included events through block/canonical metadata rather than adding duplicate business records.
- Build one checkpoint from `CheckpointRecorded`; use `DeliveryCompleted` to validate/derive delivery state without generating another checkpoint. Maintain shipment status and current handler from the ordered canonical events.
- Use an explicit confirmation/finality policy. Detect changed stored block hashes, rewind to a known canonical ancestor, invalidate affected logs, and rebuild affected projections before resuming. Expose the selected policy in verification responses.
- Recover legacy derived records by comparing/replaying authoritative logs after reconciliation; do not infer missing log indexes from transaction hash alone.
- Publish committed change notifications to the frontend, including checkpoint, custody, metadata, and shipment updates. Add SSE heartbeat, bounded subscriber queues, reconnect behavior, and relevant query invalidation.

**Acceptance:** replay and restart create no duplicates; an interrupted database write leaves the cursor unchanged; delivery adds one checkpoint; the shipment list/detail/KPIs converge to the same state; a simulated reorganization removes superseded projected data and resumes correctly.

## PR 5 — Implement evidence-based registration and verification

**Status: Done; local full-stack/browser and hosted API acceptance passed. Priority: P1 addressed.**

Delivered: verification checks successful receipt, chain, registry destination/emitter, block reference, canonical product ID, manufacturer and registered name; database presence alone cannot verify. The UI distinguishes transaction submission and exposes pending/confirmation state in memory. Increment 4 adds typed verification policy/indexed-block/last-sync fields and canonical block/depth checks. Local and hosted valid registrations were checked.

Implemented in this increment: persistent transaction attempts and payload snapshots; idempotent owner submissions; receipt/input/event/nonce validation; confirmation-depth and canonical-journal checks; retry/replacement/cancellation tracking; browser outbox and reload recovery; typed explanatory evidence with transaction/block references; separate synchronization health; manufacturer-signed metadata updates and canonical/orphaned history. Final acceptance and release evidence: [REGISTRATION_LIFECYCLE.md](REGISTRATION_LIFECYCLE.md).

**Tasks**

- Represent transaction progress separately from synchronization health: draft → submitted → confirmed/indexing → indexed, with failed/replaced transaction handling; track stale/degraded synchronization independently.
- Add an authenticated registration submission endpoint accepting a transaction hash for an owned product. Treat this as an untrusted submission until the backend checks chain, destination contract, receipt success, event ID, and manufacturer against the expected product.
- Persist submissions so reloading/closing the browser does not lose progress. Reconcile transaction replacement and reverted receipts; allow a failed registration to be retried without creating another product.
- Define a typed verification response containing registration status, evidence status/reason, chain/contract/canonical ID, transaction/block reference, confirmation/finality policy, manufacturer, and last successful synchronization time.
- Require a successful matching registration event under the selected policy before reporting verified registration. Use evidence states for pending, unavailable, not found, and mismatched records. Do not report that a genuine physical item has been authenticated by checking registration alone.
- Replace unconditional badges, update success toasts to distinguish submission from confirmation, offer explorer links, and invalidate/refetch queries after indexing catches up.
- Route metadata updates through manufacturer-signed contract transactions; show the confirmed indexed value and preserve version/event history.

**Acceptance:** a draft, invented hash, reverted receipt, wrong-contract transaction, or mismatched product event cannot verify. A valid indexed registration does verify with inspectable evidence. API outage or indexer lag produces an explanatory state rather than a false positive or counterfeit claim.

## PR 6 — Replace placeholder analytics and repair exports

**Status: complete implementation, local validation and hosted testing acceptance. Priority: P1 addressed.**

Delivered: canonical shipment lifecycle from the durable event journal; nullable timezone-aware expected arrival with owner-only pre-departure edits; completed transit/SLA/active elapsed and explicit exclusions; real normalized route aggregates and same-route anomaly sample thresholds; shared validated UTC creation/date/route filters; safe shipment/event CSV and shipment PDF with matching evidence/counts; recent-product pagination and removal of illustrative totals/trends/charts. Migration `c62a904df318` preserves historical unknown SLA. Definitions and compatibility changes: [ANALYTICS.md](ANALYTICS.md).

Local release validation: **400 backend tests passed** (three intentional dialect skips), **240 frontend tests passed** with coverage thresholds satisfied, **29 Playwright regressions** and **40 contract tests passed**. The real isolated API/PostgreSQL/Hardhat journey, SLA/analytics/export assertions, canonical fork recovery and browser downloads are exercised by the integration workflow. The final additive migration was rehearsed on the isolated production copy without changing its one shipment or inventing SLA values. Hosted testing acceptance passed: 2 shipment records, 1 delivered/transit sample, no known SLA samples, and 6 canonical events. Filtered browser CSV/API counts matched; PDF and mobile checks passed without browser errors. Exact-head CI is required before main release.

**Metric definitions**

| Metric | Definition |
| --- | --- |
| Total / active / delivered | Counts of actual shipment records; delivered state derives from indexed delivery |
| Transit duration | First departure to delivery for completed shipments with both timestamps; report incomplete samples separately |
| On-time rate | Completed journeys with a known pre-departure expected arrival delivered by that instant, divided by completed journeys with a known expected arrival; incomplete and unknown-SLA samples are reported separately |
| Active elapsed time | Time since departure for an undelivered shipment; kept separate from completed transit duration |
| Dwell | Time between defined arrival/departure events at a normalized location; until those events exist, label checkpoint intervals as checkpoint intervals |
| Trend | Change between equal explicit periods; return unavailable where the previous period has no valid comparison |

**Tasks**

- Add expected arrival and the required lifecycle timestamps. Historical shipments without an SLA remain unknown rather than receiving an invented 72-hour deadline.
- Remove fixed dashboard totals, KPI trends, route volumes, and delay bars. Return real grouped aggregates or clearly labeled missing data.
- Consume paginated product responses correctly and request recent items with an explicit descending sort and limit.
- Apply date/route filters consistently; store UTC instants and label display timezone. Validate export dates and use a documented half-open interval so end dates include the intended full day.
- Export actual shipments/events with consistent counts, evidence references, and CSV formula-injection protection for user-provided text. Add product reports only under product-specific labels.
- Keep anomaly rules explainable and include sample sizes. Suppress statistical outlier claims for insufficient or mixed-route samples.

**Acceptance:** a controlled dataset produces matching UI/API/export totals; incomplete and unknown-SLA journeys cannot inflate on-time performance; empty data and zero baselines are clear; all illustrative data is explicitly separated into demo mode.

## PR 7 — Complete integration coverage and release controls

**Status: partial; substantial validation already delivered. Priority: P1, alongside every remaining increment.**

Delivered: reproducible PostgreSQL/Hardhat/API/frontend stack; real registration/checkpoint/custody/delivery integration; real Chromium authentication/ownership checks; challenge persistence after restart; replay/deduplication regressions; backend/frontend/contract/browser/build CI, generated-type checks and a Python-application-to-OpenAPI drift check; migration rehearsals; dedicated-wallet hosted Sepolia journey. Latest recorded suite counts are listed above.

Remaining: database-write interruption and reorganization recovery acceptance tests after increment 4; verify/enforce required merge/deployment gates; document and rehearse the full release/backfill/recovery runbook. Do not count the existing complete happy-path journey as completion of these recovery criteria.

**Tasks**

- Start PostgreSQL, local Hardhat contracts, the API/indexer, and the frontend in a reproducible test environment. Generate contract configuration from the test deployment manifest.
- Exercise manufacturer A registering a draft, confirming registration, initiating tracking, transferring to handler B, receiving subsequent checkpoints, and completing delivery. Verify evidence and consistent counts through the real API and UI.
- Include draft verification, unauthorized edits/checkpoints, transaction reverts, indexer restart/replay, persistence failure, and reorganization recovery. Existing UI mocks remain useful for isolated presentation tests.
- Generate OpenAPI from the Python application with safe CI configuration, then generate TypeScript and reject schema/type drift. Add typed product detail and verification responses.
- Run relevant backend, contract, frontend, integration, build, and migration checks as required PR checks. Record the tested commit and environment.
- Test one real Sepolia journey using dedicated test wallets/contracts after local checks pass. Keep test keys isolated from normal developer and production accounts.
- Document release ordering, configuration verification, readiness thresholds, migration/backfill steps, and rollback. Release backward-compatible API/schema changes before dependent frontend changes.

**Acceptance:** the whole journey passes without mocking the business API or contract events. Failed checks prevent merging/releasing; a restart resumes from durable progress; the test environment remains isolated.

## PRs 8–10 — Improve the usable product

### PR 8: QR verification, shipment detail, and guided demo

**Status: pending; existing public verification and branding are foundations. Priority: P2.** Public `/verify` lookup works, but `/verify/:productId`, downloadable QR labels, unified shipment detail and a complete guided/mobile journey remain. Existing owner/handler controls came from increment 2; mobile wallet and accessibility acceptance still need dedicated work.

- Add `/verify/:productId` links with direct loading and downloadable QR labels. A phone's native camera can open the link; a custom in-app scanner is optional later.
- Build a unified shipment detail view with checkpoint/custody history, current handler, registration evidence, synchronization status, and only the actions allowed for the connected account/current state.
- Add mobile wallet access; complete modal naming, focus management, Escape handling, scrolling, and reduced-motion support.
- Provide a clearly labeled seeded demo journey, onboarding for wallet connection/sign-in/test ETH, and useful retry/empty states. Keep demo data separate from live aggregates.
- Update branding/favicon, route metadata, READMEs, environment documentation, and missing-route handling.

**Acceptance:** a visitor can open a QR link without a wallet, follow the complete evidence timeline, and use wallet actions on a narrow mobile viewport. Keyboard navigation works through dialogs and forms.

### PR 9: Shipment exception list

**Status: pending. Priority: P2, after trustworthy metrics and synchronization.** Existing anomaly calculations do not satisfy the planned deduplicated, acknowledged exception lifecycle.

- Add configurable expected arrival and checkpoint-interval/dwell thresholds with explicit meanings.
- Show overdue shipments, stale checkpoint activity, and unresolved custody handoffs in an in-app exception list.
- Make exceptions reproducible, deduplicated, and resolved when conditions change. Do not treat a stale indexer as proof of a delayed shipment.
- Add acknowledgement and links to the affected shipment. External email/webhook notifications are a later integration with explicit delivery/retry preferences.

**Acceptance:** controlled clock/data scenarios open, update, and resolve the expected exceptions without duplicate alerts.

### PR 10: Performance and operations

**Status: pending completion. Priority: P2.** Existing lazy routes, error reporting configuration and Lighthouse CI are a baseline. Measured optimization, environment-aware observability, readiness alerts and rehearsed backup/restore remain.

- Measure mobile loading and interaction before changing bundles; investigate wallet/provider startup, chart imports, and unnecessary SDK loading.
- Defer optional wallet/chart code where measurements justify it. Compare before/after Lighthouse and field metrics using the same scenario.
- Configure release/environment labels for error tracking, appropriate replay masking, and monitoring for indexer lag, API failures, and event-stream health.
- Document backup/restore and single-indexer ownership. Split the indexer into a worker only if uptime/scaling requirements justify the additional service.

**Acceptance:** performance improvements have measured evidence; error reporting excludes sensitive input; indexing and API degradation are actionable and observable.

## Migration, backfill, and release procedure

1. Inspect production deployment/schema state and record a restorable database checkpoint. Rehearse on an isolated database copy first.
2. Apply additive migrations and deploy compatible backend code. Keep any old cursor/projection writer paused while reconciling identities or rebuilding event projections.
3. Run reconciliation in dry-run mode, inspect conflicts, then apply validated changes. Add uniqueness/non-null constraints only after conflicting data is resolved.
4. Load/replay confirmed canonical logs in bounded ranges from each configured deployment block, validating receipt identities and projection counts. Persist progress transactionally.
5. Confirm readiness, indexing progress, permissions, verification results, and analytics. Deploy the compatible frontend against the intended environment.
6. Execute the complete acceptance journey in testing and verify the staged production configuration before publishing the release. A production deployment/promotion is a separate action from writing this plan.
7. Monitor the released commit for API errors, indexing lag, unexpected duplicate records, and verification mismatches.

Application rollback should use a version compatible with the additive schema. Avoid destructive database downgrades; use corrective migrations or a rehearsed restore when necessary. Already mined transactions remain on-chain. Fix/rebuild their database projections rather than promising that an application rollback reverses them.

## Later business-pilot backlog

After the reliable demo is complete and a specific user workflow has been validated:

- Verified manufacturer/organization profiles and memberships.
- Evidence uploads with content hashes, availability/pinning, access rules, and retention.
- CSV/batch import with idempotency and row-level error reporting.
- GS1 Digital Link identifiers and EPCIS event import/export driven by an actual integration partner.
- A contract version for repeated shipment journeys, including address/version rollout and existing-item transition.
- Optional notification integrations and route-specific analytics based on enough real observations.

## Next implementation session

Prioritize **production indexing enablement validation** and **increment 7: release-gate enforcement and the recovery runbook**. Increments 5 (transaction lifecycle/evidence) and 6 (truthful analytics/exports) are delivered. Production indexing/backfill still requires its reviewed deployment anchor, identity/history dry run and explicit enablement. Keep that gate separate from ordinary application releases.

Preserve analytics definitions and sample/exclusion counts during subsequent work. Keep production indexing enablement and release-gate configuration as explicit reviewed changes.

For each implementation PR, record changed behavior, tested commit, validation results, migration/configuration requirements and remaining acceptance criteria. Update this status dashboard after release. Completing a subset of tasks does not close the increment until its remaining acceptance criteria pass.
