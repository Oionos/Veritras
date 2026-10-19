import { useState } from "react";
import ExceptionList from "@/components/ExceptionList";
import type { ExceptionState } from "@/hooks/useExceptions";

export default function Exceptions() {
  const [state, setState] = useState<ExceptionState>("open");
  const [page, setPage] = useState(0);
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 pb-12 pt-28 sm:px-12">
      <h1 className="font-serif text-3xl">Shipment exceptions</h1>
      <p>
        Review recorded checkpoint gaps, missed arrival plans and receiving
        handler follow-up. Owners can acknowledge each occurrence;
        acknowledgement does not resolve it. No external notifications are sent.
      </p>
      <label className="block">
        Show observations
        <select
          className="ml-3 rounded border border-border bg-bg p-2"
          value={state}
          onChange={(e) => {
            setState(e.target.value as ExceptionState);
            setPage(0);
          }}
        >
          <option value="open">All open</option>
          <option value="unacknowledged">Awaiting acknowledgement</option>
          <option value="acknowledged">Acknowledged and open</option>
          <option value="resolved">Resolved history</option>
          <option value="all">All history</option>
        </select>
      </label>
      <ExceptionList state={state} page={page} onPage={setPage} />
    </div>
  );
}
