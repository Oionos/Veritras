import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import EvidenceTimeline from "./EvidenceTimeline";
import { useTimeline } from "@/hooks/useJourney";

vi.mock("@/hooks/useJourney", () => ({ useTimeline: vi.fn() }));
describe("Evidence timeline", () => {
  it("renders escaped event text, source order and pagination", () => {
    vi.mocked(useTimeline).mockImplementation(
      (_, page) =>
        ({
          data: {
            total: 101,
            skip: page * 100,
            limit: 100,
            items: page
              ? []
              : [
                  {
                    event_id: "1",
                    event_type: "CheckpointRecorded",
                    location: "<script>plain text</script>",
                    status: "3",
                    notes: "Received",
                    handler: `0x${"a".repeat(40)}`,
                    timestamp: "2026-10-19T00:00:00Z",
                    block_number: 10,
                    transaction_index: 2,
                    log_index: 3,
                    block_hash: `0x${"b".repeat(64)}`,
                    transaction_hash: `0x${"c".repeat(64)}`,
                  },
                ],
          },
          isLoading: false,
        }) as ReturnType<typeof useTimeline>,
    );
    render(<EvidenceTimeline productId="P-1" />);
    expect(
      screen.getByText("Location: <script>plain text</script>"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Block 10 · Transaction 2 · Log 3"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next events" }));
    expect(useTimeline).toHaveBeenLastCalledWith("P-1", 1);
    expect(screen.getByRole("button", { name: "Next events" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous events" }));
    expect(useTimeline).toHaveBeenLastCalledWith("P-1", 0);
  });
  it("offers retry and an explicit empty state", () => {
    const refetch = vi.fn();
    vi.mocked(useTimeline).mockReturnValue({
      error: new Error("offline"),
      refetch,
    } as unknown as ReturnType<typeof useTimeline>);
    const { rerender } = render(<EvidenceTimeline productId="P-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(refetch).toHaveBeenCalled();
    vi.mocked(useTimeline).mockReturnValue({
      data: { total: 0, items: [] },
    } as unknown as ReturnType<typeof useTimeline>);
    rerender(<EvidenceTimeline productId="P-1" />);
    expect(screen.getByText(/No canonical indexed events/)).toBeInTheDocument();
  });
});
