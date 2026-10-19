import type { VerificationResult } from "@/types";
import Card from "./ui/Card";
import TransactionLink from "./TransactionLink";

export default function RegistrationEvidence({
  verification,
}: {
  verification: VerificationResult;
}) {
  const { evidence, synchronization } = verification;
  return (
    <Card>
      <div className="space-y-2 text-sm" aria-label="Registration evidence">
        <h2 className="font-semibold">Registration evidence</h2>
        <p role="status">
          {evidence.status} · {evidence.reason.replace(/_/g, " ")}
        </p>
        <p>Transaction state: {evidence.registration_status}</p>
        <p className="break-all">
          Chain: {evidence.chain_id ?? "Unknown"} · Registry:{" "}
          {evidence.registry_address ?? "Unknown"}
        </p>
        <p className="break-all">
          Canonical product: {evidence.on_chain_product_id ?? "Unknown"}
        </p>
        <p className="break-all">
          Manufacturer: {evidence.manufacturer_address}
        </p>
        {evidence.transaction_hash && (
          <TransactionLink hash={evidence.transaction_hash} />
        )}
        {evidence.block_number != null && (
          <p className="break-all">
            Block {evidence.block_number} · {evidence.block_hash}
          </p>
        )}
        <p>
          Confirmation depth: {evidence.observed_confirmations ?? "Unknown"} /{" "}
          {evidence.required_confirmations}
        </p>
        <p>
          Synchronization: {synchronization.status} ·{" "}
          {synchronization.reason?.replace(/_/g, " ")}
        </p>
        <p>
          Last successful synchronization:{" "}
          {synchronization.last_successful_sync ?? "Unavailable"}
        </p>
        <p>Registration evidence does not authenticate a physical item.</p>
      </div>
    </Card>
  );
}
