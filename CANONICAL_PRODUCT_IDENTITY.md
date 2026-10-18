# Canonical product identity

Increment 3 keeps public product IDs stable and makes contract identity explicit.
The scope is `(chain_id, registry_address, on_chain_product_id)`; addresses and
bytes32 values are normalized to lowercase. Each product also records its tracker
address. A shipment inherits that immutable scope through its product foreign key.
One shipment lifecycle per product is enforced by `uq_shipments_product_id`.
Repeated journeys require a future contract/schema version.

## Lifecycle and compatibility

- New signed drafts reserve the full identity immediately. ID allocation retries
  collisions, including existing unscoped display/hex records.
- `created_at` records application creation; `registered_at` in API responses is
  nullable and reflects actual indexed chain registration time. Drafts have no
  registration timestamp. Unknown legacy creation times stay unknown.
- Registration status is `draft`, `indexed`, `unregistered` (orphaned chain-only
  item), `legacy_unreconciled`, or archived `superseded`.
- The existing database `registered_at` column remains for compatibility with the
  preceding application release. New code exposes `chain_registered_at` under
  the public `registered_at` response field. The compatibility timestamp grants
  neither verification nor edit rights.
- Canonical journal bindings seed migrated identities and registration times.
  Unbound anonymous legacy manufacturer fields grant no ownership. Such records
  remain readable with unknown identity and unconfirmed registration.
- Contract actions use the stored bytes32 ID and require the configured chain,
  registry, and tracker to match. Planning writes fail with HTTP 409 when scope
  needs reconciliation. A second shipment returns a clear HTTP 409, including
  concurrent attempts protected by the database constraint.
- Reorganizations preserve identity reservations and public URLs, restore draft
  lifecycle/rights from the baseline, and clear unsupported registration times.

## Shared conversion contract

`fixtures/product-ids.json` is consumed by Python and TypeScript tests. Text is
strict UTF-8, one to 32 bytes, right padded with zero bytes. Valid 32-byte hex input
is decoded directly and normalized; it is never encoded as text. Empty IDs,
malformed or zero bytes32 values, NUL characters, invalid Unicode and byte-length
overflow are rejected. Unicode normalization is deliberately not performed.

## Legacy reconciliation

Run against an explicitly configured chain, registry, tracker, deployment anchor
and database, with the normal environment configuration:

```bash
cd backend
python manage_indexer.py           # Review exact legacy checkpoint/log attribution
python manage_identity.py          # Default: read-only identity report
python manage_identity.py --apply  # Only after reviewing the report
```

The command reads confirmed canonical registration logs and validates their block
hashes before and after inspection. It uses the same database writer lock as the
indexer. Dry-run/apply is idempotent; any conflict aborts the entire apply.

Rows match only by exact canonical ID plus authoritative manufacturer, name and
registration transaction/block evidence. Conflicting owners, scopes, bindings,
multiple shipment lifecycles or unattributed history require explicit review.
Names alone never match items. Unknown unregistered legacy rows remain unknown.

Compatible duplicates retain a deterministic human display ID. Checkpoints,
transfers, shipment and projection references move atomically to that row. The
other product rows remain archived with their metadata; `product_aliases` keeps
old URLs resolvable. Lists and exports exclude archived rows. Permissions and
verification always resolve the canonical row first. Signed-draft baselines are
preserved so a later chain reorganization restores the correct rights.

## Explicit schema release

Revision: `a38f917bd260`, following `f04d9c21a873`.

1. Inspect duplicate shipment counts and canonical bindings. The migration stops
   on duplicate lifecycles or conflicting journal evidence; it deletes no records.
2. Create a restore branch and rehearse on an isolated database with matching
   public business/journal data. Keep production indexing disabled.
3. Pause/drain the old testing writer before changing its schema.
4. Apply the reviewed migration as a separate release step:

   ```bash
   cd backend
   python manage_schema.py          # Read-only revision inspection
   python manage_schema.py --apply  # Explicit migration transaction
   python start_api.py             # Read-only schema-head check, then API
   ```

5. Deploy the matching API and frontend; inspect readiness, timestamps, identity
   scopes, counts and receipt verification. Resume only the testing indexer after
   those checks. Production catchup remains a separate enablement gate.

API startup applies no DDL. A missing/outdated revision fails before Uvicorn binds
its port. The disposable Compose entrypoint explicitly migrates its local database.
PostgreSQL migrations take migration and indexer writer locks in one transaction.
The previous application can continue reading the additive columns during rollout;
its old migration entrypoint cannot start after a revision it does not recognize,
so complete the code rollout promptly after the schema stage. Use a corrective
migration for rollback, preserving aliases and records.

### Free Render / authenticated SQL release channel

The free Render services have no paid pre-deploy command. The release can instead
use authenticated database-owner SQL without exposing credentials. Reflection and
data checks mean ordinary `alembic --sql` is unsuitable for this migration.

`export_schema_release.py --output <ignored-path.json>` runs the actual migration
on a local isolated PostgreSQL `*_identity_rehearsal` copy, captures exact SQL and
rolls it back. The export includes advisory/table locks and fingerprints of every
source business/journal table and schema revision. Apply all exported statements
as **one transaction** through the owner SQL channel, first on a restore branch.
A source-data change or replay aborts before DDL. It includes no auth challenges,
JWTs, credentials or private keys. Export files belong in ignored `.testing/`.

## Validation and release evidence

Regression coverage includes shared byte conversion boundaries, new-draft scope
reservation, collision retries, aliases, conflicting owners/history/shipments,
idempotent reconciliation, reorganization after duplicate reconciliation, schema
source guards, migration rollback, legacy preservation and database uniqueness on
PostgreSQL and SQLite. The isolated real API/PostgreSQL/Hardhat journey verifies
one product across registration, custody and delivery, nullable draft registration
time and rejection of a second shipment. Deployment evidence is recorded in the
implementation PR and release status below.
