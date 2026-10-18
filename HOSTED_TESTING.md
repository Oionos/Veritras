# Hosted testing

This is a shared testing environment on Sepolia. Production stays on `main`.

## Resources

| Resource | Testing configuration |
| --- | --- |
| Git branch | `testing` |
| Vercel branch preview | `https://veritras-git-testing-hoppaysamas-projects.vercel.app` |
| API | `https://veritras-api-testing.onrender.com` |
| Render service | `srv-db9sd1vbtjjs73ct4240`, My Workspace, Singapore, free compute |
| Neon project | `Veritras Testing` / `blue-sun-65931382`, Singapore |
| Neon branch/database | `testing` / `veritras_preview` |
| Chain | Sepolia, `11155111` |
| Product registry | `0xCf9C169752E1B7AF9A0A54C3086dBa11A2DeE285` |
| Shipment tracker | `0xF5A251812Ec9A7645c29c63656EfB6b307360fDE` |
| First indexed block | `11936014` (`INDEXER_START_BLOCK=11936013`) |

Creation blocks and successful contract deployment transactions are recorded in `blockchain/deployment.testing.json`. No production rows were copied into the testing database.

The first setup journey exposed duplicate checkpoint inserts after a restart. Its database, `veritras_testing`, is retained for diagnosis and is not the application's configured database. `veritras_preview` starts empty and projects only the dedicated testing contracts' history.

Render's existing testing service is managed through its Dashboard/MCP configuration. `render.testing.yaml` is a reproducible template; it is not an attached Blueprint and must not be applied to the live production service. The current MCP creation surface uses Render's default TCP health check. The template also defines `/health/live` for a future Blueprint-managed service; use `/health/ready` to inspect database/indexer readiness separately.

## Cost and credentials

- Sepolia transactions use test ETH from a free faucet. Real ETH is not required.
- The Neon organization is on its free plan, and the Render service uses free compute. No paid upgrade was selected. Provider quotas still apply.
- Render grants 750 free instance hours per workspace per month, shared by its free web services, including production. Sleeping services do not consume these hours. Exhausting the allowance suspends all free web services until the next month; do not add continuous keep-alive pings for testing.
- Render bandwidth and build-pipeline overages can be billed if the account permits them. Free compute does not impose a universal billing cap; review account spending limits if a strict zero-cost ceiling is required.
- Render free compute sleeps when idle; the first request can take longer. Indexing runs while the service is awake. This environment does not promise continuous background indexing.
- Database credentials and a separate random JWT key are stored only in the testing Render service. Its issuer/audience are `veritras-testing-api` / `veritras-testing-web`.
- Vercel's Preview variables contain the testing API, chain, and contract addresses. Production has separate values. The WalletConnect project ID is public browser configuration shared between environments.
- The disposable contract deployment wallet is Sepolia-only and stored under ignored `.testing/` in the setup workspace. It is not an application identity or an administration key for these contracts. Do not send real assets to it or commit its key.

## Development workflow

1. Create a feature branch from current `main` and make the change.
2. For a complete API/frontend test, merge the feature into `testing` and push `testing`. Both Render's testing API and Vercel's branch preview deploy from that branch.
3. Wait for both deployments. Open the stable testing preview above, connect a Sepolia wallet, sign in, and exercise the feature with testing records/contracts.
4. Merge the reviewed feature branch into `main` after its checks pass. A push to `testing` does not publish production.

All Vercel feature previews receive testing frontend settings. They share this API/database/contracts; they are not isolated from one another. A feature preview does not automatically deploy that feature's backend code. Use the `testing` branch for the matching full stack, or provision a separate API/database/contracts for simultaneous backend branches.

### Exact preview origins

The testing API accepts explicitly configured `CORS_ORIGINS` and `SIWE_ORIGINS`. The stable testing branch origin is the primary sign-in scope. Additional deployment/feature URLs must be added explicitly to both settings before their public reads and wallet login work. Do not add a wildcard for all `vercel.app` sites.

After adding an origin, save/deploy the testing Render service and wait for it to be live. An environment-variable update does not prove the running service has loaded it. Use the stable testing branch URL when evaluating later `testing` deployments, because individual deployment URLs change on every build.

Vercel Deployment Protection remains enabled. Team members can open previews through their Vercel login. Automated checks should use Vercel's supported scoped access mechanisms.

## Operational checks

- `/health/live`: `environment=testing`, `chain_id=11155111`.
- `/health/ready`: database connected and indexer current.
- Verify a newly created draft is unregistered, then submit registration against the testing registry and wait for the testing indexer/receipt verification.
- An anonymous write must return 401, another wallet's write 403, and replaying a consumed sign-in challenge 401.
- Check the browser's API requests use `veritras-api-testing.onrender.com` and contract actions use the testing addresses above.
- Confirm the production API remains healthy after testing. Do not seed testing data through the production endpoint.

The durable indexer uses a database cursor, event journal and canonical block anchors. Migration `f04d9c21a873` follows the earlier replay-identity migration and preserves existing records. New history rows remain identified by chain, emitter, transaction and log index; distinct logs in one transaction are preserved. Reorganizations retain orphaned journal occurrences and rebuild affected canonical projections transactionally.

See [DURABLE_INDEXING.md](DURABLE_INDEXING.md) for the confirmation policy, legacy attribution, rollout and recovery procedure. Production indexing remains explicitly disabled until its identity/history reconciliation and enablement checks are complete. Free testing compute can still sleep; durable state does not imply continuous indexing.

Do not reset `testing` to `main` with a force push as a routine workflow. Merge current `main` into `testing` to keep it updated, then resolve conflicts explicitly.

## Canonical identity schema release

API startup now checks the Alembic head without migrating. Apply revision `a38f917bd260` in a separate release transaction before deploying matching API code. Pause/drain the testing writer, rehearse on a copy, preserve all legacy records, then deploy and verify the API/frontend before resuming testing indexing. See [CANONICAL_PRODUCT_IDENTITY.md](CANONICAL_PRODUCT_IDENTITY.md) for source guards, alias reconciliation and the free Render release path. Production indexing remains disabled.
