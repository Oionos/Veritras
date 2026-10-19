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

The release policy is mirrored inside each hosting root (`backend/release_policy.json`, `frontend/release_policy.json`); regression tests reject drift. Gates use GitHub's public API and fail closed on missing, failed, cancelled, skipped or untrusted checks. Rate-limit/API failures cannot authorize a release. Bounded waiting ends with a failed build. Retry the same commit only after its real checks pass.

Render remains on **On Commit**. Its Dockerfile checks CI during the image build, before replacing the API, and records `.release-admission.json` inside the built image. Startup validates the exact commit, repository, branch, policy digest and workflow identities locally before checking schema. It makes no GitHub request, so cold starts/restarts of an admitted image do not depend on GitHub availability or quota. A missing, stale or incompatible build proof refuses startup. Source copies of this generated proof are excluded from Docker context; every build discards stale proof before admission.

Do not combine native **After CI Checks Pass** mode (which waits for all checks) with a readiness check that itself waits for deployment: that introduces a cycle. The readiness workflow starts after CI and observes the latest backend-changing commit, so frontend/document-only releases can reuse a compatible API. Vercel admission also handles frontend-only commits. Native provider settings are distinct from the implemented build gates. Production indexing stays disabled under the existing reconciliation/enablement gate.

Render's build waits at most 13 minutes; Vercel waits up to 15 minutes for CI and another five for the compatible API. A long CI queue or GitHub outage can fail the candidate build safely. The last admitted image remains the rollback target. The original startup-based gate exposed a free-service interruption while a candidate waited; the Docker build gate removes that wait from API startup. Older artifacts predating these controls need explicit historical-CI review before rollback. Follow [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md).

### Authenticated build lookup

Anonymous lookup is supported, but shared hosting IPs can exhaust GitHub's anonymous quota. If authentication is needed, create a fine-grained token limited to `Oionos/Veritras` with **Actions: read-only**, **Contents: read-only**, and no write/administration permissions.

For Render Docker builds, use **Environment → Secret Files → Add Secret File**, filename **`github-release-token`**, containing only that token. The Dockerfile reads it through a BuildKit secret mount. The filename is excluded from Docker context; its contents are never saved in the image, admission proof or logs. Do not pass it through Docker `ARG`/`ENV`. Render's connected tools cannot create this account credential or manage secret files, so the owner must save it privately. Never paste the token in chat.

Vercel can use the optional build-only **`GITHUB_RELEASE_TOKEN`** Production variable if its lookup needs authentication. Never prefix it with `VITE_` or commit it. Provider errors report only type/status; rotate the token before expiry. Existing admitted API images can restart even when the build credential expires; a new release still needs successful CI admission.
