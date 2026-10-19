import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ExceptionPolicy from "./ExceptionPolicy";
import {
  useExceptionPolicy,
  useSaveExceptionPolicy,
} from "@/hooks/useExceptions";
vi.mock("@/hooks/useExceptions", () => ({
  useExceptionPolicy: vi.fn(),
  useSaveExceptionPolicy: vi.fn(),
}));
const mutate = vi.fn();
beforeEach(() => {
  mutate.mockClear();
  vi.mocked(useExceptionPolicy).mockReturnValue({
    data: {
      revision: 3,
      arrival_enabled: true,
      inactivity_hours: 24,
      checkpoint_hours: 24,
      custody_hours: 6,
    },
  } as ReturnType<typeof useExceptionPolicy>);
  vi.mocked(useSaveExceptionPolicy).mockReturnValue({
    mutate,
  } as unknown as ReturnType<typeof useSaveExceptionPolicy>);
});
it("submits explicit policy revision and null to disable a threshold", () => {
  render(<ExceptionPolicy shipmentId="SHIP-1" />);
  fireEvent.change(
    screen.getByLabelText("Hours without a checkpoint during transit"),
    { target: { value: "" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save exception policy" }),
  );
  expect(mutate).toHaveBeenCalledWith({
    expected_revision: 3,
    arrival_enabled: true,
    inactivity_hours: null,
    checkpoint_hours: 24,
    custody_hours: 6,
  });
});
it("explains checkpoint intervals and bounded threshold input", () => {
  render(<ExceptionPolicy shipmentId="SHIP-1" />);
  expect(screen.getByLabelText(/not physical dwell/)).toHaveAttribute(
    "min",
    "0.25",
  );
  expect(screen.getByText(/Blank disables/)).toBeInTheDocument();
});
