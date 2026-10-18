# Release controls

## Required GitHub setting

The repository is public and the connected account has repository admin rights, but the connected GitHub integration returns **HTTP 403: Resource not accessible by integration** for branch-protection administration. Repository write access is not administration permission. During increment 7, GitHub's branch endpoint returned `protected: true` for main and the owner explicitly confirmed saving every setting below. Detailed rule readback remains unavailable to this integration; that limit is recorded rather than presenting the rule payload as an API readback.

To enforce the reviewed policy, open [main branch settings](https://github.com/Oionos/Veritras/settings/branches), add a classic protection rule for **main**, and set:

- Require a pull request before merging. Zero additional approvals supports this repository's single-maintainer workflow.
- Require status checks before merging; require the branch to be up to date.
- Require all eight checks from **GitHub Actions**: `Blockchain Tests`, `Backend Tests`, `Frontend Unit Tests`, `Frontend E2E Tests`, `Frontend Build`, `Frontend Lighthouse`, `OpenAPI Types Drift Check`, `API and Contract Integration`.
- Enable **Do not allow bypassing the above settings** (include administrators).
- Keep force pushes and deletions disabled.

The exact REST payload is [release/protect-main.json](release/protect-main.json). An appropriately authorized admin can apply it with:

```sh
gh api --method PUT repos/Oionos/Veritras/branches/main/protection --input release/protect-main.json
```

This payload does not require an additional human reviewer or grant an actor a bypass. The intended release path is a green, up-to-date pull request followed by a squash merge. Do not disable the rule to release a failed commit.

## Hosting gates

Production hosting must wait for successful `CI` and `Isolated Testing Environment` workflows on the exact `main` push commit, with every named job successful. Hosted readiness is intentionally excluded from the release prerequisites: it observes the deployed API and would otherwise create a cycle. Preview/testing deployments keep their isolated environment behavior.

The release policy is mirrored inside each hosting root (`backend/release_policy.json`, `frontend/release_policy.json`); regression tests reject drift. Gates use GitHub's public API and fail closed on missing, failed, cancelled, skipped or untrusted checks. Anonymous access is supported, but shared hosting IPs can exhaust GitHub's anonymous quota. Configure the optional server/build-only `GITHUB_RELEASE_TOKEN` for authenticated lookup: a fine-grained GitHub token limited to this repository, with **Actions: read-only**, **Contents: read-only**, and no write/administration permissions. Add it as a secret on the production Render service; Vercel can use the same variable in Production if its build lookup needs authentication. Never prefix it with `VITE_`, put it in source, or paste it into chat. Provider errors report only a type/status and never the credential or response body. Rate-limit/API failures cannot authorize a release. Bounded waiting ends with a failed deployment rather than releasing unchecked code. Retry the same commit only after its real checks pass.

Render remains on **On Commit**; the production entrypoint holds traffic admission for CI. Do not combine its native **After CI Checks Pass** mode (which waits for all checks) with a readiness check that itself waits for deployment: that introduces a cycle. The readiness workflow starts after CI and observes the latest backend-changing commit, so frontend/document-only releases can reuse a compatible API. Vercel admission also handles frontend-only commits by verifying the latest backend commit. Native provider settings are distinct from the implemented entrypoint/build gates. Production indexing stays disabled under the existing reconciliation/enablement gate.

Render waits at most 13 minutes before refusing startup; Vercel waits up to 15 minutes for CI and another five for the compatible API. A long CI queue, GitHub rate limit, or provider outage can therefore fail a deployment safely. Retry the same commit once both required workflows have actually succeeded. The gate runs again on API process startup; public GitHub availability is a deliberate startup dependency. Existing running deployments keep serving while a replacement waits. These controls apply to this entrypoint/build wrapper; an older artifact predating increment 7 has no such admission gate. Follow [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md) for rollback and recovery.
