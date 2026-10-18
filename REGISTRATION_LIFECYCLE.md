# Registration lifecycle and evidence

## Transaction progress

Product identity and indexed state remain authoritative projections. Wallet
submissions are stored separately in `registration_attempts` (migration
`b47e203fa951`, following `a38f917bd260`). A submitted hash never grants ownership,
changes product metadata, or proves registration.

Each attempt follows `submitted` → `confirming` → `indexing` → `indexed`, or
`failed` / `replaced`. The API keeps the original hash, checked block/hash,
submission/check times, replacement links, operation, requested metadata URI and
registration payload snapshot. Retries use the existing product and append an
attempt. Identical submissions are idempotent; hashes cannot be reassigned to
another product. History is bounded at 100 attempts per product.

- `POST /products/{id}/registration`: signed owner submits a registration or
  metadata transaction hash, optionally referencing the hash it replaces.
- `GET /products/{id}/registration`: public persisted transaction history.
- `POST /products/{id}/registration/reconcile?tx_hash=0x...`: signed owner refreshes
  an observation. This updates attempt tracking, never the product projection.
- `GET /products/{id}/verify`: public fresh receipt and indexed-journal evidence.
- `GET /products/{id}/metadata-history`: up to 100 journal versions, including
  explicitly labeled orphaned versions with transaction/block references.

The owner panel reconciles one unresolved attempt every 30 seconds while visible;
there is no new hosted background service or keep-alive monitor. A manual refresh
also rechecks completed/failed observations after a reorganization. Public
verification always checks current receipt evidence independently of cached
attempt status. An unknown hash remains pending; absence from an RPC node does
not establish that a transaction was dropped.

## Evidence requirements

The API checks configured chain and registry scope, sender, destination, decoded
function and product ID, submitted registration fields or requested metadata URI,
receipt success, event emitter/product/manufacturer/name, canonical block hash,
and the configured confirmation depth. Public `verified` additionally requires
the matching canonical journal event and an indexed product. RPC requests use a
maximum two-second timeout per call with provider retries disabled.

The response includes `verified`, `pending`, `unavailable`, `not_found`,
`mismatched` or `failed` evidence and a reason; canonical identity, manufacturer,
transaction/block references and observed/required confirmation depth are
inspectable. Synchronization health, lag, cursor and last successful sync are
separate. A draft, invented hash, reverted receipt, unrelated contract/event or
orphaned/unconfirmed receipt cannot produce verified registration. RPC failure
returns explanatory unavailable evidence without exposing provider credentials.
`physical_authenticity_verified` is always false: registration alone cannot
establish physical authenticity.

## Replacement and outage recovery

Wallet replacement callbacks submit both hashes. The server requires the same
validated sender and nonce; a wallet's replacement claim alone is insufficient.
Canonical, sufficiently confirmed self-transfers with empty calldata are treated
as cancellations. The old attempt is marked replaced only after the replacement is canonical and sufficiently confirmed; pending candidates do not retire the original. Manual reconciliation can restore an original transaction after a reorganization. Replacement links retain the observed relationship. There is no
unbounded mempool or historical sender/nonce scan. If a provider has forgotten
the original transaction and its nonce was never observed, replacement evidence
requires operator review rather than a guessed association.

The browser records public hashes in an outbox before attempting the API write.
It scopes that outbox by API origin, chain, registry, wallet and product. Reloading
and reopening the product retries originals before replacements after sign-in;
wallet switches preserve the original wallet's outbox without sending its write
under another wallet session. Manual recovery accepts a transaction hash,
operation, requested metadata URI and optional original hash. No private keys or
session tokens are stored in the outbox.

Pending registration attempts lock draft editing. Successful draft edits refresh
both the list and detail queries before registration can use stale values.
A receipt received by the wallet is labeled as awaiting indexing. An indexer that
wins the submission race can still accept tracking for the product's exact
indexed registration hash.

## Metadata updates

An indexed product's manufacturer signs `updateProductMetadata` through the
wallet. API writes never change indexed metadata directly. The current URI
changes only when the confirmed event is indexed. Canonical and orphaned versions
remain inspectable in journal order. Registration evidence is checked separately
from subsequent metadata transactions.

## Migration and release

1. Run regression suites against SQLite and the isolated PostgreSQL database.
2. Rehearse the additive Alembic revision on an expiring production-copy branch;
   verify existing business counts, ownership and identity remain unchanged.
3. Apply the same revision to the isolated hosted testing database before its
   matching API starts; API startup itself performs no DDL.
4. Check submission/read/reconcile, existing Sepolia registration evidence,
   metadata history and the protected preview against the matching API.
5. After release checks pass, apply the additive revision to production and
   release the matching application. Leave production indexing disabled until
   its separate identity/history reconciliation and enablement checks pass.

Use `python backend/manage_schema.py` for inspection and explicit `--apply` for
migration through the established database-owner deployment channel. The revision
adds a table/index only; PostgreSQL uses the migration lock, a five-second lock
wait and an exact predecessor guard. No chain transaction, paid service or
production backfill is required by this migration.

## Validation evidence

Local API/PostgreSQL/Hardhat registration → checkpoint/custody/delivery → receipt
and canonical-journal evidence passed. The smoke check additionally submits and
reconciles transaction attempts, signs a metadata update, confirms both history
versions and rechecks registration proof. Real chain reorganization recovery
passed. The production-copy Neon rehearsal upgraded `a38f917bd260` to
`b47e203fa951` while preserving one product, one shipment, zero checkpoints and
zero ownership bindings; its new attempt table is empty. Rehearsal branch
`br-jolly-band-aojdyv96` expires October 19, 2026 at 18:00 UTC.

Local validation: 235 frontend unit tests passed, with 70.63% statement and
60.4% branch coverage; 29 Playwright regressions passed. The real browser journey
passed registration after a draft edit, saved transaction recovery after reload,
metadata signing and version history, wallet-switch logout and ownership checks.
Backend regression results and final release references are recorded in
[PR #21](https://github.com/Oionos/Veritras/pull/21).

Hosted testing acceptance on source `bedbdef` passed with the indexer current and
zero confirmed-target lag. The additive migration preserved three products, two
shipments, six checkpoints and two custody transfers. An existing manufacturer's
registration hash was submitted idempotently and reconciled to `indexed`;
verification returned canonical `verified` evidence and metadata history. No
chain transaction or test ETH was spent for this hosted acceptance. The testing
Vercel deployment `dpl_8M39raUZ3bujQmeD5x4RLFjyLmuF` built successfully. Protected-preview browser access was explicitly approved using a private, temporary
23-hour link. Local real browser and hosted API acceptance are complete; final
protected-browser results are recorded in PR #21.

A pre-release production restore branch, `br-empty-sunset-ao28fn9e`, has no compute
and expires October 25, 2026 at 18:00 UTC. It preserves the predecessor schema.
Chain-event notifications also invalidate registration and metadata-history
queries so newly indexed values appear without a manual reload.
