import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useWriteContract, useWaitForTransactionReceipt } from "wagmi";
import { useAuth } from "@/hooks/useAuth";
import { useRegisterProduct } from "@/hooks/useRegisterProduct";
import { fetchApi, useVerifyProduct } from "@/hooks/useApi";
import {
  pendingSubmissionKey,
  saveSubmission,
  flushSubmissionOutbox,
} from "@/hooks/registrationSubmission";
import { ownsRecord, hasCurrentIdentity } from "@/utils/permissions";
import { appEnvironment } from "@/config/runtime";
import {
  productRegistryAbi,
  PRODUCT_REGISTRY_ADDRESS,
} from "@/config/contracts";
import type { Product } from "@/types";
import type { components } from "@/types/api";
import Button from "./ui/Button";
import TransactionLink from "./TransactionLink";

type Lifecycle = components["schemas"]["RegistrationLifecycleResponse"];
type MetadataHistory = components["schemas"]["MetadataHistoryResponse"];

export default function RegistrationPanel({ product }: { product: Product }) {
  const auth = useAuth();
  const activeWallet = useRef(auth.address);
  activeWallet.current = auth.address;
  const metadataContext = useRef<{ address: string; uri: string } | null>(null);
  const client = useQueryClient();
  const owner =
    auth.isAuthenticated &&
    ownsRecord(product, auth.address) &&
    hasCurrentIdentity(product);
  const [error, setError] = useState("");
  const [uri, setUri] = useState("");
  const [recoveryHash, setRecoveryHash] = useState("");
  const [replacesHash, setReplacesHash] = useState("");
  const [recoveryOperation, setRecoveryOperation] = useState<
    "registration" | "metadata"
  >("registration");
  const registration = useRegisterProduct();
  const metadata = useWriteContract();
  const receipt = useWaitForTransactionReceipt({
    hash: metadata.data,
    onReplaced: ({ replacedTransaction, transaction }) => {
      const context = metadataContext.current;
      if (!context) return;
      void saveSubmission(
        product.product_id,
        context.address,
        {
          tx_hash: transaction.hash,
          operation: "metadata",
          metadata_uri: context.uri,
          replaces_tx_hash: replacedTransaction.hash,
        },
        activeWallet.current?.toLowerCase() !== context.address.toLowerCase(),
      ).catch(() =>
        setError(
          "Replacement tracking is retained in this browser. Sign in and refresh to retry.",
        ),
      );
    },
  });
  const { data: verification } = useVerifyProduct(product.product_id);
  const lifecycle = useQuery<Lifecycle>({
    queryKey: ["registration", product.product_id, owner, auth.address],
    queryFn: async () => {
      if (owner && auth.address) {
        try {
          await flushSubmissionOutbox(product.product_id, auth.address);
        } catch {
          /* Retain outbox for recovery. */
        }
      }
      const result: Lifecycle = await fetchApi(
        `/products/${product.product_id}/registration`,
      );
      const pending = result.attempts.find(
        (a) => !a.replaced_by && !["failed", "indexed"].includes(a.status),
      );
      if (owner && pending) {
        try {
          const updated = await fetchApi(
            `/products/${product.product_id}/registration/reconcile?tx_hash=${pending.tx_hash}`,
            { method: "POST" },
          );
          return {
            ...result,
            attempts: result.attempts.map((a) =>
              a.tx_hash === updated.tx_hash ? updated : a,
            ),
          };
        } catch {
          /* Preserve persisted observations while evidence is unavailable. */
        }
      }
      return result;
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
  const history = useQuery<MetadataHistory>({
    queryKey: ["metadata-history", product.product_id],
    queryFn: () => fetchApi(`/products/${product.product_id}/metadata-history`),
  });
  const refresh = () => {
    for (const key of [
      "registration",
      "verify",
      "product",
      "products",
      "metadata-history",
    ]) {
      void client.invalidateQueries({
        queryKey: key === "products" ? [key] : [key, product.product_id],
      });
    }
  };
  useEffect(() => {
    if (verification?.evidence?.status === "verified") {
      void client.invalidateQueries({
        queryKey: ["product", product.product_id],
      });
      void client.invalidateQueries({ queryKey: ["products"] });
    }
  }, [verification?.evidence?.status, product.product_id, client]);
  useEffect(() => {
    if (!owner || !auth.address) return;
    const saved = localStorage.getItem(
      pendingSubmissionKey(product.product_id, auth.address),
    );
    if (!saved) return;
    let active = true;
    try {
      void flushSubmissionOutbox(product.product_id, auth.address)
        .then(() => {
          if (active)
            void client.invalidateQueries({
              queryKey: ["registration", product.product_id],
            });
        })
        .catch(() => {
          if (active)
            setError(
              "Transaction tracking could not be saved. Sign in and retry, or submit the transaction hash below.",
            );
        });
    } catch {
      setError(
        "Saved tracking data is invalid. Submit the transaction hash below.",
      );
    }
    return () => {
      active = false;
    };
  }, [owner, auth.address, product.product_id, client]);
  const reconcile = async (hash: string) => {
    setError("");
    try {
      await fetchApi(
        `/products/${product.product_id}/registration/reconcile?tx_hash=${hash}`,
        { method: "POST" },
      );
      refresh();
    } catch {
      setError(
        "Evidence could not be refreshed. Retry when the API and wallet session are available.",
      );
    }
  };
  const updateMetadata = async () => {
    if (!owner || !auth.address || !hasCurrentIdentity(product)) return;
    const wallet = auth.address;
    setError("");
    metadataContext.current = { address: wallet, uri };
    try {
      const hash = await metadata.writeContractAsync({
        address: PRODUCT_REGISTRY_ADDRESS as `0x${string}`,
        abi: productRegistryAbi,
        chainId: appEnvironment.chainId,
        functionName: "updateProductMetadata",
        args: [product.on_chain_product_id, uri],
      });
      await saveSubmission(
        product.product_id,
        wallet,
        { tx_hash: hash, operation: "metadata", metadata_uri: uri },
        activeWallet.current?.toLowerCase() !== wallet.toLowerCase(),
      );
      refresh();
    } catch {
      setError(
        "Metadata transaction was rejected or tracking could not be saved. Check your wallet and transaction history before retrying.",
      );
    }
  };
  const pending = lifecycle.data?.attempts.some(
    (a) => !["failed", "replaced", "indexed"].includes(a.status),
  );
  return (
    <section
      aria-label="Registration lifecycle"
      className="space-y-4 rounded-2xl border border-white/10 p-5 text-sm"
    >
      <h3 className="font-semibold">Registration and evidence</h3>
      <p role="status">
        {verification?.evidence
          ? `${verification.evidence.registration_status} · ${verification.evidence.reason.replace(/_/g, " ")}`
          : "Registration evidence unavailable"}
      </p>
      <p className="text-muted">
        Transaction confirmation and indexing are separate steps. Registration
        evidence does not authenticate a physical item.
      </p>
      {lifecycle.isError && (
        <p role="alert">
          Registration tracking is unavailable. Retry when the API is reachable.
        </p>
      )}
      {lifecycle.data?.attempts.map((attempt) => (
        <div
          key={attempt.tx_hash}
          className="space-y-1 border-t border-white/10 pt-3"
        >
          <p>
            {attempt.operation} · {attempt.status} ·{" "}
            {attempt.reason.replace(/_/g, " ")}
          </p>
          <TransactionLink hash={attempt.tx_hash} />
          {attempt.replaced_by && (
            <p>
              Replaced by <TransactionLink hash={attempt.replaced_by} />
            </p>
          )}
          {owner && (
            <Button
              variant="secondary"
              onClick={() => void reconcile(attempt.tx_hash)}
            >
              Refresh transaction evidence
            </Button>
          )}
        </div>
      ))}
      {owner && product.registration_status === "draft" && (
        <Button
          disabled={
            !!pending || registration.isPending || registration.isConfirming
          }
          onClick={() =>
            registration.register(
              product.on_chain_product_id as `0x${string}`,
              product.name,
              product.description || "",
              product.metadata_uri || "",
              product.product_id,
            )
          }
        >
          Register existing draft on blockchain
        </Button>
      )}
      {owner && product.registration_status === "indexed" && (
        <div className="space-y-2">
          <label className="block">
            New metadata URI
            <input
              className="ml-3 rounded bg-white/10 p-2"
              maxLength={500}
              value={uri}
              onChange={(event) => setUri(event.target.value)}
            />
          </label>
          <Button
            disabled={metadata.isPending || receipt.isLoading}
            onClick={() => void updateMetadata()}
          >
            Sign metadata update
          </Button>
          <p>
            Displayed metadata changes after the confirmed event is indexed.
          </p>
        </div>
      )}
      {owner && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!auth.address) return;
            void saveSubmission(product.product_id, auth.address, {
              tx_hash: recoveryHash,
              operation: recoveryOperation,
              ...(recoveryOperation === "metadata"
                ? { metadata_uri: uri }
                : {}),
              ...(replacesHash ? { replaces_tx_hash: replacesHash } : {}),
            })
              .then(() => {
                setRecoveryHash("");
                refresh();
              })
              .catch(() =>
                setError(
                  "Could not save the transaction hash. Verify the hash and your wallet session.",
                ),
              );
          }}
        >
          <label className="block">
            Recover registration tracking
            <input
              className="ml-3 rounded bg-white/10 p-2"
              pattern="0x[0-9a-fA-F]{64}"
              required
              value={recoveryHash}
              onChange={(event) => setRecoveryHash(event.target.value)}
              placeholder="0x transaction hash"
            />
          </label>
          <label className="block">
            Operation
            <select
              className="ml-3 rounded bg-bg p-2"
              value={recoveryOperation}
              onChange={(event) =>
                setRecoveryOperation(
                  event.target.value as "registration" | "metadata",
                )
              }
            >
              <option value="registration">Registration</option>
              <option value="metadata">Metadata update</option>
            </select>
          </label>
          <label className="block">
            Original hash, if replacing
            <input
              className="ml-3 rounded bg-white/10 p-2"
              pattern="0x[0-9a-fA-F]{64}"
              value={replacesHash}
              onChange={(event) => setReplacesHash(event.target.value)}
            />
          </label>
          <Button type="submit" variant="secondary">
            Save transaction hash
          </Button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {!!history.data?.items.length && (
        <details>
          <summary>Metadata version history</summary>
          {history.data.items.map((version) => (
            <div
              key={`${version.block_hash}:${version.log_index}`}
              className="mt-2"
            >
              <p className="break-all">
                Block {version.block_number} ·{" "}
                {version.canonical ? "Canonical" : "Orphaned"} ·{" "}
                {version.metadata_uri || "(empty URI)"}
              </p>
              <TransactionLink hash={version.transaction_hash} />
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
