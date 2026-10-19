import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { appEnvironment } from "@/config/runtime";

const routes: Record<string, [string, string]> = {
  "/": [
    "Supply Chain Analytics",
    "Track recorded product provenance, shipments and supply chain metrics with Veritras.",
  ],
  "/products": [
    "Products",
    "Manage product records and inspect blockchain registration evidence.",
  ],
  "/shipments": [
    "Shipments",
    "Follow shipment checkpoints, custody and delivery.",
  ],
  "/analytics": [
    "Analytics",
    "Inspect canonical shipment metrics, cohort filters and reports.",
  ],
  "/verify": [
    "Verify Registration",
    "Inspect public product registration evidence without a wallet.",
  ],
  "/demo": [
    "Guided Demo",
    "Explore a clearly labelled simulated product journey, separate from live data.",
  ],
  "/privacy": ["Privacy Policy", "Veritras privacy policy."],
  "/terms": ["Terms & Conditions", "Veritras terms and conditions."],
};

export default function RouteMetadata() {
  const { pathname } = useLocation();
  useEffect(() => {
    const [title, description] =
      routes[pathname] ??
      (pathname.startsWith("/verify/")
        ? [
            "Verify Registration",
            "Public registration evidence and canonical event history.",
          ]
        : pathname.startsWith("/shipments/")
          ? [
              "Shipment Detail",
              "Shipment status, current handler and recorded evidence timeline.",
            ]
          : [
              "Page Not Found",
              "Find a product or return to the Veritras dashboard.",
            ]);
    document.title = `Veritras — ${title}`;
    const meta = document.querySelector<HTMLMetaElement>(
      'meta[name="description"]',
    );
    if (meta) meta.content = description;
    const robots = document.querySelector<HTMLMetaElement>(
      'meta[name="robots"]',
    );
    if (robots)
      robots.content =
        appEnvironment.name === "testing" ||
        pathname === "/demo" ||
        title === "Page Not Found"
          ? "noindex, nofollow"
          : "index, follow";
    document.getElementById("main-content")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [pathname]);
  return null;
}
