import { useEffect, useState } from "react";
import { appEnvironment } from "@/config/runtime";
import { verificationLabel, verificationUrl } from "@/utils/verificationLabel";
import Modal from "./ui/Modal";
import Button from "./ui/Button";

export default function VerificationLabel({
  productId,
}: {
  productId: string;
}) {
  const [open, setOpen] = useState(false);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const url = verificationUrl(productId);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setSvg("");
    setError("");
    verificationLabel(
      productId,
      url,
      `${appEnvironment.name} · ${appEnvironment.chainId === 11155111 ? "Sepolia test network" : "Local test chain"}`,
    )
      .then((value) => {
        if (active) setSvg(value);
      })
      .catch(() => {
        if (active) setError("Could not create the QR label.");
      });
    return () => {
      active = false;
    };
  }, [open, productId, url, attempt]);
  return (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          setOpen(true);
          setCopied(false);
        }}
      >
        Share / QR label
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Public verification label"
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Anyone can open this link without a wallet. Labels identify this
            environment; they do not certify the physical item.
          </p>
          <label className="block text-sm">
            Public verification URL
            <input
              readOnly
              value={url}
              className="mt-2 w-full rounded border border-border bg-bg p-2"
              onFocus={(event) => event.currentTarget.select()}
            />
          </label>
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(url);
                setCopied(true);
              } catch {
                setError("Copy failed. Select and copy the URL above.");
              }
            }}
          >
            {copied ? "Link copied" : "Copy link"}
          </Button>
          {error && (
            <p role="alert">
              {error}{" "}
              <button
                className="underline"
                onClick={() => setAttempt((a) => a + 1)}
              >
                Retry label
              </button>
            </p>
          )}
          {svg ? (
            <>
              <img
                className="mx-auto h-auto w-full max-w-[368px]"
                src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
                alt={`QR verification label for ${productId}`}
              />
              <a
                className="inline-block rounded-lg bg-accent px-4 py-3 text-sm text-black"
                href={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
                download={`veritras-${productId.replace(/[^a-zA-Z0-9_-]/g, "_")}.svg`}
              >
                Download QR label
              </a>
            </>
          ) : (
            !error && <p role="status">Creating QR label…</p>
          )}
        </div>
      </Modal>
    </>
  );
}
