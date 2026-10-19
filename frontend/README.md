# Veritras frontend

React 19, TypeScript and Vite application for recorded product provenance, shipment custody and analytics. RainbowKit/Wagmi connects wallets; API writes require a signed wallet session.

## Start safely

Use Node 22.12+ and npm 11. From the repository root run `make testing-up` for isolated PostgreSQL, Hardhat, API and frontend. See [TESTING.md](../TESTING.md) for named Compose projects and ports. Testing cannot use production contracts/API.

For frontend-only development run `npm ci`, configure the public values in `.env.example`, then `npm run dev` (port 3000). `VITE_*` values are browser-visible: never add private keys or service tokens. Hosted Preview requires `VITE_APP_ENV=testing`, an HTTPS testing API, Sepolia and distinct testing contracts. See [HOSTED_TESTING.md](../HOSTED_TESTING.md).

## Routes

- `/products`: records, registration lifecycle and metadata evidence.
- `/shipments`, `/shipments/:shipmentId`: list and detail, timeline and permitted wallet actions.
- `/verify`, `/verify/:productId`: wallet-free evidence, public links and SVG QR labels.
- `/analytics`: measured cohorts, samples and CSV/PDF exports.
- `/demo`: labelled simulated journey, isolated from live data, with wallet/test-ETH onboarding.

Mobile wallet controls are in the navigation menu. Dialogs support keyboard focus, Escape and viewport scrolling. Unknown routes offer recovery links. See [PRODUCT_JOURNEY.md](../PRODUCT_JOURNEY.md) for evidence semantics, QR origins and isolation.

## Checks and releases

```bash
npm test -- --run --coverage
npm exec -- tsc --noEmit
npm run gen:types
CI=true VITE_WALLETCONNECT_PROJECT_ID=ci-test-project-id npm run test:e2e
```

Browser fixtures are separate from the real API/Hardhat browser acceptance in [TESTING.md](../TESTING.md). QR tests use an independent reader.

`npm run build` compiles the configured environment. Production Vercel builds use `build-vercel.mjs`, which requires successful exact-main-commit CI and a compatible ready API. Use feature PRs and stable testing before all protected-main checks; do not promote preview artifacts into production. See [RELEASE_CONTROLS.md](../RELEASE_CONTROLS.md).
