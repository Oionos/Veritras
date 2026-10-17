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
