import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useAccount } from "wagmi";
import { appEnvironment } from "@/config/runtime";
import {
  useShipmentPermissions,
  useCheckpointStatuses,
  useRecordCheckpoint,
  useTransferCustody,
} from "@/hooks/useShipmentTracker";
import ShipmentActions from "./ShipmentActions";
import type { Shipment } from "@/types";

vi.mock("wagmi", () => ({ useAccount: vi.fn() }));
vi.mock("@/hooks/useShipmentTracker", () => ({
  useShipmentPermissions: vi.fn(),
  useCheckpointStatuses: vi.fn(),
  useRecordCheckpoint: vi.fn(),
  useTransferCustody: vi.fn(),
  StatusLabels: {
    0: "Created",
    1: "In Transit",
    2: "At Checkpoint",
    3: "Delivered",
  },
}));
const address = `0x${"1".repeat(40)}`;
const shipment = {
  shipment_id: "SHIP-1",
  status: "1",
  on_chain_product_id: `0x${"a".repeat(64)}`,
  chain_id: appEnvironment.chainId,
  registry_address: appEnvironment.productRegistry,
  tracker_address: appEnvironment.shipmentTracker,
} as Shipment;
const record = vi.fn();
const transfer = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCheckpointStatuses).mockReturnValue([2, 3]);
  vi.mocked(useAccount).mockReturnValue({
    address,
    isConnected: true,
    chainId: appEnvironment.chainId,
  } as ReturnType<typeof useAccount>);
  vi.mocked(useShipmentPermissions).mockReturnValue({
    canRecord: true,
    canTransfer: true,
  });
  vi.mocked(useRecordCheckpoint).mockReturnValue({
    record,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
  } as ReturnType<typeof useRecordCheckpoint>);
  vi.mocked(useTransferCustody).mockReturnValue({
    transfer,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
  } as ReturnType<typeof useTransferCustody>);
});

describe("Shipment detail wallet actions", () => {
  it("submits only the canonical identity and trimmed checkpoint form", () => {
    render(<ShipmentActions shipment={shipment} />);
    fireEvent.click(screen.getByRole("button", { name: "Record checkpoint" }));
    fireEvent.change(screen.getByLabelText("Location"), {
      target: { value: " Manila " },
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText("Notes (optional)"), {
      target: { value: " received " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit checkpoint" }));
    expect(record).toHaveBeenCalledWith(
      shipment.on_chain_product_id,
      "Manila",
      3,
      "received",
    );
  });
  it("offers only Created for the first checkpoint", () => {
    vi.mocked(useCheckpointStatuses).mockReturnValue([0]);
    render(<ShipmentActions shipment={{ ...shipment, status: "0" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Record checkpoint" }));
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Created" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Location"), {
      target: { value: "Factory" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit checkpoint" }));
    expect(record).toHaveBeenCalledWith(
      shipment.on_chain_product_id,
      "Factory",
      0,
      "",
    );
  });
  it("rejects zero, same-wallet and malformed custody destinations", () => {
    render(<ShipmentActions shipment={shipment} />);
    fireEvent.click(screen.getByRole("button", { name: "Transfer custody" }));
    for (const invalid of ["bad", `0x${"0".repeat(40)}`, address]) {
      fireEvent.change(screen.getByLabelText("New handler address"), {
        target: { value: invalid },
      });
      expect(
        screen.getByRole("button", { name: "Confirm custody transfer" }),
      ).toBeDisabled();
    }
    const next = `0x${"2".repeat(40)}`;
    fireEvent.change(screen.getByLabelText("New handler address"), {
      target: { value: next },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm custody transfer" }),
    );
    expect(transfer).toHaveBeenCalledWith(shipment.on_chain_product_id, next);
  });
  it("hides actions for a delivered product even with stale positive permissions", () => {
    render(<ShipmentActions shipment={{ ...shipment, status: "3" }} />);
    expect(
      screen.queryByRole("button", { name: "Record checkpoint" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Transfer custody" }),
    ).not.toBeInTheDocument();
  });
  it("hides actions when disconnected, on another chain or outside identity scope", () => {
    const { rerender } = render(
      <ShipmentActions
        shipment={{ ...shipment, registry_address: `0x${"9".repeat(40)}` }}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Record checkpoint" }),
    ).not.toBeInTheDocument();
    vi.mocked(useAccount).mockReturnValue({
      address,
      isConnected: true,
      chainId: 1,
    } as ReturnType<typeof useAccount>);
    rerender(<ShipmentActions shipment={shipment} />);
    expect(
      screen.queryByRole("button", { name: "Record checkpoint" }),
    ).not.toBeInTheDocument();
    vi.mocked(useAccount).mockReturnValue({ isConnected: false } as ReturnType<
      typeof useAccount
    >);
    rerender(<ShipmentActions shipment={shipment} />);
    expect(
      screen.queryByRole("button", { name: "Transfer custody" }),
    ).not.toBeInTheDocument();
  });
  it("closes and clears the form when the wallet changes", () => {
    const { rerender } = render(<ShipmentActions shipment={shipment} />);
    fireEvent.click(screen.getByRole("button", { name: "Record checkpoint" }));
    vi.mocked(useAccount).mockReturnValue({
      address: `0x${"2".repeat(40)}`,
      isConnected: true,
      chainId: appEnvironment.chainId,
    } as ReturnType<typeof useAccount>);
    rerender(<ShipmentActions shipment={shipment} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
