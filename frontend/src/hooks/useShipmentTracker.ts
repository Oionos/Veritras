import { appEnvironment } from '@/config/runtime'
import { useCallback } from 'react'
import {
  useWriteContract,
  useReadContract,
  useAccount,
  useWaitForTransactionReceipt,
} from 'wagmi'
import { toast } from 'sonner'
import {
  shipmentTrackerAbi,
  SHIPMENT_TRACKER_ADDRESS,
  productRegistryAbi,
  PRODUCT_REGISTRY_ADDRESS,
} from '@/config/contracts'
import { toProductBytes32 } from '@/utils/productId'

export function useShipmentPermissions(productId?: string) {
  const { address, chainId, isConnected } = useAccount()
  let id: `0x${string}` | undefined
  try {
    if (productId) id = toProductBytes32(productId)
  } catch {
    /* Invalid IDs have no actions. */
  }
  const enabled = !!id && isConnected && chainId === appEnvironment.chainId
  const query = { enabled, refetchInterval: 5000 }
  const handler = useReadContract({
    address: SHIPMENT_TRACKER_ADDRESS as `0x${string}`,
    abi: shipmentTrackerAbi,
    functionName: 'currentHandler',
    args: [id!],
    chainId: appEnvironment.chainId,
    query,
  })
  const delivered = useReadContract({
    address: SHIPMENT_TRACKER_ADDRESS as `0x${string}`,
    abi: shipmentTrackerAbi,
    functionName: 'isDelivered',
    args: [id!],
    chainId: appEnvironment.chainId,
    query,
  })
  const manufacturer = useReadContract({
    address: PRODUCT_REGISTRY_ADDRESS as `0x${string}`,
    abi: productRegistryAbi,
    functionName: 'getProductManufacturer',
    args: [id!],
    chainId: appEnvironment.chainId,
    query,
  })
  const current =
    typeof handler.data === 'string' ? handler.data.toLowerCase() : undefined
  const owner =
    typeof manufacturer.data === 'string'
      ? manufacturer.data.toLowerCase()
      : undefined
  const zero = `0x${'0'.repeat(40)}`
  const wallet = address?.toLowerCase()
  const ready =
    enabled &&
    !handler.isError &&
    !delivered.isError &&
    !manufacturer.isError &&
    !!current &&
    !!owner &&
    owner !== zero &&
    delivered.data === false
  return {
    canRecord: !!(
      ready &&
      wallet &&
      (current === zero ? owner === wallet : current === wallet)
    ),
    canTransfer: !!(ready && wallet && current === wallet),
  }
}

export type ShipmentStatus = 0 | 1 | 2 | 3

export const StatusLabels: Record<ShipmentStatus, string> = {
  0: 'Created',
  1: 'In Transit',
  2: 'At Checkpoint',
  3: 'Delivered',
}

export function useRecordCheckpoint() {
  const { writeContract, data: hash, isPending, error } = useWriteContract()

  const { isLoading: isConfirming, isSuccess } = useWaitForTransactionReceipt({
    hash,
  })

  const record = useCallback(
    (
      productId: `0x${string}`,
      location: string,
      status: ShipmentStatus,
      notes: string,
    ) => {
      writeContract(
        {
          abi: shipmentTrackerAbi,
          chainId: appEnvironment.chainId,
          address: SHIPMENT_TRACKER_ADDRESS as `0x${string}`,
          functionName: 'recordCheckpoint',
          args: [productId, location, status, notes],
        },
        {
          onSuccess: (txHash: string) => {
            toast.success('Checkpoint recorded', {
              description: `Tx: ${txHash.slice(0, 10)}...`,
            })
          },
          onError: (err: Error) => {
            toast.error('Checkpoint failed', {
              description: err.message,
            })
          },
        },
      )
    },
    [writeContract],
  )

  return {
    record,
    hash,
    isPending,
    isConfirming,
    isSuccess,
    error,
  }
}

export function useTransferCustody() {
  const { writeContract, data: hash, isPending, error } = useWriteContract()

  const { isLoading: isConfirming, isSuccess } = useWaitForTransactionReceipt({
    hash,
  })

  const transfer = useCallback(
    (productId: `0x${string}`, newHandler: `0x${string}`) => {
      writeContract(
        {
          abi: shipmentTrackerAbi,
          chainId: appEnvironment.chainId,
          address: SHIPMENT_TRACKER_ADDRESS as `0x${string}`,
          functionName: 'transferCustody',
          args: [productId, newHandler],
        },
        {
          onSuccess: (txHash: string) => {
            toast.success('Custody transferred', {
              description: `Tx: ${txHash.slice(0, 10)}...`,
            })
          },
          onError: (err: Error) => {
            toast.error('Transfer failed', {
              description: err.message,
            })
          },
        },
      )
    },
    [writeContract],
  )

  return {
    transfer,
    hash,
    isPending,
    isConfirming,
    isSuccess,
    error,
  }
}
