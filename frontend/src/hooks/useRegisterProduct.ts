import { appEnvironment } from '@/config/runtime'
import { useCallback } from 'react'
import {
  useWriteContract,
  useWaitForTransactionReceipt,
} from 'wagmi'
import { toast } from 'sonner'
import {
  productRegistryAbi,
  PRODUCT_REGISTRY_ADDRESS,
} from '@/config/contracts'

export function useRegisterProduct() {
  const {
    writeContract,
    data: hash,
    isPending,
    error,
  } = useWriteContract()

  const { isLoading: isConfirming, isSuccess } = useWaitForTransactionReceipt({
    hash,
  })

  const register = useCallback(
    (
      productId: `0x${string}`,
      name: string,
      description: string,
      metadataURI: string
    ) => {
      writeContract(
        {
          abi: productRegistryAbi,
          chainId: appEnvironment.chainId,
          address: PRODUCT_REGISTRY_ADDRESS as `0x${string}`,
          functionName: 'registerProduct',
          args: [productId, name, description, metadataURI],
        },
        {
          onSuccess: (txHash: string) => {
            toast.success('Transaction submitted', {
              description: `Hash: ${txHash.slice(0, 10)}...`,
            })
          },
          onError: (err: Error) => {
            toast.error('Transaction failed', {
              description: err.message,
            })
          },
        }
      )
    },
    [writeContract]
  )

  return {
    register,
    hash,
    isPending,
    isConfirming,
    isSuccess,
    error,
  }
}
