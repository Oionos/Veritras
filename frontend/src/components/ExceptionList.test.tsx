import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import ExceptionList from "./ExceptionList";
import { useExceptions, useAcknowledgeException } from "@/hooks/useExceptions";
import { useAuth } from "@/hooks/useAuth";
vi.mock("@/hooks/useExceptions", () => ({
  useExceptions: vi.fn(),
  useAcknowledgeException: vi.fn(),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: vi.fn() }));
const owner = "0x1234";
const mutate = vi.fn();
const item = {
  id: "episode",
  shipment_id: "SHIP-1",
  kind: "custody_followup",
  owner_address: owner,
  ownership_source: "chain_event",
  evidence: { receiving_handler: "0x5678", threshold_hours: 6 },
  triggered_at: "2026-01-01T00:00:00Z",
  first_observed_at: "2026-01-01T00:00:00Z",
  last_observed_at: "2026-01-01T01:00:00Z",
  resolved_at: null,
  acknowledged_at: null,
};
function query(items: unknown[] = [item], paused = false) {
  vi.mocked(useExceptions).mockReturnValue({
    data: {
      items,
      total: items.length,
      evaluation: {
        paused,
        reason: paused ? "indexing_disabled" : null,
        evaluated_at: null,
      },
    },
  } as ReturnType<typeof useExceptions>);
}
function mount() {
  return render(
    <MemoryRouter>
      <ExceptionList />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    isAuthenticated: true,
    address: owner,
  } as ReturnType<typeof useAuth>);
  vi.mocked(useAcknowledgeException).mockReturnValue({
    mutate,
    isPending: false,
  } as unknown as ReturnType<typeof useAcknowledgeException>);
  mutate.mockClear();
  query();
});
it("explains custody is already transferred and links to shipment evidence", () => {
  mount();
  expect(
    screen.getByText(/Custody already transferred on-chain/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /View shipment evidence/ }),
  ).toHaveAttribute("href", "/shipments/SHIP-1");
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Contacted carrier" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Acknowledge occurrence" }),
  );
  expect(mutate).toHaveBeenCalledWith({
    id: "episode",
    note: "Contacted carrier",
  });
});
it.each([
  { isAuthenticated: false, address: null },
  { isAuthenticated: true, address: "other" },
])("hides acknowledgement for nonowners: %o", (auth) => {
  vi.mocked(useAuth).mockReturnValue(auth as ReturnType<typeof useAuth>);
  mount();
  expect(
    screen.queryByRole("button", { name: "Acknowledge occurrence" }),
  ).not.toBeInTheDocument();
});
it("shows paused empty state without asserting shipment timeliness", () => {
  query([], true);
  mount();
  expect(
    screen.getByText(/missing updates do not establish/),
  ).toBeInTheDocument();
  expect(screen.getByText(/timeliness is not established/)).toBeInTheDocument();
});
it.each([
  { acknowledged_at: "2026-01-01T02:00:00Z" },
  { resolved_at: "2026-01-01T03:00:00Z", resolution: "condition_cleared" },
])(
  "retains history and prevents acknowledgement of changed episodes",
  (change) => {
    query([{ ...item, ...change }]);
    mount();
    expect(
      screen.queryByRole("button", { name: "Acknowledge occurrence" }),
    ).not.toBeInTheDocument();
  },
);
it("renders notes as text", () => {
  query([{ ...item, acknowledgement_note: "<script>unsafe</script>" }]);
  const { container } = mount();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByText(/<script>unsafe/)).toBeInTheDocument();
});
it("supports retry on read failure", () => {
  const refetch = vi.fn();
  vi.mocked(useExceptions).mockReturnValue({
    error: new Error("offline"),
    refetch,
  } as unknown as ReturnType<typeof useExceptions>);
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Retry exceptions" }));
  expect(refetch).toHaveBeenCalledOnce();
});
