import { appEnvironment } from "@/config/runtime";
import { useCallback, useRef } from "react";
import { useAccount } from "wagmi";
import { saveSubmission } from "./registrationSubmission";
import { useWriteContract, useWaitForTransactionReceipt } from "wagmi";
import { toast } from "sonner";
import {
  productRegistryAbi,
  PRODUCT_REGISTRY_ADDRESS,
} from "@/config/contracts";

export function useRegisterProduct() {
  const { address } = useAccount();
  const activeAddress = useRef(address);
  activeAddress.current = address;
  const submission = useRef<{ productId: string; address: string } | null>(
    null,
  );
  const {
    writeContract,
    data: hash,
    isPending,
    error,
    reset,
  } = useWriteContract();

  const { isLoading: isConfirming, isSuccess } = useWaitForTransactionReceipt({
    hash,
    onReplaced: ({ replacedTransaction, transaction }) => {
      const context = submission.current;
      if (context) {
        void saveSubmission(context.productId, context.address, {
          tx_hash: transaction.hash,
          operation: "registration",
          replaces_tx_hash: replacedTransaction.hash,
        }).catch(() =>
          toast.error(
            "Replacement tracking needs attention. Open the product registration panel.",
          ),
        );
      }
    },
  });

  const register = useCallback(
    (
      productId: `0x${string}`,
      name: string,
      description: string,
      metadataURI: string,
      publicProductId?: string,
    ) => {
      const wallet = address;
      submission.current =
        publicProductId && wallet
          ? { productId: publicProductId, address: wallet }
          : null;
      writeContract(
        {
          abi: productRegistryAbi,
          chainId: appEnvironment.chainId,
          address: PRODUCT_REGISTRY_ADDRESS as `0x${string}`,
          functionName: "registerProduct",
          args: [productId, name, description, metadataURI],
        },
        {
          onSuccess: (txHash: string) => {
            if (publicProductId && wallet) {
              void saveSubmission(
                publicProductId,
                wallet,
                { tx_hash: txHash, operation: "registration" },
                activeAddress.current?.toLowerCase() !== wallet.toLowerCase(),
              ).catch(() =>
                toast.error(
                  "Transaction sent; tracking could not be saved. Open this product to retry.",
                ),
              );
            }
            toast.success("Transaction submitted", {
              description: `Hash: ${txHash.slice(0, 10)}...`,
            });
          },
          onError: (err: Error) => {
            toast.error("Transaction failed", {
              description: err.message,
            });
          },
        },
      );
    },
    [writeContract, address],
  );

  return {
    register,
    reset,
    hash,
    isPending,
    isConfirming,
    isSuccess,
    error,
  };
}
