# Veritras

> **Transparent supply chain tracking powered by blockchain.**

[![Live Demo](https://img.shields.io/badge/Live_Demo-Visit_Now-4ade80?style=for-the-badge&logo=vercel)](https://veritras.vercel.app)
[![Backend](https://img.shields.io/badge/API_Status-Online-60a5fa?style=for-the-badge)](https://chainlens-4qvy.onrender.com/health)

---

## What is Veritras?

Veritras is a blockchain-powered supply chain analytics platform that brings **transparency, traceability, and trust** to product journeys. From manufacturer to doorstep, recorded checkpoints and custody events can be inspected on Ethereum Sepolia. Registration evidence does not authenticate a physical item; recent history depends on synchronization. Production indexing currently remains disabled pending its separate enablement review.

---

## Features

| Feature | Description |
|---------|-------------|
| **Product Registration** | Register products on-chain with unique IDs, manufacturer details, and IPFS metadata. |
| **Shipment Tracking** | Follow shipments through a state-machine-driven lifecycle: Created → In Transit → At Checkpoint → Delivered. |
| **Custody Transfers** | Every handoff is logged with timestamps, locations, and handler addresses. |
| **Verification Portal** | Open public product links, inspect receipt/journal evidence, and download QR labels. |
| **Guided Demo** | Follow a labelled simulated journey, isolated from live data, with mobile wallet onboarding. |
| **Analytics Dashboard** | Real-time KPIs, anomaly detection, and bottleneck analysis powered by Pandas. |
| **Export Reports** | Download analytics as CSV or PDF for auditing and compliance. |
| **Web3 Wallet Login** | Connect with MetaMask, Rainbow, or WalletConnect — no passwords needed. |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Blockchain** | Solidity 0.8.19, Hardhat, Sepolia Testnet |
| **Smart Contracts** | ProductRegistry, ShipmentTracker (92.86% test coverage) |
| **Backend** | Python, FastAPI, SQLAlchemy, Web3.py, Neon PostgreSQL |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS, RainbowKit |
| **Analytics** | Recharts, Pandas, Z-score anomaly detection |
| **Deployment** | Vercel (Frontend), Render (Backend), Neon (Database) |

---

## Live Application

| Service | URL | Status |
|---------|-----|--------|
| **Frontend** | [veritras.vercel.app](https://veritras.vercel.app) | Online |
| **API** | [chainlens-4qvy.onrender.com](https://chainlens-4qvy.onrender.com) | Online |
| **Health Check** | `/health` | Database & Web3 Connected |

> The app uses **Sepolia test ETH**, which has no monetary value. Sign-in and API drafts do not spend gas; contract writes do. Start with the [guided demo](https://veritras.vercel.app/demo) and use isolated testing for practice. See [PRODUCT_JOURNEY.md](PRODUCT_JOURNEY.md) for QR links, evidence limits and environment guidance.

---

## How It Works

```
Manufacturer registers product
        |
        v
Product ID minted on-chain (Sepolia)
        |
        v
Shipment created with origin & destination
        |
        v
Checkpoints added at each handoff (location, handler, status)
        |
        v
Dashboard visualizes real-time analytics
        |
        v
Anyone can verify provenance by product ID
```

---

## Project Origins

Veritras was built as a **portfolio project** to demonstrate full-stack blockchain application development. It combines on-chain provenance with off-chain indexing and an interactive analytics layer, bridging the gap between smart contracts and user-friendly interfaces.

---

## License

[MIT](LICENSE)

---

<p align="center">
  <a href="https://veritras.vercel.app">Try the Live Demo</a>
</p>
