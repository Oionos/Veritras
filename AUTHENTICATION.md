# Wallet authentication and ownership

Implementation increment 2, prepared October 18, 2026 on `codex/wallet-auth-and-permissions`. This increment requires a database migration and hosted configuration before production deployment. It does not enable historical indexing.

## Sign-in flow

1. The browser sends its wallet address to `POST /auth/challenge` from an explicitly allowed origin.
2. The API stores a five-minute challenge in PostgreSQL and returns the exact EIP-4361 message to sign. The server selects the origin, domain, chain, issue time, expiration, and nonce.
3. The wallet signs that message. The browser checks that it describes this origin, wallet, and selected chain before asking for the signature.
4. `POST /auth/verify` uses `siwe` to parse and verify the message, checks its stored scope and lifetime, then atomically deletes the valid challenge. Invalid signatures do not consume it. A challenge can succeed once across workers or API restarts.
5. The API returns a scoped HS256 bearer token with wallet subject, chain, issuer, audience, issue/expiry times, and token identifier. API writes verify these claims.

`GET /auth/nonce` remains for older clients, with server-selected scope and a database-backed expiration. New clients should sign the canonical message returned by `/auth/challenge`. External clients without an Origin header use the configured primary sign-in origin, not an untrusted Host header.

This implementation supports externally owned wallet signatures. EIP-1271 contract-wallet sign-in needs separate provider-aware support. Public product, shipment, analytics, and verification reads remain available without login.

The frontend shares one session store across components and tabs. Disconnecting, switching wallets or networks, token expiry, signing out, or a rejected bearer token clears the browser session. Signing out clears local credentials; it does not revoke a token already copied elsewhere. Old unscoped tokens and invalid persisted strings require signing in again.

## Permissions

| Action | Required identity |
| --- | --- |
| Create a product draft | Signed-in wallet; manufacturer and ownership come from that wallet |
| Edit draft registration fields | Established draft owner, while the registry confirms it is unregistered |
| Edit registered product fields through SQL | Rejected; chain-controlled fields must follow the contract flow |
| Create or edit shipment planning fields | Established owner of the associated product |
| Set shipment status through API input | Rejected; status changes derive from indexed contract events |
| First checkpoint | Manufacturer, as checked by the contract |
| Later checkpoint or custody transfer | Current handler, as checked by the contract |

The frontend disables unsupported contract actions using current contract reads. Contract validation remains authoritative. It offers only owned products when planning a shipment, and hides draft/planning edits for other wallets.

### Legacy records

`owner_address` and `ownership_source` are nullable on purpose. Existing manufacturer values came from anonymous clients and do not establish ownership. The migration does **not** copy them into owner fields.

New authenticated drafts use `signed_draft` provenance. The indexer records `chain_event` provenance when it processes a real registration event. Legacy records remain publicly readable and read-only until explicitly reconciled against chain evidence in the subsequent identity/indexing increments. Do not grant ownership by bulk-copying manufacturer addresses.

Draft edits also query the configured registry, because an unindexed registration can leave placeholder fields in PostgreSQL. A wrong or unavailable RPC pauses hosted draft edits with 503. Known registrations reject SQL edits with 409. Ownership failures return 403; absent or invalid credentials return 401.

## Required configuration

Supply secrets through Render's environment settings, never the frontend or Git:

- `ENVIRONMENT=production` for the live service.
- A strong random `JWT_SECRET_KEY` with at least 32 characters. Render is treated as hosted even if a stale environment label still says development. The public development/testing defaults are rejected for hosted sign-in.
- `JWT_ISSUER=veritras-api` and `JWT_AUDIENCE=veritras-web`, or your explicit matching service policy.
- `SIWE_ORIGINS=https://veritras.vercel.app` for production. Use exact isolated preview origins in a testing service; wildcards are not accepted. When omitted, the explicit CORS origins are used. Hosted Sepolia sign-in requires HTTPS.
- `CHAIN_ID=11155111` for Sepolia, or 31337 only in the isolated local stack.

The local Compose stack supplies separate scope, database, JWT key, and contracts. `AUTH_CHALLENGE_TTL_SECONDS` defaults to 300, with up to 30 seconds of clock skew for the compatibility nonce flow. Tokens expire after `JWT_EXPIRATION_HOURS` (1–24, default 24).

The reviewed dependency set pins `siwe==4.4.0`, compatible `eth-account==0.13.7`, and `abnf==2.2.0`. Newer ABNF grammar rules reject SIWE's bundled RFC 5234 definitions; do not independently raise that pin without checking the parser integration.

## Migration and release

Revision `b19e8a6c4f20` adds nullable ownership columns and the indexed challenge table. It does not rewrite existing business records.

1. Inspect the live schema and establish a recoverable checkpoint. Rehearse migration and authenticated flows on an isolated Neon branch first. Use a direct database connection for migrations.
2. With that connection configured privately, run the read-only inspection:

   ```sh
   cd backend
   python manage_schema.py
   ```

3. If the database has an existing Alembic revision or is empty, apply normally:

   ```sh
   python manage_schema.py --apply
   ```

4. If the database has the four legacy tables but no revision, inspect `baseline_differences`. Only after confirming the schema matches the original migration and rehearsing the operation on a branch, adopt the baseline and apply the additive revision:

   ```sh
   python manage_schema.py --apply --adopt-legacy
   ```

   A mismatch blocks adoption. Resolve it explicitly; do not blindly stamp or replay the initial migration. PostgreSQL adoption and upgrade share one transaction and migration lock, with a five-second lock timeout.

5. Set the exact hosted sign-in origins and strong JWT key. Confirm the live service uses the backend Docker entrypoint, or run the migration separately before a custom API command. The Docker entrypoint upgrades a versioned/empty database before serving; it refuses automatic adoption of an unversioned legacy schema.
6. Release the compatible backend before the frontend where deployment controls permit. The current main-branch integrations deploy both automatically; prepare migration and configuration first, then monitor both builds. Sign-in can briefly require a retry while the backend rollout completes. Exercise signed login, owner writes in testing, another wallet's denied writes, nonce replay rejection, and public verification. Registration data and indexing remain separate concerns.

The initial inspection found the live Neon project's four business tables and an **empty** `alembic_version` table. The schema matched the original migration. Adoption and the additive migration were rehearsed on the isolated `codex-wallet-auth-20261018` Neon branch: its existing product and shipment were preserved, and neither gained ownership. The user authorized security tests and selected Render's `My Workspace` for the release.

## Validation recorded on October 18, 2026

- Backend unit/API/migration regressions: **187 passed**, including Python 3.11 in the testing image.
- Frontend unit tests: **191 passed** across 33 files.
- Existing mocked Playwright regressions: **23 passed**.
- Real PostgreSQL + API + Hardhat smoke journey passed registration, checkpoints, custody, delivery, receipt checks, authentication replay rejection, and write permissions.
- Real Chromium wallet journey passed owner creation/editing, automatic logout on wallet changes, another wallet's denied writes, public reads, and challenge persistence across an API restart.
- Neon migration rehearsal preserved legacy records with zero ownership grants.
- Python compilation, dependency consistency, generated OpenAPI/types, and TypeScript/Vite build passed.

The local browser check is `cd frontend && node scripts/check-local-auth.mjs` after `make testing-up`. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` when using a system Chromium instead of Playwright's browser bundle. This check refuses non-local targets and chain IDs other than 31337. It creates labeled testing records and restarts only the testing API.
