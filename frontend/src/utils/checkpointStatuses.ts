import type { ShipmentStatus } from "@/hooks/useShipmentTracker";

/** Mirrors ShipmentTracker._validateStatusTransition; the contract remains authoritative. */
export function allowedCheckpointStatuses(
  history: readonly { status: number }[],
): ShipmentStatus[] {
  if (!history.length) return [0];
  switch (history.at(-1)?.status) {
    case 0:
      return [1, 2];
    case 1:
      return [2, 3];
    case 2:
      return [1, 3];
    default:
      return [];
  }
}
