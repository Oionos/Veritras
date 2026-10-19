import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/react";
import { safeAnalyticsUrl } from "@/config/telemetry";
export default function PrivateAnalytics() {
  return (
    <>
      <Analytics
        beforeSend={(event) => ({ ...event, url: safeAnalyticsUrl(event.url) })}
      />
      <SpeedInsights
        beforeSend={(event) => ({
          ...event,
          url: safeAnalyticsUrl(event.url),
          route: new URL(safeAnalyticsUrl(event.url)).pathname,
        })}
      />
    </>
  );
}
