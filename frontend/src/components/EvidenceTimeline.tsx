import { useState } from "react";
import { useTimeline } from "@/hooks/useJourney";
import TransactionLink from "./TransactionLink";
import Button from "./ui/Button";
import type { components } from "@/types/api";

export const eventNames: Record<
  components["schemas"]["TimelineEvent"]["event_type"],
  string
> = {
  ProductRegistered: "Product registered",
  ProductMetadataUpdated: "Metadata updated",
  CheckpointRecorded: "Checkpoint recorded",
  CustodyTransferred: "Custody transferred",
  DeliveryCompleted: "Delivery completed",
};

export default function EvidenceTimeline({ productId }: { productId: string }) {
  const [page, setPage] = useState(0);
  const { data, isLoading, error, refetch } = useTimeline(productId, page);
  return (
    <section
      aria-label="Evidence timeline"
      className="space-y-4 rounded-2xl border border-border p-5"
    >
      <h2 className="text-lg font-semibold">Evidence timeline</h2>
      <p className="text-sm text-muted">
        Canonical indexed events in block, transaction and log order.
        Registration evidence does not authenticate a physical item. History may
        be incomplete while synchronization is delayed or disabled.
      </p>
      {isLoading && <p role="status">Loading recorded events…</p>}
      {error && (
        <div role="alert">
          History could not be loaded.{" "}
          <Button onClick={() => void refetch()}>Retry history</Button>
        </div>
      )}
      {data && !data.total && (
        <p>
          No canonical indexed events are available. Drafts and legacy records
          are not proof of registration.
        </p>
      )}
      <ol className="space-y-5">
        {data?.items.map((event) => (
          <li
            key={event.event_id}
            className="space-y-2 border-l-2 border-accent/30 pl-4 text-sm"
          >
            <h3 className="font-semibold">{eventNames[event.event_type]}</h3>
            <p>
              {event.timestamp
                ? `${new Date(event.timestamp).toISOString().replace("T", " ").replace(".000Z", " UTC")}`
                : "Event time unavailable"}
            </p>
            {event.location && <p>Location: {event.location}</p>}
            {event.status != null && (
              <p>
                Status:{" "}
                {["Created", "In Transit", "At Checkpoint", "Delivered"][
                  Number(event.status)
                ] ?? event.status}
              </p>
            )}
            {event.handler && (
              <p className="break-all">Handler: {event.handler}</p>
            )}
            {event.from_address && (
              <p className="break-all">From: {event.from_address}</p>
            )}
            {event.to_address && (
              <p className="break-all">To: {event.to_address}</p>
            )}
            {event.notes && (
              <p className="whitespace-pre-wrap break-words">{event.notes}</p>
            )}
            {event.metadata_uri && (
              <p className="break-all">
                Recorded metadata URI: {event.metadata_uri}
              </p>
            )}
            <p>
              Block {event.block_number} · Transaction {event.transaction_index}{" "}
              · Log {event.log_index}
            </p>
            <p className="break-all">Block hash: {event.block_hash}</p>
            <TransactionLink hash={event.transaction_hash} />
          </li>
        ))}
      </ol>
      {data && data.total > 100 && (
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!page} onClick={() => setPage((p) => p - 1)}>
            Previous events
          </Button>
          <span>
            Events {data.skip + 1}–
            {Math.min(data.skip + data.limit, data.total)} of {data.total}
          </span>
          <Button
            disabled={data.skip + data.limit >= data.total}
            onClick={() => setPage((p) => p + 1)}
          >
            Next events
          </Button>
        </div>
      )}
    </section>
  );
}
