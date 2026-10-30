# CI/CD readiness and recovery foundation

Implemented October 21, 2026 on `codex/cicd-readiness-and-recovery`. Phases A–C add the read-only observer, recovery tools, private hosted orchestration, encrypted archives and owned-resource cleanup. Implementation/local validation does **not** enable production indexing or create hosted resources. See [hosted recovery setup](HOSTED_RECOVERY.md) and [the phased plan](CICD_IMPLEMENTATION_PLAN.md) for acceptance and remaining activation work.

## Implemented

- One non-secret environment policy, checked for drift across hosting roots.
- Strict frontend release checks for the configured indexing mode, contract scope and confirmation policy. The enabled mode also requires fresh/current database-backed progress and zero lag. Production remains disabled.
- Additive public health scope fields: registry, tracker and start block. Invalid address configuration is omitted rather than exposed.
- Canonical creation-receipt, contract-code, registry-linkage and deployment-anchor verification.
- A manual GitHub Actions observer, **Deployment Identity and Readiness**, restricted to trusted main in `Oionos/Veritras`. It uploads a sanitized report and never authorizes activation.
- Read-only PostgreSQL data/schema/sequence comparison with explicit target allowlists, consistent snapshots and bounded SQL operations.
- Private dump/atomic-restore coordination into an explicitly selected empty rehearsal database; no database creation, cleaning or overwrite.
- Regression coverage in the existing CI backend job, including real PostgreSQL dump/restore using the service's matching clients.
- Manual hosted rehearsal and optional scheduled cleanup workflows; authenticated resource ownership, required expiry, review digests, measured recovery objectives and AES-256-GCM evidence archives. See [phase C details](HOSTED_RECOVERY.md).

## 1. Policy maintenance

The source of truth is `release/environment-policy.json`. Its copies in `backend/` and `frontend/` let each hosting root build independently. Required GitHub check policies remain separate.

```sh
# From the repository root: check copies; no mutations.
python backend/sync_environment_policy.py

# After a reviewed source-policy change: explicitly regenerate both copies.
python backend/sync_environment_policy.py --write
```

Current production creation hashes and anchor are intentionally `null`: they have not been independently verified. The historical start block in `render.yaml` does not establish a verified deployment record. Do not replace unknown values with guesses. Obtain the public creation transactions, verify canonical receipts/linkage and review the computed anchor before updating the policy.

The initial production policy is `indexer_mode: disabled`. A policy change does not modify Render's runtime environment. Production activation still requires the coordinated procedure and explicit review.

## 2. Hosted read-only observer

After this workflow is merged to main:

1. Testing uses the existing protected `recovery-testing` environment and its `SEPOLIA_RPC_URL` secret. Production uses `readiness`, restricted to main with its own RPC secret. No database password, wallet key or Render credential is required. Approve the testing environment job when prompted; this observer does not declare an RTO/RPO drill.
2. Verify and commit the production creation hashes/anchor before expecting a production pass. Hosted testing's separate deployment evidence is already recorded in policy.
3. In Actions, run **Deployment Identity and Readiness** from main and select production or testing. Alternatively:

   ```sh
   gh workflow run production-readiness.yml --repo Oionos/Veritras \
     --ref main --field environment=production
   ```

4. Inspect the summary and `readiness-<environment>-<sha>` artifact. Both health and canonical identity must pass. Unknown scope/receipt, missing RPC access, wrong release or stale progress blocks the report.

The workflow reads main's reviewed policy. For testing it inspects the fetched testing branch tip and its latest backend-changing ancestor. For production it uses main and its backend ancestor. Both health responses must agree on one of those specifically allowed SHAs; an arbitrary SHA reported by the API is never accepted as its own proof.

Reports distinguish the verifier's `candidate_sha`, target `release_sha`, expected backend ancestor, and verified observed `backend_sha`. A 24-hour expiry is descriptive metadata for later orchestration, not an activation credential. Every current report explicitly has `authorizes_activation: false`.

RPC failures include a fixed `rpc_stage` and `rpc_failure_kind`, plus numeric HTTP
or JSON-RPC codes when available. These distinguish invalid endpoint configuration,
missing historical receipts/blocks, response formatting and contract-call errors.
Raw exception messages, URLs, keys and unknown exception class names are withheld.
For the reconciliation failure, select **inspect_history** or add
`--field inspect_history=true` when dispatching the observer. It additionally
probes the initial 1,000 confirmed blocks through five historical event filters,
retaining only counts and safe error categories/codes. It has no database or
provider-management credentials, and does not certify full recovery.

For an operator-run contract-only check, with RPC supplied privately:

```sh
python backend/check_deployment_identity.py --environment testing
```

Exit 0 means verified. Missing evidence/credentials or mismatches exit nonzero with a fixed sanitized diagnostic. The standalone command does not check the API.

## 3. Compare a frozen checkpoint with its restore

Install the locked backend dependencies. Configure `SOURCE_DATABASE_URL` and `TARGET_DATABASE_URL` privately. Both must be PostgreSQL connections whose host, port and database exactly match a reviewed manifest. Hosted connections require `sslmode=verify-full`; pooled endpoints and URL query overrides such as `host`, `service` or `options` are rejected.

Example **non-secret** manifest; replace it with actual privately verified target identities:

```json
{
  "version": 1,
  "frozen": true,
  "source": {"host": "checkpoint.example", "port": 5432, "database": "checkpoint"},
  "target": {"host": "restore.example", "port": 5432, "database": "veritras_restore_20261021"}
}
```

The manifest asserts the operator has frozen the targets; it does not prove provider branch ownership. Hosted orchestration must verify provider metadata before using these tools. Do not compare a moving production database against an older restore.

```sh
python backend/compare_recovery.py \
  --manifest /private/path/recovery-targets.json \
  --output /private/path/new-comparison-report.json
```

The output file must not already exist. It is created with mode 0600. Exit 0 means the covered comparisons match; exit 1 means mismatch or comparison failure; exit 2 means the report could not be created. Console output contains only a result/category, not connection strings or rows.

Coverage includes application rows in all discovered non-system tables/materialized views, table/column definitions, constraints, indexes, triggers/rules, routines, enums/domains, RLS policies, extensions, sequences and inheritance. PostgreSQL sorts full JSON row representations while the client streams hashes, keeping client memory bounded. RLS must not silently hide rows: insufficient full-read access fails the snapshot.

Object owners and raw role grants are excluded. Effective table privileges of the supplied roles are compared; intended application-role/schema/function/sequence access must still be checked separately. This foundation is not a universal backup validator for every PostgreSQL object type, large objects, external systems or provider configuration. It does not establish off-provider retention, RPO/RTO, API correctness or replay by itself.

## 4. Rehearse dump and restore

This command writes to the selected **private empty target**, not the checkpoint. It does not create the database or provision Neon resources. Verify ownership, source freeze, target isolation and budget before running it.

Requirements:

- Compatible `pg_dump` and `pg_restore` on `PATH`; use clients matching the intended source/target major version. A newer dump client can emit SQL an older restore server rejects.
- Target database named `veritras_restore_` followed by 8–64 lowercase letters, numbers or underscores, matching the manifest exactly.
- An empty target with no application relations, routines or non-default extensions; no connected application/indexer writes.
- An existing private artifact parent directory and fresh report filename. Raw backups must never be uploaded as ordinary CI artifacts.

```sh
python backend/rehearse_recovery_restore.py \
  --manifest /private/path/recovery-targets.json \
  --artifact-directory /private/path/recovery-artifacts \
  --output /private/path/new-restore-report.json \
  --timeout 600
```

The command validates targets, checks the destination is empty, creates a private per-attempt backup directory, dumps with a read-only source session, and restores with `--single-transaction --exit-on-error --no-owner --no-acl`. Credentials are passed through child environment variables, never command arguments. Inherited PostgreSQL service/options overrides are removed. It then compares both frozen databases.

A failed restore retains its private backup/artifacts for investigation. A rerun requires another empty target; there is no `--clean` or reset option. Reapply/review intended ownership and grants separately. The operator must arrange backup retention and cleanup; this tool does not delete resources or establish a backup schedule.

## Validation and remaining work

The implementation was exercised with disposable local PostgreSQL 15, including real dump/restore, refusals to overwrite populated targets, and actual separate replay processes with a read-only RPC fixture. CI retains PostgreSQL 17 and uses its service's matching client tools. Latest local backend result: **598 passed, five skipped**. Phase A–B frontend results remain **323 unit tests and three browser health checks passed**, with a passing TypeScript/frontend build. Policy, Actionlint, workflow shell syntax and whitespace checks pass. Hosted GitHub/provider runs remain pending release and configuration.

Still pending:

1. Merge/release the foundation through existing protected checks; configure hosted RPC access and verified production deployment evidence.
2. Phase C acceptance: configure protected environments and complete a supervised hosted run. Resource lifecycle/orchestration/encryption/replay code is implemented; local fixtures do not prove hosted data reconciliation or provider timing.
3. Phase D: proof provenance/freshness enforcement, protected production approval, provider deployment coordination, any required write-pause control and verified failure recovery.
4. Phase E: expanded performance scenarios, alert-delivery drill, field observations and business pilot.

Production indexing remains disabled until the separate activation prerequisites are met.
