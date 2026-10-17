import { appEnvironment } from '@/config/runtime'
import { useCallback } from 'react'
import {
  useWriteContract,
  useWaitForTransactionReceipt,
} from 'wagmi'
import { toast } from 'sonner'
import {
  shipmentTrackerAbi,
  SHIPMENT_TRACKER_ADDRESS,
} from '@/config/contracts'

export type ShipmentStatus = 0 | 1 | 2 | 3

export const StatusLabels: Record<ShipmentStatus, string> = {
  0: 'Created',
  1: 'In Transit',
  2: 'At Checkpoint',
  3: 'Delivered',
}

export function useRecordCheckpoint() {
  const {
    writeContract,
    data: hash,
    isPending,
    error,
  } = useWriteContract()

  const { isLoading: isConfirming, isSuccess } = useWaitForTransactionReceipt({
    hash,
  })

  const record = useCallback(
    (
      productId: `0x${string}`,
      location: string,
      status: ShipmentStatus,
      notes: string
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
        }
      )
    },
    [writeContract]
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
  const {
    writeContract,
    data: hash,
    isPending,
    error,
  } = useWriteContract()

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
        }
      )
    },
    [writeContract]
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
