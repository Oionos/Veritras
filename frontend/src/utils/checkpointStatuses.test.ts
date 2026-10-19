import { describe, it, expect } from "vitest";
import { allowedCheckpointStatuses } from "./checkpointStatuses";

describe("Contract checkpoint transitions", () => {
  it("requires Created first and follows every permitted transition", () => {
    expect(allowedCheckpointStatuses([])).toEqual([0]);
    expect(allowedCheckpointStatuses([{ status: 0 }])).toEqual([1, 2]);
    expect(allowedCheckpointStatuses([{ status: 0 }, { status: 1 }])).toEqual([
      2, 3,
    ]);
    expect(allowedCheckpointStatuses([{ status: 2 }])).toEqual([1, 3]);
    expect(allowedCheckpointStatuses([{ status: 3 }])).toEqual([]);
    expect(allowedCheckpointStatuses([{ status: 99 }])).toEqual([]);
  });
});
