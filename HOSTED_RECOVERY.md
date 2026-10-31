# Hosted recovery rehearsal (phase C)

Implemented locally October 21, 2026. **Hosted acceptance is pending configuration, protected release and a supervised hosted run.** Production indexing remains disabled. This workflow never changes Render/Vercel settings or signs a blockchain transaction.

## What the workflow does

`Hosted Recovery Rehearsal` runs manually from trusted main, after the existing eight exact-main checks pass. It:

1. Checks the workflow origin, clean checkout, required environment reviewers/branch restrictions, candidate admission and verified contract deployment evidence.
2. Creates one private Neon branch at a recorded point in time, with mandatory two-hour expiration and compute bounded to 0.25–0.5 CU.
3. Uses the copied database as a frozen checkpoint and creates a separate empty restore database **inside that branch**. Expiring branches cannot have child branches, so no child branch is created.
4. Dumps and restores with matching official PostgreSQL client tools; compares the frozen data, covered schema and effective table access.
5. Previews history attribution and dependent identity reconciliation in one uncommitted transaction. Conflicts block the run. Changes require the exact reviewed plan digest; otherwise the preview rolls back.
6. Replays the restored database to a fixed confirmed block using three fresh processes. The two restarts must preserve complete fingerprints except the cursor's poll timestamp.
7. Starts the normal private indexer against the live confirmed head, requires current/zero-lag progress, and checks actual application reads through a private in-process ASGI transport. No public API or preview is published.
8. Encrypts the backup and detailed evidence with AES-256-GCM, attempts verified cleanup, and publishes a sanitized report. Cleanup or encryption failure blocks the result.

Only the run-owned branch is deleted, including its disposable databases/compute. The configured source branch is never a mutation target. Existing local reorg/write-failure checks remain in the ordinary integration suite; this workflow does not simulate faults on live Sepolia.

The workflow rotates the database-owner password **on the verified temporary branch only**, then checks both connection URIs use that new credential. It never rotates or retrieves the source branch's password. The SQL endpoint retains Neon's network/authentication controls; “private” here means authenticated database access and no published application URL.

## One-time GitHub setup

Complete this after reviewing/releasing the implementation. These names are the workflow interfaces, not confirmation that secrets or environments already exist.

### Rehearsal environments

Create `recovery-testing` first, then `recovery-production` when ready. For each:

- Configure at least one required reviewer. The workflow checks the actual GitHub environment settings; declaring an environment in YAML alone is insufficient.
- Restrict deployments to protected branches, or to a single selected **branch** named `main`. The job itself also rejects non-main refs. Use the team's intended bypass restrictions.
- Choose a reviewer who can approve promptly: approval/queue/setup time counts toward the recovery objective.
- Verify the source project/branch/database against the intended live service privately. The protected configuration is the authority for source selection; the workflow does not read Render's production connection secret.

Set these **environment variables**:

| Variable | Value |
| --- | --- |
| `NEON_PROJECT_ID` | Explicit existing project containing the selected source |
| `NEON_SOURCE_BRANCH_ID` | Explicit `br-...` source branch; never an automatic default |
| `NEON_DATABASE_NAME` | Database to recover from that branch |
| `NEON_DATABASE_ROLE` | That database's actual owner role, verified against Neon metadata |
| `POSTGRES_MAJOR` | Actual project major version: 16, 17 or 18 |
| `REHEARSAL_RPO_SECONDS` | Approved objective, 60–3600 seconds |
| `REHEARSAL_RTO_SECONDS` | Approved objective, 60–1200 seconds |
| `REHEARSAL_MAX_BRANCHES` | Optional total project branch ceiling, default 20, maximum 100 |
| `REHEARSAL_BATCH_SIZE` | Optional initial RPC range, default 1000, maximum 10000; use provider-supported ranges |

The checkpoint targets roughly 60 seconds before workflow creation. RPO is measured against that declaration time. RTO includes GitHub queue, reviewer approval, setup, restore, replay and verified private reads. A run whose time budget is already exhausted stops before allocating resources. Select objectives based on business needs and a measured drill, not a promised default SLA.

Set these **environment secrets**:

| Secret | Purpose |
| --- | --- |
| `NEON_API_KEY` | Least provider-supported access for the selected project, branch/database creation, clone-only connection retrieval and owned-resource deletion |
| `SEPOLIA_RPC_URL` | Trusted read access, including historical logs/state needed for reconciliation |
| `REHEARSAL_OWNERSHIP_KEY` | Separate strong random secret, at least 32 characters, authenticating resource ownership |
| `REHEARSAL_BACKUP_KEY` | Exactly 64 hexadecimal characters representing a random 32-byte encryption key |

Generate/store keys privately through the normal secret-management process. Do not paste them into chat, workflow inputs or command arguments. Retain the archive key securely for at least the backup retention period. Do not rotate ownership keys while their resources are active without arranging cleanup; provider expiration remains a separate fallback.

The workflow's built-in GitHub token has only Contents/Actions read access. It reads candidate checks, workflow identity and environment protection settings. No production database password, wallet private key or Render API key is required. Clone-only database credentials are retrieved in memory after ownership verification.

### Cleanup environments

Create matching `recovery-cleanup-testing` and `recovery-cleanup-production` environments:

- Restrict source branches to main and protect changes through the existing repository rules.
- Set `NEON_PROJECT_ID` and `NEON_SOURCE_BRANCH_ID` to the matching rehearsal scope.
- Supply `NEON_API_KEY` and the **same** `REHEARSAL_OWNERSHIP_KEY` used by that rehearsal environment.
- Automated cleanup needs to run without waiting for a human reviewer. It can delete only authenticated, expired resources that still match project/parent/time/protection metadata.

After both cleanup scopes are configured, set repository variable `RECOVERY_REAPER_ENABLED=true` to enable the hourly reaper. Until then the scheduled job is inactive. Manual cleanup can select one configured scope. The reaper reads provider metadata only; it does not connect to/wake database computes.

## First hosted run

1. Release the feature through persistent testing and the protected-main process. The workflows intentionally cannot run hosted copies from an arbitrary feature SHA.
2. Verify the selected environment's creation receipts and anchor in `release/environment-policy.json`, then regenerate/check policy copies. **Production evidence is currently unverified** and blocks provisioning until corrected through review. Do not copy the testing anchor into production.
3. Confirm project retention covers the chosen checkpoint, branch/compute quota is sufficient, and the resource budget is approved. One temporary branch with compute/storage can incur provider charges; no paid upgrade is assumed.
4. Start testing first, from Actions → **Hosted Recovery Rehearsal** → main → testing, leaving reconciliation approval fields empty. Or:

   ```sh
   gh workflow run recovery-rehearsal.yml --repo Oionos/Veritras \
     --ref main --field environment=testing
   ```

5. Approve the protected environment job. Inspect both its final conclusion and sanitized `recovery-report-...` artifact. A `review_required` result can finish the planning job successfully, but full recovery remains incomplete. Only a genuine, unapplied review plan with a digest/target, matching restore, passing RPO, encrypted archive, verified cleanup and an unexpired review window qualifies. RPC errors, conflicts, encryption/cleanup failures and expired objectives still fail. A report's `pass` alone is not approval to activate production.
6. Require successful restore comparison, actual schema revision, accepted reconciliation, two stable restarts, fresh zero-lag private reads, measured RPO/RTO, encrypted evidence and verified cleanup.

No migration is automatically applied. An older/unrecognized restored schema blocks the private worker. Rehearse any future migration explicitly rather than stamping or silently adopting it. Source integrations or database jobs that would execute automatically from a clone must be reviewed before enabling this drill.

## Diagnose a restore comparison failure

`restore_comparison_failed` means the dump and restore completed, but the frozen
source and restored database did not compare equal. Inspect the sanitized report's
`restore_comparison.difference_summary` (also printed as `restore_difference_summary`
in the command output): it contains mismatch counts by section and
allowlisted schema categories such as `columns`, `constraints` or `indexes`.
Object names, row values and complete fingerprints remain in the encrypted
`restore-comparison.json`. Missing legacy diagnostics are reported as unavailable.

Constraint fingerprints parse CHECK definitions and normalize the specific
lossless rewrite PostgreSQL performs when a literal `varchar[]` is cast to
`text[]` during dump/restore. The parser handles SQL literals and quoted names;
normalization does not execute SQL. Literal values, surrounding predicates,
names and validation flags remain checked. Other definitions retain exact
comparison; domains, length-limited casts and nonliteral arrays are not treated
as this rewrite. Fingerprints record the normalization/parser version, and mixed
versions cannot compare equal. Older saved results are not changed retroactively.

An RPC verification failure also prints its fixed state and numeric HTTP/JSON-RPC
error codes when available. Provider messages, URLs and credentials remain hidden.
The fixed `rpc_stage` and `rpc_failure_kind` identify which call failed, including
configuration, historical receipts/blocks and registry linkage. Use the manual
**Deployment Identity and Readiness** workflow with environment **testing** to
inspect these checks through `recovery-testing` without allocating recovery
resources or declaring a timed drill. Approve that read-only job when prompted.
Select **inspect_history** to additionally probe the first 1,000 confirmed blocks
through all five contract-event filters. This identifies the failing event,
RPC method and safe numeric error codes without returning event data or opening
a database. Passing this bounded probe does not prove full history replay.
The history step runs after a failed readiness check too, but repeats its own
canonical identity verification before reading logs. A failed readiness step
still fails the job; a later probe cannot turn it into a successful observation.

If contract identity and history pass but health is
`invalid_or_unavailable_response`, check the testing API's startup and health
logs. The observer waits up to 120 seconds for a sleeping API to start and its
indexer to catch up, using fresh live/ready response pairs. It records
`health_observation` attempts and elapsed time. Persistent unavailability, wrong
environment/policy/scope, stale progress or an expired deadline still fail.
This observer wait does not extend the full recovery objective, which starts
when the recovery workflow is created.

Identity RPC reads retry temporary missing receipts/blocks, timeouts and
throttling at most three times, waiting one and two seconds. Authentication
errors, returned identity mismatches and known permanent range/history errors
remain blocking. Provider-internal retries are disabled so they cannot multiply
this attempt budget. Reports retain retry counts and fixed reasons such as
`rate_limited`, `range_limit` or `historical_data_unavailable`; provider messages
remain private.

If `receipt_not_found` persists after three attempts for a previously verified
creation transaction, verify that public transaction on Sepolia and use an RPC
endpoint that serves its historical receipts and logs. Save the complete HTTPS
endpoint privately in **GitHub Settings → Environments → recovery-testing →
SEPOLIA_RPC_URL**. Keep the existing contract addresses, transaction hashes and
anchor; missing provider data cannot establish a different deployment identity.

Reconciliation RPC failures now retain their fixed worker state, error category,
numeric HTTP/JSON-RPC codes and failed block range in the sanitized report and
console. The coordinator's broad `private_reconciliation_not_accepted` state
alone does not mean review is needed. For example, `reconciliation_rpc_failed`
is a real failure. The worker retries at most five times with 1/2/4/8-second
backoff, preserves the failed range for retry, and obeys its existing deadline.

Successful historical ranges grow back toward the configured batch limit after
temporary RPC failures. This prevents throttling from permanently reducing the
remaining scan to one-block requests. The range limit, five-attempt retry bound,
canonical-header checks and recovery objective remain enforced.

Workers checkpoint only bounded scan counters in an atomic private file:
completed ranges/blocks, target, batch size, event count and retry count. A killed
reconciliation worker reports `reconciliation_timeout` with its last validated
`scan_progress`, rather than losing the phase as a generic interrupted result.
These counters contain no event rows, provider messages, URLs or credentials.

Required connection, chain-head and canonical-header reads also use finite
deadline-aware retries for transient throttling or connectivity errors. Each
read has at most five attempts with one/two/four/eight-second waits. The scan
records header retries as well as event retries. A retried header must still
match the event or pinned target hash; unavailable history, authentication
errors, wrong hashes and expired objectives remain blocking. Final history
checks after writer shutdown use the same read budget without restarting it.

Private API reads allow at most three attempts for timeouts, throttling and
temporary server errors, waiting one/two seconds within the remaining recovery
deadline. The entire read sequence is capped at two minutes. Permission/missing
route errors and malformed JSON remain immediate failures. Every required route
must actually return a JSON object successfully, and the worker must still be
fresh/current with zero lag after the reads.

A failed read reports a fixed `api_route`, numeric `api_http_status` when present,
`api_failure_kind` and `api_attempts`. Product identifiers, response bodies, URLs
and exception messages remain private. The report lists successful route labels
and whether a representative product was available; an empty fixture does not
claim product detail/timeline/verification coverage.

Do not skip a failed comparison or assume its differences are harmless. Identify
the failing category, reproduce the cause and review any correction before the
next drill. Start a new workflow run after a correction; rerunning an old execution
retains its original recovery declaration time.

### Inspect an existing encrypted report in CI

Use **Actions → Inspect Saved Recovery Evidence** from **main**, with the original
testing recovery run ID and attempt. For the first comparison failure, use run
`40649974176`, attempt `1`. Approve its `recovery-testing` environment job.

This job downloads the existing report and encrypted evidence, verifies the source
workflow/main ancestry, authenticates the archive's run/SHA/policy provenance and
checks the saved comparison digest. It publishes only fixed mismatch categories
and counts. It does not connect to a database or RPC, create a branch, restore
data, change the original result or certify recovery objectives. Its execution
timeout starts when the approved job runs; it does not declare a new RTO/RPO drill.

The existing `REHEARSAL_BACKUP_KEY` is the only application secret required. Keep
the original key available until evidence expires. Wrong keys, expired artifacts,
untrusted origins, mismatched provenance and missing comparison evidence block
inspection. Plaintext is confined to a private temporary directory, removed on
completion and excluded from workflow artifacts. Both the sanitized inspection
and its report explicitly have `authorizes_activation: false`.

## When reconciliation requires review

The first run saves the detailed plan inside the encrypted archive. Its public summary contains a plan digest and the confirmed target block/hash.

1. Download the encrypted artifact and matching sanitized report from the trusted workflow run.
2. Supply the archive key privately and decrypt to a new private file:

   ```sh
   python backend/recovery_evidence.py \
     --decrypt /private/path/recovery-evidence.enc \
     --output /private/path/recovered-evidence.tar
   ```

3. Inspect `reconciliation-plan.json` in a private extraction directory. Verify each attribution/alias against authoritative chain evidence. Archive authentication proves byte integrity; also verify the repository, workflow, run/attempt, candidate SHA and policy digest.
4. If conflict-free changes are accepted, start a **new** manual run of the same candidate with `approved_reconciliation_digest`, `target_block` and `target_hash` set to the reviewed values. These are public evidence fields, not credentials.
5. The workflow recomputes the plan on a fresh restore. Any changed plan, candidate, schema, scope or canonical target prevents applying the approval. Conflicts remain blocking even with a supplied digest.

History attribution is simulated before identity planning, then both are committed together only on the private restore when the exact digest matches. A first run needing review does not commit those changes. Never provide a dummy digest, erase ambiguous legacy rows, or advance a cursor manually to obtain a pass.

## Retention, cancellation and failures

- Only the sanitized JSON and encrypted `.enc` file are uploaded. Raw dumps, plans and connection information are not ordinary CI artifacts.
- Both artifacts retain seven days. The private runner is disposable; the temporary Neon branch is cleaned immediately, with mandatory provider expiration after two hours. Resource lifetime and encrypted-backup retention are different settings.
- Encryption streams data and authenticates header/body/tag. Wrong keys, tampering or truncation do not publish a plaintext output. Decryption refuses an existing output path and does not automatically extract a tar archive.
- Cleanup runs in the coordinator's `finally`, again in an independent `always()` step, and through expiration/reaping. Runner loss can prevent the first two paths; provider expiration is mandatory and the reaper supplies additional recovery.
- Every deletion checks authenticated naming, project/parent, creation time, changed expiration, and default/protected flags. Protected, renamed, moved or unowned resources require review; the code never unprotects them or deletes a guessed branch.
- A creation timeout is not retried blindly. The ledger records intent before POST and cleanup can rediscover the exact signed name. An uncertain outcome is reported for review.
- A failed workflow's encrypted file may contain an incomplete dump. Do not treat it as a usable backup without independent restore validation.

| Blocked condition | Next action |
| --- | --- |
| Missing reviewer or branch protection | Correct the actual GitHub environment settings; the YAML environment name is insufficient |
| Deployment identity unverified | Obtain canonical creation receipts/anchor and rerun read-only verification |
| Provider expiry unsupported or absent | Resolve account/API support; do not retry without expiration |
| Restore/schema admission failure | Check compatible clients, TLS, empty target and schema on a private copy; do not drop platform objects to force success |
| Reconciliation review/conflicts | Review encrypted evidence; approve only an exact conflict-free plan |
| Reconciliation RPC failure | Run the read-only observer with `inspect_history=true`; inspect fixed method/stage, codes and block range before repeating a full rehearsal |
| Restart/history mismatch | Keep production activation blocked; inspect canonical evidence and the private reports |
| Encryption failure | Fix the private archive key/configuration and repeat the drill; plaintext is not uploaded as a fallback |
| Cleanup failed/uncertain | Inspect `resource_intent` and cleanup-step results; verify only the authenticated owned resource in Neon or run the configured reaper |
| RPO/RTO exceeded | Identify queue/setup/RPC/restore bottlenecks and repeat against an explicitly approved objective |

## Validation boundary

Local regression coverage includes provider ownership/expiry guards, pagination and operation failures, encryption round trips/tampering, rollback of unapproved reconciliation, time-budget handling, and actual PostgreSQL worker processes with a read-only RPC fixture. The fixture process test does not prove hosted Sepolia latency or production data reconciliation. Existing real local-chain integration continues to cover business events, write failures and reorgs.

A supervised successful hosted run is still required before closing phase C acceptance. Production activation remains phase D and requires separate reviewed approval; all current reports explicitly state `authorizes_activation: false`.
