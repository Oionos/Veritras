import { useEffect, useState } from "react";
import { useAccount } from "wagmi";
import { isAddress, zeroAddress } from "viem";
import {
  useRecordCheckpoint,
  useTransferCustody,
  useShipmentPermissions,
  useCheckpointStatuses,
  StatusLabels,
  type ShipmentStatus,
} from "@/hooks/useShipmentTracker";
import { hasCurrentIdentity } from "@/utils/permissions";
import { appEnvironment } from "@/config/runtime";
import type { Shipment } from "@/types";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import TransactionLink from "./TransactionLink";

export default function ShipmentActions({ shipment }: { shipment: Shipment }) {
  const { address, isConnected, chainId } = useAccount();
  const scoped = hasCurrentIdentity(shipment);
  const permissions = useShipmentPermissions(
    scoped ? shipment.on_chain_product_id : undefined,
  );
  const checkpoint = useRecordCheckpoint();
  const custody = useTransferCustody();
  const [action, setAction] = useState<"checkpoint" | "custody" | null>(null);
  const [lastAction, setLastAction] = useState<"checkpoint" | "custody" | null>(
    null,
  );
  const transaction = lastAction === "custody" ? custody : checkpoint;
  const [location, setLocation] = useState("");
  const [status, setStatus] = useState<ShipmentStatus>(0);
  const [notes, setNotes] = useState("");
  const [handler, setHandler] = useState("");
  const busy =
    checkpoint.isPending ||
    checkpoint.isConfirming ||
    custody.isPending ||
    custody.isConfirming;
  const delivered = shipment.status === "3";
  const eligible = scoped && isConnected && chainId === appEnvironment.chainId;
  const recordPermission = eligible && !delivered && permissions.canRecord;
  const allowedStatuses = useCheckpointStatuses(
    scoped ? shipment.on_chain_product_id : undefined,
    recordPermission,
  );
  const canRecord = recordPermission && allowedStatuses.length > 0;
  const selectedStatus = allowedStatuses.includes(status)
    ? status
    : allowedStatuses[0];
  const canTransfer = eligible && !delivered && permissions.canTransfer;
  useEffect(() => {
    setAction(null);
    setLastAction(null);
    setLocation("");
    setNotes("");
    setHandler("");
  }, [address, chainId, shipment.shipment_id]);
  useEffect(() => {
    if (
      lastAction &&
      transaction.isSuccess &&
      !transaction.isPending &&
      !transaction.isConfirming
    )
      setAction(null);
  }, [
    lastAction,
    transaction.isSuccess,
    transaction.isPending,
    transaction.isConfirming,
  ]);
  const invalidHandler =
    !isAddress(handler) ||
    handler.toLowerCase() === zeroAddress ||
    handler.toLowerCase() === address?.toLowerCase();
  return (
    <section className="space-y-3" aria-label="Shipment actions">
      <h2 className="text-lg font-semibold">Wallet actions</h2>
      {delivered ? (
        <p>
          This shipment is delivered. No further checkpoint or custody actions
          are available.
        </p>
      ) : !scoped ? (
        <p>Identity reconciliation is required before actions are available.</p>
      ) : !isConnected ? (
        <p>
          Connect your wallet using the menu to check your permissions. Public
          evidence remains available without signing in.
        </p>
      ) : chainId !== appEnvironment.chainId ? (
        <p>
          Switch your wallet to{" "}
          {appEnvironment.chainId === 11155111
            ? "Sepolia"
            : "the local test chain"}{" "}
          to check actions.
        </p>
      ) : !canRecord && !canTransfer ? (
        <p>
          No actions are available for this wallet, or permissions are still
          loading. The manufacturer records the first checkpoint; the current
          handler records subsequent checkpoints and transfers custody.
        </p>
      ) : (
        <p>
          Actions are checked against the contracts for this wallet. A mined
          transaction may still be awaiting indexed confirmations.
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        {canRecord && (
          <Button disabled={busy} onClick={() => setAction("checkpoint")}>
            Record checkpoint
          </Button>
        )}
        {canTransfer && (
          <Button disabled={busy} onClick={() => setAction("custody")}>
            Transfer custody
          </Button>
        )}
      </div>
      {lastAction && transaction.isSuccess && !busy && (
        <p role="status">
          Transaction mined. Awaiting synchronized evidence; the timeline will
          refresh after indexing.
        </p>
      )}
      {lastAction && transaction.hash && (
        <TransactionLink hash={transaction.hash} />
      )}
      <Modal
        open={action !== null}
        onClose={() => setAction(null)}
        title={
          action === "checkpoint" ? "Record checkpoint" : "Transfer custody"
        }
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy || !scoped) return;
            if (action === "checkpoint" && canRecord && location.trim()) {
              setLastAction("checkpoint");
              checkpoint.record(
                shipment.on_chain_product_id!,
                location.trim(),
                selectedStatus,
                notes.trim(),
              );
            }
            if (action === "custody" && canTransfer && !invalidHandler) {
              setLastAction("custody");
              custody.transfer(
                shipment.on_chain_product_id!,
                handler as `0x${string}`,
              );
            }
          }}
        >
          {action === "checkpoint" ? (
            <>
              <label className="block">
                Location
                <input
                  autoComplete="off"
                  required
                  maxLength={200}
                  className="mt-1 w-full rounded border border-border bg-bg p-3"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  disabled={busy}
                />
              </label>
              <div>
                <label htmlFor="detail-checkpoint-status" className="block">
                  Status
                </label>
                <select
                  id="detail-checkpoint-status"
                  className="mt-1 w-full rounded border border-border bg-bg p-3"
                  value={selectedStatus ?? ""}
                  onChange={(e) =>
                    setStatus(Number(e.target.value) as ShipmentStatus)
                  }
                  disabled={busy}
                >
                  {allowedStatuses.map((id) => (
                    <option key={id} value={id}>
                      {StatusLabels[id]}
                    </option>
                  ))}
                </select>
              </div>
              <label className="block">
                Notes (optional)
                <textarea
                  maxLength={1000}
                  className="mt-1 w-full rounded border border-border bg-bg p-3"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  disabled={busy}
                />
              </label>
            </>
          ) : (
            <>
              <label className="block">
                New handler address
                <input
                  autoComplete="off"
                  required
                  className="mt-1 w-full rounded border border-border bg-bg p-3"
                  value={handler}
                  onChange={(e) => setHandler(e.target.value.trim())}
                  disabled={busy}
                  aria-describedby="handler-help"
                />
              </label>
              <p id="handler-help" className="text-sm text-muted">
                Use a different, nonzero Ethereum wallet address. Transferring
                custody gives that wallet control of subsequent checkpoints.
              </p>
            </>
          )}
          {(action === "checkpoint" ? checkpoint.error : custody.error) && (
            <p role="alert" className="break-words text-red-400">
              Transaction failed or was rejected. Review the wallet request and
              try again.
            </p>
          )}
          <Button
            type="submit"
            disabled={
              busy ||
              (action === "checkpoint"
                ? !canRecord || !location.trim()
                : !canTransfer || invalidHandler)
            }
          >
            {busy
              ? "Awaiting wallet / confirmation…"
              : action === "checkpoint"
                ? "Submit checkpoint"
                : "Confirm custody transfer"}
          </Button>
        </form>
      </Modal>
    </section>
  );
}
