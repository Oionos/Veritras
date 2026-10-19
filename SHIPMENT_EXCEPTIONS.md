# Shipment exceptions (increment 9)

`/exceptions` lists durable operational observations and resolved history. Each entry links to the shipment's canonical evidence. Shipment detail shows open observations and the owner's exception policy. These observations describe missing **confirmed indexed records**; they do not prove a physical shipment delay or authenticate an item.

## Rules and defaults

| Rule | Trigger | Default | Clears when |
| --- | --- | --- | --- |
| Planned arrival overdue | A planned arrival has passed after canonical departure, without canonical delivery. The plan must have been recorded on or before that departure. | Enabled; uses the shipment's optional UTC arrival plan | Delivery, valid plan/eligibility change, disabled rule or withdrawn departure evidence |
| Checkpoint activity overdue | No checkpoint follows the latest checkpoint during a journey with an indexed departure | 24 hours | A new checkpoint resets the interval, delivery, disabled rule or evidence withdrawal |
| Checkpoint follow-up overdue | No checkpoint follows the latest **At Checkpoint** record | 24 hours | A new checkpoint, delivery, disabled rule or evidence withdrawal |
| Receiving handler follow-up overdue | The latest custody transfer has no subsequent checkpoint by its receiving handler | 6 hours | A checkpoint by that recipient, a newer transfer, delivery, disabled rule or evidence withdrawal |

A threshold is reached at `now >= anchor timestamp + threshold`. At Checkpoint uses its own interval instead of also raising the general inactivity rule. It measures time since a **record**, not physical dwell. Custody transfers already take effect on-chain; follow-up does not represent a pending acceptance transaction. A checkpoint by a different wallet does not satisfy receiving-handler follow-up. Transaction/log order decides which event follows another, including equal timestamps.

Owners can set intervals from 0.25 to 8760 hours or leave an interval blank to disable its rule. Arrival planning remains on the shipment record and is locked before indexed departure. Unknown historical plans are not invented. Drafts, unreconciled scope, superseded products and products without a canonical registration cannot establish exceptions.

## Lifecycle and permissions

- An occurrence persists with its threshold-crossing time, first/last observation, anchor event and occurrence identities, policy revision and evidence summary.
- A partial unique index permits one open occurrence per scope, shipment and rule. Repeated evaluations update that occurrence; they do not duplicate it.
- Material changes to a still-overdue rule/anchor resolve the prior occurrence as `condition_replaced` and open a new one. An unrelated policy change preserves acknowledgements. Newly cleared conditions use `condition_cleared`; removed canonical anchors use `evidence_withdrawn`.
- A previously resolved condition that recurs opens a new occurrence. Its acknowledgement starts empty. Closed history and earlier acknowledgements remain intact across restarts and reorg recovery.
- Only an authenticated, established product owner in the current contract scope may change policy or acknowledge. Current chain custody alone does not grant these API permissions. Legacy manufacturer text grants no rights.
- Policy PUTs require `expected_revision`; stale saves return 409. Identical saves are idempotent. Acknowledgement POSTs are idempotent and preserve the first actor, timestamp and note. Resolved occurrences return 409.
- Notes are public, plain text and limited to 500 characters. Acknowledgement records review; it does not resolve or suppress a condition. No email, webhook, external delivery or retry queue is configured.

## Synchronization and operation

The API process runs a lightweight evaluator approximately every 60 seconds when indexing is enabled. No additional paid service is required. Disabled indexing starts no evaluator. Render sleep naturally pauses assessment; the page reports the stored assessment time.

Evaluation requires cached indexer status `current`, readiness, zero lag and zero finality gap. Inside the indexer's shared transaction writer lock, the evaluator checks the configured scope's durable cursor and block anchor against cached progress. It rechecks indexer health before committing. Journal reorgs, concurrent evaluators, policy writes and acknowledgements cannot interleave their write transactions. Failure rolls back the entire assessment. No RPC is performed by exception rules or public reads.

Disabled, stale, catching-up, changed or unavailable indexing opens/resolves nothing. Invalid/future event timestamps and missing recipient evidence retain that shipment's previous observations; the response reports an uncertain-shipment count. A regressed clock cannot overwrite a later assessment. The UI labels paused evaluation and retains prior observations without treating missing data as proof of delay. Assessments older than three minutes are labelled stale even if indexer health is current. Public GET requests never evaluate or mutate lifecycle state.

The list polls every 30 seconds, supports open/unacknowledged/acknowledged/resolved/all filters, shipment filtering and bounded pagination (maximum 100 via API). No count is inferred from client time. Existing anomaly analytics remain a separate statistical view.

**Production indexing remains disabled.** Its exception list therefore shows paused evaluation. Production reconciliation/backfill and enablement retain their separate reviewed gate in [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md).

## Schema and release

Additive Alembic revision `e93a107bd624` follows `c62a904df318`. It adds `exception_policies`, `shipment_exceptions` and `exception_evaluations` with constraints and indexes. There is no business-data backfill or canonical-journal modification. Rehearse on isolated copies, retain a pre-migration checkpoint, compare existing table fingerprints, and apply the same generated SQL transaction to the explicitly selected target before starting the new backend.

October 19 rehearsals preserved fingerprints for products, shipments, checkpoints, transfers, canonical/orphan journal, block anchors, cursor, bindings, aliases and registration attempts on copies of both hosted databases. Retained `before-shipment-exceptions-20261019` checkpoint branches expire October 26; disposable rehearsal branches expire October 20. No database credentials were changed. Keep the additive schema on rollback. An old API artifact with an earlier schema head cannot pass its strict startup admission against this revision; use a corrective compatible release instead of a destructive downgrade.

Recovery/backup fingerprints now include all three exception tables. Local PostgreSQL regressions use disposable schemas, preserving the shared regression database. Controlled-clock tests cover threshold crossings, custody source order, deduplication, material policy changes, acknowledgements, delivery, orphan recovery, uncertain evidence, paused/changed indexing, interrupted commits, restart persistence and concurrent writers. Browser coverage includes paused states, public mobile history, shipment links, retry and owner policy persistence/permission denial in the actual local wallet journey.
