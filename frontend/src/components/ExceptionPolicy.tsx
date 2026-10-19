import {
  useExceptionPolicy,
  useSaveExceptionPolicy,
  type Policy,
} from "@/hooks/useExceptions";
import Button from "./ui/Button";

function PolicyForm({
  policy,
  save,
}: {
  policy: Policy;
  save: ReturnType<typeof useSaveExceptionPolicy>;
}) {
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const hours = (key: string) =>
          String(form.get(key) ?? "").trim() === ""
            ? null
            : Number(form.get(key));
        save.mutate({
          expected_revision: policy.revision ?? 0,
          arrival_enabled: form.has("arrival_enabled"),
          inactivity_hours: hours("inactivity_hours"),
          checkpoint_hours: hours("checkpoint_hours"),
          custody_hours: hours("custody_hours"),
        });
      }}
    >
      <label className="flex gap-2">
        <input
          name="arrival_enabled"
          type="checkbox"
          defaultChecked={policy.arrival_enabled ?? true}
        />
        Flag missed arrival planned before indexed departure
      </label>
      {(
        [
          ["inactivity_hours", "Hours without a checkpoint during transit"],
          [
            "checkpoint_hours",
            "Hours since the last At Checkpoint record (not physical dwell)",
          ],
          [
            "custody_hours",
            "Hours after transfer without a checkpoint by the receiving handler",
          ],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="block">
          {label}
          <input
            className="mt-1 block w-full rounded border border-border bg-bg p-2"
            name={key}
            type="number"
            min="0.25"
            max="8760"
            step="any"
            defaultValue={policy[key] ?? ""}
          />
        </label>
      ))}
      <p className="text-sm text-muted">
        Blank disables that rule. Valid range: 0.25–8760 hours. Changes apply on
        the next current-index evaluation and create a new occurrence when an
        active condition changes. Arrival planning is managed with the shipment
        record before departure.
      </p>
      <Button type="submit" disabled={save.isPending}>
        Save exception policy
      </Button>
    </form>
  );
}

export default function ExceptionPolicy({
  shipmentId,
}: {
  shipmentId: string;
}) {
  const query = useExceptionPolicy(shipmentId);
  const save = useSaveExceptionPolicy(shipmentId);
  return (
    <section
      aria-label="Exception policy"
      className="space-y-4 rounded-2xl border border-border p-5"
    >
      <h2 className="text-xl">Exception policy</h2>
      <p>
        Owner settings for this shipment. These are operational observations,
        not proof of a physical delay.
      </p>
      {query.isLoading && <p role="status">Loading policy…</p>}
      {query.error && (
        <div role="alert">
          <p>Exception policy unavailable.</p>
          <Button onClick={() => void query.refetch()}>Reload policy</Button>
        </div>
      )}
      {query.data && (
        <PolicyForm key={query.data.revision} policy={query.data} save={save} />
      )}
      {query.data && !query.error && (
        <Button onClick={() => void query.refetch()}>Reload policy</Button>
      )}
      {save.error && (
        <p role="alert">
          Policy could not be saved: {save.error.message}. Reload policy before
          retrying a revision conflict.
        </p>
      )}
      {save.isSuccess && (
        <p role="status">
          Policy saved. Evaluation follows when indexing is current.
        </p>
      )}
    </section>
  );
}
