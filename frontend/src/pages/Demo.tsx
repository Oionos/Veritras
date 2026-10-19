import { useState } from "react";
import { Link } from "react-router-dom";
import Button from "@/components/ui/Button";

const steps = [
  {
    title: "Register a product",
    time: "09:00 UTC",
    actor: "Manufacturer",
    text: "Create a product draft, sign in with the manufacturer wallet, then submit its registration. A receipt and canonical indexed event establish registration evidence.",
  },
  {
    title: "Plan the shipment",
    time: "09:05 UTC",
    actor: "Manufacturer",
    text: "Create one shipment for the product from Manila Factory to Cebu Warehouse. Set an optional expected arrival before the first departure checkpoint.",
  },
  {
    title: "Record departure",
    time: "10:00 UTC",
    actor: "Manufacturer",
    text: "Record a Created checkpoint at Manila Factory to establish the manufacturer as the current handler. Then record an In Transit checkpoint when the item departs. The form offers only transitions allowed by the contract.",
  },
  {
    title: "Transfer custody",
    time: "12:00 UTC",
    actor: "Manufacturer → Carrier",
    text: "Transfer custody to the carrier wallet. The contract permits subsequent checkpoints and custody changes only from that current handler.",
  },
  {
    title: "Complete delivery",
    time: "18:00 UTC",
    actor: "Carrier",
    text: "Record a Delivered checkpoint at Cebu Warehouse. Delivery closes this product’s shipment lifecycle; further checkpoint and custody actions are unavailable.",
  },
  {
    title: "Share the evidence",
    time: "18:05 UTC",
    actor: "Public visitor",
    text: "Open the product’s public verification link or scan its QR label without a wallet. Inspect the registration receipt, confirmation depth, synchronization status and ordered event timeline.",
  },
];

export default function Demo() {
  const [step, setStep] = useState(0);
  const current = steps[step];
  return (
    <div className="mx-auto max-w-5xl space-y-8 px-6 pb-12 pt-28 sm:px-12">
      <div className="space-y-3">
        <p className="text-sm font-semibold uppercase tracking-wider text-accent">
          Guided demo · Simulated data
        </p>
        <h1 className="font-serif text-3xl sm:text-4xl">
          Follow one product’s journey
        </h1>
        <p className="text-muted">
          This seeded example runs entirely in your browser. It makes no
          transactions or business API requests and contributes nothing to live
          products, shipments or analytics. No example receipt is presented as
          blockchain proof.
        </p>
      </div>
      <section
        className="rounded-2xl border border-accent/30 p-5"
        aria-label="Simulated shipment"
      >
        <p className="break-all font-mono">
          DEMO-COFFEE-001 · Philippine coffee
        </p>
        <p className="mt-2">Manila Factory → Cebu Warehouse</p>
        <p className="mt-2 text-sm text-muted">
          Example day: 20 October 2026 · Simulated handler:{" "}
          {step < 2 ? "Not established" : step < 3 ? "Manufacturer" : "Carrier"}
        </p>
        <p className="mt-2 text-sm text-muted">
          Example status:{" "}
          {step < 2 ? "Created" : step < 4 ? "In Transit" : "Delivered"}
        </p>
      </section>
      <div className="grid gap-6 md:grid-cols-[1fr_2fr]">
        <nav aria-label="Demo steps" className="flex flex-col gap-2">
          {steps.map((item, index) => (
            <button
              key={item.title}
              aria-current={index === step ? "step" : undefined}
              className={`rounded-xl border p-3 text-left text-sm ${step === index ? "border-accent text-accent" : "border-border text-muted"}`}
              onClick={() => setStep(index)}
            >
              {index + 1}. {item.title}
            </button>
          ))}
        </nav>
        <section
          className="space-y-4 rounded-2xl border border-border p-6"
          aria-live="polite"
          aria-atomic="true"
        >
          <p className="text-sm text-muted">
            Step {step + 1} of {steps.length} · {current.time} · {current.actor}
          </p>
          <h2 className="text-xl font-semibold">{current.title}</h2>
          <p className="leading-relaxed text-muted">{current.text}</p>
          <p className="text-sm text-amber-300">
            Simulated example — no on-chain evidence
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="secondary"
              disabled={!step}
              onClick={() => setStep((value) => value - 1)}
            >
              Previous step
            </Button>
            {step < steps.length - 1 ? (
              <Button onClick={() => setStep((value) => value + 1)}>
                Next step
              </Button>
            ) : (
              <Button onClick={() => setStep(0)}>Restart demo</Button>
            )}
          </div>
        </section>
      </div>
      <section
        aria-label="Try it with a wallet"
        className="space-y-4 rounded-2xl border border-border p-6"
      >
        <h2 className="text-xl font-semibold">Try it with a wallet</h2>
        <ol className="list-decimal space-y-3 pl-5 text-sm leading-relaxed text-muted">
          <li>
            Use the{" "}
            <a
              className="text-accent underline"
              href="https://veritras-git-testing-hoppaysamas-projects.vercel.app/demo"
              target="_blank"
              rel="noopener noreferrer"
            >
              isolated testing site
            </a>{" "}
            for a real practice journey. Vercel may require your project account
            to access the protected preview. Production indexing currently
            remains disabled.
          </li>
          <li>
            Open the navigation menu on mobile and choose Connect Wallet. Use a
            wallet you control, switch to Ethereum Sepolia, then Sign In.
            Signing in proves wallet control and does not spend gas.
          </li>
          <li>
            Request free Sepolia test ETH from the{" "}
            <a
              className="text-accent underline"
              href="https://cloud.google.com/application/web3/faucet/ethereum/sepolia"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google Cloud Sepolia faucet
            </a>
            . Sepolia ETH has no monetary value; do not buy real ETH for this
            demo or share a seed phrase.
          </li>
          <li>
            In{" "}
            <Link className="text-accent underline" to="/products">
              Products
            </Link>
            , create a draft and register it. Wait for receipt confirmation and
            indexed evidence. Retry/reconcile from the registration panel if a
            submitted transaction is interrupted.
          </li>
          <li>
            In{" "}
            <Link className="text-accent underline" to="/shipments">
              Shipments
            </Link>
            , plan the route and open the shipment ID. Use the permitted wallet
            actions to record checkpoints, transfer custody and deliver. The
            receiving handler needs its own test ETH to send transactions.
          </li>
          <li>
            Download a QR label from shipment detail or{" "}
            <Link className="text-accent underline" to="/verify">
              public verification
            </Link>
            . If evidence is pending or the indexer is delayed, wait for
            synchronization and retry. A label alone cannot authenticate a
            physical item.
          </li>
        </ol>
      </section>
    </div>
  );
}
