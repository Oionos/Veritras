import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useShipment } from "@/hooks/useJourney";
import { useProduct, useVerifyProduct } from "@/hooks/useApi";
import ShipmentDetail from "./ShipmentDetail";

vi.mock("@/hooks/useJourney", () => ({ useShipment: vi.fn() }));
vi.mock("@/components/ExceptionList", () => ({
  default: () => <div>Exception observations</div>,
}));
vi.mock("@/components/ExceptionPolicy", () => ({
  default: () => <div>Exception policy</div>,
}));
vi.mock("@/hooks/useApi", () => ({
  useProduct: vi.fn(),
  useVerifyProduct: vi.fn(),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
vi.mock("@/components/EvidenceTimeline", () => ({
  default: () => <div>Canonical timeline</div>,
}));
vi.mock("@/components/VerificationLabel", () => ({
  default: () => <button>QR label</button>,
}));
vi.mock("@/components/ShipmentActions", () => ({
  default: () => <div>Contract permissions</div>,
}));
vi.mock("@/components/RegistrationEvidence", () => ({
  default: () => <div>Receipt and synchronization evidence</div>,
}));
function mount() {
  return render(
    <MemoryRouter initialEntries={["/shipments/SHIP-1"]}>
      <Routes>
        <Route path="/shipments/:shipmentId" element={<ShipmentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.mocked(useProduct).mockReturnValue({
    data: { product: { name: "Coffee" } },
  } as ReturnType<typeof useProduct>);
  vi.mocked(useVerifyProduct).mockReturnValue({
    data: { evidence: {} },
  } as ReturnType<typeof useVerifyProduct>);
});
describe("Shipment detail route", () => {
  it("combines route, status, handler and evidence using the fetched product identity", () => {
    vi.mocked(useShipment).mockReturnValue({
      data: {
        shipment_id: "SHIP-1",
        product_id: "P-1",
        origin: "Manila",
        destination: "Cebu",
        status: "3",
        current_handler: `0x${"a".repeat(40)}`,
      },
    } as ReturnType<typeof useShipment>);
    mount();
    expect(useShipment).toHaveBeenCalledWith("SHIP-1");
    expect(useProduct).toHaveBeenCalledWith("P-1");
    expect(
      screen.getByRole("heading", { name: "Shipment SHIP-1" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Manila → Cebu")).toBeInTheDocument();
    expect(screen.getByText("Status: Delivered")).toBeInTheDocument();
    expect(screen.getByText("Canonical timeline")).toBeInTheDocument();
    expect(
      screen.getByText("Receipt and synchronization evidence"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Public verification" }),
    ).toHaveAttribute("href", "/verify/P-1");
  });
  it("handles missing shipments and retries without fetching an empty product", () => {
    const refetch = vi.fn();
    vi.mocked(useShipment).mockReturnValue({
      error: new Error("API Error (404)"),
      refetch,
    } as unknown as ReturnType<typeof useShipment>);
    mount();
    expect(screen.getByText(/Shipment not found/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry shipment" }));
    expect(refetch).toHaveBeenCalledOnce();
    expect(useProduct).toHaveBeenCalledWith("");
  });
});
