# CI/CD implementation preparation

Prepared October 21, 2026; status updated October 31. **Phases A–C are released; the replacement RPC passed hosted identity and initial historical-log checks. Full hosted recovery acceptance remains pending. Phases D–E are pending.** See [current commands](CICD_AUTOMATION.md) and [hosted recovery setup](HOSTED_RECOVERY.md). Production identity remains blocked until its creation receipts/anchor are verified.

This translates [the next-steps guide](NEXT_STEPS_GUIDE.md) into an implementation backlog. Production indexing remains disabled. Resource creation, reconciliation applies and activation are separate operational actions; preparing this plan does not perform them.

## 1. Scope and implementation order

Automate production readiness first, then private recovery and replay, then approved production activation. Keep the existing eight required checks and exact-main provider admission intact. Extend performance and alert verification after the recovery foundations.

| Phase / proposed PR | Deliverable | Operational access | Exit criterion |
| --- | --- | --- | --- |
| A — readiness foundation | Versioned environment identity, strict indexer-mode policy, read-only readiness report | Public health endpoints; RPC secret for contract checks | Valid evidence passes; identity/policy mismatches fail; production stays disabled |
| B — recovery comparison tools | Generic hosted-safe data/schema comparison and dump/restore coordinator | Local PostgreSQL for implementation validation | Complete comparison detects changed/missing data and schema without exposing rows |
| C — isolated hosted rehearsal | Manually started workflow creates private checkpoint/work databases, restores, reconciles and replays | Protected Neon/RPC access; private backup destination if retained off-runner | Reviewed exact release has matching restore evidence and conflict-free replay/restart evidence |
| D — production activation | Approved, serialized workflow consumes verified rehearsal evidence and performs coordinated activation | Protected Render access; tightly scoped reconciliation access if needed | Exact admitted release reaches fresh/current zero-lag state; failure disables writer and preserves history |
| E — measurement and response | Deterministic performance scenarios, isolated alert-delivery drill and field reporting | Existing telemetry and selected responder | Reproducible reports, confirmed alert delivery and pilot-ready operations |

Each PR stages through persistent testing and protected main. Do not add hosted observers to the eight deployment prerequisites: a job waiting for deployment cannot also be a prerequisite for that deployment.

**Implemented slices: phases A–C.** The read-only observer, strict shared policy, recovery comparison, private dump/restore coordination, hosted orchestration, encryption and guarded resource lifecycle are released with regression coverage. Protected testing environments are configured. [Observer 41169061238](https://github.com/Oionos/Veritras/actions/runs/41169061238) passed complete hosted testing readiness and the initial historical probe after the RPC replacement and bounded startup wait. [Recovery run 41169970382](https://github.com/Oionos/Veritras/actions/runs/41169970382) then matched restore with zero differences, passed RPO at 59 seconds, encrypted evidence and deleted its temporary branch, but exhausted the 20-minute objective during reconciliation. A read-only reproduction found repeated HTTP 429 responses permanently shrinking the scan to one-block ranges. The scan now recovers its batch size after successful ranges and checkpoints safe progress for timeout diagnostics. Next: release and verify that fix in a fresh full rehearsal. Complete replay, restart checks and private reads remain unverified; full hosted acceptance remains open.

## 2. Current components to reuse

| Existing component | How it fits |
| --- | --- |
| `.github/workflows/ci.yml` | Existing contract/backend/frontend/build/Lighthouse/type checks |
| `.github/workflows/testing-environment.yml` | Real local-chain integration, reorg, interrupted writes, restore and wallet browser checks |
| `.github/workflows/hosted-health.yml` | Observer of deployed readiness; retain its separation from admission |
| `.github/workflows/operations-monitor.yml` | Scheduled readiness, API error and SSE checks |
| `backend/check_health.py` | Strict release/environment/chain/confirmation/indexer readiness validation |
| `backend/manage_schema.py` | Read-only schema inspection; explicit migrations only |
| `backend/manage_identity.py`, `backend/manage_indexer.py` | Existing confirmed-chain reconciliation rules and dry-run/apply behavior |
| `backend/build_release.py`, `release_gate.py`, `start_api.py` | Existing exact-main build admission and offline startup proof |
| `frontend/release-gate.mjs` | Existing frontend admission and compatible-backend verification |
| Backend/frontend `release_policy.json` | Existing required-check policy; keep its meaning and drift protection |

Do not weaken local-only helpers to accept hosted connections. New hosted orchestration should call reusable reconciliation logic with independently verified targets.

## 3. Proposed files and interfaces

This is the original design inventory. Current implemented interfaces are documented in [CI/CD automation](CICD_AUTOMATION.md); hosted orchestration/resource-management/activation commands below remain planned.

| Proposed path | Responsibility |
| --- | --- |
| `release/environment-policy.json` | Non-secret expected environment, chain, contracts, anchor, confirmations, indexer mode and allowed API origins |
| `backend/check_deployment_identity.py` | Verify canonical creation receipts, contract bytecode and tracker→registry linkage |
| `backend/prepare_readiness_report.py` | Compose strict health and contract evidence into a sanitized versioned report |
| `backend/compare_recovery.py` | Read-only consistent fingerprints of all application tables and schema; compare frozen source and restore |
| `backend/rehearse_hosted_recovery.py` | Verify allowed targets, coordinate dump/restore and run private reconciliation/replay |
| `backend/manage_rehearsal_resources.py` | Create/record/delete only owned disposable Neon resources, with bounded lifetimes |
| `backend/activate_production_indexer.py` | Validate evidence and exact release; coordinate approved activation and failure recovery |
| `.github/workflows/production-readiness.yml` | Read-only manual observer and sanitized report |
| `.github/workflows/recovery-rehearsal.yml` | Trusted manual hosted drill, validation report and resource cleanup |
| `.github/workflows/production-indexing.yml` | Approval-gated production writer activation |

Keep provider operations separate from verification logic so local fixtures can exercise failure cases without real credentials. CLI arguments identify approved environments, release SHAs and workflow run IDs; they must not accept arbitrary secret-bearing URLs as unvalidated workflow inputs.

### Shared policy decisions

- Introduce an environment policy alongside the existing CI-check policy; do not overload or silently change the required-check policy.
- Add policy parsing and drift checks for Python, frontend build admission and workflows. Mirror generated policy into hosting roots if build-context boundaries require it.
- Production mode remains `disabled` throughout preparation. Testing remains `enabled` with separate testing contracts.
- Production creation hashes and start block remain explicitly **unverified** until checked against authoritative evidence. A readiness report with unknown identity is blocked, not green.
- Mode validation is strict. The enabled case requires fresh successful polls, correct scope/anchor, 12 confirmations and zero confirmed-target lag. Never accept either mode merely to permit a transition.
- A change of expected mode is a reviewed activation-policy change, not an automatic consequence of observing the runtime mode.

## 4. Phase A: read-only readiness

### Implementation tasks

1. Extract existing duplicated environment constants into the non-secret policy while preserving behavior.
2. Add contract verification using the established backend Web3 dependency. Check RPC chain, creation status/address, canonical receipt block, current bytecode, tracker registry and computed start block.
3. Compose results with existing API health/release validation. Distinguish unavailable evidence from verified mismatches and from success.
4. Add a manually triggered observer workflow, initially available from trusted main. Check deployed backend compatibility using the existing backend-changing-ancestor logic.
5. Upload only sanitized JSON and a GitHub job summary. Report full release SHAs, public contract evidence, observed time and individual outcomes; redact provider exception messages that may contain credentials.
6. Keep RPC credentials out of fork/PR runs. Ordinary CI validates the verifier against fixtures; hosted verification runs only from reviewed trusted code.

### Acceptance criteria

- Wrong chain, address, registry linkage, deployment receipt, anchor, SHA or indexing policy produces failure.
- An unreachable RPC, missing creation hash or missing required secret produces an explicit blocked/error result, never a pass or fabricated evidence.
- A failed check cannot be hidden by an earlier successful workflow attempt.
- No database mutation permission or provider write credential is needed.
- Existing frontend/backend admission and all eight required checks retain their behavior.
- Reports identify the code/policy they verified and contain no credentials or private row data.

## 5. Phase B: hosted-safe recovery tooling

### Target protections

Require explicit source/target project, branch, host and database identities. Refuse the live branch as any restore/apply target. Verify targets through provider metadata as well as a branch-name prefix; a plausible name alone is insufficient.

Use two frozen roles in the drill: a checkpoint source and a restored target. Live production is not a comparison baseline because it continues changing. Read each database through a consistent read-only snapshot.

### Comparison design

- Discover the application tables/schema rather than relying on the local helper's fixed 14-table list. Include authentication and schema-version state.
- Hash normalized complete rows in deterministic order; stream data where possible rather than loading the whole database into runner memory.
- Include schema constraints, indexes, sequences, defaults and required extensions. Normalize irrelevant owner/name differences explicitly; list every intentional exclusion in the report.
- Record roles/grants separately and verify the intended application's minimum access. Portable dumps using `--no-owner --no-acl` do not reproduce the source access policy.
- Use compatible PostgreSQL client versions, direct connections and fresh empty restore targets. Fail on the first restore error; do not clean or overwrite an existing target.
- Keep raw dumps off standard workflow artifacts. If retained, encrypt them in approved private storage with an agreed retention period and tested retrieval.

### Acceptance criteria

A changed value, missing row/table, altered constraint/index or unusable application role is detected. Frozen source/restore comparison succeeds for an intact restore. Bad target identities are rejected before writes. Error paths do not print connection strings or row contents. Measured recovery time and checkpoint age can be compared with operator-approved RTO/RPO.

## 6. Phase C: isolated hosted rehearsal

### Proposed job sequence

```text
Validate trusted release and policy
  → Verify provider/project/source metadata and resource limits
  → Create private checkpoint and owned working targets
  → Dump, restore, compare data/schema/access
  → Run identity/history dry runs
  → Stop on conflicts; otherwise rehearse explicitly permitted changes
  → Start private indexer, reach confirmed target, restart and recheck
  → Publish sanitized report
  → Cleanup owned disposable resources / report retained resources
```

Start with `workflow_dispatch`, not scheduled production-data copying. Add a schedule only after a successful supervised drill and a cost/retention review. The workflow runs reviewed code from trusted main; do not execute arbitrary PR code with production data or provider secrets. Reject arbitrary checkout refs.

### Isolation and bounded operations

- Full-data recovery needs a normal private branch; schema-only is insufficient. No public preview or shared testing API may use it.
- Configure the private backend with explicit clone connection, production contracts and `ENVIRONMENT=production`; testing mode rejects production addresses. Keep indexing disabled until reconciliation review passes.
- Generate a unique rehearsal JWT secret, retain exact HTTPS origin validation, bind any runner API to loopback, and expose no public tunnel.
- Set job timeout, RPC retry/range limits, maximum branch/compute usage and a recorded cleanup deadline. Choose actual values after checking plan limits and data volume; no paid upgrade is assumed.
- Persist created resource IDs immediately. Cleanup may delete only IDs created by this run after rechecking ownership, parent/project and protected-branch exclusions.
- Use a cancellation-resistant expiry/reaper strategy in addition to `always()` cleanup: job cancellation or runner loss can prevent cleanup steps from executing. The reaper must never delete the source or an unowned resource.
- Reconciliation dry runs acquire locks. Run them serially with the rehearsal indexer stopped; do not treat them as contention-free reads.
- If history attribution is needed before identity consolidation, rehearse that order and rerun the identity report. Stop on ambiguity; no guessed attribution.
- For validation of durable replay, compare canonical identities/projections at recorded chain targets. Poll timestamps and newly confirmed events can legitimately change.
- Keep deterministic reorg and database-fault drills in the existing local integration suite; do not inject faults into the live Sepolia network or production database.

### Acceptance criteria

The report proves complete restore comparison, reviewed reconciliation results, fresh zero-lag indexing and two restart observations without duplicate canonical identities. It records chain target/hash, policy digest, release SHA, resource IDs, recovery timing and cleanup result. Missing credentials, conflicts, timeouts or cleanup failures produce an explicit failed/blocked outcome. A retained failed target is tracked with an owner and expiry; raw dumps are not published.

## 7. Evidence required before activation

Use an allowlisted versioned report format. Proposed fields:

```text
report_version, repository, trusted_workflow_identity, run_id, run_attempt
candidate_sha, policy_digest, schema_revision
observed_at, expires_at
chain_id, registry, tracker, deployment_receipts, start_block, confirmations
source_project_and_branch, checkpoint_time, owned_rehearsal_resource_ids
restore_comparison, access_check, reconciliation_summary
replay_target_and_hash, readiness_result, restart_results
RPO_result, RTO_result, cleanup_status, overall_result
```

Activation fetches evidence by trusted repository/workflow run ID and checks origin, successful **latest** attempt, report schema, candidate identity and policy binding. A user-supplied JSON file or a green unrelated workflow is insufficient. If using signed attestations, verify their issuer/subject as well; do not label an ordinary uploaded artifact cryptographically signed.

Choose a short evidence validity window during implementation, initially proposed at 24 hours. Regardless of that window, recheck the live scope, schema, canonical anchors, approved actions and exact release immediately before activation. If they differ, require a new rehearsal/review. The final activation candidate and effective policy must be covered by evidence; rebasing or changing runtime-affecting code invalidates earlier evidence unless an explicit reviewed compatibility rule proves equivalence.

## 8. Phase D: approval-gated production activation

### GitHub environment and deployment coordination

Create a protected environment proposed as `production-indexing`, with the intended reviewer and trusted-main deployment restriction. Verify reviewer protection is available and actually configured for this repository/plan. If unsupported, use a demonstrable equivalent approval control; do not claim a YAML `environment:` name enforces approval by itself.

Use `cancel-in-progress: false` for production operations. A concurrency group only serializes GitHub jobs in that group: it does not lock Render auto-deploys, manual Dashboard actions or unrelated database writers. Establish a release window and inspect provider queues before changing the runtime flag.

**Activation must account for existing Render auto-deploy.** Merging an activation-policy PR is not itself permission to turn the writer on. Keep `INDEXER_ENABLED=false` until the approved job performs the switch. Validate provider semantics for pinning a deployment to the admitted SHA and changing environment settings before implementing the mutating job. Never assume a generic deploy request selects the intended artifact.

### Proposed activation sequence

1. Validate successful exact-main CI and candidate admission, rehearsal origin/freshness, approved scope and current live state.
2. Present a sanitized approval summary: exact release, expected changes, checkpoint, estimated duration, costs and rollback.
3. Enter the protected approval job; then repeat freshness/target checks because time may have elapsed during review.
4. Confirm exclusive writer ownership and apply the established API write-pause procedure where reconciliation needs a consistent window. There is no generic write-pause flag today; implement it first if the procedure requires one.
5. Take a fresh recoverable checkpoint. Run a fresh live dry run and compare it with the approved plan; stop if materially different. Never pass an arbitrary `--apply` command from workflow inputs.
6. Apply only reviewed actions, then coordinate enabled runtime configuration, expected-mode policy and the exact admitted deployment. Preserve the old serving frontend while the new frontend waits for a ready compatible API.
7. Require fresh/current readiness, correct scope and confirmation policy, zero confirmed-target lag, representative canonical reads and the reviewed restart check.
8. Record deployment IDs and evidence; complete the write-pause release and operator handoff.

### Failure handling and acceptance

If validation fails before mutation, exit without activating. After activation, a failed health/replay check must attempt to disable the writer, verify that action, retain all journal/history and report whether manual intervention is required. Failure to contact Render cannot be described as a successful rollback. Align expected-mode policies through the gated corrective path; do not erase data, downgrade schema or jump the cursor.

Accept only after the approved exact release passes all checks and operator recovery instructions are verified. The implementation must cover wrong/stale evidence, provider timeouts, partial updates, concurrent run attempts, failed writer disablement and queued unrelated deployments.

## 9. Access configuration to prepare

The following are **proposed GitHub Actions names**, not confirmed existing repository secrets. Connector access in this chat does not automatically provide credentials to a runner. This session's cloud environment currently reports no configured secret bindings; repository/environment secrets have not been inspected.

| Location / proposed name | Purpose and boundary |
| --- | --- |
| Protected readiness environment: `SEPOLIA_RPC_URL` | Contract verification; secret because provider URLs can embed keys |
| Variables: production creation hashes and approved non-secret environment policy | Public deployment identity; verify before accepting |
| Protected rehearsal environment: `NEON_API_KEY` | Create/inspect/delete rehearsal resources; use the narrowest provider-supported access and validate project/branch allowlists in code |
| Protected rehearsal variables: `NEON_PROJECT_ID`, `NEON_SOURCE_BRANCH_ID` | Explicit non-secret source selection; no automatic default project |
| Protected rehearsal secret: source read credential, only if needed | Dump/checkpoint reads; prefer deriving a clone-only connection through approved provider access |
| Private backup storage credential/key, if retained off-runner | Restricted backup destination and retention; provider choice remains open |
| Protected activation environment: `RENDER_API_KEY` | Only production deployment/configuration operations needed by the orchestrator, subject to provider scope limits |
| Protected activation database credential, only if approved reconciliation requires it | Restricted to reviewed operations; never share it with ordinary PR jobs |
| GitHub built-in token / optional attestation permissions | Minimal job permissions; start with `contents: read`, add narrowly scoped permissions only where implemented |

Provider API keys may grant more access than a desired single operation. Document the actual scope, compensate with protected environments and strict allowlists, and rotate them. Do not store a wallet private key: verification/indexing needs RPC reads, not signed chain writes.

RPO/RTO, branch retention/cost limits, backup destination and approval owner are configuration decisions before the first hosted drill. They need not block writing phases A–B.

## 10. Validation and rollout checklist

Implementation includes regression coverage for identity mismatches, strict modes, target protection, covered fingerprints, sanitized errors and real dump/restore. The user approved adding/running these tests. Provenance enforcement, resource cleanup/cancellation and production activation recovery remain acceptance work for phases C–D. Run the existing eight required checks before release.

- [x] Phase A implemented and released through protected checks; hosted contract verification remains pending.
- [ ] Read-only hosted identity report succeeds with verified production receipts.
- [x] Phase B comparison detects deliberate differences on disposable local databases; real dump/atomic restore passes and refuses a populated target.
- [x] Phase C orchestration, protected-environment checks, encrypted artifacts and guarded cleanup implemented locally.
- [x] Protected testing environments, reviewer controls, objectives and resource limits configured; archived evidence successfully decrypted through the protected inspection job.
- [x] Testing deployment identity/RPC access passed the protected read-only observer using `recovery-testing` configuration.
- [x] Hosted dump/restore comparison matches with zero differences; RPO, encrypted evidence and cleanup verified in run 40859767005.
- [x] Replacement RPC passes hosted canonical receipts and the initial 1,000-block historical probe (12 events); this does not prove full replay.
- [x] Complete hosted readiness passes with the bounded API startup wait (observer 41169061238).
- [ ] Full historical reconciliation succeeds within the configured objective in a fresh rehearsal. Only a genuine review-required plan can be treated as a non-failing planning outcome.
- [ ] Phase C completes a supervised hosted drill and produces verifiable evidence.
- [ ] Cancellation/cleanup and failed-rehearsal behavior demonstrated safely.
- [ ] Phase D provider coordination and write-pause design verified before mutation support is enabled.
- [ ] Exact activation candidate has fresh matching rehearsal evidence.
- [ ] Explicit production activation approval recorded; gated job completes or reports a verified safe recovery state.
- [ ] Performance, alert delivery, field reporting and business pilot follow the acceptance criteria in the next-steps guide.

**Next operational milestone:** verify scan range recovery and complete a fresh supervised hosted drill using [HOSTED_RECOVERY.md](HOSTED_RECOVERY.md). **Next implementation slice:** phase D production activation. Keep production activation gated until hosted evidence, scope and explicit approval prerequisites are demonstrably satisfied.
