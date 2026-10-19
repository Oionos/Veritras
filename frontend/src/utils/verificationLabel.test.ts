import { describe, it, expect } from "vitest";
import {
  verificationLabel,
  verificationPath,
  verificationUrl,
} from "./verificationLabel";

describe("Public verification labels", () => {
  it("encodes path separators and never includes the current query or access token", () => {
    expect(verificationPath("A/B?x=1#C")).toBe("/verify/A%2FB%3Fx%3D1%23C");
    expect(
      verificationUrl("PROD-001", "https://example.test/?secret=private"),
    ).toBe("https://example.test/verify/PROD-001");
  });
  it("escapes untrusted label text and includes network and evidence limitations", async () => {
    const svg = await verificationLabel(
      '<script>"&',
      "https://example.test/verify/item",
      "Testing <Sepolia>",
    );
    expect(svg).toContain("&lt;script&gt;&quot;&amp;");
    expect(svg).not.toContain("<script>");
    expect(svg).toContain("Testing &lt;Sepolia&gt;");
    expect(svg).toContain("Does not authenticate a physical item");
    expect(svg).toContain("viewBox=");
  });
});
