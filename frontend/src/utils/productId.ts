import { pad, toHex } from 'viem'

export function toProductBytes32(productId: string): `0x${string}` {
  if (/^0x[\da-f]{64}$/i.test(productId)) return productId as `0x${string}`
  const hex = toHex(productId)
  if (hex.length > 66) throw new Error('Product ID exceeds 32 bytes')
  return pad(hex, { size: 32, dir: 'right' })
}
