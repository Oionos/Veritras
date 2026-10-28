# Next steps: implementation and operations guide

Prepared October 21, 2026. Based on increment 10 at main commit `9c4f81984d92c5144291d1bbbf03d2d359d7b679`. This guide describes future work; writing it does not enable indexing, change a deployment, or establish that the hosted services are currently healthy. Recheck live state before an operational change.

For automation of these procedures, see [the CI/CD implementation plan](CICD_IMPLEMENTATION_PLAN.md), [current commands](CICD_AUTOMATION.md) and [hosted recovery setup](HOSTED_RECOVERY.md). Read-only checks, recovery tools and hosted orchestration are implemented locally; a supervised hosted acceptance run and production activation remain pending. The operational acceptance criteria below still apply.

## 1. What to do first

The next milestone is **a demonstrated, recoverable production indexer**, followed by performance and operational validation with real users.

| Order | Work | Priority | Depends on | Completion evidence |
| --- | --- | --- | --- | --- |
| 1 | Verify production deployment identity and anchor | P0 | Read access to RPC and deployment records | Creation receipts, contract linkage, chain and start block |
| 2 | Rehearse hosted database recovery | P0 | Neon operator access and agreed recovery objectives | Private restored database, comparison report and measured restore time |
| 3 | Rehearse identity/history reconciliation and backfill | P0 | Steps 1–2 | Reviewed changes, conflict-free replay and restart evidence |
| 4 | Prepare strict enabled-indexer release policy; activate production after review | P0 | Steps 1–3 and explicit enablement approval | Green release gates, current indexer, zero confirmed-target lag |
| 5 | Improve performance checks and remaining slow paths | P1 | Can begin alongside steps 1–3 | Reproducible baseline, route coverage, controlled improvement |
| 6 | Prove alert delivery and incident response | P1 | Current monitoring; enabled policy after step 4 | Controlled failure notification, recovery notification/check and named owner |
| 7 | Observe real-user performance | P1 | Traffic and measurement access | Comparable reports with sample sizes and p75 metrics |
| 8 | Complete a defined business pilot | P1 | Reliable testing journey; production prerequisites before a production pilot | Signed-off journey, evidence and prioritized findings |

The operator owns cloud configuration, recovery objectives and production approval. Implementation work includes the policy changes, automated checks, performance work and evidence reports. Access keys belong in provider secret settings, never in the guide or a pull request.

### Set up a private evidence folder

Run from the repository in a clean checkout. Subsequent shell examples assume Bash and the indicated working directory.

```sh
cd /workspace/Veritras
git status --short
git rev-parse HEAD
umask 077
REPO_ROOT="$(git rev-parse --show-toplevel)"
RUN_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/.testing/readiness-$RUN_TAG"
mkdir -p "$EVIDENCE_DIR"
export REPO_ROOT RUN_TAG EVIDENCE_DIR
```

`.testing/` is ignored. Keep raw recovery dumps and reports private because they can contain production data. Put only a redacted summary in the PR: exact SHA, environment, timestamps, result, counts and links to access-controlled evidence. An ignored local folder is not a durable backup; retain important artifacts in approved private storage.

### Identify the environments before touching them

| Environment | Frontend / API | Chain and contracts |
| --- | --- | --- |
| Production | `https://veritras.vercel.app` / `https://chainlens-4qvy.onrender.com` | Sepolia `11155111`; registry `0x1F76018532D619194f6628ADc186e3c86FcB5AaA`; tracker `0x95b09C0aeD53f6b63C072F4ecaC18861FcbBFB30` |
| Hosted testing | `https://veritras-git-testing-hoppaysamas-projects.vercel.app` / `https://veritras-api-testing.onrender.com` | Sepolia `11155111`; registry `0xCf9C169752E1B7AF9A0A54C3086dBa11A2DeE285`; tracker `0xF5A251812Ec9A7645c29c63656EfB6b307360fDE` |
| Local testing | Compose services; frontend `13000`, API `18000`, Postgres `55432`, RPC `18545` | Hardhat `31337`; use that stack's deployment manifest |
| Private production rehearsal | Private restored database and operator-only backend process | Production Sepolia contracts, with an isolated database and no public writes |

These are the recorded environment identities, not a substitute for checking current provider settings. Verify database **project, branch, hostname and database name** privately against the selected Render service. Do not print a credential-bearing connection URL to prove the target.

---

## 2. Verify production contract identity and deployment anchor

**Why:** A correct indexer pointed at the wrong contract or starting too late still produces an incomplete history. The production deployment blocks must be established independently; the testing start block cannot be reused.

### Procedure

1. Open Render → My Workspace → the production API service. Record its source branch, deployed full SHA, environment, chain ID, registry, tracker, confirmation depth and configured start block. Record secret variable names, not their values.
2. Open production `/release.json`. Record the frontend SHA and the backend SHA observed during its build. A frontend-only change may legitimately use an admitted backend ancestor; confirm this against the release gate rather than demanding identical SHAs in every case.
3. Check the production API with the admitted **backend** SHA. Replace the placeholder before running:

   ```sh
   cd "$REPO_ROOT"
   EXPECTED_BACKEND_SHA='<full-40-character-admitted-backend-SHA>'
   python backend/check_health.py \
     --url https://chainlens-4qvy.onrender.com \
     --environment production --chain-id 11155111 --confirmations 12 \
     --expected-commit "$EXPECTED_BACKEND_SHA" \
     --expect-indexer disabled --deadline 180 --interval 15 --timeout 4
   ```

4. In the Sepolia explorer, open each production contract address and locate its creation transaction. Cross-check deployment records, creator and constructor arguments. Save both public transaction hashes in the evidence record.
5. With a trusted Sepolia RPC, verify each creation receipt succeeded, created the expected address, and belongs to the canonical block. Check both addresses currently have bytecode. Call the tracker's `productRegistry()` getter and require the production registry address.
6. Compute `INDEXER_START_BLOCK = min(registry_creation_block, tracker_creation_block) - 1`. Confirm this is the same scope expected by any existing journal/cursor. An incompatible existing cursor needs investigation, not manual editing.

The following **read-only example** uses the installed backend Web3 dependency. Set the three required environment variables privately; the transaction hashes are public. Run in the backend Python environment. It prints only public evidence and deliberately avoids printing RPC exception details.

```sh
python - <<'PY'
import json, os
from web3 import Web3

def inspect():
    w3 = Web3(Web3.HTTPProvider(os.environ['SEPOLIA_RPC_URL'],
                              request_kwargs={'timeout': 10}))
    assert w3.eth.chain_id == 11155111, 'Wrong chain'
    registry = Web3.to_checksum_address('0x1F76018532D619194f6628ADc186e3c86FcB5AaA')
    tracker = Web3.to_checksum_address('0x95b09C0aeD53f6b63C072F4ecaC18861FcbBFB30')
    receipts = []
    for label, address, variable in [
        ('registry', registry, 'REGISTRY_CREATION_TX'),
        ('tracker', tracker, 'TRACKER_CREATION_TX'),
    ]:
        receipt = w3.eth.get_transaction_receipt(os.environ[variable])
        assert receipt['status'] == 1, 'Creation failed'
        assert receipt['contractAddress'] == address, 'Wrong created address'
        block = w3.eth.get_block(receipt['blockNumber'])
        assert block['hash'] == receipt['blockHash'], 'Noncanonical receipt'
        assert len(w3.eth.get_code(address)) > 0, 'Missing contract code'
        receipts.append({'contract': label, 'address': address,
                         'transaction': receipt['transactionHash'].hex(),
                         'block': receipt['blockNumber'],
                         'block_hash': receipt['blockHash'].hex()})
    abi = [{'type': 'function', 'name': 'productRegistry',
            'stateMutability': 'view', 'inputs': [],
            'outputs': [{'name': '', 'type': 'address'}]}]
    linked = w3.eth.contract(address=tracker, abi=abi).functions.productRegistry().call()
    assert linked.lower() == registry.lower(), 'Wrong registry linkage'
    print(json.dumps({'chain_id': 11155111, 'receipts': receipts,
                      'tracker_registry': linked,
                      'indexer_start_block': min(r['block'] for r in receipts) - 1}, indent=2))

try:
    inspect()
except Exception as error:
    raise SystemExit('Verification failed: ' + type(error).__name__)
PY
```

**Accept when:** Both receipts, canonical blocks, bytecode, registry linkage, scope and anchor agree; the health report matches the admitted release and disabled policy. A second reviewer can reproduce the result from public hashes.

**Stop when:** A receipt is unavailable, addresses disagree, the RPC reports another chain, or the cursor has a different scope. Obtain a provider with the necessary historical access; do not guess an anchor or redeploy contracts to manufacture evidence.

---

## 3. Rehearse hosted recovery on an isolated database

**Why:** Local restore tests are implemented. A hosted drill must prove that the actual production data, schema and access configuration can be recovered.

### Decide recovery objectives first

Write down an approved **RPO** (maximum acceptable data loss measured in time) and **RTO** (maximum acceptable recovery duration). For example, a one-hour RPO and one-hour RTO are possible business goals, not capabilities already demonstrated by this project. Choose values based on data value, provider retention and operator availability.

In Neon, inspect the project's actual history retention under Settings → Postgres, its branch/compute limits, and any charges for the drill. Do not assume a free account retains a full day of history. Confirm how backups are retained outside the project if loss of the entire provider/project is in scope.

### Create a private recovery checkpoint

1. In the production Neon project, verify the branch behind the live API connection.
2. Record a UTC checkpoint time `T0` and create a full-data branch from that point within retained history. Give it a clear disposable rehearsal name and record its parent and creation point. Console labels can vary; use the branch creation screen's point-in-time selection.
3. Record the new branch's direct hostname and database name. Keep its connection private. Do not connect Vercel previews, a public API, scheduled jobs or an indexer to it yet.
4. Verify you can connect and read the expected schema and business records. Treat it as production data, with the same access restrictions.
5. Keep this initial branch/database frozen. It is the comparison source, because the live database can continue changing after `T0`.

A branch isolates writes but remains within the same provider/project. It does not by itself prove recovery from project deletion or provider failure. A schema-only branch cannot demonstrate recovery of production rows.

### Prove a logical dump can be restored

Use a supported PostgreSQL client whose `pg_dump` version is compatible with the server. Use a **direct**, non-pooled connection. Configure a private PostgreSQL service entry named `veritras_checkpoint`, pointing to the checkpoint branch; store its password in a protected password file rather than command history. Both files should be readable only by the operator. Use `sslmode=verify-full` with trusted roots where supported, following the provider's connection guidance.

The commands below write only to a **new empty rehearsal database on that checkpoint branch**. Confirm the service entry's host first. They require a role allowed to create databases.

```sh
PGSERVICE=veritras_checkpoint psql -X -v ON_ERROR_STOP=1 \
  -c 'SELECT current_database(), current_user, version();'

BACKUP_FILE="$EVIDENCE_DIR/checkpoint.dump"
REHEARSAL_DB="veritras_restore_$(date -u +%Y%m%d%H%M%S)"
export REHEARSAL_DB

PGSERVICE=veritras_checkpoint pg_dump \
  --format=custom --no-owner --no-acl --file="$BACKUP_FILE"

createdb --maintenance-db='service=veritras_checkpoint' "$REHEARSAL_DB"

pg_restore \
  --dbname="service=veritras_checkpoint dbname=$REHEARSAL_DB" \
  --no-owner --no-acl --exit-on-error --single-transaction "$BACKUP_FILE"
```

If creating a second database is unavailable, use another approved empty private target. Review its host and database name again. Do not add `--clean`, overwrite the source, or run `pg_dump --create` as a workaround. Preserve a failed target for inspection; a partial or failed restore is not success.

### Compare the checkpoint with the restored target

Do this while both databases remain frozen:

- Run `python manage_schema.py` from `backend/` against each explicitly selected database. At the documented baseline, expect `revisions: ["e93a107bd624"]`, `legacy: false`, and no baseline differences. Check `alembic heads` for the selected code before interpreting an older guide as current.
- Enumerate every application table. Compare row counts and deterministic hashes of complete rows, with a stable sort/order and normalized timestamp/JSON representation. Include products, shipments, checkpoints, transfers, canonical and noncanonical events, block anchors, cursors, aliases, registration attempts, exceptions/evaluations and authentication tables.
- Compare schema objects: columns, defaults, primary/foreign keys, unique constraints, indexes, sequences and required extensions. A row-count match alone cannot detect lost constraints or altered values.
- Record and recreate necessary least-privilege roles/grants separately. `--no-owner --no-acl` intentionally does not restore the original ownership and access policy. Verify access using the intended application role.
- Start only an isolated backend with indexing disabled, verify its readiness, and inspect representative product, history, verification and analytics reads. Follow the configuration safeguards in section 4.
- Measure the time from declaring recovery to a verified usable target. Record the checkpoint's age as well as the restore duration. Compare these with the approved RPO/RTO.

**Automation foundation implemented:** `backend/compare_recovery.py` validates explicit target allowlists and compares consistent read-only PostgreSQL snapshots; `backend/rehearse_recovery_restore.py` coordinates private dump/restore into an empty target. See [coverage, limitations and commands](CICD_AUTOMATION.md). Provider ownership verification, lifecycle orchestration, application-role checks and a successful hosted drill are still required. Existing local chain recovery helpers retain their hosted-target safeguards.

**Accept when:** Dump/restore completes without errors; frozen source and target data/schema match; grants work; the isolated API serves consistent reads; measured RPO/RTO meet the chosen objectives; backup retention and access have an owner.

**Recovery if the drill fails:** Preserve the source and failed restore. Diagnose the first restore error, missing permissions, incompatible client or comparison mismatch. Restore into another fresh target after correcting the cause. No production connection switch is part of this drill.

---

## 4. Rehearse reconciliation and durable backfill

Use a separate working copy of the recovered checkpoint so the frozen comparison source remains available. The following procedure changes only the private working database after its dry-run reports have been reviewed.

### Configure the private backend explicitly

Supply secrets through an isolated operator environment, not a committed `.env` file. Verify these values before starting any process:

| Variable | Required value for the private production rehearsal |
| --- | --- |
| `DATABASE_URL` | Explicit connection to the private working restore; verify hostname and database against an allowlist |
| `ENVIRONMENT` | `production` because testing mode rejects production contract addresses |
| `CHAIN_ID` | `11155111` |
| `PRODUCT_REGISTRY_CONTRACT` / `SHIPMENT_TRACKER_CONTRACT` | Verified production addresses from section 2 |
| `SEPOLIA_RPC_URL` | Reviewed private RPC configuration; sufficient historical log access |
| `INDEXER_START_BLOCK` | Anchor verified in section 2 |
| `INDEXER_CONFIRMATIONS` | `12` |
| `INDEXER_ENABLED` | Explicitly `false` during reconciliation |
| `JWT_SECRET_KEY` | Unique private secret of at least 32 characters; do not reuse the live session secret |
| `SIWE_ORIGINS` / `CORS_ORIGINS` | Exact reviewed HTTPS origin(s), without wildcards |

`ENVIRONMENT=production` does not choose the production database automatically. Isolation comes from the explicit database connection and private process. Conversely, missing configuration is dangerous: settings can default to SQLite and an enabled indexer. Validate required variables before loading application settings, and inspect the resolved non-secret target identity.

Bind an operator rehearsal API only to loopback, or use an authenticated private service. Never expose the production-data copy as the normal testing preview. No deployment wallet/private key is needed for RPC reads and indexing.

### Inspect and reconcile

Run in the backend dependency environment, after the target check:

```sh
cd "$REPO_ROOT/backend"
python manage_schema.py
alembic heads
python manage_identity.py > "$EVIDENCE_DIR/identity-dry-run.json"
python manage_indexer.py > "$EVIDENCE_DIR/history-dry-run.json"
```

Both reconciliation tools acquire database writer locks and inspect confirmed canonical chain evidence. A dry run rolls back database changes, but can still contend with other writers and consume RPC quota. Run them serially while the private indexer is stopped.

Read the complete reports:

- Identity output includes `applied`, proposed `changes`, and `conflicts`.
- History output includes `matched_rows`, `conflicts`, and `applied`.
- Every attribution must resolve to a unique authoritative event. Product names, old manufacturer text and placeholder transaction hashes are insufficient evidence.
- Unmatched legacy rows remain legacy/unverified. Do not invent ownership or a chain registration to make a report green.
- When duplicate identity consolidation depends on history attribution, review and apply the history matches first. Then rerun the identity dry run and review its new result before applying identity changes.

Only after reviewing the exact report and target, the available mutating commands are:

```sh
# Private working restore only; run each only when its report is approved.
python manage_indexer.py --apply
python manage_identity.py
# Review this new identity report before the next command.
python manage_identity.py --apply
```

Do not run both applies blindly. Stop on conflicts. Capture before/after counts and proposed identities. `manage_schema.py --apply` is not a routine prerequisite: the increment 10 schema is already current, so no migration is expected merely to enable indexing.

### Replay and test restart behavior

1. Record the confirmed target block and its hash, plus initial journal/cursor and business counts.
2. On the private working restore, change `INDEXER_ENABLED=true` and start the reviewed backend version. There is no standalone backfill command: the normal durable indexer performs the replay in bounded batches.
3. For a local operator process, verify the checkout SHA and schema first, then use the ASGI development entrypoint bound to `127.0.0.1` on a separate port. This is a private rehearsal, not evidence that Render image admission passed. A hosted rehearsal must use the normal admitted artifact/entrypoint; retain production admission checks.
4. Observe cursor progress, confirmed-target lag, RPC errors and `/health/ready`. Backfill can legitimately return 503 while catching up. Do not loosen readiness to report a partially indexed database as current.
5. At zero lag, compare each event's chain/contract/transaction/log identity with RPC evidence. Check registration receipts, metadata changes, checkpoint order, custody, delivery and analytics treatment of legacy/noncanonical records.
6. Restart the same version gracefully. Require readiness to recover and the cursor to resume. Canonical events and projections must not duplicate. New chain events may legitimately increase counts; compare against the recorded chain target rather than expecting a live database hash never to change.
7. Repeat a restart and retain both observations. Cursor poll timestamps may change even when business data does not.

Deterministic reorg and interrupted-write fault injection belong on the local chain. Run the existing local checks serially in a **fresh isolated Compose namespace** after checking disk space and fixed-port conflicts:

```sh
cd "$REPO_ROOT"
export TESTING_COMPOSE_PROJECT="veritras-readiness-$RUN_TAG"
make testing-up
make testing-check
make testing-indexer-check
make testing-recovery-check
make testing-release-rehearsal
cd frontend
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='/actual/path/to/chromium' \
  node scripts/check-local-auth.mjs
```

These checks share one chain; do not run them concurrently. Retain older volumes. `make testing-reset` deletes data and is not part of this procedure. The local Hardhat chain is in memory while Postgres persists: restarting an old stack can produce an incompatible chain/database pair. Use a fresh namespace for a new rehearsal rather than rewriting an old cursor. Stop any existing stack that occupies the fixed ports first.

**Accept when:** All reviewed changes are justified; no ambiguity is unresolved; replay reaches a fresh zero-lag state; chain-backed identities and projections agree; restarts do not duplicate data; local reorg/write-failure/recovery checks pass; the private restore remains recoverable.

---

## 5. Prepare the release policy before enabling production indexing

**Important finding:** Flipping Render's flag alone would break the reviewed release expectations. The automation foundation now shares the expected policy across consumers; production still expects indexing to be disabled.

| File | Current expectation | Required work |
| --- | --- | --- |
| `frontend/release-gate.mjs` | Reads shared policy; production expects disabled | Change policy only with the reviewed activation; enabled readiness validation is implemented |
| `frontend/release-gate.test.ts`, `frontend/environment-policy.test.ts` | Both strict modes and unhealthy/mismatched evidence covered | Rerun against the exact activation candidate |
| `.github/workflows/hosted-health.yml` | Reads the shared expected mode | Verify against the reviewed activation policy |
| `.github/workflows/operations-monitor.yml` | Reads the shared expected mode | Verify against the reviewed activation policy |
| `render.yaml` | Production disabled | Align deployment configuration with the approved activation |
| Backend Docker default | Disabled by default | Preserve an explicit safe default; use reviewed runtime configuration |

The automation foundation provides a versioned shared environment policy and strict mode handling; production's expected mode remains disabled and this implementation does not change the recorded disabled runtime setting. See [policy maintenance](CICD_AUTOMATION.md). Do not change the gate to accept either mode indiscriminately.

### Use two reviewed phases

**Preparation PR (implemented locally, release pending):** Strict policy handling and regression coverage keep production's expected mode disabled. Cases cover healthy disabled mode, healthy enabled mode, wrong environment/chain/SHA, stale polls, nonzero lag and policy mismatch. Release through protected checks and confirm deployed production/testing behavior before activation.

**Activation PR:** After sections 2–4 are accepted and explicit enablement is approved, coordinate the expected mode, provider runtime setting and source configuration. Include the exact activation order, rollback and deployment IDs in this PR.

Release through the existing route: feature branch → persistent testing branch → protected main PR → all eight required checks → squash merge → exact-main push checks → provider admission → hosted verification. Keep Render's native auto-deploy mode **On Commit**; the Docker build supplies the CI admission gate.

### Production activation checklist

1. Confirm no unrelated/queued deployment can accidentally pick up the activation environment. Record the intended exact release and verified database scope.
2. Establish a controlled window for any reviewed reconciliation writes. Disabling indexing does not stop API writes. There is no general maintenance-mode flag today; if API writes cannot be safely paused through an established operational control, implement and test that control first.
3. Take a fresh recoverable checkpoint and retain a snapshot of the current journal/cursor. Pause every old projection writer; confirm one intended indexing owner.
4. Apply only changes that were rehearsed and explicitly approved against the exact live target. Stop if the fresh dry run differs materially from the reviewed report.
5. Stage the approved runtime configuration in Render. **Save only** stores changes for the next deployment; it does not change the running process. **Save and deploy** restarts with the new environment using an existing build. **Save, rebuild, and deploy** performs a new build. Choose the reviewed sequence deliberately; do not accidentally restart early.
6. Deploy the activation release through the normal gates with the enabled policy and runtime configuration coordinated. Ensure an attached Blueprint will not overwrite the intended Dashboard settings.
7. Wait for backfill. Run the health command from section 2 with the actual backend SHA and `--expect-indexer enabled`. Require HTTP 200, correct scope/anchor, 12 confirmations, current state, fresh successful progress and zero confirmed-target lag.
8. Inspect business reads and journal identities, then perform the reviewed graceful restart check. Run hosted readiness and Operations Monitor with their enabled expectations.
9. Record the final API/frontend attestations and reopen controlled writes only after the result is accepted.

The frontend API wait is bounded. If initial backfill exceeds it, retain the serving frontend and retry the exact checked release after readiness is established. Do not accept `catching_up` as ready or weaken CI admission to finish a deployment.

**Accept when:** The enabled policy agrees across application gate, workflows and runtime; exact release admission succeeds; readiness is fresh/current at zero lag; representative reads agree with canonical evidence; restart recovery is demonstrated; rollback instructions have an owner.

**If activation fails:** Stop the writer by setting `INDEXER_ENABLED=false` and applying that environment change through the appropriate deployment action. Preserve the database and cursor. Align the release/monitoring policy back to disabled in a corrective gated change; an enabled expectation will correctly report a policy mismatch until that alignment is restored. Record maintenance and investigate the first failure. Never clear history, manually advance the cursor, or perform a destructive downgrade to make readiness pass.

---

## 6. Improve performance with reproducible measurements

The increment 10 controlled mobile median was LCP **5.368 s**, TBT **448 ms**, CLS **0**, and initial script gzip **383,058 bytes**. These are historical lab results, not a field baseline or a guarantee on every machine. The current browser startup budget is **450,000 gzip bytes**.

### Establish a comparable baseline

Use the locked dependencies, Node 24 for the measurement script's TypeScript fixture import, and an installed Chromium executable. Avoid running CPU-heavy integration stacks while collecting lab comparisons. From `frontend/`:

```sh
npm ci
CI=true VITE_API_URL=http://127.0.0.1:18010 \
  VITE_WALLETCONNECT_PROJECT_ID=ci-test-project-id \
  npm exec -- vite build --manifest

PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='/actual/path/to/chromium' \
  node scripts/measure-performance.mjs dist "$EVIDENCE_DIR/performance-before"
```

The script starts its own fixture server on `18010` and browser debugging port `19222`. It collects three cold-cache mobile Lighthouse runs, a summary and screenshot. Keep those ports free. The browser path must exist; `/usr/bin/chromium` is only the script's default, not a portable installation location.

Record SHA, Node/browser versions, machine, viewport, network/CPU settings and fixture version. After an optimization, rebuild and run the same command with a different output directory such as `performance-after`. Compare medians, all individual runs, transferred bytes and startup scripts.

### Fix the coverage gap before trusting the score

The current LHCI configuration uses a static build and the inherited `/index.html` scenario. It does not establish performance for every real application route. The controlled script currently has dashboard/basic-product fixtures, not a complete registration/exception/timeline backend.

Implement a separate performance PR that:

1. Extracts a reusable deterministic fixture server from the controlled measurement setup.
2. Serves the actual application routes and explicit API fixtures for the selected dashboard, verification and shipment scenarios.
3. Configures LHCI with an explicit server start command and absolute scenario URLs. Confirm it measures the intended page content rather than an empty/error screen.
4. Blocks uncontrolled third-party network requests in lab comparisons. Adds the necessary fixture response schemas for each new route.
5. Keeps raw Lighthouse reports and route screenshots as CI artifacts.

Do not claim these new scenarios exist until implemented and checked.

### Optimize one measured cause at a time

Use Lighthouse's LCP element and main-thread trace plus the Vite manifest to choose the work. Candidate changes include reducing remaining startup dependencies, removing initial render work, sizing the LCP element correctly, and preventing layout shifts. Chart and remote-wallet SDK deferral already exist; verify they stay deferred rather than counting them as new work.

Recheck opening the navigation menu and wallet picker, scrolling charts into view, route changes and error/loading states. Proposed next lab targets are mobile median **LCP ≤4.3 s**, **TBT ≤300 ms**, **CLS ≤0.1**, with startup scripts within **450,000 gzip bytes**. These are proposed improvements, not current universal CI thresholds. Existing LHCI thresholds are recorded in `frontend/lighthouserc.cjs`; change them only after establishing an honest scenario and baseline.

**Accept when:** The same frozen scenarios reproduce before/after results; all target routes render real content; the selected bottleneck measurably improves without breaking wallet, charts, accessibility or navigation; relevant unit/browser/build checks and the normal release gates pass. A higher single-run Lighthouse score alone is insufficient.

---

## 7. Prove monitoring and alert delivery

The current Operations Monitor runs every six hours at minute 15 UTC. It is a scheduled check, not continuous availability monitoring. It checks consecutive readiness observations, recent API error counters, and a real SSE heartbeat. An HTTP 200 from `/health/operations` alone does not prove the nested health state is good.

### First run the existing monitor

In GitHub → Oionos/Veritras → Actions → Operations Monitor → Run workflow → main. Or, with an authenticated GitHub CLI:

```sh
gh workflow run operations-monitor.yml --repo Oionos/Veritras --ref main
gh run list --repo Oionos/Veritras --workflow operations-monitor.yml --limit 5
gh run view '<run-id>' --repo Oionos/Veritras --log-failed
```

For a direct operator check using the current disabled production policy:

```sh
cd "$REPO_ROOT"
python backend/monitor_operations.py \
  --url https://chainlens-4qvy.onrender.com \
  --environment production --expect-indexer disabled
```

After activation, use `enabled` and update the workflow policy. `monitor_operations.py` has a cold-start `--grace` option; `check_health.py` uses `--deadline`. They are different interfaces. Read the diagnostic category when a run fails instead of treating all cold-start delays as application defects.

### Prove a human receives an actionable failure

1. Name a primary responder and backup. Choose a recipient/channel explicitly; verify that person's GitHub Actions notification settings and repository access.
2. Add an opt-in fixture workflow or isolated synthetic service for controlled failures. The existing workflow has fixed production/testing targets and no fault-injection input; creating a safe fixture path is new work.
3. Simulate, separately, persistent not-ready/stale indexer state, repeated API 5xx, and an SSE connection that never heartbeats. Keep the monitor's production criteria intact.
4. Trigger a fixture failure, record its workflow ID, and have the recipient confirm delivery and useful context: environment, failure category, timestamp, run link and first response action.
5. Restore the fixture and prove the next check passes. Record who closes the incident and how recovery is communicated.
6. If using optional Sentry, separately verify delivery with a deliberate sanitized test error. Replay is off; do not include signatures, wallet secrets, product notes or private URLs in the event.

Do not break the production API, silence its stream, or generate business writes merely to test notifications. Process-local counters reset at restart; they are not a durable incident history.

**Accept when:** Both live environments pass their intended policies; controlled fixture failures reach the chosen responder; recovery is confirmed; escalation ownership and a short response checklist are documented. A green workflow alone proves neither email delivery nor human response.

---

## 8. Collect real-user performance evidence

Lab measurements help diagnose code. Field measurements determine what users experience on their devices and networks.

1. In Vercel, select the actual production project and inspect Speed Insights/Analytics availability, retention, access and current plan limits. Use the available dashboard/export path; do not assume an upgrade or programmatic API access is enabled.
2. Define cohorts before collecting results: production deployment, route, mobile/desktop, and geography/network where available. Keep browser and API failure diagnostics separate from performance measurements.
3. Collect a baseline over a complete representative period, for example seven days. After a release, collect an equally representative period using the same filters. Record the deployment boundary and excluded incidents.
4. Report p75 LCP, INP and CLS with counts and coverage. Suggested good-experience thresholds are LCP ≤2.5 s, INP ≤200 ms, CLS ≤0.1. A pilot target such as 100 observations per important cohort is a planning floor, not statistical proof; low traffic may require a longer window.
5. Use lab traces to investigate poor routes, then repeat the field comparison. Menu-click timing from the local script is not field INP.

The project does not have a demonstrated pre-increment-10 field baseline. Do not reconstruct one from lab numbers. Start a real baseline now and label periods with inadequate data as pending.

**Accept when:** Reports contain source, dates, release, filters and sample counts; important cohorts have enough coverage for a useful decision; regressions produce concrete follow-up work; telemetry contains no sensitive payloads. With insufficient traffic, leave field acceptance pending rather than declaring success.

---

## 9. Run a business pilot with a complete acceptance journey

Begin on hosted testing with separate testing contracts and database. Sepolia uses test ETH; faucet funding need not involve purchasing real ETH. Provider subscriptions, extra resources or a paid faucet may still have separate costs. A production pilot requires the preceding production readiness gate and an agreed scope.

### Define the pilot

Choose one product type, one route, a small agreed number of items, and the people responsible for manufacturer, custodian/receiver and anonymous verification. Write down the business question: for example, whether a receiver can verify the item's recorded registration and custody without help. Blockchain provenance records what participants recorded; it does not independently establish physical authenticity.

Use distinct manufacturer wallet A, receiving wallet B, and unauthorized wallet C. Use a new pilot item per completed lifecycle, because delivery is terminal under the current contract behavior. Agree how feedback is recorded and who resolves blockers.

### Execute this checklist per pilot item

| Step | How to perform it | Required outcome/evidence |
| --- | --- | --- |
| Sign in | Connect A on the correct chain; complete the wallet signature challenge | Session is valid for the intended origin/wallet; wrong origin or replay is rejected |
| Create and register | Create a draft, submit the real registration transaction | Draft, pending and confirmed states are distinct; retain transaction hash and canonical identity |
| Confirm evidence | Wait for the configured 12 confirmations and indexer catch-up | UI/API evidence agrees with canonical receipt, registry and chain; a submitted hash alone is not verified |
| Recover the browser | Reload/reopen while registration is pending and after confirmation | Registration attempt and final identity persist without duplicate registration |
| Change metadata | Submit a supported metadata update | New value and authoritative transaction appear; prior history remains attributable |
| Transfer custody | Transfer A → B and inspect B's session | B becomes the authorized handler; A/C cannot make unauthorized subsequent writes |
| Record movement | Add valid checkpoints and inspect the shipment timeline | Ordered canonical history, correct handler and shipment lifecycle |
| Exercise exception rules | Choose a supported policy and controlled testing scenario | Exception state explains its evidence and resolves according to the implemented policy |
| Deliver | Complete delivery with the authorized handler | Terminal delivery state and history agree; invalid later contract writes revert |
| Verify by QR | Scan using a second physical phone as an anonymous user | Correct testing URL/item, no sign-in required for public verification, readable on mobile |
| Inspect analytics | Apply relevant filters and export | Counts/history agree with the item's canonical state and legacy/noncanonical exclusions |
| Attempt prohibited actions | Use C; attempt duplicate registration and invalid lifecycle transitions | Appropriate authorization failures/reverts with understandable UI messages and no corrupted state |

Use API 401 for unauthenticated scenarios and 403 where an authenticated wallet lacks permission, as applicable to the endpoint. Preserve contract revert evidence separately. Do not deliberately make unauthorized attempts against someone else's production item.

Measure task completion time, help requests, failed attempts, confusing labels and receiver confidence. Review every unresolved issue with severity and owner. Mark the pilot blocked if a core journey cannot complete; a successful screenshot of one screen is not pilot acceptance.

**Accept when:** All agreed pilot items complete the journey; recorded chain/API/UI evidence agrees; unauthorized writes fail; QR works on an actual phone; no unresolved critical correctness/security issue remains; participants accept the workflow and remaining findings have owners and priorities.

---

## 10. Evidence and troubleshooting

### Copy this record for each work item

```text
Work item / priority:
Owner and reviewer:
Status: pending | in progress | blocked | accepted
Code SHA / schema revision:
Environment / non-secret database identity / chain / contracts:
Start and finish times (UTC):
Approved objective and acceptance checks:
Exact commands, provider actions and workflow/deployment IDs:
Expected result:
Observed result and private artifact locations:
Data counts/hashes and canonical chain target, where relevant:
Recovery/rollback action and evidence:
Open issue, impact, owner and next action:
Reviewer acceptance and date:
```

| Symptom | Check first | Appropriate response |
| --- | --- | --- |
| `/health/live` 200, readiness 503 | Readiness body: database, schema, indexer state, scope and lag | Fix the identified dependency; liveness alone does not establish readiness |
| Protected testing preview returns 403 | Vercel Deployment Protection and the chosen access method | Use approved authenticated access; do not remove protection from a production-data clone |
| Reconciliation conflict | Exact legacy rows and confirmed authoritative chain evidence | Stop applies; resolve on the private restore and rerun the dry run |
| Wrong/missing database config | Explicit host/database validation and required environment variables | Stop before importing settings or executing a tool; do not accept SQLite fallback |
| Catch-up stalls | RPC availability/range limits, writer lock, cursor scope and first failing batch | Fix the cause and resume the same durable cursor; do not jump it forward |
| Writer disabled but release gate fails | Expected policy in frontend gate/workflows vs actual runtime flag | Align the reviewed policy; do not accept both modes to suppress the failure |
| Old local stack reports chain mismatch | Persisted Postgres vs newly restarted in-memory Hardhat | Retain old evidence and create a fresh consistent rehearsal namespace |
| Restore counts match but reads fail | Schema constraints, extensions, grants, environment and application role | Correct the restore process and retry into a fresh target |
| Frontend build times out waiting for API | Exact CI attempts, backend deployment and real readiness | Keep serving release; retry the checked SHA once the dependency is ready |
| Monitoring says healthy but no notification arrived | Whether a controlled failure actually occurred; recipient settings/delivery | Prove delivery with an isolated fixture, then record recipient confirmation |

### Related project documents

- [Implementation plan](IMPLEMENTATION_PLAN.md)
- [Release and recovery procedure](RELEASE_RUNBOOK.md)
- [Required release checks](RELEASE_CONTROLS.md)
- [Hosted testing configuration](HOSTED_TESTING.md)
- [Durable indexing](DURABLE_INDEXING.md)
- [Canonical product identity](CANONICAL_PRODUCT_IDENTITY.md)
- [Indexer health](INDEXER_HEALTH.md)
- [Operations](OPERATIONS.md)
- [Performance evidence](PERFORMANCE.md)

Provider references checked while preparing this guide:

- [Neon branching](https://neon.com/docs/introduction/branching)
- [Neon recovery workflows](https://neon.com/branching/recovery-workflows)
- [Neon PostgreSQL dump/restore guidance](https://neon.com/docs/import/migrate-from-postgres)
- [Render environment variables and save/deploy behavior](https://render.com/docs/configure-environment-variables)

**Immediate next action:** Complete the production deployment-identity record in section 2, while choosing recovery objectives and reserving a private hosted restore target for section 3. Keep production indexing disabled until the rehearsal, strict policy change and explicit enablement review are complete.
