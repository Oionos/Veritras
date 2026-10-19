import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useWaitForTransactionReceipt } from "wagmi";

vi.mock("wagmi", () => ({
  useWriteContract: () => ({
    writeContract: vi.fn(),
    data: `0x${"a".repeat(64)}`,
    isPending: false,
    error: null,
  }),
  useWaitForTransactionReceipt: vi.fn(),
}));
const { useRecordCheckpoint, useTransferCustody } = await vi.importActual<
  typeof import("./useShipmentTracker")
>("./useShipmentTracker");

describe("Shipment transaction receipt status", () => {
  for (const [name, hook] of [
    ["checkpoint", useRecordCheckpoint],
    ["custody", useTransferCustody],
  ] as const) {
    it(`${name} rejects a reverted receipt and accepts only success`, () => {
      vi.mocked(useWaitForTransactionReceipt).mockReturnValue({
        isSuccess: true,
        isLoading: false,
        data: { status: "reverted" },
      } as ReturnType<typeof useWaitForTransactionReceipt>);
      const { result, rerender } = renderHook(() => hook());
      expect(result.current.isSuccess).toBe(false);
      expect(result.current.error?.message).toBe(
        "Transaction reverted on chain",
      );
      vi.mocked(useWaitForTransactionReceipt).mockReturnValue({
        isSuccess: true,
        isLoading: false,
        data: { status: "success" },
      } as ReturnType<typeof useWaitForTransactionReceipt>);
      rerender();
      expect(result.current.isSuccess).toBe(true);
      expect(result.current.error).toBeNull();
    });
  }
});
