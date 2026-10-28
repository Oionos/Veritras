# CI/CD readiness and recovery release

Prepared October 28, 2026 (Asia/Manila). Scope: phases A–C. Production indexing remains disabled; this release performs no production migration, reconciliation apply or chain transaction.

## Candidate

- Base: increment 10, `9c4f81984d92c5144291d1bbbf03d2d359d7b679`.
- Feature branch: `codex/cicd-readiness-and-recovery`.
- Existing testing branch has the same base application tree; no upstream changes needed reconciliation at preparation time.
- Schema stays `e93a107bd624`. Existing release-admission checks remain required.

## Validation before publishing

- Backend: **598 passed, five skipped**, with disposable PostgreSQL, actual dump/restore, process-loss checks and three fresh private replay processes using a read-only RPC fixture.
- Frontend: **323 unit tests passed**, TypeScript check passed.
- Browser: **38 Playwright tests passed**, including the frontend build.
- Environment policy copies and Actionlint passed.
- Local workspace disk limits prevent allocating a second complete Docker stack safely; the required GitHub `API and Contract Integration` job will execute the full fresh Docker journey, reorg, interrupted-write/restart and backup rehearsal before staging acceptance. The PR remains draft until staging is verified.

## Staging and protected-main acceptance

Pending external evidence: exact feature CI, ordinary merge into persistent testing, Render/Vercel deployment IDs, matching API health/scope, protected preview reads, and final PR readiness. Record these in the PR/release update when observed; a triggered deploy is not proof it is live.

Production uses a strict disabled-indexer policy throughout this release. Production deployment creation receipts/anchor remain explicitly unknown in policy and block the new full identity/recovery observer; they do not authorize an inferred backfill.

## Hosted recovery configuration

At preparation time GitHub lists only the existing `Preview` and `Production` environments. The integration returns HTTP 403 for repository Actions secrets/variables administration. Recovery environment configuration and a supervised hosted run are therefore separate pending acceptance items; no missing secret is replaced with a development credential.

Follow [HOSTED_RECOVERY.md](../HOSTED_RECOVERY.md) for `recovery-testing`, `recovery-production` and cleanup settings, reviewer/branch restrictions, encryption/ownership keys, provider credentials and recovery objectives. The scheduled reaper stays opt-in. No temporary Neon branch or production-data backup was created by local validation.

Phase D production activation remains unimplemented and separately gated. All readiness/recovery evidence reports state `authorizes_activation: false`.
