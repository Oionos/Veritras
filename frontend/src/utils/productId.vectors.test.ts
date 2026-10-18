import { describe, it, expect } from 'vitest'
import vectors from '../../../fixtures/product-ids.json'
import { toProductBytes32 } from './productId'

describe('shared canonical product identities', () => {
  vectors.forEach((vector, index) =>
    it(`converts vector ${index}`, () => {
      const input = vector.input ?? String.fromCodePoint(...vector.codepoints!)
      if (vector.error) expect(() => toProductBytes32(input)).toThrow()
      else {
        expect(toProductBytes32(input)).toBe(vector.expected)
        expect(toProductBytes32(vector.expected!)).toBe(vector.expected)
      }
    }),
  )
})
