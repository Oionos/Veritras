import { pad, toHex } from 'viem'

export function toProductBytes32(productId: string): `0x${string}` {
  if (typeof productId !== 'string' || !productId)
    throw new Error('Product ID must be nonempty')
  let result: `0x${string}`
  if (/^0x/i.test(productId)) {
    if (!/^0x[\da-f]{64}$/i.test(productId))
      throw new Error('Hex product ID must contain exactly 32 bytes')
    result = `0x${productId.slice(2).toLowerCase()}`
  } else {
    for (const character of productId) {
      const point = character.codePointAt(0)!
      if (point === 0 || (point >= 0xd800 && point <= 0xdfff))
        throw new Error('Invalid product ID character')
    }
    const hex = toHex(productId)
    if (hex.length > 66) throw new Error('Product ID exceeds 32 bytes')
    result = pad(hex, { size: 32, dir: 'right' })
  }
  if (/^0x0{64}$/.test(result))
    throw new Error('Zero product ID is not accepted')
  return result
}
