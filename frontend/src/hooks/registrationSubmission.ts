import { appEnvironment } from "@/config/runtime";
import { fetchApi } from "./useApi";
import { getAuthToken } from "./useAuth";

export interface Submission {
  tx_hash: string;
  operation: "registration" | "metadata";
  metadata_uri?: string;
  replaces_tx_hash?: string;
}
const prefix = `veritras:submission:${appEnvironment.apiUrl}:${appEnvironment.chainId}:${appEnvironment.productRegistry}:`;
export function pendingSubmissionKey(productId: string, address: string) {
  return `${prefix}${address.toLowerCase()}:${productId}`;
}
function readOutbox(key: string): Submission[] {
  const stored = localStorage.getItem(key);
  if (!stored) return [];
  const parsed = JSON.parse(stored);
  return Array.isArray(parsed) ? parsed : [parsed];
}
export async function flushSubmissionOutbox(
  productId: string,
  address: string,
) {
  const key = pendingSubmissionKey(productId, address);
  if (!getAuthToken())
    throw new Error(
      "Sign in to save transaction tracking. Your hash is retained in this browser.",
    );
  // Original hashes precede replacements, including when both were sent offline.
  for (const submission of readOutbox(key)) {
    await fetchApi(`/products/${encodeURIComponent(productId)}/registration`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(submission),
    });
    const remaining = readOutbox(key).filter(
      (item) => item.tx_hash !== submission.tx_hash,
    );
    if (remaining.length) localStorage.setItem(key, JSON.stringify(remaining));
    else localStorage.removeItem(key);
  }
}
export async function saveSubmission(
  productId: string,
  address: string,
  submission: Submission,
  persistOnly = false,
) {
  const key = pendingSubmissionKey(productId, address);
  // Public transaction data only; preserve every attempt through API outages.
  const outbox = readOutbox(key).filter(
    (item) => item.tx_hash !== submission.tx_hash,
  );
  if (outbox.length >= 100)
    throw new Error(
      "Transaction tracking outbox is full. Recover saved hashes before submitting more.",
    );
  localStorage.setItem(key, JSON.stringify([...outbox, submission]));
  if (!persistOnly) await flushSubmissionOutbox(productId, address);
}
