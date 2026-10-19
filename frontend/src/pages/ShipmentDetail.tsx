import { Link, useParams } from "react-router-dom";
import { useShipment } from "@/hooks/useJourney";
import { useProduct, useVerifyProduct } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { hasCurrentIdentity, ownsRecord } from "@/utils/permissions";
import EvidenceTimeline from "@/components/EvidenceTimeline";
import RegistrationEvidence from "@/components/RegistrationEvidence";
import VerificationLabel from "@/components/VerificationLabel";
import ShipmentActions from "@/components/ShipmentActions";
import Button from "@/components/ui/Button";
import { verificationPath } from "@/utils/verificationLabel";

export default function ShipmentDetail() {
  const { shipmentId = "" } = useParams();
  const shipment = useShipment(shipmentId);
  const productId = shipment.data?.product_id ?? "";
  const product = useProduct(productId);
  const verification = useVerifyProduct(productId);
  const auth = useAuth();
  const item = shipment.data;
  const error = shipment.error || product.error || verification.error;
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 pb-12 pt-28 sm:px-12">
      <Link className="text-accent underline" to="/shipments">
        All shipments
      </Link>
      <h1 className="break-all font-serif text-3xl">Shipment {shipmentId}</h1>
      {(shipment.isLoading || product.isLoading || verification.isLoading) && (
        <p role="status">Loading shipment evidence…</p>
      )}
      {error && (
        <div role="alert" className="space-y-3">
          <p>
            {shipment.error?.message.includes("404")
              ? "Shipment not found. Check the link or choose a shipment from the list."
              : "Some shipment evidence is unavailable. Recorded data below may be incomplete."}
          </p>
          <Button
            onClick={() => {
              void shipment.refetch();
              if (productId) {
                void product.refetch();
                void verification.refetch();
              }
            }}
          >
            Retry shipment
          </Button>
        </div>
      )}
      {item && (
        <>
          <section
            aria-label="Shipment summary"
            className="space-y-3 rounded-2xl border border-border p-5"
          >
            <h2 className="text-xl">
              {item.origin} → {item.destination}
            </h2>
            <p className="break-all">
              Product: {product.data?.product.name ?? item.product_id} ·{" "}
              {item.product_id}
            </p>
            <p>
              Status:{" "}
              {["Created", "In Transit", "At Checkpoint", "Delivered"][
                Number(item.status)
              ] ?? "Unknown"}
            </p>
            <p className="break-all">
              Current indexed handler:{" "}
              {item.current_handler && !/^0x0{40}$/.test(item.current_handler)
                ? item.current_handler
                : "Not established by indexed evidence"}
            </p>
            <p>
              Planned arrival (UTC):{" "}
              {item.expected_arrival_at
                ? new Date(item.expected_arrival_at).toISOString()
                : "Not planned"}
            </p>
            {item.notes && (
              <p className="whitespace-pre-wrap break-words">{item.notes}</p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Link
                className="text-accent underline"
                to={verificationPath(item.product_id)}
              >
                Public verification
              </Link>
              <VerificationLabel productId={item.product_id} />
            </div>
            {auth.isAuthenticated &&
              ownsRecord(item, auth.address) &&
              hasCurrentIdentity(item) && (
                <Link
                  className="inline-block text-accent underline"
                  to="/shipments"
                >
                  Manage shipment records
                </Link>
              )}
          </section>
          <ShipmentActions key={item.shipment_id} shipment={item} />
          {verification.data?.evidence && (
            <RegistrationEvidence verification={verification.data} />
          )}
          <EvidenceTimeline key={item.product_id} productId={item.product_id} />
        </>
      )}
    </div>
  );
}
