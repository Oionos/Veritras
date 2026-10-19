# Performance measurements

Increment 10 measured the anonymous dashboard before changing loading boundaries. The measured frontend source is feature commit `25819f84866787e741ab4dcd039313ac094b451a`; subsequent changes harden URL allowlisting and monitoring without changing loading boundaries. The baseline is main `7adb990863aa399d2dd323d80e1bfa090794716f`. Results and individual sample values are retained in [performance/increment10.json](performance/increment10.json).

## Controlled mobile comparison

Measured October 20, 2026 (Asia/Manila), Chromium 154.0.8037.57. Three cold-cache Lighthouse runs per build, same frozen API fixtures, gzip server, 390×844 viewport and Lighthouse simulated mobile CPU/network. External HTTPS was blocked equally in both builds. API latency, production CDN behavior, WalletConnect provider latency and real user devices are outside this comparison.

| Median | Before | After | Change |
| --- | ---: | ---: | ---: |
| Lighthouse performance | 47 | 61 | +14 points |
| First contentful paint | 6.50 s | 3.52 s | 46% lower |
| Largest contentful paint | 11.33 s | 5.37 s | 53% lower |
| Total blocking time | 463 ms | 448 ms | 3% lower |
| Cumulative layout shift | 0 | 0 | unchanged |
| Total transferred bytes | 1,671,523 | 660,866 | 60% lower |
| Initial JavaScript, gzip | 1,226,486 | 383,058 | 69% lower |

One supplementary menu interaction took 146 ms before and 106 ms after. It includes Playwright click overhead and two animation frames: **it is not field INP or a percentile**, and is not the basis of the improvement claim. LCP remains above the 2.5-second good threshold in this constrained lab.

A repeat on the final build retained the loading/transfer gains; blocking time varied from the initial trial, so the table uses the final measurements. The previous manual Web3 group combined optional SDKs with eager imports. Removing it alone reduced transfer but worsened blocking time in an intermediate trial. The final change also defers remote connector setup until wallet intent, restores it immediately for stored wallet connections, defers the below-fold chart by visibility, and schedules optional diagnostic SDK loading during idle time. No dependency upgrade or weaker Lighthouse threshold was needed.

## Reproduce and prevent regression

From `frontend`, build with `CI=true VITE_API_URL=http://127.0.0.1:18010 VITE_WALLETCONNECT_PROJECT_ID=ci-test-project-id npm exec -- vite build --manifest`, then run `node scripts/measure-performance.mjs dist ../.testing/performance-comparison`. Use Node 24 for direct fixture TypeScript loading and set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` if Chromium is elsewhere. Preserve the baseline artifact, use the same browser and machine, and avoid competing workloads. The output contains three Lighthouse JSON reports, a summary and mobile screenshot; keep them local unless reviewed for publication.

The existing Lighthouse CI checks remain required. The Playwright startup regression additionally caps anonymous dashboard script bytes at **450,000 gzip bytes**, including idle diagnostics; verifies no chart or remote WalletConnect/Reown SDK starts before intent/visibility; scrolls the chart into view and opens the wallet picker. Real local integration checks cover signing, reconnect, switching wallets and contract writes.

## Field measurements

No valid production before/after field comparison was available for this release. The connected metrics query could not retrieve a valid dataset, and Vercel documents programmatic metric queries as requiring Observability Plus. No plan upgrade was requested or made. Lab measurements above must not be presented as production percentiles.

Vercel Speed Insights remains enabled after idle loading and receives sanitized route URLs. Compare production mobile p75 LCP and INP over equal seven-day windows only after both windows have meaningful counts; record dates, release, device mix, route and count alongside each value. Do not combine preview/demo traffic with production or compare a single synthetic visit to field traffic. The public API diagnostics expose process-local browser LCP/CLS means and maximum-interaction samples; these are untrusted diagnostic samples, not durable RUM percentiles or field INP. See [operations](OPERATIONS.md) for retention and privacy.
