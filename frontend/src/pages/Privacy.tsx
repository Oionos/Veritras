export default function Privacy() {
  return (
    <div className="animate-fade-in space-y-6 px-6 sm:px-12 lg:px-20">
      {/* ─── Header ──────────────────────────────────────────────── */}
      <div className="space-y-3 pt-28">
        <div className="flex items-center gap-4">
          <div className="h-px w-8 bg-accent/40" />
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-accent/60">
            Legal
          </span>
        </div>
        <h1 className="font-serif text-3xl leading-[1.1] tracking-tight text-text sm:text-4xl">
          Privacy Policy
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted">
          How Veritras handles your data on the blockchain supply-chain
          platform.
        </p>
        <p className="text-xs text-muted/50">Last Updated: October 20, 2026</p>
      </div>

      {/* ─── 1. Overview ─────────────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Overview
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          Veritras is a blockchain-based supply chain transparency platform.
          This policy explains what data we collect, how we use it, and your
          rights.
        </p>
      </section>

      {/* ─── 2. Data We Collect ──────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Data We Collect
        </h2>
        <ul className="space-y-3 text-sm leading-relaxed text-muted">
          <li>
            <span className="font-medium text-text">Wallet addresses</span>{" "}
            (Ethereum / Sepolia) — collected via RainbowKit for authentication.
          </li>
          <li>
            <span className="font-medium text-text">
              IP addresses and browser metadata
            </span>{" "}
            — collected automatically by our hosting providers Vercel and
            Render.
          </li>
          <li>
            <span className="font-medium text-text">
              Product and shipment data you submit
            </span>{" "}
            — stored on our backend and referenced on-chain.
          </li>
          <li>
            <span className="font-medium text-text">Usage analytics</span> —
            Vercel Analytics and Speed Insights for performance monitoring, with
            dynamic identifiers and URL parameters removed. Aggregate error and
            connection-health diagnostics exclude wallet addresses, signatures,
            tokens and form input. Session replay is disabled.
          </li>
        </ul>
      </section>

      {/* ─── 3. How We Use Your Data ─────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          How We Use Your Data
        </h2>
        <ul className="space-y-3 text-sm leading-relaxed text-muted">
          <li>To authenticate your identity via wallet connection.</li>
          <li>
            To operate the platform — registering products, tracking shipments.
          </li>
          <li>To monitor performance and prevent abuse.</li>
          <li>To improve the platform based on usage patterns.</li>
        </ul>
      </section>

      {/* ─── 4. Blockchain Data ──────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Blockchain Data
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          Transactions on Ethereum / Sepolia are publicly visible on the
          blockchain by nature. Wallet addresses and transaction data are part
          of the public ledger and cannot be deleted.
        </p>
      </section>

      {/* ─── 5. Data Sharing ─────────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Data Sharing
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          We do not sell your data. Data is shared only with hosting providers
          (Vercel, Render), an optional configured error-reporting provider,
          under their respective privacy policies, and the blockchain network
          (public by design).
        </p>
      </section>

      {/* ─── 6. Your Rights ──────────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Your Rights
        </h2>
        <ul className="space-y-3 text-sm leading-relaxed text-muted">
          <li>You can disconnect your wallet at any time.</li>
          <li>You can request deletion of off-chain data by contacting us.</li>
          <li>
            You can view all on-chain data associated with your wallet on
            blockchain explorers.
          </li>
        </ul>
      </section>

      {/* ─── 7. Data Retention ───────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Data Retention
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          Off-chain data is retained as long as your account is active. On-chain
          data is permanent by design. You may request deletion of off-chain
          records at any time. Operational browser aggregates are held only in
          API process memory and reset when that process restarts.
        </p>
      </section>

      {/* ─── 8. Contact ──────────────────────────────────────────── */}
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-xl">
        <h2 className="mb-3 font-serif text-xl tracking-tight text-text">
          Contact
        </h2>
        <p className="text-sm leading-relaxed text-muted">
          For privacy inquiries, contact the project maintainer via the GitHub
          repository.
        </p>
      </section>
    </div>
  );
}
