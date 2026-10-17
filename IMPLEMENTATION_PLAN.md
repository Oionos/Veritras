# Veritras implementation plan

Prepared October 17, 2026. Based on [PROJECT_REVIEW.md](PROJECT_REVIEW.md) and repository checkout `9b06a15`.

Implementation started on `codex/isolated-testing-environment`. The local stack, preview configuration guards, indexer startup/health fixes, receipt checks, and initial ID/status reconciliation are implemented. Hosted Neon/Render provisioning is pending service access and a separate Sepolia test deployment. See [TESTING.md](TESTING.md) for commands, validation, and remaining boundaries; subsequent PRs below remain planned unless explicitly noted there.

## Goal and completion criteria

Deliver a reliable supply chain demonstration in which a manufacturer registers an item, creates its shipment, records checkpoints, transfers custody, completes delivery, and shares independently inspectable registration evidence. The contract, API, user interface, and reports must agree about that item.

The first release is complete when:

- Feature previews use isolated API, database, and contract state.
- Signed login works, and API writes enforce ownership.
- Drafts and submitted transactions cannot appear as blockchain verified.
- Confirmed events reconcile into one product and one shipment lifecycle.
- Restarting or replaying the indexer cannot duplicate checkpoints or lose committed progress.
- Shipment status and analytics reflect indexed events, with no unlabeled example metrics.
- A complete journey passes through the browser, API, database, and local contracts, followed by a Sepolia check in the testing environment.

## Working decisions

1. Retain React/Vite, FastAPI, SQLAlchemy, Neon, Vercel, Render, and the current contracts for the first release.
2. Use `main` for production and short-lived feature branches with pull requests and Vercel Previews.
3. Start with one shared testing API and Neon test branch. Introduce per-PR services only when concurrent work requires them.
4. Keep a single indexer owner. API replica scaling requires a separate worker or leadership lock first.
5. Model one shipment lifecycle per tracked item, matching the existing product-keyed contract. Repeated journeys require a separately planned contract version keyed by shipment ID.
6. Preserve existing public product IDs and already registered bytes32 values. Store their relationship explicitly.
7. Treat manufacturer identity and physical-item authenticity as separate evidence from blockchain registration.
8. Keep public verification available without wallet login; require authentication and ownership for mutations.

## Pull request sequence

| PR | Suggested branch | Deliverable | Depends on |
| --- | --- | --- | --- |
| 0 | `chore/testing-environment` | Isolated testing configuration and release baseline | None |
| 1 | `fix/indexer-startup-and-health` | ABI loading, startup recovery, useful health checks, conservative verification | PR 0 for hosted testing |
| 2 | `fix/wallet-auth-and-permissions` | Working SIWE login and authorized API writes | PR 0 |
| 3 | `feat/canonical-product-identity` | Stable IDs, additive schema migrations, one shipment per item | PR 2 for draft ownership |
| 4 | `fix/durable-chain-indexing` | Replay-safe event storage, persistent cursor, consistent projections | PRs 1 and 3 |
| 5 | `feat/evidence-based-verification` | Complete transaction lifecycle and proof-backed verification | PRs 2–4 |
| 6 | `fix/live-analytics-and-reports` | Real metrics and consistent exports | PR 4 |
| 7 | `test/complete-provenance-flow` | Integration coverage, CI gates, release and recovery runbook | PRs 2–6 |
| 8 | `feat/qr-verification-and-demo` | Shareable verification, mobile usability, guided sample journey | PRs 5 and 7 |
| 9 | `feat/shipment-exceptions` | Expected arrival, overdue and dwell exception list | PRs 6–8 |
| 10 | `perf/frontend-and-operations` | Measured loading improvements and operational cleanup | Stable first release |

Tests and migration checks belong in each implementation PR. PR 7 assembles the complete flow and release gates; it is not the first testing work.

## PR 0 — Establish isolated testing

**Tasks**

- Record the actual production frontend/backend deployment commits, runtime versions, database migration state, contract addresses, and deployment blocks using logs and non-secret metadata. Reconcile differences from the repository configuration.
- Create a Neon test branch and configure a dedicated Render testing service to use its connection string. Use production-like validation in the testing service with distinct environment identifiers and secrets.
- Deploy the existing contracts to local Hardhat for integration work and separate Sepolia addresses for hosted testing. Record addresses, chain IDs, ABIs, and deployment blocks in a reproducible manifest.
- Configure Vercel Preview variables to target the testing API and contracts. Generate/configure CSP for the selected API origin; configure the testing backend with the intended preview origins. Keep production CORS limited to production clients.
- Ensure SIWE origin configuration follows the same environment selection. Use explicit preview hosts or a narrowly scoped project-specific rule, rather than allowing arbitrary hosted domains.
- Document `main` as the production branch and require relevant CI checks for merges. Set production auto-deployment to respect the chosen release gates on both hosting providers.
- Add an environment setup guide and examples containing placeholders only.

**Primary files:** `frontend/index.html`, `frontend/src/config/env.ts`, `frontend/src/config/contracts.ts`, `frontend/src/config/wagmi.ts`, `backend/app/core/config.py`, `render.yaml`, `.github/workflows/ci.yml`, environment examples, deployment documentation.

**Acceptance:** a preview can read/write a labeled test record without changing live database records or using live contract addresses. API calls, wallet connections, and signed login requests are permitted by the intended CSP/CORS/origin settings.

## PR 1 — Restore indexer startup and truthful health reporting

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

**Metric definitions**

| Metric | Definition |
| --- | --- |
| Total / active / delivered | Counts of actual shipment records; delivered state derives from indexed delivery |
| Transit duration | First departure to delivery for completed shipments with both timestamps; report incomplete samples separately |
| On-time rate | Delivered shipments with a known expected arrival that arrived by that time, divided by delivered shipments with a known expected arrival |
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

- Add `/verify/:productId` links with direct loading and downloadable QR labels. A phone's native camera can open the link; a custom in-app scanner is optional later.
- Build a unified shipment detail view with checkpoint/custody history, current handler, registration evidence, synchronization status, and only the actions allowed for the connected account/current state.
- Add mobile wallet access; complete modal naming, focus management, Escape handling, scrolling, and reduced-motion support.
- Provide a clearly labeled seeded demo journey, onboarding for wallet connection/sign-in/test ETH, and useful retry/empty states. Keep demo data separate from live aggregates.
- Update branding/favicon, route metadata, READMEs, environment documentation, and missing-route handling.

**Acceptance:** a visitor can open a QR link without a wallet, follow the complete evidence timeline, and use wallet actions on a narrow mobile viewport. Keyboard navigation works through dialogs and forms.

### PR 9: Shipment exception list

- Add configurable expected arrival and checkpoint-interval/dwell thresholds with explicit meanings.
- Show overdue shipments, stale checkpoint activity, and unresolved custody handoffs in an in-app exception list.
- Make exceptions reproducible, deduplicated, and resolved when conditions change. Do not treat a stale indexer as proof of a delayed shipment.
- Add acknowledgement and links to the affected shipment. External email/webhook notifications are a later integration with explicit delivery/retry preferences.

**Acceptance:** controlled clock/data scenarios open, update, and resolve the expected exceptions without duplicate alerts.

### PR 10: Performance and operations

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

## First implementation session

Start with PR 0's environment inventory and reproducible local test configuration. Prepare PR 1's ABI/startup/health fixes and conservative verification behavior against the isolated setup. Complete PR 2's login and permission fixes before enabling broader mutation testing. Continue through canonical identity and durable indexing before starting production catchup.

Each implementation PR should describe the changed behavior, validation performed, migration/configuration requirements, and its acceptance criteria. This document is the plan; its tasks have not been implemented by creating it.
