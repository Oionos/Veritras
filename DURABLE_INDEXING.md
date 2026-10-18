# Durable indexing and recovery

## Guarantees

The indexer uses PostgreSQL for progress, canonical block anchors, an event journal and reversible product projections. `INDEXER_STATE_PATH` and old JSON cursor files are ignored. A transaction-level advisory lock (`864382025`) serializes projection writers, including overlapping deployments; it is released on rollback, connection loss or process death. SQLite uses `BEGIN IMMEDIATE` for local regression work.

Each batch commits its logs, product/checkpoint/custody/shipment updates, anchors and cursor in one transaction. A failed event, flush, commit, inconsistent RPC response or interrupted recovery leaves the previously committed cursor and projections intact. Fetch ranges shrink after RPC failures. Historical registration metadata is read at the event's block, never at `latest`. If old account state is unavailable, directly submitted `registerProduct` calldata is accepted only after matching its canonical block, registry, manufacturer, product ID and name. Indirect contract registrations still require historical calls. Provider errors are reduced to exception types to avoid exposing credentialed URLs.

Events are applied in `(block_number, transaction_index, log_index)` order. Identity includes chain, emitter, transaction hash and log index. The journal retains a separate occurrence for each block hash, and a unique partial index permits only one canonical occurrence of an event identity. Re-included transactions do not create duplicate business rows.

`DeliveryCompleted` changes delivery state and never inserts a checkpoint. The tracker emits it before `CheckpointRecorded`; the actual delivered checkpoint supplies location and notes. Incomplete delivery event pairs abort the batch. Metadata events and custody changes participate in the same ordered replay. Shipment status follows the product projection, including shipments planned after indexing; `current_handler` is exposed in shipment responses.

## Confirmation policy and health

- `INDEXER_CONFIRMATIONS=12` by default. The target is `max(0, observed head - confirmations)`. This is a depth policy, not Ethereum consensus finality. Local Hardhat testing explicitly uses zero confirmations.
- `INDEXER_START_BLOCK` is the last block **before** the earliest deployment. That anchor is stored and the next block is processed inclusively. Changing the anchor of an existing scope requires operator reconciliation.
- `INDEXER_MAX_REORG_DEPTH=2048` bounds automatic recovery. Block anchors are stored at batch boundaries and blocks containing events; recovery may conservatively rewind to an earlier known canonical anchor.
- `/health/ready` requires a connected database and progress current against the confirmation target when indexing is enabled. Health includes observed/target heads, lag, database cursor storage, confirmation policy and a safe `recovery_reason` when review is required.
- Verification also checks confirmation depth and the receipt's canonical block hash. Its typed response includes policy, indexed block and last successful synchronization time. Complete persisted registration transaction tracking remains increment 5.

Render free services can sleep. Durable state survives sleep/redeploy; continuous background indexing is still not promised. Keep one API/indexer instance as the operating baseline. The lock prevents competing projection commits; it is not a reason to add replicas without an explicit operating plan.

## Reorganization recovery

Before advancing, the indexer compares its stored cursor hash with the current chain. On mismatch it finds a matching stored anchor inside the recovery window, marks later journal occurrences noncanonical, restores affected products' pre-indexing baselines, removes only history rows attributed to those journal identities, and replays the remaining canonical events. Replacement logs and the rewound/new cursor commit in that same transaction.

Draft fields and signed draft ownership are restored when a registration disappears. Products discovered solely from chain history keep their public URL as an unregistered placeholder with no chain-derived ownership or receipt evidence. Shipment planning fields (origin, destination and notes) are preserved. Orphaned logs remain available for audit; they do not contribute to canonical projections.

A lower RPC head is treated as stale/unavailable, not permission to erase history. A changed deployment anchor, conflicting display/hex identities, different chain configuration, unattributed legacy history or absence of a canonical ancestor stops progress and reports degraded readiness. Do not clear the cursor or increase the start block to hide these conditions. Inspect the provider/configuration and rehearse a reviewed reconstruction on an isolated database copy.

## Migration and existing history

Migration `f04d9c21a873` follows `c72b53d91e04` and adds `indexer_cursors`, `chain_blocks`, `chain_events` and `indexed_products`. It does not delete business records or grant legacy ownership. Existing tagged history is adopted only when its payload agrees with the authoritative log. The projection binding establishes chain/contract scope for indexed products; the broader public identity/schema/reconciliation work remains increment 3.

Before enabling a new writer against existing projections:

1. Pause the old indexer and wait until that deployment is retired. Old versions do not honor the new database lock.
2. Record a restorable database checkpoint and rehearse the additive migration on an isolated copy. Deploy compatible code with indexing disabled. Keep the existing deployment anchor and contract configuration.
3. Inspect legacy attribution using the intended environment's privately supplied connection and RPC:

   ```sh
   cd backend
   python manage_indexer.py
   ```

   This is read-only. It compares product ID, transaction, block, timestamp and all event fields with authoritative logs; it never infers a log index from transaction hash alone.
4. If the report has no conflicts, explicitly apply exact attributions if needed:

   ```sh
   python manage_indexer.py --apply
   ```

   Apply only tags uniquely matched history rows. Any duplicate/ambiguous/unmatched row aborts the update. It never deletes or merges records, resets the journal, or grants ownership. Review conflicts in a separate reconciliation change.
5. Enable the new indexer with the reviewed anchor and confirmation policy. The new database cursor starts from deployment history; the old file is not imported. Wait for readiness, inspect journal identities and business counts, and verify registration/custody/delivery in testing.
6. Recheck after a same-code API restart/redeploy: the database cursor must resume and counts must remain unchanged.

Production indexing remains an explicit configuration decision after identity/history reconciliation. Shipping this additive code does not automatically enable it.

## Notifications

After a successful batch commit, the indexer publishes `chain_updated`. `/analytics/events` has bounded subscriber queues, five-second heartbeats and a resync signal on connection/overflow. Database revision polling also detects commits made by another process. The frontend uses one stream across pages and refreshes product evidence/history, shipment and analytics queries after changes or reconnects. These are cache invalidations; the stream is not a durable event-delivery API.

## Validation

- Backend regressions run against SQLite and a dedicated PostgreSQL database. Set `INDEXER_TEST_DATABASE_URL` only for local/CI database `veritras_indexer_regression`; the suite refuses other database names/hosts and clears only its dedicated test tables.
- Tests cover interrupted projections/commits, restart, competing writers, process-loss lock release, distinct logs in one transaction, canonical/orphan occurrences, registration re-inclusion, metadata/custody/delivery recovery, incomplete logs, stale heads and recovery-window exhaustion.
- `make testing-check` exercises the real isolated registration-to-delivery journey.
- `make testing-indexer-check` snapshots/reverts the local Hardhat chain, creates a replacement fork and checks the real API/PostgreSQL projections. It refuses hosted APIs and non-Hardhat chains. It deliberately mutates the disposable local testing chain; run it serially with other chain checks.
- GitHub CI runs both real journeys, both database regression variants, generated OpenAPI/type checks and existing browser/build/contract checks.

Application rollback must retain this additive schema. Disable indexing before rolling back to a writer that uses the old file cursor. Do not run a schema downgrade or delete the journal as an application rollback.

## Acceptance recorded October 18, 2026

- 236 backend tests passed across SQLite/PostgreSQL; two intentional skips are PostgreSQL-only cases in the SQLite variant. 192 frontend tests, 23 Playwright regressions, 40 contract tests, build and type checks passed locally.
- Real local API/PostgreSQL/Hardhat journey, actual chain fork/recovery, browser wallet/security journey and API restart checks passed.
- Hosted testing migration `f04d9c21a873` and backfill preserved two products, six unique checkpoints, two unique transfers and the delivered shipment; the journal contains 12 canonical events and two product bindings.
- Same-code Render redeploy `dep-dba32obrjlhs738na0g0` preserved all those counts and resumed from database progress (cursor 11938155 before, 11938172 after). Readiness was current with zero lag against the 12-block target.
- The protected testing Vercel preview displayed receipt-backed delivered verification for `PROD-31CBA002`, three checkpoints, no browser errors and no production API requests.
- Neon rehearsal `br-orange-mud-aoo70fzu` preserved the production copy's product/shipment with zero ownership bindings; it expires October 19. Pre-release checkpoint `br-small-bar-aobxzb8h` has no compute and expires October 25.
- Delivery is tracked in [PR #18](https://github.com/Oionos/Veritras/pull/18). Production indexing remains disabled pending its separate identity/history reconciliation and enablement checks.
