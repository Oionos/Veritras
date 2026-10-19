import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Demo from "./Demo";

describe("Isolated guided demo", () => {
  it("walks every stage and resets without a wallet or business API", () => {
    render(
      <MemoryRouter>
        <Demo />
      </MemoryRouter>,
    );
    expect(
      screen.getByText(/makes no transactions or business API requests/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("DEMO-COFFEE-001 · Philippine coffee"),
    ).toBeInTheDocument();
    for (let i = 0; i < 5; i++)
      fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(
      screen.getByRole("heading", { name: "Share the evidence" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Example status: Delivered")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restart demo" }));
    expect(
      screen.getByRole("heading", { name: "Register a product" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Previous step" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "4. Transfer custody" }),
    );
    expect(screen.getByText("Example status: In Transit")).toBeInTheDocument();
  });
});
