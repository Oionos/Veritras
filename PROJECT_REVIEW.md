# Veritras project review and roadmap

Reviewed: October 17, 2026 (Asia/Manila). Repository checkout: `9b06a15`, branch `work`.

## Recommendation

Make the complete provenance flow dependable before expanding the feature set: create a product, register it on Sepolia, index the receipt, record checkpoints, transfer custody, complete delivery, and verify the resulting evidence. The present gaps affect the product's central promise of trustworthy traceability.

The current stack fits the project's stated portfolio purpose. Prioritize integration, accurate information, and a polished demonstration before considering a framework migration or additional infrastructure.

## What the project contains

| Layer | Current implementation |
| --- | --- |
| Product | Supply chain traceability, custody history, public verification, analytics, CSV/PDF export |
| Frontend | React 19, TypeScript, Vite 8, Tailwind 4, React Router, TanStack Query, Recharts, Framer Motion |
| Wallet and transactions | RainbowKit, wagmi, viem; Sepolia in production; Hardhat also available during development |
| Backend | FastAPI, Pydantic, SQLAlchemy, PostgreSQL in hosted use, SQLite for local use |
| Blockchain | Solidity `ProductRegistry` and `ShipmentTracker`; product registration, metadata updates, checkpoints, custody transfers, delivery |
| Synchronization | Python polling thread inside the API process; event data stored in SQL; cursor stored in a JSON file |
| Hosting | Vercel frontend, Render backend, Neon PostgreSQL according to repository documentation |
| Existing engineering support | Hardhat tests, backend pytest tests, frontend Vitest tests, Playwright UI tests, Lighthouse CI, OpenAPI type generation, Sentry integration, Vercel Analytics and Speed Insights |

The main screens are Dashboard, Products, Shipments, Analytics, and Verify. The product form first saves a database record, then optionally registers it on the blockchain. Checkpoint and custody actions write directly to the contract. The backend should subsequently index those contract events and supply the screens with updated data.

The contracts already enforce manufacturer initiation, current-handler permissions, legal checkpoint status transitions, and a delivered state. The API's database write paths do not currently enforce equivalent ownership rules.

## Evidence and scope

This review combines source inspection, a successful frontend production build, small local reproductions, read-only live HTTP checks, and research in official documentation. It did not submit blockchain transactions, alter hosted data, inspect deployment secrets, or establish that the deployed commit exactly matches this checkout. The complete backend and contract test suites were not run as part of this research review.

### Live observations

| Read-only request | Observed response |
| --- | --- |
| Frontend homepage | HTTP 200 |
| API `/health` | HTTP 200; database and Web3 both `connected` |
| API `/health/indexer` | HTTP 200, but `status: stopped`; last processed block `10779035` |
| API `/health/cors` | `environment: development`; allowed origins were the production frontend and `http://localhost:5173` |
| API product list | One product; sampled record had `block_number: 0`, `tx_hash: "0x"` |
| API shipment list | One shipment; sampled record had status `0`, `block_number: 0`, `tx_hash: "0x"` |
| Verification for that sampled product | `is_registered: true`, with zero checkpoints |
| Live OpenAPI document | Auth response declares `access_token`; product/shipment POST and PUT operations declare no security requirement |

These are observations at review time, not continuous availability measurements. Placeholder transaction fields and a positive verification response show that the current endpoint does not require recorded blockchain evidence. They do not independently establish whether a particular product also exists on-chain.

## Immediate fixes

### 1. Restore indexing and report its health accurately — critical

**Evidence:** `backend/app/services/indexer.py:42` loads ABI JSON using a normal text open and `json.load`. Both files in `backend/app/abi/` begin with a UTF-8 byte order mark. Reading them as this loader does raises `JSONDecodeError: Unexpected UTF-8 BOM`. The startup thread catches connection/setup failures, sets `running` to false, and exits. This is a reproduced local startup failure and a plausible explanation for the live stopped state; confirming the deployed cause requires Render logs.

There is also a compatibility risk after startup: the code passes `fromBlock`/`toBlock` to contract `get_logs`, while current Web3.py uses `from_block`/`to_block`. The backend requirements allow unbounded major upgrades through `web3>=6.19.0` and other lower-bound-only dependencies. The installed production version was not checked.

**Next change:** normalize ABI encoding or read with `utf-8-sig`; lock compatible backend dependencies; exercise real contract ABI loading and the polling loop; expose initialization errors, last successful poll, chain head, indexed head, and lag. Separate basic liveness from readiness so a stopped required indexer cannot look healthy.

**Done when:** the indexer starts after restart, catches up through bounded log ranges, and a stopped or stalled indexer makes readiness fail. An actual test product transaction appears in the API.

### 2. Make verification represent evidence — critical

**Evidence:** `backend/app/api/routes/products.py:118` returns `is_registered: true` whenever a product exists in SQL. The Products detail view displays “Blockchain Verified” unconditionally, and Verify describes this response as authentication of the product. A missing SQL record is presented as possible counterfeiting even though indexing can be delayed or stopped.

**Next change:** introduce explicit registration states such as draft, pending transaction, confirmed, indexing, indexed, and failed. Verification should identify the chain, contract, canonical product ID, transaction receipt and relevant event, confirmation/finality policy, and last synchronization time. Distinguish unavailable evidence, not found, and mismatched data. Treat transaction success as a confirmed receipt rather than transaction submission.

Blockchain registration proves that an address recorded information. Establishing the identity of the manufacturer and the connection to the physical item requires additional evidence. Product wording should state the proof actually checked.

**Done when:** a database-only draft is never shown as blockchain verified, valid indexed registrations have inspectable evidence, and synchronization failures produce an honest unavailable/pending state.

### 3. Repair authentication and protect writes — critical

**Evidence:** `frontend/src/hooks/useAuth.ts:86` reads `token` from the response, but `backend/app/api/routes/auth.py:56` returns `access_token`. The frontend can consequently save the string `undefined` to local storage. Product and shipment creation/update routes do not depend on `get_current_user`, and a caller can supply a manufacturer address independently of the signer.

The SIWE implementation extracts an address and nonce and checks a signature, but does not fully validate message format, expected domain/URI, chain, or time fields. The JWT configuration has a development secret fallback without a production startup guard. This review did not inspect the secret actually configured in production.

**Next change:** share a typed auth response; enforce authentication and object ownership on writes; derive manufacturer identity from the authenticated wallet; clear or replace sessions when accounts change or disconnect; check expiry. Validate SIWE against the expected environment and chain using a maintained implementation. Fail startup if production secrets are missing or still defaults. Keep public verification readable without login.

The current nonce store and rate limits are process-local. If multiple API workers or instances are introduced, move those states to a shared store or database so login challenges and limits remain consistent.

**Done when:** a legitimate signed login works, unsigned writes fail, another wallet cannot edit an existing owner's record, and invalid domain/chain/expired challenges are rejected.

## Data integrity and release workflow

### 4. Use one stable product identity and define shipment identity — high

**Evidence:** API creation uses display IDs such as `PROD-F8E863A4`. The frontend converts that text to right-padded bytes32. The indexer stores the raw `0x...` bytes32 string as `product_id`, creating a separate identity rather than reconciling the original row. Passing that indexed hex ID through the frontend helper encodes its text again and exceeds 32 bytes. This round-trip failure was reproduced with viem.

The database permits multiple shipments for one product, while the contract stores history, handler, and terminal delivery state by product ID. Once delivered, that product cannot begin another contract journey. The indexer never updates SQL `Shipment.status` from checkpoints. Product metadata updates also have a contract event that the indexer does not consume.

**Next change:** distinguish a display ID from a canonical on-chain ID, with a defined conversion and uniqueness rule. Reconcile confirmed events into the existing record. For the initial demo, explicitly enforce one shipment lifecycle per tracked item. If repeat shipments are a real requirement, design a contract version keyed by shipment/journey ID. Define how edits and metadata updates synchronize with immutable fields and contract events.

**Done when:** one registered item has one reconciled identity; checkpoints update its selected shipment; delivery changes the list, detail view, and KPIs consistently. Contract changes include an explicit deployment/address and data transition plan.

### 5. Make event processing safe to replay — high

**Evidence:** the cursor is a file in the backend container; checkpoint and custody rows have no unique event key; handlers swallow persistence errors while the outer poll can still advance the cursor. One delivered checkpoint emits both `CheckpointRecorded` and `DeliveryCompleted`, and the indexer writes a delivered checkpoint for each event. This can double-count deliveries in checkpoint history. Polling processes event types separately rather than one chronological stream.

**Next change:** persist cursor and block hash in PostgreSQL; store event identity using chain, contract, transaction hash, and log index; process ordered events idempotently. Commit progress only after successful processing. Use bounded/adaptive block ranges and retries, and define confirmation/finality and reorganization handling. Model delivery as the existing checkpoint plus a derived delivery state rather than inventing a second checkpoint. Retry initialization failures with bounded backoff and observable errors.

Keep a single indexer owner at first. If the API scales to multiple instances, run one dedicated worker or use a leader lock before enabling parallel API replicas.

**Done when:** replaying a block produces no duplicate business records, a failed write is retried, restart preserves progress, and one delivery adds one checkpoint.

### 6. Create a complete testing environment — high

Feature branches with Vercel Preview deployments fit this project. However, a frontend preview alone does not isolate the Render API, Neon database, or contract state.

| Resource | Live environment | Testing environment |
| --- | --- | --- |
| Git | `main` | Short-lived feature branch / pull request |
| Frontend | Vercel production | Vercel Preview |
| API | Production Render service | Dedicated test service, or a PR preview when needed |
| Database | Production Neon branch | Isolated Neon test branch |
| Contracts | Current Sepolia addresses | Separate test contract addresses, or local Hardhat |
| Configuration | Production API URL, origins, auth secret, contract addresses | Test values for the corresponding resources |

A shared testing backend and database is a practical starting point for one developer. Add per-PR backend/database environments if concurrent development makes that useful. Neon branches isolate data changes. Render service previews initially inherit environment variables, including database connection settings, so explicitly configure test database connections. The Neon/Vercel integration does not by itself reconfigure the separately hosted Render API.

The current frontend CSP hardcodes the production API hostname, so simply changing `VITE_API_URL` may still leave test API connections blocked. The live CORS list also does not currently include a preview origin. Generate or configure CSP from the selected API origin and allow the intended test origins in the test backend. Set the live API to production mode and require validated configuration.

**Done when:** creating/editing data through a feature preview changes only testing resources; its wallet operations use the intended test contracts; protected `main` accepts changes after required checks pass.

### 7. Replace placeholder analytics and agree on definitions — high

**Evidence:** `frontend/src/pages/Dashboard.tsx:41` contains fixed KPI trends and a shipment summary of `1,247`. `frontend/src/pages/Analytics.tsx:22` supplies fixed route volumes and delays to charts. Dashboard's recent product list expects an array, but the API returns `{items, total}`, so real recent products are ignored.

Backend transit metrics group checkpoints by product, including incomplete journeys and products with just one checkpoint. The on-time calculation treats those short partial histories as on-time against a universal 72-hour expectation. KPI counts switch between shipment rows and checkpoint-derived product counts depending on whether shipment rows exist. PDF export labels a product count as total shipments. Export date filters apply to product registration time, not necessarily the event dates a user expects.

**Next change:** replace fixed values with API aggregates, or place illustrative data in an explicit demo mode. Count shipments consistently, compute delivered transit durations from departure to delivery, define expected arrival/SLA per shipment, and show sample counts and missing data. Separate elapsed time for active shipments from completed transit time. Add date and route filters with clear timezone semantics; validate export dates and provide genuine shipment/event reports. Begin with explainable overdue/dwell rules before investing in predictive analytics.

**Done when:** no unlabeled example numbers appear as live data; shipment counts agree across screens and exports; one-checkpoint/incomplete journeys cannot inflate delivery performance.

## Product improvements after the foundation works

| Order | Improvement | Why it matters / first useful scope |
| --- | --- | --- |
| 1 | Guided demonstration and onboarding | Offer “Explore a sample journey” without a wallet; explain Sepolia, test ETH, and the difference between connecting and signing in; show a complete seeded journey with clearly labeled demo data |
| 2 | QR codes and shareable verification URLs | Open a specific product via `/verify/:id` or a query parameter; generate downloadable labels; support a phone camera scan; keep evidence readable without wallet access |
| 3 | One complete shipment detail screen | Bring origin, destination, current handler, allowed next actions, checkpoint/custody timeline, transaction links, and synchronization status together |
| 4 | Delay and custody exception alerts | Add expected arrival, overdue status, excessive dwell, and stalled handoff detection; start with an in-app exception list before optional email/webhooks |
| 5 | Manufacturer and organization identity | Verify which organization controls an address; add memberships and permissions if pursuing real business users; define which operational fields are public |
| 6 | Evidence attachments and metadata integrity | Attach certificates/photos, validate structured metadata, persist content hashes/CIDs, and ensure uploaded content is actually available; a metadata URI field alone is not a complete IPFS workflow |
| 7 | Batch/import and traceability interoperability | Support CSV import and event export; later map events and identifiers to GS1 EPCIS and Digital Link for integrations |

QR navigation is a useful first product feature once verification is accurate. GS1 Digital Link provides a standard way to link product identifiers with online information; EPCIS provides a common traceability event model. Adopt the minimum useful fields first rather than claiming standards compliance from a similar JSON structure.

For a portfolio project, focus on a reliable sample journey, architecture documentation, and a short demonstration. For a business pilot, validate one specific workflow with actual manufacturers/handlers before adding organization management, integrations, or advanced analytics.

## Engineering follow-ups

- **Integration coverage:** retain the existing unit and mocked UI suites, and add a small real flow using Hardhat, the API, and PostgreSQL: registration → indexing → checkpoint → custody → delivery → verification. Include rejected writes, draft verification, restart/replay, and ID round trips. Existing Playwright routes mock the API; they cannot establish that the API and contracts agree.
- **API types:** generate OpenAPI from the running Python application during CI before generating TypeScript. The current drift check compares TypeScript only with the committed `openapi.json`, allowing both to lag behind Python changes. Replace broad untyped response paths with explicit schemas, including auth, product detail, and verification.
- **Migrations:** run Alembic as a release step and remove automatic production schema creation. The backend Dockerfile currently copies `alembic.ini` but not the `alembic/` directory, so the documented migration workflow is not packaged completely.
- **Dependencies:** use a reviewed backend lockfile and separate runtime/development requirements. Keep contract ABI generation synchronized rather than maintaining multiple potentially divergent copies.
- **Monitoring:** monitor indexing lag and API errors, and connect frontend error reports to release/environment identifiers. SSE broadcasts currently cover only API create events; contract indexing and edits do not publish updates. Add relevant events and cache invalidation, stream heartbeats, and bounded queues before relying on the “Live” indicator.
- **Mobile and accessibility:** wallet controls are hidden below the `sm` breakpoint and are absent from the mobile menu. Add mobile wallet access. Improve modal accessible naming, focus containment/restoration, Escape handling, mobile scrolling, and reduced-motion behavior.
- **Performance:** the build produced a Web3 vendor chunk of about 2.80 MiB raw / 577 KiB gzip. Routes already use lazy loading, so focus measurements on wallet/provider startup and the dashboard's initial chart dependencies. Consider deferring wallet UI/SDK loading and below-the-fold charts after measuring mobile impact. Do not interpret bundle size alone as a measured loading-time failure.
- **Error reporting and privacy:** review Sentry replay masking before enabling broad collection; the current configuration sets text/media masking off. Ensure CSP permits the selected Sentry endpoint and that disclosure matches actual collection.
- **Documentation and presentation:** update the READMEs from React 18/Node 18 to the actual requirements, document the preview setup and indexer recovery, replace the Vite favicon, and add useful verification-page metadata and a missing-route page.

## Suggested sequence of pull requests

1. **Indexer recovery:** ABI decoding, dependency compatibility, initialization/poll coverage, useful readiness and lag reporting.
2. **Authentication and write authorization:** typed token response, SIWE validation, production config guards, owner permissions, session lifecycle.
3. **Trustworthy verification:** honest draft/pending/confirmed states and transaction evidence, including unavailable/stale cases.
4. **Canonical identities and event persistence:** reconcile product IDs, define shipment identity, deduplicate logs, persist progress, synchronize shipment state and metadata.
5. **Preview isolation:** Vercel Preview → test API → Neon test branch → test contract configuration, with CSP/CORS and required checks.
6. **Real analytics:** remove illustrative live figures, repair recent products, implement agreed shipment metrics and accurate reports.
7. **Product usability:** mobile wallet, guided demo, shareable/QR verification, and unified shipment detail.
8. **Operational features:** overdue/dwell alerts, identity/organization workflow, and integrations driven by a chosen pilot use case.

Use the testing environment for these changes before merging to `main`. Initial environment setup can proceed alongside the first repairs. The release acceptance scenario should follow one identifiable item from registration through delivery and verify the same evidence across contract, API, screens, and exports.

## Official research sources

- [ERC-4361: Sign-In with Ethereum](https://eips.ethereum.org/EIPS/eip-4361): validate the signed message structure and expected scope/session fields, in addition to its signature.
- [Web3.py events and logs](https://web3py.readthedocs.io/en/stable/filters.html): current log API examples and a scanner design covering bounded ranges, retry, persisted state, and rescanning around reorganizations. Check against the version selected for this project.
- [Vercel deployment environments](https://vercel.com/docs/deployments/environments): feature branch previews and environment-specific configuration.
- [Render service previews](https://render.com/docs/service-previews): preview configuration inherits settings, including database variables, that must be adjusted for isolated testing.
- [Neon branching](https://neon.com/docs/introduction/branching): isolated database branches for development and testing.
- [GS1 Digital Link](https://www.gs1.org/standards/gs1-digital-link): connecting standard product identifiers to online resources and QR-based navigation.
- [GS1 EPCIS standard](https://ref.gs1.org/standards/epcis/): interoperable traceability event representation and exchange.

Research informs the proposed design; it does not establish that these integrations are configured in the user's hosted accounts.
