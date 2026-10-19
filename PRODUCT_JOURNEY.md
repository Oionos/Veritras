# Public verification, shipment detail and guided demo

Increment 8 adds public product links, locally generated QR labels, a canonical evidence timeline, shipment detail, and a separate guided example. No database migration or contract deployment is required. Production indexing remains disabled under its existing enablement gate.

## Routes and data

| Route | Purpose |
| --- | --- |
| `/verify` | Public product lookup; submitting updates the URL |
| `/verify/:productId` | Direct public lookup, including reloads and existing aliases |
| `/shipments/:shipmentId` | Route/status, indexed handler, evidence, timeline and permitted wallet actions |
| `/demo` | Six-step seeded, simulated browser journey and real testing instructions |
| Unrecognized paths | Named missing-page screen with recovery links |

`GET /shipments/{shipment_id}` is public and hydrates the lifecycle used by shipment lists and analytics. `GET /products/{product_id}/timeline?skip=0&limit=100` resolves aliases, then reads only the bound product's canonical journal in its chain/contract scope. Ordering is block number, transaction index, log index. Pagination exposes every retained canonical event; orphaned occurrences remain in the audit journal and are excluded. Drafts and legacy records without a binding return an explicit empty timeline. No events are inferred from creation dates, placeholder hashes or current metadata.

The timeline includes registration, metadata changes, checkpoints, custody transfers and delivery. URIs and notes are text, never executed or automatically fetched. Receipt/confirmation/synchronization evidence is separate. A mined transaction is not labelled synchronized; recent history can be incomplete while indexing is delayed or disabled.

## QR labels

Use **Share / QR label** from product detail, public verification or shipment detail. Copy the URL or download a printable SVG. A native phone camera can open it; no custom scanner or wallet is required. Generation runs locally without a third-party QR service.

QR payloads use the current site's origin and encoded product path. Query parameters, preview access tokens, sign-in tokens and wallet secrets are never embedded. Generate durable labels on the stable production domain. Testing labels stay on the testing site and display the environment/network; protected previews still require authorized Vercel access. Localhost labels work only on the machine hosting that address. A copied physical label does not authenticate the attached item.

## Wallet and keyboard behavior

On mobile open the labelled navigation menu to connect, switch network, sign in or sign out. The menu scrolls within the viewport. Escape closes wallet dialogs before the menu. Shipment detail checks current contract permissions and canonical identity; manufacturers record the first Created checkpoint, then only legal next statuses from live contract history are offered; current handlers record/transfer, and delivered shipments expose no further actions. Custody destinations must be valid, nonzero and different from the wallet. Account/network changes clear open action forms. API ownership and contract authorization remain authoritative.

Dialogs are named, portalled outside page stacking contexts, scroll within the viewport, make background content inert, trap focus, support Escape, and restore their invoking control. Main content has a skip link and receives focus on route changes. CSS and Framer Motion honor reduced motion; the decorative canvas does not animate for that preference.

## Demo and environments

`/demo` seeds one fictitious coffee shipment in component state. Move through six steps and restart. It never writes to a database, wallet or analytics cache. Live health polling and the business event stream are disabled on this route; live routes reconnect normally. Example dashboard artwork is labelled simulated.

Onboarding points to the stable isolated testing site and a free Sepolia faucet. Sign-in signatures cost no gas; contract writes use valueless test ETH. A receiving handler needs its own test ETH. Do not fund this demo with real ETH or share private keys.

No new environment variables are required. Existing `VITE_APP_ENV`, `VITE_API_URL`, `VITE_CHAIN_ID`, registry/tracker addresses, optional `VITE_RPC_URL` and public WalletConnect project ID determine isolation. Hosted Preview values belong in Vercel's Preview scope, using the testing API/contracts in [HOSTED_TESTING.md](HOSTED_TESTING.md). QR links use the browser origin, without an override or bypass secret. Production admission gates are unchanged. Testing/demo routes request `noindex, nofollow`. SPA rewrites support direct links; titles/descriptions update client-side and do not provide server-rendered social previews.

## Acceptance checks

- API: public detail, aliases, source ordering within a block, pagination, missing/invalid input, orphan/scope exclusion, no invented legacy evidence.
- UI: canonical write IDs, custody validation, delivery/account/network/scope guards, text safety, pagination, SVG escaping, demo stages and focus trap/restore.
- Browser: independent QR decoding, public route reload, shipment timeline, mobile wallet modal, no-API demo and missing-route recovery.
- Full stack: real local browser/API/PostgreSQL/Hardhat journey, then stable hosted testing acceptance before the protected-main release.

Commands and gates: [TESTING.md](TESTING.md), [RELEASE_CONTROLS.md](RELEASE_CONTROLS.md), [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md).
