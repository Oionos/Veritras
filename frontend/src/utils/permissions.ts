import { appEnvironment } from '@/config/runtime'
export function ownsRecord(
  record: { owner_address?: string | null; ownership_source?: string | null },
  address: string | null,
) {
  return (
    !!address &&
    ['signed_draft', 'chain_event'].includes(record.ownership_source || '') &&
    record.owner_address?.toLowerCase() === address.toLowerCase()
  )
}

export interface ProductIdentity {
  on_chain_product_id?: string | null
  chain_id?: number | null
  registry_address?: string | null
  tracker_address?: string | null
}

export function hasCurrentIdentity(
  record: ProductIdentity | null | undefined,
  environment = appEnvironment,
): record is ProductIdentity & { on_chain_product_id: `0x${string}` } {
  return (
    !!record &&
    /^0x[\da-f]{64}$/.test(record.on_chain_product_id || '') &&
    !/^0x0{64}$/.test(record.on_chain_product_id || '') &&
    record.chain_id === environment.chainId &&
    record.registry_address?.toLowerCase() ===
      environment.productRegistry.toLowerCase() &&
    record.tracker_address?.toLowerCase() ===
      environment.shipmentTracker.toLowerCase()
  )
}
