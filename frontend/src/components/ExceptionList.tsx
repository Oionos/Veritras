import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import {
  useExceptions,
  useAcknowledgeException,
  type ExceptionState,
  type ShipmentException,
} from "@/hooks/useExceptions";
import { ownsRecord } from "@/utils/permissions";
import Button from "./ui/Button";

export const exceptionLabels: Record<ShipmentException["kind"], string> = {
  arrival_overdue: "Planned arrival overdue",
  checkpoint_inactivity: "Checkpoint activity overdue",
  checkpoint_wait: "Checkpoint follow-up overdue",
  custody_followup: "Receiving handler follow-up overdue",
};

function timestamp(value: string | null | undefined) {
  if (!value) return "Not yet assessed";
  // SQLite development timestamps may omit the UTC designator.
  return new Date(
    /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`,
  ).toLocaleString();
}

export default function ExceptionList({
  state = "open",
  page = 0,
  shipmentId,
  onPage,
}: {
  state?: ExceptionState;
  page?: number;
  shipmentId?: string;
  onPage?: (page: number) => void;
}) {
  const query = useExceptions(state, page, shipmentId);
  const acknowledge = useAcknowledgeException();
  const auth = useAuth();
  const data = query.data;
  return (
    <div className="space-y-4">
      {query.isLoading && <p role="status">Loading exception observations…</p>}
      {query.error && (
        <div role="alert">
          <p>Exception observations are unavailable.</p>
          <Button onClick={() => void query.refetch()}>Retry exceptions</Button>
        </div>
      )}
      {data && (
        <>
          <div
            className="space-y-2 rounded-xl border border-border p-4"
            role="status"
          >
            {data.evaluation.paused ? (
              <p>
                Evaluation paused ({data.evaluation.reason?.replace(/_/g, " ")}
                ). Previous observations remain visible; missing updates do not
                establish a shipment delay.
              </p>
            ) : (
              <p>
                Evaluated from confirmed, current indexed evidence. New
                conditions are assessed about once a minute.
              </p>
            )}
            <p className="text-sm text-muted">
              Last assessment: {timestamp(data.evaluation.evaluated_at)}
              {data.evaluation.block_number != null &&
                ` · confirmed block ${data.evaluation.block_number}`}
            </p>
            {!!data.evaluation.uncertain_shipments && (
              <p>
                {data.evaluation.uncertain_shipments} shipment(s) have uncertain
                event timestamps or handler evidence. Their previous
                observations were retained for review.
              </p>
            )}
          </div>
          {data.items.length === 0 && (
            <p>
              {data.evaluation.paused
                ? "No stored observations match this view. Shipment timeliness is not established while evaluation is paused."
                : "No exception observations match this view."}
            </p>
          )}
          {data.items.map((item) => (
            <article
              key={item.id}
              className="space-y-3 rounded-2xl border border-border p-5"
            >
              <h2 className="text-lg">{exceptionLabels[item.kind]}</h2>
              <Link
                className="break-all text-accent underline"
                to={`/shipments/${encodeURIComponent(item.shipment_id)}`}
              >
                {item.shipment_id} · View shipment evidence
              </Link>
              <p>
                {item.kind === "custody_followup"
                  ? "Custody already transferred on-chain. The receiving handler has not recorded a subsequent checkpoint within the configured interval."
                  : item.kind === "checkpoint_wait"
                    ? "No checkpoint follows the latest At Checkpoint record within the configured interval. This is a recorded interval, not measured physical dwell."
                    : item.kind === "checkpoint_inactivity"
                      ? "No checkpoint follows the latest recorded checkpoint within the configured interval."
                      : "The arrival planned before indexed departure has passed without an indexed delivery."}
              </p>
              {item.evidence.threshold_hours != null && (
                <p>Threshold: {item.evidence.threshold_hours} hours</p>
              )}
              {item.evidence.location && (
                <p className="break-words">
                  Last recorded location: {item.evidence.location}
                </p>
              )}
              {item.evidence.receiving_handler && (
                <p className="break-all">
                  Receiving handler: {item.evidence.receiving_handler}
                </p>
              )}
              <p className="text-sm text-muted">
                Threshold reached: {timestamp(item.triggered_at)} · Last
                observed: {timestamp(item.last_observed_at)}
              </p>
              <p>
                {item.resolved_at
                  ? `Resolved ${timestamp(item.resolved_at)} (${item.resolution?.replace(/_/g, " ")})`
                  : item.acknowledged_at
                    ? `Acknowledged ${timestamp(item.acknowledged_at)}`
                    : "Open · awaiting acknowledgement"}
              </p>
              {item.acknowledgement_note && (
                <p className="whitespace-pre-wrap break-words">
                  Acknowledgement: {item.acknowledgement_note}
                </p>
              )}
              {!item.resolved_at &&
                !item.acknowledged_at &&
                auth.isAuthenticated &&
                ownsRecord(item, auth.address) && (
                  <form
                    className="space-y-2"
                    aria-label={`Acknowledge ${item.shipment_id} ${exceptionLabels[item.kind]}`}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = new FormData(e.currentTarget);
                      acknowledge.mutate({
                        id: item.id,
                        note: String(form.get("note") ?? ""),
                      });
                    }}
                  >
                    <label className="block">
                      Public acknowledgement note (optional)
                      <textarea
                        name="note"
                        maxLength={500}
                        className="mt-1 block w-full rounded border border-border bg-bg p-2"
                      />
                    </label>
                    <Button type="submit" disabled={acknowledge.isPending}>
                      Acknowledge occurrence
                    </Button>
                  </form>
                )}
            </article>
          ))}
          {acknowledge.error && (
            <p role="alert">
              Could not acknowledge: {acknowledge.error.message}. Reload if the
              occurrence has changed.
            </p>
          )}
          {acknowledge.isSuccess && (
            <p role="status">
              Acknowledgement saved. The condition remains open until the
              evidence or policy clears it.
            </p>
          )}
          {onPage && (
            <nav
              aria-label="Exception pages"
              className="flex flex-wrap items-center gap-4"
            >
              <Button disabled={page === 0} onClick={() => onPage(page - 1)}>
                Previous
              </Button>
              <p>
                {data.total} matching observations · Page {page + 1}
              </p>
              <Button
                disabled={(page + 1) * 20 >= data.total}
                onClick={() => onPage(page + 1)}
              >
                Next
              </Button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
